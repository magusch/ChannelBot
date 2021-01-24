import re
from datetime import timedelta

WEEKNAMES = {
    0: "Пн",
    1: "Вт",
    2: "Ср",
    3: "Чт",
    4: "Пт",
    5: "Сб",
    6: "Вск",
}
MONTHNAMES = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}
MIN_POSTING_HOUR_INTERVAL = 2  # minimum hour between two posting times


def weekday_name(dt):
    return WEEKNAMES[dt.weekday()]


def month_name(dt):
    return MONTHNAMES[dt.month]


def date_to_post(date_from, date_to):
    s_weekday = weekday_name(date_from)
    s_day = date_from.day
    s_month = month_name(date_from)
    s_hour = date_from.hour
    s_minute = date_from.minute

    if date_to is not None:
        e_day = date_to.day
        e_month = month_name(date_to)
        e_hour = date_to.hour
        e_minute = date_to.minute

        if s_day == e_day:
            start_format = f"{s_weekday}, {s_day} {s_month} {s_hour:02}:{s_minute:02}-"
            end_format = f"{e_hour:02}:{e_minute:02}"

        else:
            start_format = f"с {s_day} {s_month} {s_hour:02}:{s_minute:02} "
            end_format = f"по {e_day} {e_month} {e_hour:02}:{e_minute:02}"

    else:
        end_format = ""
        start_format = f"{s_weekday}, {s_day} {s_month} {s_hour:02}:{s_minute:02}"

    return start_format + end_format


def create(event):
    """
    Creating post by event (namedtuple).

    Parameters:
    -----------
    event : namedtuple
        event that exist in table.

    Returns:
    --------
    photo_url : str

    post : str
    """

    post = event.Post.replace("__", "*").replace("] (", "](").replace("_", r"\_")

    # simetimes event.Image has invalid value [["a"]]
    if event.Image is None or isinstance(event.Image, list):
        image = None

    else:
        image = event.Image

    return image, post


def parse_title(event):
    title = event.title.replace("`", r"\`").replace("_", r"\_").replace("*", r"\*")

    return title


def parse_post(event):
    title = parse_title(event)

    title = re.sub(r"[\"«](?=[^\ \.!\n])", "**«", title)
    title = re.sub(r"[\"»](?=[^a-zA-Zа-яА-Я0-9]|$)", "»**", title)

    date_from_to = date_to_post(event.date_from, event.date_to)

    title_date = "{day} {month}".format(
        day=event.date_from.day,
        month=month_name(event.date_from),
    )

    title = f"**{title_date}** {title}\n\n"

    post_text = (
        event.post_text.strip()
        .replace("`", r"\`")
        .replace("_", r"\_")
        .replace("*", r"\*")
    )

    footer = (
        "\n\n"
        f"**Где:** {event.place_name}, {event.adress} \n"
        f"**Когда:** {date_from_to} \n"
        f"**Вход:** [{event.price}] ({event.url})"
    )

    return title + post_text + footer


def parse_price(event):
    return event.price


def parse_url(event):
    return event.url


def parse_from_date(event):
    return event.date_from


def parse_to_date(event):
    if event.date_to is None:
        return event.date_from + timedelta(hours=2)

    return event.date_to


def parse_image(event):
    if event.poster_imag:
        if event.id.startswith("TIMEPAD"):
            return "http://" + event.poster_imag

        return event.poster_imag


def parse_id(event):
    return event.id
