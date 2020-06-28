from telebot import TeleBot

from .utils import get_token
from .collecting_events import update_database


BOT_TOKEN = get_token()
bot = TeleBot(BOT_TOKEN)


@bot.message_handler(commands=["start"])
def start_message(incoming_msg):
    uid = incoming_msg.from_user.id
    text = incoming_msg.text
    bot.send_message(chat_id=uid, text=incoming_msg)


@bot.message_handler(content_types=["text"])
def reply_to_text(incoming_msg):
    uid = incoming_msg.from_user.id
    text = incoming_msg.text

    if text == "update":
        update_database()
    else:
        bot.send_message(chat_id=uid, text=text)
