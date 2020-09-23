import os

from telebot import TeleBot


def get_bot():
    return TeleBot(
        token=os.environ.get("BOT_TOKEN"),
        parse_mode="Markdown",
    )
