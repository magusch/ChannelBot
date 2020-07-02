
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


def check_post_tags(tags):
    if tags is None:
        raise ValueError("Event tags not found.")

    missing_tags = TAGS_TO_POST - set(tags)

    if missing_tags:
        raise ValueError(
            f"Not found some tags for creating post: {missing_tags}"
        )


def create(ed):
    """
    Creating post by raw data.

    Parameters:
    -----------
    ed : namedtuple
        parsers.EventData
    """

    if ed.poster_imag is None:
        imag = ""
    else:
        imag = f"[ ]({ed.poster_imag}) "

    title = f"{imag}*{ed.title_date}* {ed.title}\n\n"

    footer = (
        "\n"
        f"*Где:* {ed.place_name}, {ed.adress} \n"
        f"*Когда:* {ed.date_from_to} \n"
        f"*Вход:* [{ed.price}]({ed.url})"
    )

    # if ed.price==:
    #     footer +=f'Регистрация ограничена: [подробности](ed.url)'
    # elif ed.price==0:
    #     footer +=f'*Вход свободный* [по предварительной регистрации]({ed.url})'
    # elif ed.price>0:
    #     footer +=f'*Вход:* [от {ed.price}₽]({ed.url})'

    full_text = title + ed.post_text + footer
    return full_text
