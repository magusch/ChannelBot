from . import database


TAGS_TO_POST = (
    "title",
    "title_date",
    "place_name",
    "post_text",
    "date_from_to",
    "adress",
    "poster_imag",
    "url",
    "price",
)
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
            start_format = (
                f"{s_weekday}, {s_day} {s_month} {s_hour:02}:{s_minute:02}-"
            )
            end_format = f"{e_hour:02}:{e_minute:02}"

        else:
            start_format = f"с {s_day} {s_month} {s_hour:02}:{s_minute:02} "
            end_format = f"по {e_day} {e_month} {e_hour:02}:{e_minute:02}"

    else:
        end_format = ""
        start_format = f"{s_weekday}, {s_day} {s_month} {s_hour:02}:{s_minute:02}"

    return start_format + end_format


def check_post_tags(tags):
    if tags is None:
        raise ValueError("Event tags not found.")

    missing_tags = TAGS_TO_POST - set(tags)

    if missing_tags:
        raise ValueError(
            f"Not found some tags for creating post: {missing_tags}"
        )


def create(event_id):
    """
    Creating post by event_id.

    Parameters:
    -----------
    event_id : int
        event id that exist in postgresql database.

    Returns:
    --------
    photo_url : str
    
    post : str
    """

    event = database.get_event_by_id(event_id)

    title_date = "{day} {month}".format(
        day=event.date_from.day,
        month=month_name(event.date_from),
    )
    date_from_to = date_to_post(event.date_from, event.date_to)
    title = (
        event.title
        .replace("`", "\`")
        .replace("_", "\_")
        .replace("*", "\*")
        .replace(' &quot;', ' «')
        .replace('&quot;', '»')
        .replace(' "', ' «')
        .replace('"', '»')
        .replace('«','*«')
        .replace('»','»*')
    )
    title = f"*{title_date}* {title}\n\n"
    footer = (
        "\n\n"
        f"*Где:* {event.place_name}, {event.adress} \n"
        f"*Когда:* {date_from_to} \n"
        f"*Вход:* [{event.price}]({event.url})"
    )

    post_text = (
        event.post_text.strip()
        .replace("`", "\`")
        .replace("_", "\_")
        .replace("*", "\*")
    )
    full_text = title + post_text + footer

    return "http://" + event.poster_imag, full_text
