import os
import re

import pytz

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .dsn_parameters import DSNParameters
from .markdown_v2 import escape_v2, escape_v2_url
from ..scoring import resolve_category_id


@dataclass
class PlaceView:
    """Pure view object for a venue, used by PostHelper. No SQLAlchemy coupling."""
    id: int
    name: str
    address: str
    url: str = ''
    metro: str = ''
    schedule_str: Optional[str] = None


TELEGRAM_BOT_NAME = os.environ.get("TELEGRAM_BOT_NAME", None)

EXHIBITION_CATEGORY_ID = 11
EXHIBITION_MIN_DAYS = 8


WEEKNAMES = {
    0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт",
    4: "Пт", 5: "Сб", 6: "Вск",
}

MONTHNAMES = {
    1: "января",   2: "февраля",  3: "марта",
    4: "апреля",   5: "мая",      6: "июня",
    7: "июля",     8: "августа",  9: "сентября",
    10: "октября", 11: "ноября",  12: "декабря",
}


def weekday_name(dt):
    return WEEKNAMES[dt.weekday()]


def month_name(dt):
    return MONTHNAMES[dt.month]


class DictAsMethods:
    """Wraps a dict into an object with attribute-style access."""
    def __init__(self, data):
        self.__dict__['data'] = data

    def __getattr__(self, name):
        if name in self.data:
            return self.data[name]
        raise AttributeError(f"'DictAsMethods' has no attribute '{name}'")

    def __setattr__(self, name, value):
        if name == 'data':
            super().__setattr__(name, value)
        else:
            self.data[name] = value

    def __contains__(self, name):
        return name in self.data


