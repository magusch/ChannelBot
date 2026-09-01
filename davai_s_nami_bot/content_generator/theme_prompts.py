# -*- coding: utf-8 -*-
"""Prompts for themed digests, split the same way as event-preparation prompts.

* **Editorial part** — the voice of the digest: what the intro should do, how
  long a comment is, what is banned. Owned by the editor, read from a Redis
  param (`theme_post_user_message`) and **replacing** the code default entirely.
  Stacking a param on top of the default does not work — the rules contradict
  each other and the model returns mush. `theme_post_extra_rules` is the small
  additive slot for a spot fix.
* **Contract** — the JSON shape, the ids, the character ceilings, the
  `{{id|label}}` markers. Owned by the code: a careless prompt edit here breaks
  parsing or produces a post that cannot be rendered, so it is always appended
  and cannot be overridden.

Kept separate from :mod:`helper.ai.prompts` (which does event preparation)
because the two have different contracts and different editors — one writes
event descriptions, the other writes the digest around them.
"""

import json
import logging

log = logging.getLogger(__name__)

SYSTEM_PARAM = 'theme_post_system_message'
EDITORIAL_PARAM = 'theme_post_user_message'
EXTRA_RULES_PARAM = 'theme_post_extra_rules'


def _city_loc():
    """City name in the prepositional case ("о мероприятиях в …"); SPb default."""
    try:
        from ..settings.settings_loader import settings

        return getattr(settings, 'city_name_loc', None) or 'Санкт-Петербурге'
    except Exception:
        return 'Санкт-Петербурге'


def default_system_message():
    return (
        f"Ты ведёшь Telegram-канал о мероприятиях в {_city_loc()}. "
        "Аудитория — 17–29 лет. Пишешь как человек, который сам туда ходит и "
        "делится находками: живо, но без рекламы и без восторгов."
    )


def default_editorial_message():
    """Editorial prompt used when no param is set."""
    return """Ты составляешь подборку мероприятий на неделю — как блогер, который сам по ним ходит.

Вступление: 2–3 предложения от первого лица, как пишет блогер, а не афиша.

Да, перескажи, что в подборке — но так, чтобы читать было интересно: не голым перечислением, а с деталью, которая цепляет. «Ткачество как искусство» — это перечисление; «как станок Жаккарда довёл ремесло до Chanel» — это уже повод пойти.

Личный выбор — только с названием. «Я бы сходил» без имени мероприятия запрещено: читатель не понимает, о чём речь. Запрещённые обороты: «сходил бы на любое», «хотя бы на одно из этих», «на ту, где…», «из этих трёх».
  Плохо: «Я бы сходил хотя бы на один из этих трёх — тут есть и лингвистика, и разговор про триггеры».
  Хорошо: «Сам пойду на „Триггерный музей“: разговор про то, почему музейные вещи цепляют, ведёт арт-терапевт».

Не повторяй слова из заголовка подборки. Если она называется «Бесплатно на этой неделе», слово «бесплатные» во вступлении уже лишнее — это и так понятно.

Не заканчивай дежурным выводом («все три выглядят интересными», «есть из чего выбрать», «каждый найдёт своё»). Лучше закончить на конкретике.

Без вопросов к читателю, без «мы собрали», без канцелярита.

Комментарий к мероприятию: 1–2 предложения. Первое — что это такое и чем отличается от соседних. Второе — конкретика, которую не угадать по названию: имена, что в программе, формат, для кого. Название не повторяй — оно стоит рядом. Дату, место и цену не пиши — они подставляются отдельно.

Не описывай всё по одной схеме: где-то факт, где-то субъективная оценка («на любителя», «если любите тишину»). Сухой юмор уместен. Не строй все комментарии одинаково — одинаковое начало у пяти подряд читается как шаблон.

Запрещены клише («погрузиться в атмосферу», «машина времени», «не пропустите», «что может быть лучше», «мы собрали для вас»), рекламные эпитеты («уникальный», «незабываемый»), восклицательные знаки, эмодзи и markdown."""


def resolve_prompts(dsn_param):
    """``(system_message, editorial_message)`` for a themed digest."""
    def param(name):
        try:
            value = dsn_param.site_parameters(name, last=1)
        except Exception as e:  # noqa: BLE001 — a Redis hiccup must not break a post
            log.warning(f"theme_prompts: failed to read param {name!r}: {e}")
            return None
        return value if value and str(value).strip() else None

    system = param(SYSTEM_PARAM) or default_system_message()
    editorial = param(EDITORIAL_PARAM) or default_editorial_message()

    extra = param(EXTRA_RULES_PARAM)
    if extra:
        editorial = f"{editorial}\n\nДополнительные правила:\n{extra}"

    return system, editorial


def _also_block(also):
    """Titles that are in the post but not described — context for the intro."""
    titles = [str(e.get("title") or "").strip() for e in also or []]
    titles = [t for t in titles if t]
    if not titles:
        return ""
    listed = "\n".join(f"- {t}" for t in titles)
    return (
        "\nЭто тоже есть в подборке, но комментировать их не надо — используй "
        f"только чтобы понять контекст недели:\n{listed}"
    )


def comments_contract(theme_title, payload, comment_max, intro_max=260, also=()):
    """Response contract for the list layouts. Always from code."""
    return f"""

Тема подборки: «{theme_title}».

Верни СТРОГО JSON без markdown-обёртки, вида:
{{"intro": "...", "comments": [{{"id": <id>, "text": "..."}}]}}

intro — до {intro_max} символов, по правилам выше. Не используй слова из
заголовка «{theme_title}» и однокоренные с ними.
comments — по одному на каждое мероприятие из списка, с тем же id.
text — до {comment_max} символов.

Мероприятия (JSON):
{json.dumps(payload, ensure_ascii=False, default=str)}
{_also_block(also)}"""


def prose_contract(theme_title, payload, prose_max, paragraph_max, intro_max=260, also=()):
    """Response contract for the flowing-text layout. Always from code."""
    return f"""

Тема подборки: «{theme_title}».

Верни СТРОГО JSON: {{"intro": "...", "paragraphs": ["...", "..."]}}

intro — до {intro_max} символов, по правилам выше. Не используй слова из
заголовка «{theme_title}» и однокоренные с ними.
paragraphs — 2–3 абзаца сплошного текста, каждый объединяет 2–3 мероприятия по
смыслу: одна тема, один день, один формат, «на выбор». Не по одному мероприятию
на абзац, не список.

— Абзац до {paragraph_max} символов, весь текст до {prose_max} символов.
— На каждое мероприятие — одна короткая мысль, максимум одно предложение.
— Упомяни каждое мероприятие ровно один раз и пометь маркером:
  {{{{id}}}} — подставится название ссылкой,
  {{{{id|твои слова}}}} — ссылкой станут твои слова (так лучше).
  Маркер — часть предложения, не отдельная строка.
— Дату и место называй словами, если это важно («в четверг», «на Лендоке»).

Мероприятия (JSON):
{json.dumps(payload, ensure_ascii=False, default=str)}
{_also_block(also)}"""
