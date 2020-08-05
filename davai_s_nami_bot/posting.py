import re


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

    title = re.sub(r"[\"«](?=[^\ \.!\n])", "*«", event.Title)
    title = re.sub(r"[\"»](?=[^a-zA-Zа-яА-Я0-9]|$)", "»*", title)

    title_date = "{day} {month}".format(
        day=event.From_date.start.day,
        month=month_name(event.From_date.start),
    )
    title = f"*{title_date}* {title}\n\n"
    footer = (
        "\n\n"
        f"*Где:* {event.Where} \n"
        f"*Когда:* {event.When} \n"
        f"*Вход:* [{event.Ticket}]({event.URL})"
    )

    full_text = title + event.Post + footer

    return event.Image, full_text


def parse_title(event):
    title = (
        event.title
        .replace("`", "\`")
        .replace("_", "\_")
        .replace("*", "\*")
    )

    return title


def parse_post(event):
    return (
        event.post_text.strip()
        .replace("`", "\`")
        .replace("_", "\_")
        .replace("*", "\*")
    )


def parse_from_date(event):
    return event.date_from


def parse_event_id(event):
    return event.id


def parse_image(event):
    return "http://" + event.poster_imag


def parse_url(event):
    return event.url


def parse_ticket(event):
    return event.price


def parse_where(event):
    return f"{event.place_name}, {event.adress}"


def parse_when(event):
    date_from_to = date_to_post(event.date_from, event.date_to)
    return f"{date_from_to}"