class PostHelper:
    """Pure post formatter. Does not access the database.

    The place (PlaceView) must be resolved externally
    (via crud._resolve_place_view) and passed to the constructor.
    """
    def __init__(self, event, place: Optional[PlaceView] = None):
        """
        Args:
            event: dict or ORM object representing the event.
            place: optional PlaceView. If None, the address in the post
                   will be formatted from the raw event.address string.
        """
        self.TIMEZONE = pytz.timezone("Europe/Moscow")
        if isinstance(event, dict):
            event = DictAsMethods(event)
        self.event = event
        self.place = place
        self.dates_to_right_tz()

        self.param_manager = DSNParameters()

    @staticmethod
    def price_int(price_str: str) -> int:
        """Extract numeric price. 0 — free, -1 — cannot parse, otherwise min price."""
        if not price_str:
            return -1
        if "бесплатн" in price_str.lower():
            return 0
        prices = re.findall(r"\d+", price_str)
        if len(prices) == 1:
            return int(prices[0])
        elif len(prices) > 1:
            prices = [int(p) for p in prices if int(p) > 100 or int(p) == 0]
            if prices:
                return min(prices)
        return -1

    def _safe_get(self, name, default=None):
        """Safe attribute access — returns default if attribute missing or None."""
        try:
            value = getattr(self.event, name)
            return value if value is not None else default
        except AttributeError:
            return default

    def dates_to_right_tz(self):
        msk = self.TIMEZONE
        for field in ('from_date', 'to_date'):
            val = self._safe_get(field)
            if val is None:
                continue
            if isinstance(val, str):
                val = datetime.fromisoformat(val)
            if val.tzinfo is None:
                val = msk.localize(val)
            else:
                val = val.astimezone(msk)
            setattr(self.event, field, val)

    def _is_long_exhibition(self):
        main_cat_id = self._safe_get('main_category_id')
        if main_cat_id is None or main_cat_id == '':
            return False
        try:
            if int(main_cat_id) != EXHIBITION_CATEGORY_ID:
                return False
        except (ValueError, TypeError):
            return False
        date_from = self._safe_get('from_date')
        date_to = self._safe_get('to_date')
        if date_to is None or date_from is None:
            return False
        return (date_to - date_from).days >= EXHIBITION_MIN_DAYS

    def _get_exhibition_schedule(self):
        # 1. From the resolved PlaceView
        if self.place and self.place.schedule_str:
            return self.place.schedule_str

        # 2. Fallback: schedule derived from the event's time range
        date_from = self._safe_get('from_date')
        date_to = self._safe_get('to_date')
        if date_from and date_to:
            s_hour, s_minute = date_from.hour, date_from.minute
            e_hour, e_minute = date_to.hour, date_to.minute
            if s_hour != 0 or s_minute != 0 or e_hour != 0 or e_minute != 0:
                day_from = WEEKNAMES[date_from.weekday()]
                day_to = WEEKNAMES[date_to.weekday()]
                return f"{day_from}-{day_to} {s_hour:02}:{s_minute:02}–{e_hour:02}:{e_minute:02}"

        return None

    def _title_markdown(self):
        title = self.event.title
        title = re.sub(r"[\"’](\S.*?)[\"’]", r"«\1»", title)
        title = escape_v2(title)

        if '«' in title and '»' in title:
            pattern = r'(«[^»]*»)'
            title = re.sub(pattern, r'*\1*', title)
        elif re.search(r'[A-Za-z]', title):
            pattern = r'(\b[A-Za-z0-9]+\b(?: \b[A-Za-z0-9]+\b)*)'
            title = re.sub(pattern, r'*\1*', title)
        elif re.search(r'[A-ZА-Я]{3,}', title):
            pattern = r'(\b[A-ZА-Я]{3,}\b(?: \b[A-ZА-Я0-9]{1,}\b)*)'
            title = re.sub(pattern, r'*\1*', title)
        else:
            title = f"{title[0]}*{title[1:]}*"

        return title

    def post_markdown(self) -> str:
        title = self._title_markdown()
        date_from_to = self.date_to_post()
        title_date = self.date_to_title()

        full_title = f"*{title_date}* {title}\n\n"

        prepared_text = self._safe_get('prepared_text')
        full_text = self._safe_get('full_text')

        if not prepared_text and not full_text:
            post_text = ""
        elif not prepared_text:
            post_text = self.reduce_text(full_text)
        else:
            post_text = self.reduce_text(prepared_text)

        post_text = escape_v2(post_text.strip())

        address_line = self.address_markdown()

        footer_link = self.param_manager.site_parameters('finish_link', last=1)
        footer_link = escape_v2(footer_link) if footer_link else ''

        remind_link = ''
        event_id = self._safe_get('id')
        if TELEGRAM_BOT_NAME and event_id:
            bot_url = escape_v2_url(f"https://t.me/{TELEGRAM_BOT_NAME}?start=save-{event_id}")
            remind_link = f"\\|\\| [Сохранить в боте]({bot_url})"

        ticket_url = self._safe_get('ticket_url')
        event_url = ticket_url if ticket_url else self._safe_get('url', '')

        escaped_price = escape_v2(self._safe_get('price', ''))
        escaped_event_url = escape_v2_url(event_url)
        escaped_date = escape_v2(date_from_to)

        footer = (
            "\n\n"
            f"*Где:* {address_line}\n"
            f"*Когда:* {escaped_date} \n"
            f"*Вход:* [{escaped_price}]({escaped_event_url})"
            f"\n\n{footer_link} {remind_link}"
        )

        full_post = (full_title + post_text.strip() + footer).strip()
        return full_post

    def address_markdown(self):
        need_url_param = self.param_manager.site_parameters('need_address_line_url', last=1)
        need_url = False
        if need_url_param:
            need_url = need_url_param.lower() in ('true', '1')

        if self.place:
            name_addr = escape_v2(f"{self.place.name}, {self.place.address}")
            if self.place.url and need_url:
                url = escape_v2_url(self.place.url)
                result = f"[{name_addr}]({url})"
            else:
                result = name_addr
            if self.place.metro:
                result += escape_v2(f", м.{self.place.metro}")
            return result

        raw_address = self._safe_get('address')
        if not raw_address:
            return ''

        escaped_addr = escape_v2(raw_address)
        if need_url:
            addr_url = escape_v2_url(f"https://2gis.ru/spb/search/{raw_address}")
            return f"[{escaped_addr}]({addr_url})"
        return escaped_addr

    def date_to_title(self):
        date_from = self._safe_get('from_date')
        date_to = self._safe_get('to_date')

        if self._is_long_exhibition():
            return "До {day} {month}".format(
                day=date_to.day,
                month=month_name(date_to),
            )

        if date_to is None:
            return "{day} {month}".format(day=date_from.day, month=month_name(date_from))
        elif date_from.month != date_to.month:
            return "{day_s} {month_s} – {day_e} {month_e}".format(
                day_s=date_from.day, month_s=month_name(date_from),
                day_e=date_to.day, month_e=month_name(date_to),
            )
        elif date_to.day - date_from.day == 1:
            return "{day_s} и {day_e} {month_s}".format(
                day_s=date_from.day, month_s=month_name(date_from), day_e=date_to.day,
            )
        elif date_from.day != date_to.day:
            return "{day_s} – {day_e} {month_s}".format(
                day_s=date_from.day, month_s=month_name(date_from), day_e=date_to.day,
            )
        else:
            return "{day} {month}".format(day=date_from.day, month=month_name(date_from))

    def date_to_post(self):
        if self._is_long_exhibition():
            schedule = self._get_exhibition_schedule()
            if schedule:
                return schedule

        date_from = self._safe_get('from_date')
        date_to = self._safe_get('to_date')

        s_weekday = weekday_name(date_from)
        s_day = date_from.day
        s_month = month_name(date_from)
        s_hour = date_from.hour
        s_minute = date_from.minute

        if date_to is not None:
            e_weekday = weekday_name(date_to)
            e_day = date_to.day
            e_month = month_name(date_to)
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

    def main_category(self):
        """Resolve textual category → main_category_id."""
        category_str = self._safe_get('category')
        if not category_str:
            return None
        return resolve_category_id(
            main_category_id=self._safe_get('main_category_id'),
            category_str=category_str,
            title=self._safe_get('title', ''),
            full_text=self._safe_get('full_text', ''),
        )

    def reduce_text(self, post_text):
        if not post_text:
            return ''
        if len(post_text) > 550:
            sentences = post_text.split(".")
            post = ""
            for s in sentences:
                if len(post) < 365:
                    post = post + s + "."
                else:
                    post_text = post.strip()
                    break
        return post_text
