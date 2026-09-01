import re

from datetime import datetime, timedelta, timezone
import pytz
import json
import random

from typing import List, Dict, Any

import logging

from . import crud
from davai_s_nami_bot import crud as dsn_crud

from ..settings.settings_loader import settings
from ..helper.dsn_parameters import DSNParameters
from ..helper.ai_helper import AIHelper
from .. import utils
from davai_s_nami_bot.pydantic_models import EventRequestParameters

log = logging.getLogger(__name__)


def _build_location(event):
    """Build smart location fields without duplication.

    Returns (location, metro) where:
    - location: "Place Name, улица, д.1" or just "улица, д.1"
    - metro: "м.Невский проспект" or ""
    """
    place = event.get('place') or {}
    place_name = place.get('place_name', '') or ''
    place_metro = place.get('place_metro', '') or ''
    raw_address = event.get('address') or ''

    metro = place_metro
    address_without_metro = raw_address
    if raw_address:
        metro_match = re.search(
            r',?\s*(м\.\s*\S+(?:\s+\S+)?|метро\s+\S+(?:\s+\S+)?)\s*$',
            raw_address,
        )
        if metro_match:
            if not metro:
                metro = metro_match.group(1).strip().lstrip(',').strip()
            address_without_metro = raw_address[:metro_match.start()].strip().rstrip(',')

    street = address_without_metro
    if place_name and street:
        if street.lower().startswith(place_name.lower()):
            street = street[len(place_name):].lstrip(',').lstrip().lstrip(',').strip()

    if place_name and street:
        location = f"{place_name}, {street}"
    elif place_name:
        location = place_name
    else:
        location = street

    return location, metro or ''


MSK_TZ = pytz.timezone(settings.timezone if settings.timezone else 'Europe/Moscow')


