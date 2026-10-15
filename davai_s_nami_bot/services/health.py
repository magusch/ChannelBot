"""Morning health report: is the stack alive and what did the nightly pipeline do.

Findings come in two kinds:

- ``problems`` — breakage that does not depend on volumes: a component is down,
  a nightly task never ran or failed, the scrape wrote nothing, the channel
  posted nothing yesterday, today's slot holds an unprepared event. They set
  ``status`` (``fail`` for a dead component, otherwise ``warn``).
- ``notes`` — comparisons against the city's own recent history, never against
  a fixed volume: a source silent for longer than its usual gap, a short queue
  runway. Holidays and seasons move the numbers, so a note carries its baseline
  and the reader decides. Notes do not change ``status``.

Volume metrics are returned as is, next to their 28-day baseline.

``build_report`` is the entry point; the ``evaluate_*``/``analyze_*`` functions
are pure and tested without DB, Redis or Celery.
"""
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Optional

from sqlalchemy import func, or_, text

from ..city_context import current_city
from ..content_generator.models import PostingSchedule
from ..database.database_orm import get_db_session
from ..database.models import Events2Posts, EventsNotApproved

MSK = timezone(timedelta(hours=3))

HISTORY_DAYS = 28
# A tracked task is "missing" only after this much time past its slot: the
# catch-up task needs a chance to re-fire it first.
TASK_MISSING_GRACE = timedelta(minutes=45)
# A task whose marker still says "started" this long after its slot most likely
# died with the worker (prerun marker set, postrun never fired).
TASK_HUNG_AFTER = timedelta(hours=3)
# Source silence: only sources active on at least this many days of the
# history window have a usual rhythm to compare against.
SOURCE_MIN_ACTIVE_DAYS = 3
SOURCE_MIN_SILENT_DAYS = 3
SOURCE_SILENCE_FACTOR = 2
RUNWAY_NOTE_DAYS = 3
BROKER_BACKLOG_NOTE = 50

_DONE_STATES = {'SUCCESS'}
_FAILED_STATES = {'FAILURE', 'REVOKED'}


@dataclass
class Findings:
    problems: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    fatal: bool = False

    def extend(self, other: 'Findings'):
        self.problems += other.problems
        self.notes += other.notes
        self.fatal = self.fatal or other.fatal

    @property
    def status(self) -> str:
        if self.fatal:
            return 'fail'
        return 'warn' if self.problems else 'ok'


def _short_task(name: str) -> str:
    return name.rsplit('.', 1)[-1]


def _decode(value) -> Optional[str]:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


# --- Pure evaluation ---------------------------------------------------------


def evaluate_components(components: dict) -> Findings:
    """``components``: ``{'db': 'ok'|err, 'redis': ..., 'workers': [names]|err,
    'broker_backlog': int|None}``."""
    found = Findings()
    for name in ('db', 'redis'):
        if components.get(name) != 'ok':
            found.fatal = True
            found.problems.append(f"{name} недоступен: {components.get(name)}")
    workers = components.get('workers')
    if not isinstance(workers, list) or not workers:
        found.fatal = True
        found.problems.append(f"Celery: ни один воркер не ответил на ping ({workers})")
    backlog = components.get('broker_backlog')
    if isinstance(backlog, int) and backlog > BROKER_BACKLOG_NOTE:
        found.notes.append(
            f"В очереди брокера {backlog} задач: воркер не успевает или завис"
        )
    return found


