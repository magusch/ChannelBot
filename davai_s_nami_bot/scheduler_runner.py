from datetime import timedelta, datetime
import logging
import pytz
import os
from io import BytesIO

import PIL
from PIL import Image
import requests
from telebot import TeleBot
import prefect
from prefect.core import Edge
from prefect.schedules import filters
from prefect.schedules.schedules import Schedule
from prefect.schedules.clocks import IntervalClock

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
maxsize = (1920, 1080)


class Task:
    def __init__(self, logger):
        self.log = logger.getChild(self.__class__.__name__)


class PrepareEvents(Task):
    def update_today_time(self):
        global utc_today, msk_today
        utc_today = datetime.utcnow()
        msk_today = datetime.now()

    def move_approved(self):
        self.log.info("Move approved events from table1 and table2 to table3")
        notion_api.move_approved(log=self.log)

    def check_status(self):
        """
        Checking event status in table3 and update posting time.
        """
        self.log.info("Check events posting status")

        posting_datetimes = self.posting_datetimes(msk_today)
        for row in notion_api.table3.collection.get_rows():
            if row.status is None or row.status == "Posted":
                continue

            elif row.status == "Skip posting time":
                next(posting_datetimes)  # skip time
                posting_datetime = next(posting_datetimes)
                notion_api.set_property(row, "status", "Ready to skiped posting time")

            elif row.status == "Ready to skiped posting time":
                dt = row.posting_datetime.start
                if dt.hour == msk_today.hour and dt.minute == msk_today.minute:
                    notion_api.set_property(row, "status", "Ready to post")
                    posting_datetime = next(posting_datetimes)

                else:
                    next(posting_datetimes)  # skip time
                    posting_datetime = next(posting_datetimes)

            elif row.status == "Ready to post":
                posting_datetime = next(posting_datetimes)

            else:
                raise ValueError(f"Unavailable posting status: {row.status}")

            notion_api.set_property(row, "posting_datetime", posting_datetime)

    def posting_datetimes(self, today):
        datetimes_schecule = self.datetimes_schecule(today)

        while True:
            day_schedule = next(datetimes_schecule)
            for posting_datetime in day_schedule:
                yield posting_datetime

    def datetimes_schecule(self, today):
        weekday = weekday_posting_times + everyday_posting_times
        weekend = weekend_posting_times + everyday_posting_times

        current_day_datetimes = list()
        if filters.is_weekday(today):
            today_datetimes = weekday
        else:
            today_datetimes = weekend

        for dt in today_datetimes:
            if (
                dt.hour < today.hour
                or (dt.hour == today.hour and dt.minute < today.minute)
            ):
                continue

            current_day_datetimes.append(
                dt.replace(year=today.year, month=today.month, day=today.day)
            )

        if current_day_datetimes:
            yield current_day_datetimes

        while True:
            today += timedelta(days=1)
            ymd = dict(year=today.year, month=today.month, day=today.day)

            datetimes = weekday if filters.is_weekday(today) else weekend
            yield [i.replace(**ymd) for i in datetimes]

    def run(self):
        self.update_today_time()

        # in case changed table views
        notion_api.update_table_views()

        self.move_approved()
        self.check_status()


class IsEmptyCheck(Task):
    """
    Checking events in table3: if empty, send warning message to dev channel.
    """
    def run(self):
        not_published_count = notion_api.not_published_count()
        text = None

        if not_published_count == 1:
            text = "Warning: posting last event."

        elif not_published_count == 0:
            text = (
                "Warning: not found events for posting."
            )

        if text:
            bot.send_message(chat_id=DEV_CHANNEL_ID, text=text)


class PostingEvent(Task):
    def run(self):
        if utc_today.strftime("%H:%M") in strftimes_weekday + strftimes_weekend:
            self.log.info("Check posting status")

            event = notion_api.next_event_to_channel()

            if event is None:
                self.log.info("Skipping posting time")
                return

            self.log.info("Generating post.")
            photo_url, post = posting.create(event)

            if photo_url is None:
                message = bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=post,
                    disable_web_page_preview=True,
                )

            else:
                with Image.open(BytesIO(requests.get(photo_url).content)) as img:
                    photo_name = str(event.Event_id)
                    img.thumbnail(maxsize, PIL.Image.ANTIALIAS)

                    img.save(photo_name + ".png", "png")
                    if img.mode == "RGBA":
                        # jpeg does not support transparency
                        img = img.convert("RGB")
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
            database.add(event, post_id)