def _to_local(dt):
    """Convert a datetime to local timezone (from settings)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return MSK_TZ.localize(dt)
    return dt.astimezone(MSK_TZ)


CATEGORIES_NAME = [
    "Концерты", "Без категории", "Кино", "Лекции", "Культура", "Фестивали",
    "Театр", "Вечеринки", "Перфомансы", "Стэндап", "Выставки",
    "Мастер-классы", "Экскурсии",
]

VIRTUAL_FIELD_DEPENDENCIES = {
    'event_date': ['from_date', 'to_date'],
    'place_name': ['address', 'place'],
    'event_time': ['from_date'],
    'location': ['address', 'place'],
    'metro': ['address', 'place'],
}

def category_name(cat_id):
    if not isinstance(cat_id, int) or not 1 <= cat_id <= len(CATEGORIES_NAME):
        return "Без категории"
    return CATEGORIES_NAME[cat_id - 1]


def month_name_genitive(m):
    return {
        1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
        7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
    }.get(m, "")


def weekday_name(dt):
    return {
        0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт",
        4: "Пт", 5: "Сб", 6: "Вск"
    }[dt.weekday()]


def fmt_single_date(d):
    if isinstance(d, datetime):
        return f"{d.day} {month_name_genitive(d.month)}"
    return str(d)


def fmt_two_dates(d1, d2):
    if isinstance(d1, datetime) and isinstance(d2, datetime):
        if d1.month == d2.month:
            if d2.day - d1.day == 1:
                return f"{d1.day} и {d2.day} {month_name_genitive(d1.month)}"
            elif d1.day != d2.day:
                return f"{d1.day}–{d2.day} {month_name_genitive(d1.month)}"
            else:
                return f"{d1.day} {month_name_genitive(d1.month)}"
        return f"{d1.day} {month_name_genitive(d1.month)} – {d2.day} {month_name_genitive(d2.month)}"
    return f"{fmt_single_date(d1)} – {fmt_single_date(d2)}"


def date_to_post(date_from, date_to=None):
    s_weekday = weekday_name(date_from)
    s_day = date_from.day
    s_month = month_name_genitive(date_from.month)
    s_hour = date_from.hour
    s_minute = date_from.minute

    if date_to is not None:
        e_weekday = weekday_name(date_to)
        e_day = date_to.day
        e_month = month_name_genitive(date_to.month)
        e_hour = date_to.hour
        e_minute = date_to.minute

        if s_day == e_day:
            start_format = f"{s_weekday}, {s_day} {s_month} {s_hour:02}:{s_minute:02}-"
            end_format = f"{e_hour:02}:{e_minute:02}"

        elif s_month != e_month:
            start_format = f"{s_weekday}-{e_weekday}, {s_day} {s_month} - "
            end_format = f"{e_day} {e_month} {s_hour:02}:{s_minute:02}–{e_hour:02}:{e_minute:02}"
        else:
            start_format = f"{s_weekday}-{e_weekday}, {s_day}–{e_day} {s_month} {s_hour:02}:{s_minute:02}-"
            end_format = f"{e_hour:02}:{e_minute:02}"

    else:
        end_format = ""
        start_format = f"{s_weekday}, {s_day} {s_month} {s_hour:02}:{s_minute:02}"

    return start_format + end_format


def join_list(items):
    items = [str(x).strip() for x in items if x]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " и " + items[-1]


class GeneratorPost:

    def __init__(self):
        pass

    @staticmethod
    def _parse_json_field(value):
        """Parse a JSON string field, returning the value as-is if already parsed."""
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return {}
        return value if value is not None else {}

    # Make in model ContentGeneratorEventSelection new event selection by random filter set and also put events from Events2Posts to ContentGeneratorEventSelectionSelectedEvents
    def event_selection(self, filter_set_id: int = None) -> dict:
        filter_set = crud.get_filter(filter_set_id)
        if not filter_set:
            raise ValueError("Фильтр не найден")

        filter_params = self._parse_json_field(filter_set['filter_params'])

        filtered_events = self.apply_filters(filter_set)
        if not filtered_events:
            return {}

        event_selection_dict = {
            'filter_set_id': filter_set['id'],
            'name':          filter_set['name'],
            'status':       'draft',
            'generation_settings': json.dumps(filter_params),
        }

        event_selection = crud.create_event_selection(event_selection_dict)

        crud.add_selected_events(event_selection, filtered_events)
        return event_selection

    def apply_filters(self, filter_set): # -> models.QuerySet:
        """Apply filter and return filtered events."""
        filter_params = self._parse_json_field(filter_set['filter_params'])

        today = datetime.today()
        week_ahead = today + timedelta(days=7)

        # No `status: 'all'`: it drops the publicly-valid predicate.
        parameters = {'date_from': today, 'date_to': week_ahead}

        if 'main_category' in filter_params:
            parameters['category'] = filter_params['main_category']
            if not isinstance(parameters['category'], list):
                parameters['category'] = [parameters['category']]

        if 'date_from' in filter_params:
            parameters['date_from'] = filter_params['date_from']

        if 'date_to' in filter_params:
            parameters['date_to'] = filter_params['date_to']

        if 'week_ahead' in filter_params:
            parameters['date_from'] = today
            parameters['date_to'] = week_ahead

        if 'this_week' in filter_params:
            start_week = today - timedelta(days=today.weekday())
            end_week = start_week + timedelta(days=7)

            parameters['date_from'] = today
            parameters['date_to'] = end_week

        if 'weekend' in filter_params:
            saturday = today + timedelta(5 - today.weekday())
            sunday = saturday + timedelta(days=1)

            parameters['date_from'] = saturday
            parameters['date_to'] = sunday

        if 'location' in filter_params:
            # Assuming 'location' is a string or a list of strings
            if isinstance(filter_params['location'], list):
                parameters['place'] = filter_params['location']
            else:
                parameters['place'] = [filter_params['location']]

        if 'max_price' in filter_params:
            try:
                parameters['price_max'] = int(filter_params['max_price'])
            except (ValueError, TypeError):
                pass

        # if 'keywords' in params:
        #     q_objects = Q()
        #     for keyword in params['keywords']:
        #         q_objects |= Q(title__icontains=keyword) | Q(description__icontains=keyword)
        #     queryset = queryset.filter(q_objects)
        # Without a cap this returned every matching event of the week (~20+).
        parameters['limit'] = int(filter_params.get('limit') or 12)
        parameters['order_by'] = filter_params.get('order_by') or 'score-desc'

        parameters['fields'] = ['id']
        params = EventRequestParameters(**parameters)
        answer = dsn_crud.get_events_by_date_and_category(params)
        return answer['events']

    def generate_post_by_template(self, event_selection_id: int = None, post_template_id: int = None, generated_by_id: int = None) -> Dict[str, Any]:
        # Fetch the post template
        post_template = crud.get_post_template(post_template_id)
        if not post_template:
            raise ValueError("Post template not found")

        event_selection = crud.get_event_selection(event_selection_id)
        selected_event_ids = crud.get_selected_events(event_selection['id'])
        if not selected_event_ids:
            raise ValueError("Selected Events not found for the event selection")

        # Parse JSON string fields from DB
        variables = self._parse_json_field(post_template['variables'])
        if isinstance(variables, str):
            variables = []
        generation_settings = self._parse_json_field(event_selection['generation_settings'])

        variables_to_db = []
        for var in variables:
            if var in VIRTUAL_FIELD_DEPENDENCIES:
                for v in VIRTUAL_FIELD_DEPENDENCIES[var]:
                    if v not in variables_to_db:
                        variables_to_db.append(v)
            else:
                variables_to_db.append(var)

        # Always fetch image fields for collage
        for img_field in ['image', 'image_upload']:
            if img_field not in variables_to_db:
                variables_to_db.append(img_field)

        parameters = {'ids': selected_event_ids, 'fields': variables_to_db}
        params = EventRequestParameters(**parameters)
        selected_events = dsn_crud.get_approved_events(params)

        post_template_parsed = {**post_template, 'variables': variables}
        new_post, headline = self.generate_post(post_template_parsed, selected_events, generation_settings)

        # Create collage from event images
        image_urls = []
        for event in selected_events:
            img = event.get('image_upload') or event.get('image')
            if img and isinstance(img, str) and img.startswith('http'):
                image_urls.append(img)

        collage_result = None
        if image_urls:
            try:
                collage_result = utils.create_collage_and_upload(image_urls)
            except Exception as e:
                log.warning(f"Collage creation failed, continuing without image: {e}")

        # Create a new generated post
        new_post = {
            'title': headline or event_selection['name'],
            'content': new_post,
            'status': 'draft',
            'event_selection_id': event_selection['id'],
            'post_template_id': post_template['id'],
        }
        if collage_result:
            new_post['media_files'] = json.dumps([collage_result['url']])

        new_post = crud.create_generated_post(new_post)

        result = {
            "id": new_post['id'],
            "title": new_post['title'],
            "content": new_post['content'],
            "status": new_post['status'],
        }
        if collage_result:
            result['image'] = collage_result['url']
        return result


    def generate_post(self, post_template: dict, selected_events: list[dict], generation_settings: dict) -> Dict[str, Any]:
        """Generates a post based on the selected events and the post template."""
        divided_text = post_template['template_text'].split("---EVENTS---")
        new_post = ''
        generation_settings['event_count'] = len(selected_events)

        if len(divided_text) == 2:
            new_post, headline = self.generate_introduction(divided_text[0], generation_settings)
            template_events_text = divided_text[1]
        elif len(divided_text) == 1:
            # if 'introduction' in generation_settings:
            #     new_post += self.generate_introduction("", generation_settings)
            # else:
            #     new_post += f"**{post_template['name']}**\n\n"
            new_post, headline = self.generate_introduction("", generation_settings)

            template_events_text = post_template['template_text']

        for event in selected_events:
            new_post += self.generate_event_text(template_events_text, event, post_template['variables']) + "\n\n"
        # TODO: using AI make post
        return new_post, headline

    def generate_event_text(self, template: str, event: dict, variables: list[str] = []):
        if not variables:
            variables = re.findall(r'\{(.*?)\}', template)

        local_from = _to_local(event.get('from_date'))
        local_to = _to_local(event.get('to_date'))

        if 'event_date' in variables and local_from:
            event['event_date'] = date_to_post(local_from, local_to)
        else:
            event['event_date'] = ''

        if 'event_time' in variables and local_from:
            event['event_time'] = local_from.strftime('%H:%M')

        if 'address' in variables and event.get('place'):
            event['address'] = f"{event['place']['place_name']}, {event['place']['place_address']}"
            if event['place'].get('place_metro'):
                event['address'] += f", м.{event['place']['place_metro']}"

        if 'place_name' in variables:
            event['place_name'] = event['place']['place_name'] if event['place'] else event['address'].split(',')[0]

        if 'location' in variables or 'metro' in variables:
            location, metro = _build_location(event)
            event['location'] = location
            event['metro'] = metro

        event_text = template.format(
            **event,
        )
        return event_text

    def generate_introduction(self, template: str, generation_settings: dict):
        # introduction = ""
        # if 'introduction' in generation_settings:
        #     template = generation_settings['introduction'] + "\n" + template

        params = generation_settings or {}

        # Categories
        categories = params.get('main_category')
        if categories and not isinstance(categories, list):
            categories = [categories]
        categories = [category_name(x).strip() for x in (categories or []) if x > 0]
        categories_title = join_list([c.capitalize() for c in categories]) if categories else "Мероприятия"
        categories_nominative = join_list([c for c in categories]) if categories else "мероприятия"

        # Dates / period
        date_from = params.get('date_from')
        date_to = params.get('date_to')
        is_weekend = bool(params.get('weekend'))
        is_this_week = bool(params.get('this_week'))
        is_week_ahead = bool(params.get('week_ahead'))

        # Dates descriptors for templates
        dates_text = ""
        dates_desc = ""
        if is_weekend:
            dates_desc = "выходные"
            if date_from and date_to:
                dates_text = fmt_two_dates(date_from, date_to)
        elif is_this_week:
            dates_desc = "этой неделе"
            if date_from and date_to:
                dates_text = fmt_two_dates(date_from, date_to)
        elif is_week_ahead:
            dates_desc = "ближайшую неделю"
            if date_from and date_to:
                dates_text = fmt_two_dates(date_from, date_to)
        else:
            dates_desc = "ближайшие дни"
            if date_from and date_to:
                dates_text = fmt_two_dates(date_from, date_to)

        price_desc = ""

        if params.get('max_price'):
            if int(params.get('max_price')) == 0:
                price_desc = " c бесплатным входом"
            elif int(params.get('max_price')) <= 1500:
                price_desc = f" с билетами до {params['max_price']}₽"

        # Emoji selection
        emoji_pool = ["✨", "🎉", "📅", "🎟️", "⭐", "🗓️", "🔥", "🧭", "🎭", "🎬", "🎵", "🖼️", "📚"]
        lowered = " ".join(categories).lower() if categories else ""
        if any(k in lowered for k in ["концерт", "музыка"]):
            emoji_pool = ["🎵", "🎶", "🎤", "🎸"]
        elif any(k in lowered for k in ["кино", "кинопоказ"]):
            emoji_pool = ["🎬", "🍿", "📽️"]
        elif any(k in lowered for k in ["выставк"]):
            emoji_pool = ["🖼️", "🎨", "🏛️"]
        elif any(k in lowered for k in ["спектакл"]):
            emoji_pool = ["🎭", "🦕", "🦋"]
        elif any(k in lowered for k in ["лекци"]):
            emoji_pool = ["📚", "🦕", "🎓"]
        emoji = random.choice(emoji_pool)

        # Templates
        HEADLINE_VARIANTS = [
            "{categories_title} на {dates_desc}",
        ]

        DIGEST_VARIANTS = [
            "Подборка из {event_count} интересных {categories_nominative}{price_desc} на {dates_desc}",
            "{event_count} отличных мероприятий{price_desc} на {dates_desc}, как провести время.",
            "Вся подборка {categories_nominative}",
            "Главные {categories_nominative}#{price_desc}.",
            "Лучшие варианты{price_desc} для досуга на {dates_desc}.",
            "Ваш гид по мероприятиям{price_desc} на {dates_desc}.",
        ]

        # Compose randomized parts
        headline_raw = random.choice(HEADLINE_VARIANTS).format(
            categories_title=categories_title.capitalize(),
            categories_nominative=categories_nominative,
            dates_desc=dates_desc
        )

        digest = random.choice(DIGEST_VARIANTS).format(
            categories_title=categories_title.lower(),
            categories_nominative=categories_nominative,
            dates_desc=dates_desc,
            price_desc=price_desc,
            event_count=params.get('event_count', 'множества')
        )

        composed_intro = "{emoji} {headline}\n\n{digest}".format(
            emoji=emoji,
            headline=f"*{headline_raw}*",
            digest=digest,
            dates_text=dates_text or dates_desc
        ).strip()

        introduction = composed_intro + "\n\n"
        if template and template.strip():
            introduction += template.strip() + "\n\n"
        return introduction, headline_raw

    def generate_post_by_ai(self, event_selection_id: int = None, event_ids: list = None, post_template_id: int = None, title: str = None) -> Dict[str, Any]:
        """Generate a digest post using AI instead of templates.

        Accepts either event_selection_id (from saved selection) or event_ids (direct list).
        """
        generation_settings = {}
        event_selection = None

        if event_selection_id:
            event_selection = crud.get_event_selection(event_selection_id)
            selected_event_ids = crud.get_selected_events(event_selection['id'])
            if not selected_event_ids:
                raise ValueError("Selected Events not found for the event selection")
            generation_settings = self._parse_json_field(event_selection['generation_settings'])
        elif event_ids:
            selected_event_ids = event_ids
        else:
            raise ValueError("event_selection_id or event_ids required")

        # Title priority: API param > event_selection name > fallback
        post_title = title or (event_selection.get('name') if event_selection else '') or ''

        fields = [
            'id', 'title', 'prepared_text', 'from_date', 'to_date',
            'address', 'price', 'url', 'ticket_url', 'category', 'place',
            'image', 'image_upload',
        ]
        parameters = {'ids': selected_event_ids, 'fields': fields}
        params = EventRequestParameters(**parameters)
        selected_events = dsn_crud.get_approved_events(params)

        if not selected_events:
            raise ValueError("No events found for the selection")

        events_for_prompt = []
        for event in selected_events:
            e = {
                'title': event.get('title', ''),
                'description': event.get('prepared_text') or event.get('full_text', ''),
                'date': date_to_post(_to_local(event['from_date']), _to_local(event.get('to_date'))) if event.get('from_date') else '',
                'price': event.get('price', ''),
                'url': event.get('url', ''),
                'ticket_url': event.get('ticket_url', ''),
            }
            if event.get('place'):
                place = event['place']
                addr = place.get('place_name', '')
                if place.get('place_address'):
                    addr += f", {place['place_address']}"
                if place.get('place_metro'):
                    addr += f", м.{place['place_metro']}"
                e['address'] = addr
            else:
                e['address'] = event.get('address', '')
            events_for_prompt.append(e)

        events_json = json.dumps(events_for_prompt, ensure_ascii=False, default=str)

        # Context from generation settings
        categories = generation_settings.get('main_category', [])
        if categories and not isinstance(categories, list):
            categories = [categories]
        cat_names = [category_name(c) for c in (categories or []) if isinstance(c, int) and c > 0]
        cat_text = ", ".join(cat_names) if cat_names else "разные"

        period = "ближайшие дни"
        if generation_settings.get('weekend'):
            period = "выходные"
        elif generation_settings.get('this_week'):
            period = "эту неделю"
        elif generation_settings.get('week_ahead'):
            period = "ближайшую неделю"

        CITY_NAMES = {
            'spb': 'Санкт-Петербурге',
            'kzn': 'Казани',
            'msk': 'Москве',
        }
        city_name = CITY_NAMES.get(settings.city, settings.city)

        system_prompt = (
            f"Ты ведёшь Telegram-канал о мероприятиях в {city_name}. "
            "Аудитория — 17–29 лет. "
            "Пиши сдержанно и по делу, как человек, который просто делится находками. "
            "Не продавай, не нахваливай, не кричи. Один восклицательный знак на весь пост — максимум."
        )

        user_prompt = f"""Напиши пост-подборку для Telegram.