def evaluate_nightly_tasks(schedule: Iterable[tuple], now_msk: datetime,
                           marker_of: Callable[[str], Optional[str]]):
    """State of each tracked daily task today.

    ``schedule`` rows are ``(task_name, hour, minute, weekdays_iso|None, kwargs)``
    as in ``celery_tasks._daily_task_schedule`` (already shifted for the city);
    ``marker_of(task_name)`` returns today's Redis marker or ``None``.
    Returns ``(tasks, findings)``.
    """
    found = Findings()
    tasks = []
    for task_name, hour, minute, weekdays, _kwargs in schedule:
        if weekdays is not None and now_msk.isoweekday() not in weekdays:
            continue
        name = _short_task(task_name)
        slot = now_msk.replace(hour=hour, minute=minute, second=0, microsecond=0)
        marker = marker_of(task_name)
        tasks.append({'task': name, 'slot': f"{hour:02d}:{minute:02d}", 'state': marker})

        if marker is None:
            if now_msk >= slot + TASK_MISSING_GRACE:
                found.problems.append(
                    f"{name} ({hour:02d}:{minute:02d}) сегодня не запускался: "
                    f"beat или catch-up не работают"
                )
                tasks[-1]['state'] = 'missing'
            else:
                tasks[-1]['state'] = 'not_due'
        elif marker in _FAILED_STATES:
            found.problems.append(f"{name} ({hour:02d}:{minute:02d}) упал: {marker}")
        elif marker == 'catch_up_queued':
            found.notes.append(
                f"{name}: beat пропустил слот {hour:02d}:{minute:02d}, "
                f"задачу поставил catch-up"
            )
        elif marker == 'started' and now_msk >= slot + TASK_HUNG_AFTER:
            found.notes.append(
                f"{name} запущен в {hour:02d}:{minute:02d} и не завершился: "
                f"завис или воркер упал посреди задачи"
            )
    return tasks, found


def analyze_scraping(rows: Iterable[tuple], today: date, days: int = HISTORY_DAYS):
    """New events written per day and source.

    ``rows`` are ``(source, explored_day, count)``. Returns ``(summary, findings)``.
    The source rhythm is learned from the window itself: a source is flagged
    only when it has been quiet longer than ``SOURCE_SILENCE_FACTOR`` times its
    usual gap between active days, so rotation days and seasonal dips do not
    trigger it.
    """
    start = today - timedelta(days=days - 1)
    per_day: Dict[date, int] = defaultdict(int)
    active: Dict[str, set] = defaultdict(set)
    today_by_source: Dict[str, int] = defaultdict(int)
    for source, day, count in rows:
        if day is None or not (start <= day <= today) or not count:
            continue
        source = source or 'unknown'
        per_day[day] += count
        active[source].add(day)
        if day == today:
            today_by_source[source] += count

    totals = [per_day.get(start + timedelta(days=i), 0) for i in range(days)]
    past = totals[:-1]
    found = Findings()
    sources = {}
    for source, days_set in sorted(active.items()):
        ordered = sorted(days_set)
        gaps = [(b - a).days for a, b in zip(ordered, ordered[1:])]
        silent = (today - ordered[-1]).days
        usual_gap = statistics.median(gaps) if gaps else None
        sources[source] = {
            'last_seen': ordered[-1].isoformat(),
            'days_silent': silent,
            'active_days': len(ordered),
            'usual_gap_days': usual_gap,
        }
        if len(ordered) < SOURCE_MIN_ACTIVE_DAYS or usual_gap is None:
            continue
        limit = max(SOURCE_MIN_SILENT_DAYS, SOURCE_SILENCE_FACTOR * usual_gap)
        if silent > limit:
            found.notes.append(
                f"{source} молчит {silent} дн. (обычно новые раз в {usual_gap:g} дн., "
                f"последние — {ordered[-1].isoformat()})"
            )

    summary = {
        'today_total': per_day.get(today, 0),
        'today_by_source': dict(sorted(today_by_source.items(), key=lambda kv: -kv[1])),
        'baseline_days': days - 1,
        'baseline_median_per_day': statistics.median(past) if past else 0,
        'baseline_zero_days': sum(1 for t in past if t == 0),
        'last_7_days': {
            (today - timedelta(days=i)).isoformat(): per_day.get(today - timedelta(days=i), 0)
            for i in range(7)
        },
        'sources': sources,
    }
    return summary, found


def evaluate_scrape_result(summary: dict, full_update_state: Optional[str]) -> Findings:
    """Nothing new after a completed scrape is breakage, not a quiet day: on a
    normal day rotation alone brings dozens of events."""
    found = Findings()
    if full_update_state in _DONE_STATES and summary['today_total'] == 0:
        found.problems.append(
            "full_update отработал, но не записал ни одного нового события "
            f"(обычно ~{summary['baseline_median_per_day']:g} в день)"
        )
    return found


