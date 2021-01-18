import os
from io import BytesIO

import PIL
import requests
from PIL import Image
from telebot import TeleBot

from . import database, logger, posting

TO_CHANNEL = dict(
    dev=os.environ.get("DEV_CHANNEL_ID"),
    prod=os.environ.get("CHANNEL_ID"),
)
IMG_MAXSIZE = (1920, 1080)

bot = TeleBot(
    token=os.environ.get("BOT_TOKEN"),
    parse_mode="Markdown",
)


def get_bot():
    return TeleBot(
        token=os.environ.get("BOT_TOKEN"),
        parse_mode="Markdown",
    )


def send_logs():
    with open(logger.LOG_FILE, "r+b") as logs:
        bot.send_document(TO_CHANNEL["dev"], logs)
        logs.truncate(0)
        logs.write(b"")


def send_message(text, channel):
    """
    Parameters:
    -----------
    msg : str
        Send message.

    channel : str
        'dev' or 'prod'
    """
    return bot.send_message(
        chat_id=TO_CHANNEL[channel],
        text=text,
        disable_web_page_preview=True,
    )


def send_post(event):
    photo_url, post = posting.create(event)

    if photo_url is None:
        message = send_message(text, channel="prod")

    else:
        with Image.open(BytesIO(requests.get(photo_url).content)) as img:
            photo_name = "img"
            img.thumbnail(IMG_MAXSIZE, PIL.Image.ANTIALIAS)

            if img.mode != "RGB":
                img = img.convert("RGB")

            # TODO: if line above work fine, this isn't necessary
            if img.mode == "CMYK":
                # can't save CMYK as PNG
                img.save(photo_name + ".jpg", "jpeg")
                photo_path = photo_name + ".jpg"

            else:
                img.save(photo_name + ".png", "png")
                img.save(photo_name + ".jpg", "jpeg")

                image_size = os.path.getsize(photo_name + ".png") / 1_000_000

                if image_size > 5:
                    photo_path = photo_name + ".jpg"
                else:
                    photo_path = photo_name + ".png"

            with open(photo_path, "rb") as photo:
                message = bot.send_photo(
                    chat_id=TO_CHANNEL["prod"],
                    photo=photo,
                    caption=post,
                )

            os.remove(photo_name + ".jpg")
            os.remove(photo_name + ".png")

    post_id = message.message_id
    database.add(event, post_id)
