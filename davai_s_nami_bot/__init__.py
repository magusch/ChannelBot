from telebot import TeleBot

from .utils import get_token
from . import database, notion_api, events, posting


bot = TeleBot(token=get_token(), parse_mode="Markdown")
