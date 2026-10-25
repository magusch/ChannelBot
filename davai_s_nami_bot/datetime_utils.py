import datetime
from datetime import timezone as tz, timedelta as td


STRFTIME = "%Y-%m-%dT%H:%M:%S"


def get_msk_today(replace_seconds=False):
    params = dict()

    if replace_seconds:
        params.update(
            dict(
                second=0,
                microsecond=0,
            )
        )

    return datetime.datetime.now(tz(td(hours=3))).replace(**params)


# A night event (23:00–06:00) belongs to the day it starts.
NIGHT_END_HOUR = 7


def last_day(date_from, date_to):
    """Local calendar date of the event's last day, ignoring a night tail."""
    if date_to is None:
        return date_from.date()
    if date_to - date_from >= td(days=1):
        return date_to.date()
    return max(date_from, date_to - td(hours=NIGHT_END_HOUR)).date()
