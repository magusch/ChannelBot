from datetime import timedelta, datetime
import logging
import random
import pytz
import os
from io import BytesIO

from PIL import Image
import requests
from telebot import TeleBot
import prefect
from prefect.core import Edge
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
LOG_FILE = "bot_logs.txt"


class MoveApproved(Task):
    def run(self):
        log = prefect.utilities.logging.get_logger("TaskRunner.MoveApproved")

        global utc_today, msk_today
        utc_today = datetime.utcnow()
        msk_today = datetime.now()

        log.info("Move approved events from table1 and table2 to table3")
        notion_api.move_approved(log=log)


class IsEmptyCheck(Task):
    """
    Checking events in table3: if empty, send warning message to dev channel.
    """
    def run(self):
        not_published_count = notion_api.not_published_count()
        text = None

        if not_published_count == 1:
            text = "Warning: last event left."

        elif not_published_count == 0:
            text = (
                "Warning: not found events for posting."
            )

        if text:
            bot.send_message(chat_id=DEV_CHANNEL_ID, text=text)


class PostingEvent(Task):
    def run(self):
        log = prefect.utilities.logging.get_logger("TaskRunner.PostingEvent")

        if utc_today.strftime("%H:%M") in strftimes_weekday + strftimes_weekend:
            log.info("Generating post.")

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

                    with Image.open(BytesIO(requests.get(photo_url).content)) as img:
                        photo_name = str(event_id)
                        img.save(photo_name + ".png", "png")
                        img.save(photo_name + ".jpg", "jpeg")

                        image_size = os.path.getsize(photo_name + ".png") / 1_000_000

                        if image_size > 5:
                            photo_path = photo_name + ".jpg"
                        else:
                            photo_path = photo_name + ".png"

                        with open(photo_path, "rb") as photo:
                            message = bot.send_photo(
                                chat_id=CHANNEL_ID,
                                photo=photo,
                                caption=post,
                            )

                        os.remove(photo_name + ".jpg")
                        os.remove(photo_name + ".png")

                post_id = message.message_id
                database.update_post_id(event_id, post_id)


class UpdateEvents(Task):
    def run(self):
        log = prefect.utilities.logging.get_logger("TaskRunner.UpdateEvents")

        if utc_today.strftime("%H:%M") in strftime_event_updating:
            log.info("Start updating events.")

            log.info("Removing old events from postgresql")
            removing_ids = database.old_events(utc_today)
            database.remove(removing_ids)

            log.info("Removing old events from notion table")
            notion_api.remove_old_events(removing_ids, msk_today + timedelta(hours=1), log=log)

            log.info("Getting new events for next 7 days")
            today_events = events.next_days(days=7, log=log)

            event_count = len(today_events)
            log.info(f"Done. Collected {event_count} events")

            log.info("Checking for existing events")
            new_events_id = database.get_new_events_id(today_events)

            new_events = [i for i in today_events if i.id in new_events_id]
            log.info(f"New evenst count = {len(new_events)}")

            log.info("Start updating postgresql")
            database.add(new_events)

            log.info("Start updating notion table")
            notion_api.add_events(new_events, msk_today, log=log)

            db_count = database.events_count()
            notion_count = notion_api.events_count()

            log.info(f"Events count in database: {db_count}")
            log.info(f"Events count in notion table: {notion_count}")

            if db_count != notion_count:
                log.warn("The number of events does not match.")


class Formatter(logging.Formatter):
    def send_logs(self):
        with open(LOG_FILE, "rb") as logs:
            bot.send_document(DEV_CHANNEL_ID, logs)

        with open(LOG_FILE, "w") as logs:
            logs.write("")

    def converter(self, timestamp):
        dt = datetime.fromtimestamp(timestamp)

        return MSK_TZ.localize(dt)

    def format(self, record):
        if record.name == "prefect.DavaiSNami":
            str_time = record.message[-25:]
            message = record.message[:-25]

            dt = datetime.strptime(str_time, "%Y-%m-%dT%H:%M:%S%z") + MSK_UTCOFFSET
            message += dt.strftime("%Y-%m-%dT%H:%M:%S")

            bot.send_message(DEV_CHANNEL_ID, text=message)
            self.send_logs()

        else:
            message = record.message

        if record.exc_info:
            message += record.exc_text


        return self._fmt % dict(
            asctime=self.formatTime(record),
            levelname=record.levelname,
            name=record.name,
            message=message,
        )

    def formatTime(self, record, datefmt="%Y-%m-%dT%H:%M:%S"):
        dt = self.converter(record.created)
        if datefmt:
            s = dt.strftime(datefmt)
        else:
            try:
                s = dt.isoformat(timespec="milliseconds")
            except TypeError:
                s = dt.isoformat()
        return s


def scheduling_filter(dt):
    strftime = dt.strftime("%H:%M")
    return (
        filters.is_weekend(dt) and strftime in strftimes_weekend
        or filters.is_weekday(dt) and strftime in strftimes_weekday
        or strftime in strftime_event_updating
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

    strftime_event_updating = get_strftimes(everyday_task_times)
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

    # create tasks graph
    move_approved = MoveApproved()
    is_empty_check = IsEmptyCheck()
    posting_event = PostingEvent()
    update_events = UpdateEvents()

    edges = [
        Edge(move_approved, is_empty_check),
        Edge(is_empty_check, posting_event),
        Edge(posting_event, update_events),
    ]

    flow = Flow(
        name="DavaiSNami",
        schedule=schedule,
        edges=edges,
    )

    # prepare logging
    prefect_logger = prefect.utilities.logging.get_logger()
    prefect_formatter = prefect_logger.handlers[0].formatter
    formatter = Formatter(prefect_formatter._fmt)

    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    prefect_logger.addHandler(file_handler)

    flow.run()
