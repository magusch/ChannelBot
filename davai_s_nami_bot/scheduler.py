from datetime import timedelta, datetime
import random
import pytz
import os

from telebot import TeleBot
from prefect.schedules import filters
from prefect.schedules.schedules import Schedule
from prefect.schedules.clocks import IntervalClock
from prefect import Flow, Task

from .utils import get_token
from . import database
from . import notion_api
from . import events
from . import posting


MSK_TZ = pytz.timezone('Europe/Moscow')
MSK_UTCOFFSET = datetime.now(MSK_TZ).utcoffset()
CHANNEL_ID = os.environ.get("CHANNEL_ID")
DEV_CHANNEL_ID = os.environ.get("DEV_CHANNEL_ID")
bot = TeleBot(token=get_token(), parse_mode="Markdown")


class MoveApproved(Task):
    def run(self):
        global utc_today, msk_today
        utc_today = datetime.utcnow()
        msk_today = datetime.now()

        print("Move approved events from table1 and table2 to table3")
        notion_api.move_approved()


class IsEmptyCheck(Task):
    """
    Checking events in table3: if empty, send warning message to dev channel.
    """
    def run(self):
        not_published_count = notion_api.not_published_count()

        if not_published_count == 1:
            text = "Warning: last event left."

        elif not_published_count == 0:
            text = (
                "Warning: not found events for posting, skip."
            )

        bot.send_message(chat_id=DEV_CHANNEL_ID, text=text)


class PostingEvent(Task):
    def run(self):
        if utc_today.strftime("%H:%M") in strftimes_weekday + strftimes_weekend:
            print("Generating post.")

            event_id = notion_api.next_event_id_to_channel()

            if event_id:
                photo_url, post = posting.create(event_id)

                if photo_url is None:
                    message = bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=post,
                        disable_web_page_preview=True,
                    )
                else:
                    message = bot.send_photo(
                        chat_id=CHANNEL_ID,
                        photo=photo_url,
                        caption=post,
                    )

                post_id = message.message_id
                database.update_post_id(event_id, post_id)


class UpdateEvents(Task):
    def run(self):
        if utc_today.strftime("%H:%M") == strftime_event_updating:
            print("Start updating events.")

            print("Removing old events from postgresql...")
            database.remove_old_events(utc_today)
            print("Removing old events from notion table...")
            notion_api.remove_old_events(msk_today + timedelta(hours=1))
            print("Done.")

            print("Getting new events for next 7 days...")
            today_events = events.next_days(days=7)

            event_count = len(today_events)
            print(f"Done. Collected {event_count} events")

            print("Checking for existing events")
            existing_events_ids = database.get_existing_events_id(today_events)
            print(f"Existing events count = {len(existing_events_ids)}")

            new_events = [i for i in today_events if i.id not in existing_events_ids]
            print(f"New evenst count = {len(new_events)}")

            print("Start updating postgresql...")
            database.add(new_events)

            print("Start updating notion table...")
            notion_api.add_events(today_events, existing_events_ids, msk_today)

            print("Done.")


def scheduling_filter(dt):
    strftime = dt.strftime("%H:%M")
    return (
        filters.is_weekend(dt) and strftime in strftimes_weekend
        or filters.is_weekday(dt) and strftime in strftimes_weekday
        or strftime == strftime_event_updating
    )


def convert_to_utc(scheduled_times, utcoffset):
    for i, dt in enumerate(scheduled_times):
        scheduled_times[i] = dt - timedelta(seconds=utcoffset.seconds)

    return scheduled_times


def get_strftimes(scheduled_times):
    strftimes = list()
    for dt in scheduled_times:
        utc_dt = dt - timedelta(seconds=MSK_UTCOFFSET.seconds)
        strftimes.append(f"{utc_dt.hour:02}:{utc_dt.minute:02}")

    return strftimes


def run():
    seconds = dict(second=00, microsecond=00)
    today = datetime.utcnow().replace(**seconds)

    weekday_posting_times = [
        today.replace(hour=9, minute=30),
        today.replace(hour=12, minute=00),
        today.replace(hour=14, minute=20),
        today.replace(hour=16, minute=30),
    ]
    weekend_posting_times = [
        today.replace(hour=11, minute=00),
        today.replace(hour=12, minute=30),
        today.replace(hour=14, minute=40),
        today.replace(hour=17, minute=00),
    ]
    everyday_posting_times = [
        today.replace(hour=18, minute=40),
    ]
    everyday_task_times = [
        today.replace(hour=00, minute=00),
    ]

    global strftimes_weekday, strftimes_weekend, strftime_event_updating

    strftime_event_updating = get_strftimes([today.replace(hour=00, minute=00)])[0]
    strftimes_weekday = get_strftimes(weekday_posting_times+everyday_posting_times)
    strftimes_weekend = get_strftimes(weekend_posting_times+everyday_posting_times)

    all_task_times = convert_to_utc(
        scheduled_times=(
            weekday_posting_times
            + weekend_posting_times
            + everyday_posting_times
            + everyday_task_times
        ),
        utcoffset=MSK_UTCOFFSET,
    )

    schedule_clocks = [
        IntervalClock(
            interval=timedelta(days=1),
            start_date=today.replace(hour=i.hour, minute=i.minute)
        )
        for i in all_task_times
    ]

    schedule = Schedule(clocks=schedule_clocks, filters=[scheduling_filter])

    text = (
        "I'm running. First scheduled task in {} (MSK)"
        .format(schedule.next(1)[0].astimezone(MSK_TZ).strftime("%H:%M"))
    )
    bot.send_message(chat_id=DEV_CHANNEL_ID, text=text)

    flow = Flow(
        name="DavaiSNami",
        schedule=schedule,
        tasks=[MoveApproved(), IsEmptyCheck(), PostingEvent(), UpdateEvents()]
    )

    flow.run()