class UpdateEvents(Task):
    def remove_old(self):
        self.log.info("Removing old events")
        notion_api.remove_old_events(msk_today + timedelta(hours=1), log=self.log)
        database.remove(msk_today + timedelta(hours=1))

    def update_events(self, events, table=None):
        self.log.info("Checking for existing events")

        new_events = notion_api.get_new_events(events)
        self.log.info(f"New evenst count = {len(new_events)}")

        self.log.info("Updating notion table")
        notion_api.add_events(new_events, msk_today, table=table, log=self.log)

    def run(self):
        if utc_today.strftime("%H:%M") in strftime_event_updating:
            self.log.info("Start updating events.")

            self.remove_old()

            self.log.info("Getting events from approved organizations for next 7 days")
            approved_events = events.from_approved_organizations(days=7, log=self.log)
            self.log.info(f"Collected {len(approved_events)} approved events.")

            self.update_events(approved_events, table=notion_api.table3)

            self.log.info("Getting new events from other organizations for next 7 days")
            other_events = events.from_not_approved_organizations(days=7, log=self.log)
            self.log.info(f"Collected {len(other_events)} events")

            self.update_events(other_events, table=notion_api.table1)

            notion_count = notion_api.events_count()

            self.log.info(f"Events count in notion table: {notion_count}")


class Formatter(logging.Formatter):
    def send_logs(self):
        with open(LOG_FILE, "r+b") as logs:
            bot.send_document(DEV_CHANNEL_ID, logs)
            logs.truncate(0)
            logs.write(b"")

    def converter(self, timestamp):
        dt = datetime.fromtimestamp(timestamp)

        return MSK_TZ.localize(dt)

    def format(self, record):
        if record.name == "DavaiSNami":
            str_time = record.message[-25:]
            message = record.message[:-25]

            dt = datetime.strptime(str_time, "%Y-%m-%dT%H:%M:%S%z") + MSK_UTCOFFSET
            message += dt.strftime("%Y-%m-%dT%H:%M:%S")

            bot.send_message(DEV_CHANNEL_ID, text=message)
            self.send_logs()

        else:
            message = record.msg

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


class Flow:
    def __init__(self, graph):
        self.graph = graph

    def run(self):
        self.execute_graph()

    def execute_graph(self):
        for task in self.graph:
            task.run()


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

    global weekday_posting_strftimes, weekend_posting_strftimes, everyday_task_strftimes

    weekday_posting_strftimes, weekend_posting_strftimes = notion_api.get_posting_times()
    everyday_task_strftimes = notion_api.get_everyday_times()  # dict(task_name=strftime)

    # all_task_times = convert_to_utc(
    #     scheduled_times=(
    #         weekday_posting_times
    #         + weekend_posting_times
    #         + list(everyday_task_times.values())
    #     ),
    #     utcoffset=MSK_UTCOFFSET,
    # )

    # schedule_clocks = [
    #     IntervalClock(
    #         interval=timedelta(days=1),
    #         start_date=today.replace(hour=i.hour, minute=i.minute)
    #     )
    #     for i in all_task_times
    # ]

    # schedule = Schedule(clocks=schedule_clocks, filters=[scheduling_filter])

    # prepare logging
    logger = logging.getLogger("DavaiSNami")
    logger.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setLevel(logging.DEBUG)
    formatter = Formatter("[%(asctime)s] %(name)s - %(levelname)s | %(message)s")
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)

    graph = (
        PrepareEvents(logger=logger),
        IsEmptyCheck(logger=logger),
        PostingEvent(logger=logger),
        UpdateEvents(logger=logger),
    )

    flow = Flow(graph)
    flow.run()