Тема: «{post_title}». Мероприятий: {len(events_for_prompt)}.

СТРУКТУРА:
— Вводная — максимум одно предложение. Просто обозначь тему и переходи к делу. Не растягивай, не интригуй, не задавай вопросов читателю.
— Мероприятия — для каждого: название-ссылка, 1-2 предложения своими словами, дата, место, цена.
— Концовка — не нужна. Не пиши призывов, итогов, пожеланий.

ТЕХНИЧЕСКИЕ ТРЕБОВАНИЯ (Telegram MarkdownV2 — канал отправляет именно в ней):
— Название мероприятия — кликабельная ссылка: [Название](url) — можно обернуть в *жирный*
— Если есть ticket_url — используй для ссылки на билеты/цену
— MarkdownV2 требует экранировать обратным слэшем ВСЕ эти символы в обычном тексте
  (включая текст внутри квадратных скобок ссылки): _ * [ ] ( ) ~ ` > # + - = | {{ }} . !
  Например: «Стоимость — 500\\₽\\.» → точка, дефис и прочее обязаны быть экранированы.
  Не экранируй символы внутри (url) — там спецсимвол только ) и \\.
— Компактно, читаемо с телефона

ТОН И СТИЛЬ:
— Спокойный, без восторгов. Описывай что это и зачем идти — без оценок типа "невероятный", "потрясающий", "отрыв".
— Запрещено: восклицательные знаки через предложение, клише ("машина времени", "погрузиться в атмосферу", "что может быть лучше", "бегом за билетами"), продающий тон, риторические вопросы.
— Не описывай каждое мероприятие по одной схеме (крючок → описание → вывод). Варьируй: где-то просто факт, где-то личное мнение, где-то одно предложение.
— Ок: сухой юмор, ирония, субъективность ("на любителя", "если любите тишину", "странное, но цепляет").
— Пост должен читаться как заметка в блокноте, а не как рекламный текст.

Данные мероприятий (JSON):
{events_json}"""

        model_name = settings.content_generator.get('ai_model_name') or DSNParameters().site_parameters('ai_model', last=1)
        ai_helper = AIHelper(model_name)

        try:
            ai_content = ai_helper.generate_text(system_prompt, user_prompt, temperature=0.7, max_tokens=4000)
        except Exception as e:
            log.error(f"AI generation failed: {e}")
            raise ValueError(f"AI generation failed: {e}")

        # Strip markdown fences if AI wrapped the response
        ai_content = ai_content.strip()
        if ai_content.startswith('```'):
            ai_content = ai_content.split('\n', 1)[1] if '\n' in ai_content else ai_content[3:]
            ai_content = ai_content.rsplit('```', 1)[0].strip()

        # Extract headline from first line (truncate to DB limit of 300 chars)
        first_line = ai_content.split('\n')[0].strip()
        headline = re.sub(r'[*_`]', '', first_line).strip()
        if len(headline) > 295:
            headline = headline[:295] + '…'

        # Collect event images and create collage
        image_urls = []
        for event in selected_events:
            img = event.get('image_upload') or event.get('image')
            if img and isinstance(img, str) and img.startswith('http'):
                image_urls.append(img)

        collage_result = None
        if image_urls:
            try:
                collage_result = utils.create_collage_and_upload(image_urls)
            except Exception as e:
                log.warning(f"Collage creation failed, continuing without image: {e}")

        selection_name = event_selection['name'] if event_selection else ''
        generated_post_data = {
            'title': headline or post_title or selection_name,
            'content': ai_content,
            'status': 'draft',
            'post_template_id': post_template_id or None,
        }
        if event_selection:
            generated_post_data['event_selection_id'] = event_selection['id']
        if collage_result:
            generated_post_data['media_files'] = json.dumps([collage_result['url']])

        new_post = crud.create_generated_post(generated_post_data)

        result = {
            "id": new_post['id'],
            "title": new_post['title'],
            "content": new_post['content'],
            "status": new_post['status'],
        }
        if collage_result:
            result['image'] = collage_result['url']
        return result