def evaluate_posting(posting: dict) -> Findings:
    found = Findings()
    y = posting['yesterday']
    if y['events_posted'] == 0 and y['digests_posted'] == 0:
        found.problems.append("Вчера в канал не ушло ни одного поста")
    elif y['events_posted'] == 0:
        found.notes.append("Вчера не вышло ни одного событийного поста (только дайджесты)")
    if y['events_error'] or y['digests_error']:
        found.problems.append(
            f"Ошибки публикации за вчера/сегодня: события {y['events_error']}, "
            f"дайджесты {y['digests_error']}"
        )
    t = posting['today']
    if t['events_scheduled'] == 0:
        found.problems.append("На сегодня в канал не поставлено ни одного события")
    if t['events_unprepared']:
        found.problems.append(
            f"На сегодня стоят {t['events_unprepared']} событий без AI-подготовки "
            f"(is_ready не True)"
        )
    q = posting['queue']
    runway = q.get('runway_days')
    if runway is not None and runway < RUNWAY_NOTE_DAYS:
        found.notes.append(
            f"Подготовленной очереди хватит на ~{runway:g} дн. "
            f"({q['ready']} событий при ~{q['posted_per_day']:g} постах в день)"
        )
    return found


# --- Collection --------------------------------------------------------------


def collect_components() -> dict:
    from ..celery_app import celery_app, redis_client

    components = {}
    try:
        with get_db_session() as db:
            db.execute(text('SELECT 1'))
        components['db'] = 'ok'
    except Exception as e:
        components['db'] = f"{type(e).__name__}: {e}"
    try:
        redis_client.ping()
        components['redis'] = 'ok'
    except Exception as e:
        components['redis'] = f"{type(e).__name__}: {e}"
    try:
        replies = celery_app.control.ping(timeout=1.5) or []
        components['workers'] = sorted(name for reply in replies for name in reply)
    except Exception as e:
        components['workers'] = f"{type(e).__name__}: {e}"
    try:
        with celery_app.connection_for_read() as conn:
            components['broker_backlog'] = int(
                conn.default_channel.client.llen(celery_app.conf.task_default_queue)
            )
    except Exception:
        components['broker_backlog'] = None
    return components


def collect_task_markers(now_msk: datetime):
    from .. import celery_tasks
    from ..celery_app import redis_client

    today = now_msk.date()

    def marker_of(task_name):
        value = redis_client.get(celery_tasks._daily_marker_key(task_name, today))
        if value is None:
            for legacy in celery_tasks._legacy_daily_marker_keys(task_name, today):
                value = redis_client.get(legacy)
                if value is not None:
                    break
        return _decode(value)

    return celery_tasks._daily_task_schedule(), marker_of


def collect_scraped_rows(db, today: date, days: int = HISTORY_DAYS) -> List[tuple]:
    """``(source, day, count)`` of newly written events, both tables: promoted
    rows leave ``EventsNotApproved``, so it alone would undercount."""
    since = _day_bounds(today - timedelta(days=days - 1))[0]
    counts: Dict[tuple, int] = defaultdict(int)
    for model in (EventsNotApproved, Events2Posts):
        rows = (
            db.query(model.source, model.explored_date)
            .filter(model.explored_date >= since)
            .all()
        )
        for source, explored in rows:
            if isinstance(explored, datetime):
                if explored.tzinfo is not None:
                    explored = explored.astimezone(MSK)
                explored = explored.date()
            counts[(source, explored)] += 1
    return [(source, day, n) for (source, day), n in counts.items()]


def _day_bounds(day: date):
    start = datetime.combine(day, datetime.min.time(), tzinfo=MSK)
    return start, start + timedelta(days=1)


