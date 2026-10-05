# -*- coding: utf-8 -*-
"""Prompt assembly for event preparation, shared by all copywriting providers.

A prepared-post prompt has two parts with different owners:

* **Editorial part** — the channel's voice (tone, length, bans). That's the
  editor's area, tuned live through a Redis param, and it **replaces** the code
  default entirely. Stacking the param on top of the code prompt does not work:
  the rules contradict each other ("завлекающий, с капелькой любопытства" vs
  "нейтральный тон, никаких эмоций") and the model returns mush.
* **Contract** — JSON shape, field list, date/price formats, categories. That's
  the code's area: a careless prompt edit breaks parsing, so it is always
  appended from code and can't be overridden by a param.

Plus a third, small slot: ``ai_extra_rules`` is appended to whichever editorial
part is active, so a spot fix ("don't use the word «спикер»") doesn't require
copying the whole prompt.
"""

import datetime
import json
import logging
import re

from ...scoring import CATEGORY_ID_TO_NAME

log = logging.getLogger(__name__)

# Internal fields: they only confuse the model.
SKIP_FIELDS = {
    'post_date', 'post_url', 'queue', 'is_ready', 'status',
    'score', 'score_breakdown', 'explored_date', 'image_upload',
}

JSON_SCHEMA = {
    "title": "<ЭМОДЗИ> <Тип> <Название>",
    "prepared_text": "<Текст 2-4 предложения>",
    "category": "<Категория>",
    "address": "<Место, адрес, метро>",
    "price": "<Цена или Бесплатно>",
    "from_date": "<YYYY-MM-DDTHH:MM>",
    "to_date": "<YYYY-MM-DDTHH:MM или null>",
    "url": "<ссылка>",
    "relevant": True,
    "reject_reason": "",
}

# One param for every provider; the old per-provider names stay as a fallback so
# nothing breaks before the values are moved over in Django.
SYSTEM_PARAM = 'ai_system_message'
USER_PARAM = 'ai_user_message'
EXTRA_RULES_PARAM = 'ai_extra_rules'


def _city_loc():
    """City name in the prepositional case ("о мероприятиях в …"); SPb default."""
    try:
        from ...settings.settings_loader import settings

        return getattr(settings, 'city_name_loc', None) or 'Санкт-Петербурге'
    except Exception:
        return 'Санкт-Петербурге'


def default_system_message():
    return (
        f"Ты редактор-копирайтер для телеграм-канала о мероприятиях в {_city_loc()}. "
        "У нас есть сырая информация по мероприятию, необходимо адаптировать её для поста."
    )


def default_editorial_message():
    """Editorial prompt used when no param is set."""
    return """Необходимо прочитать текст, заголовок и другую информацию и отредактировать их по следующим инструкциям:
Заголовок не должен содержать даты и упоминания места проведения. Определи по тексту тип мероприятия (лекция, кинопоказ, концерт, фестиваль и другие, на кириллице); название на кириллице поставь в кавычки, название на латинице — без кавычек. Добавь в начало яркое и небанальное эмодзи по смыслу. Итоговый шаблон: "<ЭМОДЗИ> <Тип мероприятия> <Название мероприятия>". Пример: 🚀 Лекция «Покорение космоса в СССР».
Первое предложение отвечает на вопрос «что это вообще такое»: тип события, его масштаб и для кого оно. Образец: «<Название> — <что это> <для кого/про что>». Не дата, не адрес, не город, не номер выпуска. Никогда не копируй первое предложение исходного текста: в пресс-релизах в лид вынесено «состоится там-то тогда-то», а дата и место у читателя уже есть в посте. Не начинай с «VII», «Второй ежегодный», «состоится», «пройдёт», «стартует».
Дальше — только та конкретика, которую нельзя угадать по названию: имена, страны-участники, названия фильмов и тем, состав программы, что именно происходит. Из длинного текста бери детали из глубины, а не из первого абзаца. Общие слова о миссии («направленное на поддержку и развитие», «служит важнейшей площадкой») не используй — это язык отчёта; если в источнике только такое, лучше два коротких предложения.
Не делай текст официальным и сухим, но и не рекламным. Длительность передавай словами («три дня», «на следующей неделе»), без чисел и дат. Убирай ссылки, спецсимволы, цены и адреса — они уже есть в посте. Пиши в третьем лице и в настоящем/будущем времени, без обращений к читателю и без первого лица. Объём — 2-4 предложения.
Не используй рекламные клише («уникальный», «невероятный», «незабываемый», «потрясающий») и повелительное наклонение («приходите», «не пропустите», «узнайте»)."""


