import os

from telebot import TeleBot


bot = TeleBot(token=os.environ.get("BOT_TOKEN"), parse_mode="Markdown")
