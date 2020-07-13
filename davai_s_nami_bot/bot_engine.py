from datetime import datetime
import random
import os

from telebot import TeleBot

from .utils import get_token
from . import notion_api
from . import events
from . import database
from . import posting


BOT_TOKEN = get_token()
bot = TeleBot(token=BOT_TOKEN, parse_mode="Markdown")
CHANNEL_ID = os.environ.get("CHANNEL_ID")


@bot.message_handler(commands=["update"])
def update(incoming_msg):
    uid = incoming_msg.from_user.id
    today = datetime.now()

    bot.send_message(chat_id=uid, text="Removing old events from postgresql...")
    database.remove_old_events(today)
    bot.send_message(chat_id=uid, text="Removing old events from notion table...")
    notion_api.remove_old_events(today)
    bot.send_message(chat_id=uid, text="Done.")

    bot.send_message(chat_id=uid, text="Getting new events for next 7 days...")
    today_events = events.next_days(days=7)

    event_count = len(today_events)
    bot.send_message(chat_id=uid, text=f"Done. Collected {event_count} events")

    bot.send_message(chat_id=uid, text="Checking for existing events")
    existing_events_ids = database.get_existing_events_id(today_events)
    bot.send_message(chat_id=uid, text=f"Existing events count = {len(existing_events_ids)}")

    new_events = [i for i in today_events if i.id not in existing_events_ids]
    bot.send_message(chat_id=uid, text=f"New evenst count = {len(new_events)}")

    bot.send_message(chat_id=uid, text="Start updating postgresql...")
    database.add(new_events)

    bot.send_message(chat_id=uid, text="Start updating notion table...")
    notion_api.add_events(today_events, existing_events_ids)

    bot.send_message(chat_id=uid, text="Done.")


@bot.message_handler(commands=["test_post"])
def test_post(incoming_msg):
    event_id = random.choice(notion_api.all_event_ids())

    photo_url, post = posting.create(event_id)

    if photo_url is None:
        mess=bot.send_message(chat_id=CHANNEL_ID, text=post, disable_web_page_preview=True)
    else:
        mess=bot.send_photo(chat_id=CHANNEL_ID, photo=photo_url, caption=post)

    post_id=mess.message_id
    database.update_post_id(event_id, post_id)

@bot.message_handler(content_types=["text"])
def reply_to_text(incoming_msg):
    uid = incoming_msg.from_user.id
    text = incoming_msg.text

    bot.send_message(chat_id=uid, text=text)
