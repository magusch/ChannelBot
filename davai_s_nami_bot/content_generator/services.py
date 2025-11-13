from datetime import datetime, timedelta
import json
import random

from typing import List, Dict, Any

from . import crud
from davai_s_nami_bot import crud as dsn_crud

from davai_s_nami_bot.pydantic_models import EventRequestParameters

CATEGORIES_NAME = ["Концерты", "Без категории", "Кино", "Лекции", "Культура", "Фестивали", "Театр", "Вечеринки", "Перфомансы", "Стэндап", "Выставки"]

VIRTUAL_FIELD_DEPENDENCIES = {
    'event_date': ['from_date', 'to_date'],
    'place_name': ['address', 'place'],
    'event_time': ['from_date'],
}

def category_name(cat_id):
    return CATEGORIES_NAME[cat_id-1]


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

    # Make in model ContentGeneratorEventSelection new event selection by random filter set and also put events from Events2Posts to ContentGeneratorEventSelectionSelectedEvents
    def event_selection(self, filter_set_id: int = None) -> dict:
        filter_set = crud.get_filter(filter_set_id)
        if not filter_set:
            raise ValueError("Фильтр не найден")

        filtered_events = self.apply_filters(filter_set)
        if not filtered_events:
            return {}
        
        event_selection_dict = {
            'filter_set_id': filter_set['id'],
            'name':          filter_set['name'],
            'status':       'draft',
            'generation_settings': json.dumps(filter_set['filter_params']),
        }

        event_selection = crud.create_event_selection(event_selection_dict)

        crud.add_selected_events(event_selection, filtered_events)
        return event_selection

    def apply_filters(self, filter_set): # -> models.QuerySet:
        """Apply filter and return filtered events."""
        filter_params = filter_set['filter_params']

        today = datetime.today()
        week_ahead = today + timedelta(days=7)

        parameters = {
            'date_from': today, 'date_to': week_ahead, 'status': 'all'
        }

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
                parameters['price_int'] = int(filter_params['max_price'])
            except (ValueError, TypeError):
                pass

        # if 'keywords' in params:
        #     q_objects = Q()
        #     for keyword in params['keywords']:
        #         q_objects |= Q(title__icontains=keyword) | Q(description__icontains=keyword)
        #     queryset = queryset.filter(q_objects)
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

        variables_to_db = []
        for var in post_template['variables']:
            if var in VIRTUAL_FIELD_DEPENDENCIES:
                for v in VIRTUAL_FIELD_DEPENDENCIES[var]:
                    if v not in variables_to_db:
                        variables_to_db.append(v)
            else:
                variables_to_db.append(var)

        parameters = {'ids': selected_event_ids, 'fields': variables_to_db}
        params = EventRequestParameters(**parameters)
        selected_events = dsn_crud.get_approved_events(params)

        new_post, headline = self.generate_post(post_template, selected_events, event_selection['generation_settings'])
        # Create a new generated post
        new_post = {
            'title': headline or event_selection['name'],
            'content': new_post,
            'status': 'draft',  # Default status
            # 'tags': post_template.tags,
            # 'media_files': post_template.media_files,
            'event_selection_id': event_selection['id'],
            #'generated_by_id': generated_by_id or 1,
            'post_template_id': post_template['id'],
        }
        
        new_post = crud.create_generated_post(new_post)
       
        return {
            "id": new_post['id'],
            "title": new_post['title'],
            "content": new_post['content'],
            "status": new_post['status']
        }


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

        if 'event_date' in variables and event.get('from_date'):
            event['event_date'] = date_to_post(event['from_date'], event.get('to_date'))
        else:
            event['event_date'] = ''

        if 'event_time' in variables and event.get('from_date'):
            event['event_time'] = event['from_date'].strftime('%H:%M')

        if 'address' in variables and event.get('place'):
            event['address'] = f"{event['place']['place_name']}, {event['place']['place_address']}"
            if event['place'].get('place_metro'):
                event['address'] += f", м.{event['place']['place_metro']}"

        if 'place_name' in variables:
            event['place_name'] = event['place']['place_name'] if event['place'] else event['address'].split(',')[0]

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
            "Подборка из {count_event} интересных {categories_nominative}{price_desc} на {dates_desc}",
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