def resolve_prompts(dsn_param, provider):
    """(system_message, editorial_message) for the given provider.

    Resolution order: shared param → provider param (legacy) → code default.
    ``ai_extra_rules`` is then appended to the editorial part.
    """
    def param(name):
        try:
            value = dsn_param.site_parameters(name, last=1)
        except Exception as e:  # noqa: BLE001 — a Redis hiccup must not break prep
            log.warning(f"prompts: failed to read param {name!r}: {e}")
            return None
        return value if value and str(value).strip() else None

    system = (
        param(SYSTEM_PARAM)
        or param(f'{provider}_system_message')
        or default_system_message()
    )
    editorial = (
        param(USER_PARAM)
        or param(f'{provider}_user_message')
        or default_editorial_message()
    )

    extra = param(EXTRA_RULES_PARAM)
    if extra:
        editorial = f"{editorial}\n\nДополнительные правила:\n{extra}"

    return system, editorial


def format_event_info(event):
    """Raw event fields as prompt text, minus the internal ones."""
    lines = ["Мероприятие:"]
    for key, value in event.items():
        if key in SKIP_FIELDS or value is None:
            continue
        lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n"


def json_contract(today=None):
    """Response contract. Always from code — never overridden by a param."""
    today = today or datetime.date.today().isoformat()
    # Categories come from scoring, not a hardcoded list: the old prompt carried
    # "Спорт", which does not exist in category_category, so the model routed
    # events into a category that resolves to nothing.
    categories = ", ".join(CATEGORY_ID_TO_NAME.values())
    schema = json.dumps(JSON_SCHEMA, ensure_ascii=False, indent=2)
    return f"""
На основе предоставленной информации о мероприятии, адаптируй её для поста.

Верни результат строго в формате JSON (без markdown, без ```):
{schema}

Правила заполнения полей:
1) title — заголовок по шаблону "<ЭМОДЗИ> <Тип мероприятия> <Название>".
2) prepared_text — описание мероприятия по правилам выше.
3) category — одна из: {categories}. Если ничего не подходит — "Без категории".
4) price — если указана: "цифры + валюта". Скидка для студентов: "цена / студ.цена (инфо)". Бесплатно: "Бесплатно". Если не указана — null.
5) address — название места, адрес, станция метро (если знаешь). Без города и района.
6) from_date, to_date — формат YYYY-MM-DDTHH:MM, UTC+3. Только из исходных данных.
7) url — ссылка на мероприятие из исходных данных.
8) relevant — false если мероприятие: корпоратив, бизнес-мероприятие, детское, платный курс/тренинг, реклама без события, онлайн-вебинар, или мероприятие уже прошло (from_date < {today}). Мероприятие должно быть релевантно аудитории 17-29 лет. true во всех остальных случаях.
9) reject_reason — причина если relevant=false, иначе пустая строка.

Сегодняшняя дата: {today}. Используй её, чтобы определить, прошло ли мероприятие.
Включай только достоверные данные из исходной информации.

Исходная информация:
"""


THIN_DESCRIPTION_CHARS = 80

_TAG_RE = re.compile(r"<[^>]+>")

THIN_DESCRIPTION_RULES = """
Внимание: у этого мероприятия почти нет описания — только название и служебные поля.
Для prepared_text в этом случае:
- одно-два коротких предложения, а не 2-4;
- не повторяй дату, время, длительность, цену и адрес — они уже есть в посте, и текст из них читается как пересказ подвала;
- не пиши об отсутствии информации («подробности не раскрывают», «детали уточняются») и не гадай вслух («вероятно», «похоже», «судя по названию»);
- общеизвестные факты использовать можно, только если уверен: классическое произведение, известный автор, известный артист или коллектив. Если имя тебе не знакомо — не придумывай ни жанр, ни биографию, ни программу;
- если сказать нечего, кроме типа события и имени, так и напиши одним предложением: «Сольный концерт Нины Потехиной».
"""


def is_thin_description(event):
    """True when the event's own description carries almost nothing."""
    text = _TAG_RE.sub(" ", str(event.get("full_text") or ""))
    return len(" ".join(text.split())) < THIN_DESCRIPTION_CHARS


def build_user_message(editorial_message, event, today=None):
    """Full user message: editorial part + contract + event data."""
    contract = json_contract(today)
    if is_thin_description(event):
        # Rules go before the event data, not after the «Исходная информация:» header.
        head, sep, tail = contract.rpartition("Исходная информация:")
        contract = head + THIN_DESCRIPTION_RULES.lstrip("\n") + "\n" + sep + tail
    return editorial_message + contract + format_event_info(event)
