from abc import abstractmethod
from datetime import timedelta

from . import notion_api


class Task:
    def __init__(self, log):
        self.log = log.getChild(self.__class__.__name__)

    @abstractmethod
    def run(self) -> None: pass

    def is_need_running(self) -> bool:
        """
        By default is True.
        """
        return True


class CheckEventStatus(Task):
    def is_weekday(self, dt):
        return dt.weekday() in [0, 1, 2, 3, 4]

    def in_past(self, dt, msk_today):
        return (
            dt.hour < msk_today.hour
            or (
                dt.hour == msk_today.hour
                and dt.minute < msk_today.minute
            )
        )

    def datetimes_schecule(self, msk_today):
        weekday = notion_api.get_weekday_posting_times()
        weekend = notion_api.get_weekend_posting_times()

        current_day_datetimes = list()
        if self.is_weekday(msk_today):
            today_datetimes = weekday
        else:
            today_datetimes = weekend

        for dt in today_datetimes:
            if not self.in_past(dt, msk_today):
                current_day_datetimes.append(
                    dt.replace(
                        year=msk_today.year,
                        month=msk_today.month,
                        day=msk_today.day,
                    )
                )

        if current_day_datetimes:
            yield current_day_datetimes

        while True:
            msk_today += timedelta(days=1)
            ymd = dict(
                year=msk_today.year,
                month=msk_today.month,
                day=msk_today.day,
            )

            datetimes = weekday if self.is_weekday(msk_today) else weekend
            yield [i.replace(**ymd) for i in datetimes]

    def posting_datetimes(self, msk_today):
        datetimes_schecule = self.datetimes_schecule(msk_today)

        while True:
            day_schedule = next(datetimes_schecule)
            for posting_datetime in day_schedule:
                yield posting_datetime

    def run(self, msk_today) -> None:
        self.log.info("Check events posting status")

        posting_datetimes = self.posting_datetimes(msk_today)
        for row in notion_api.table3.collection.get_rows():
            if row.status is None:
                notion_api.set_property(row, "status", "Ready to post")

            if row.status == "Posted" or row.posting_datetime is not None:
                continue

            elif row.status == "Skip posting time":
                next(posting_datetimes)  # skip time
                posting_datetime = next(posting_datetimes)
                notion_api.set_property(row, "status", "Ready to post")

            elif row.status == "Ready to post":
                posting_datetime = next(posting_datetimes)

            else:
                raise ValueError(f"Unavailable posting status: {row.status}")

            notion_api.set_property(
                row, "posting_datetime", posting_datetime, log=self.log
            )


class MoveApproved(Task):
    def run(self) -> None:
        self.log.debug("Move approved events from table1 and table2 to table3")
        notion_api.move_approved(log=self.log)


class IsEmptyCheck(Task):
    def run(self) -> None:
        self.log.debug("Running task")

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
    def run(self) -> None:
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

                if img.mode == "CMYK":
                    # can't save CMYK as PNG
                    img.save(photo_name + ".jpg", "jpeg")
                    photo_path = photo_name + ".jpg"

                else:
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

    def is_need_running(self, msk_today) -> bool:
        return msk_today == notion_api.next_posting_time()


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

    def is_need_running(self, msk_today) -> bool:
        return msk_today == notion_api.next_updating_time(msk_today)


def get_edges(log):
    return [
        CheckEventStatus(log),
        MoveApproved(log),
        IsEmptyCheck(log),
        PostingEvent(log),
        UpdateEvents(log),
    ]