SCHEDULE_GRACE_MINUTES = 10
SCHEDULE_EARLY_MINUTES = 5


class Posting:

    def __init__(self, log):
        self.log = log

    def get_next_time_posting(self, grace_minutes: int = SCHEDULE_GRACE_MINUTES):
        """Nearest publishable schedule per platform, as UTC etas."""
        time_posting_by_platform = {}

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=grace_minutes)
        stale = crud.count_stale_schedules(cutoff)
        if stale:
            self.log.warning(
                f"{stale} posting schedule(s) missed their slot and are skipped; "
                f"check content_generator_postingschedule for unposted rows"
            )

        next_by_platform = crud.get_next_schedule_per_platform(not_before=cutoff)
        for platform, schedule in next_by_platform.items():
            eta = schedule['scheduled_time']
            if eta is None:
                continue

            tz_name = settings.timezone if settings.timezone else 'UTC'
            tz = pytz.timezone(tz_name)
            if eta.tzinfo is None:
                eta_local = tz.localize(eta)
            else:
                eta_local = eta.astimezone(tz)
            eta_utc = eta_local.astimezone(pytz.UTC)
            time_posting_by_platform[platform] = {'eta_utc': eta_utc, 'schedule_id': schedule['id']}
        return time_posting_by_platform

    def schedule_posting(self, schedule_id):
        schedule = crud.get_schedule_by_id(schedule_id)
        if not schedule:
            self.log.info("Schedule not found")
            return

        # Double-check: skip if already posted
        if schedule.get('is_posted'):
            self.log.info(f"Schedule {schedule_id} already posted, skipping")
            return

        try:
            tz_name = settings.timezone if settings.timezone else 'UTC'
            tz = pytz.timezone(tz_name)
            eta = schedule.get('scheduled_time')
            if eta is None:
                self.log.info("Schedule time is None, skipping")
                return
            if eta.tzinfo is None:
                eta_local = tz.localize(eta)
            else:
                eta_local = eta.astimezone(tz)
            eta_utc = eta_local.astimezone(pytz.UTC)
            now_utc = datetime.now(timezone.utc)

            lateness = now_utc - eta_utc
            if (lateness > timedelta(minutes=SCHEDULE_GRACE_MINUTES)
                    or lateness < -timedelta(minutes=SCHEDULE_EARLY_MINUTES)):
                self.log.info(
                    f"Skipping schedule {schedule_id}: time window mismatch "
                    f"(now={now_utc}, eta={eta_utc}, late by {lateness})"
                )
                return
        except Exception as e:
            self.log.error(f"Error validating schedule time for {schedule_id}: {e}")
            return

        generated_post = crud.get_generated_post_by_id(schedule['generated_post_id'])
        if not generated_post:
            self.log.info("Generated post not found")
            return

        try:

            post_text = generated_post['content']

            # Choose client by platform
            platform = (schedule.get('platform') or 'telegram').lower()

            # media_files holds S3 URLs; the clients send a local file.
            image_path = None
            media_files = GeneratorPost._parse_json_field(generated_post.get('media_files'))
            if isinstance(media_files, list) and media_files:
                try:
                    image_path = utils.prepare_image(media_files[0])
                except Exception as e:
                    self.log.warning(f"Could not prepare media for schedule {schedule_id}: {e}")
                if image_path is None:
                    # prepare_image returns None (not raises) on a failed S3 fetch,
                    # and the post would then go out as text with no word about it.
                    self.log.warning(
                        f"Schedule {schedule_id}: media {media_files[0]} could not be "
                        f"fetched, posting as text without the collage"
                    )

            if platform in ('telegram', 'vk'):
                blob = self._selection_settings(generated_post)
                post = {
                    'platform': platform,
                    'text': post_text,
                    'image_path': image_path,
                    'buttons': self._buttons_from(blob),
                    'format': (blob.get('format') or 'plain'),
                }
                if post['format'] == 'rich' and platform == 'telegram':
                    # In collage mode media_files holds the source posters and the
                    # collage is built here, so nothing has to round-trip through S3.
                    if (blob.get('photos') or 'each') == 'collage':
                        post['image_paths'] = self._collage_media(
                            media_files, schedule_id
                        )
                    else:
                        post['image_paths'] = self._materialise_media(
                            media_files, schedule_id
                        )
                return post
            else:
                self.log.info(f"Unsupported platform: {platform}")
                return

        except Exception as e:
            self.log.error(f"Error posting generated content for schedule {schedule_id}: {e}")
            crud.increment_schedule_retry(schedule_id, error_message=str(e))

    def _selection_settings(self, generated_post):
        """``generation_settings`` of the post's selection, or ``{}``.

        Themed posts keep their rendering details here — the inline button and
        the delivery format. The generated post has no column for either, and
        adding one means a Django-side migration for what is a rendering detail.
        """
        selection_id = generated_post.get('event_selection_id')
        if not selection_id:
            return {}
        try:
            selection = crud.get_event_selection(selection_id) or {}
            blob = GeneratorPost._parse_json_field(selection.get('generation_settings'))
        except Exception as e:
            self.log.warning(f"Could not read settings for selection {selection_id}: {e}")
            return {}
        return blob if isinstance(blob, dict) else {}

    @staticmethod
    def _buttons_from(settings_blob):
        """The post's inline buttons, or ``None``.

        ``buttons`` is a list; ``button`` is the earlier single-button shape and
        is still read so drafts generated before it stay postable.
        """
        blob = settings_blob or {}
        raw = blob.get('buttons')
        if raw is None:
            raw = blob.get('button')
        if isinstance(raw, dict):
            raw = [raw]
        buttons = [
            b for b in (raw or [])
            if isinstance(b, dict) and b.get('text') and b.get('url')
        ]
        return buttons or None

    def _collage_media(self, media_files, schedule_id):
        """One combined picture from the event posters, as a local file path."""
        if not media_files:
            return []
        try:
            collage = utils.create_collage(list(media_files))
        except Exception as e:
            self.log.warning(f"Schedule {schedule_id}: collage failed: {e}")
            return []
        if not collage:
            return []

        path = 'collage.jpg'
        with open(path, 'wb') as handle:
            handle.write(collage)
        return [path]

    def _materialise_media(self, media_files, schedule_id):
        """Download every media URL to a local file, skipping the ones that fail.

        A missing photo costs the post that photo; it must not cost the post.
        """
        paths = []
        for index, url in enumerate(media_files or []):
            try:
                # prepare_image writes one file per call; a shared name would collide.
                path = utils.prepare_image(url, name=f"media_{index}")
            except Exception as e:
                self.log.warning(f"Schedule {schedule_id}: media {url} failed: {e}")
                continue
            if path:
                paths.append(path)
            else:
                self.log.warning(f"Schedule {schedule_id}: media {url} not fetched")
        return paths

    def schedule_posted(self, schedule_id):
        crud.mark_schedule_posted(schedule_id, posted_at=datetime.now(timezone.utc))