def collect_posting(db, now_msk: datetime) -> dict:
    today = now_msk.date()
    y_start, y_end = _day_bounds(today - timedelta(days=1))
    t_start, t_end = _day_bounds(today)
    E = Events2Posts

    def count_events(*criteria):
        return db.query(func.count(E.id)).filter(*criteria).scalar() or 0

    def count_digests(*criteria):
        return db.query(func.count(PostingSchedule.id)).filter(*criteria).scalar() or 0

    yesterday = {
        'events_posted': count_events(
            E.status == 'Posted', E.post_date >= y_start, E.post_date < y_end),
        'digests_posted': count_digests(
            PostingSchedule.is_posted.is_(True),
            PostingSchedule.scheduled_time >= y_start,
            PostingSchedule.scheduled_time < y_end),
        'events_error': count_events(
            E.status == 'Error', E.post_date >= y_start, E.post_date < t_end),
        'digests_error': count_digests(
            PostingSchedule.status == 'Error',
            PostingSchedule.scheduled_time >= y_start,
            PostingSchedule.scheduled_time < t_end),
    }

    in_today = (E.post_date >= t_start, E.post_date < t_end)
    today_block = {
        # Posted already today + still queued for today. OnlyApi keeps its
        # post_date after being routed off the channel, so it is not counted.
        'events_scheduled': count_events(
            E.status.in_(('ReadyToPost', 'Posted')), *in_today),
        'events_posted': count_events(E.status == 'Posted', *in_today),
        'events_unprepared': count_events(
            E.status == 'ReadyToPost', or_(E.is_ready.is_(None), E.is_ready.is_(False)),
            *in_today),
        'digests_scheduled': count_digests(
            PostingSchedule.scheduled_time >= t_start,
            PostingSchedule.scheduled_time < t_end),
        'digests_posted': count_digests(
            PostingSchedule.is_posted.is_(True),
            PostingSchedule.scheduled_time >= t_start,
            PostingSchedule.scheduled_time < t_end),
    }

    alive = func.coalesce(E.to_date, E.from_date) >= now_msk
    ready = count_events(E.status == 'ReadyToPost', E.is_ready.is_(True), alive)
    window_start = _day_bounds(today - timedelta(days=14))[0]
    posted_14d = count_events(
        E.status == 'Posted', E.post_date >= window_start, E.post_date < t_start)
    per_day = round(posted_14d / 14, 1)
    queue = {
        'ready': ready,
        'unprepared': count_events(
            E.status == 'ReadyToPost',
            or_(E.is_ready.is_(None), E.is_ready.is_(False)), alive),
        'onlyapi_unprepared': count_events(
            E.status == 'OnlyApi', E.is_ready.is_(None), alive),
        'posted_per_day': per_day,
        'runway_days': round(ready / per_day, 1) if per_day else None,
    }
    return {'yesterday': yesterday, 'today': today_block, 'queue': queue}


def build_report(now_msk: Optional[datetime] = None) -> dict:
    now_msk = now_msk or datetime.now(MSK)
    today = now_msk.date()
    found = Findings()

    components = collect_components()
    found.extend(evaluate_components(components))

    tasks = []
    full_update_state = None
    try:
        schedule, marker_of = collect_task_markers(now_msk)
        tasks, task_found = evaluate_nightly_tasks(schedule, now_msk, marker_of)
        found.extend(task_found)
        full_update_state = next(
            (t['state'] for t in tasks if t['task'] == 'full_update'), None)
    except Exception as e:
        found.problems.append(f"Не удалось прочитать маркеры ночных задач: {e}")

    scraping = posting = None
    if components.get('db') == 'ok':
        try:
            with get_db_session() as db:
                rows = collect_scraped_rows(db, today)
                posting = collect_posting(db, now_msk)
            scraping, scrape_found = analyze_scraping(rows, today)
            found.extend(scrape_found)
            found.extend(evaluate_scrape_result(scraping, full_update_state))
            found.extend(evaluate_posting(posting))
        except Exception as e:
            found.problems.append(f"Не удалось посчитать метрики из БД: {type(e).__name__}: {e}")

    return {
        'status': found.status,
        'city': current_city(),
        'generated_at': now_msk.isoformat(timespec='seconds'),
        'problems': found.problems,
        'notes': found.notes,
        'components': components,
        'nightly_tasks': tasks,
        'scraping': scraping,
        'posting': posting,
    }
