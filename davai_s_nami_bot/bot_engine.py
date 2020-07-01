from telebot import TeleBot

from .utils import get_token
from . import notion_api
from . import events
from . import database


BOT_TOKEN = get_token()
bot = TeleBot(BOT_TOKEN)


@bot.message_handler(commands=["update"])
def update(incoming_msg):
    uid = incoming_msg.from_user.id

    bot.send_message(chat_id=uid, text="Getting new events...")
    today_events = events.today()

    event_count = len(today_events)
    bot.send_message(chat_id=uid, text=f"Done. Collected {event_count} events")

    bot.send_message(chat_id=uid, text="Start updating postgresql...")
    existing_event_ids = database.update(today_events)
    bot.send_message(
        chat_id=uid, text=f"Done. Existing events = {len(existing_event_ids)}"
    )

    bot.send_message(
        chat_id=uid, text="Start updating notion table (without existing)..."
    )
    notion_api.add_events(today_events, existing_event_ids)
    bot.send_message(chat_id=uid, text="Done.")


@bot.message_handler(content_types=["text"])
def reply_to_text(incoming_msg):
    uid = incoming_msg.from_user.id
    text = incoming_msg.text

    bot.send_message(chat_id=uid, text=text)
