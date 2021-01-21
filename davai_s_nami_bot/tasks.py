from abc import abstractmethod
from datetime import timedelta

from . import database, events, notion_api, telegram
from .exceptions import PostingDatetimeError
from .logger import get_logger


class Task:
    def __init__(self):
        self.log = get_logger().getChild(self.__class__.__name__)

    @abstractmethod
    def run(self, msk_today) -> None:
        """
        Running task.
        """

    def is_need_running(self, msk_today) -> bool:
        """
        By default is True.
        """
        return True


class CheckEventStatus(Task):
    def _is_weekday(self, dt):
        return dt.weekday() in [0, 1, 2, 3, 4]

    def _in_past(self, dt, msk_today):
        return dt.hour < msk_today.hour or (
            dt.hour == msk_today.hour and dt.minute < msk_today.minute
        )

    def _datetimes_schecule(self, msk_today):
        weekday = notion_api.get_weekday_posting_times(msk_today)
        weekend = notion_api.get_weekend_posting_times(msk_today)

        current_day_datetimes = list()
        if self._is_weekday(msk_today):
            today_datetimes = weekday
        else:
            today_datetimes = weekend

        for dt in today_datetimes:
            if not self._in_past(dt, msk_today):
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

            datetimes = weekday if self._is_weekday(msk_today) else weekend
            yield [i.replace(**ymd) for i in datetimes]

    def _posting_datetimes(self, msk_today):
        datetimes_schecule = self._datetimes_schecule(msk_today)

        while True:
            day_schedule = next(datetimes_schecule)
            yield from day_schedule

    def run(self, msk_today, *args) -> None:
        self.log.info("Check events posting status")

        posting_datetimes = self._posting_datetimes(msk_today)
        posting_datetime = next(posting_datetimes)

        for row in notion_api.table3.collection.get_rows():
            if row.status == "Posted":
                continue

            if row.status is None:
                notion_api.set_property(row, "status", "Ready to post")

            if row.posting_datetime is None:
                if row.status == "Skip posting time":
                    posting_datetime = next(posting_datetimes)  # skip time
                    notion_api.set_property(row, "status", "Ready to post")

                notion_api.set_property(row, "posting_datetime", posting_datetime)
                posting_datetime = next(posting_datetimes)

            else:
                while row.posting_datetime.start >= posting_datetime:
                    posting_datetime = next(posting_datetimes)

                if row.status == "Skip posting time":
                    posting_datetime = next(posting_datetimes)  # skip time
                    notion_api.set_property(row, "status", "Ready to post")

                    notion_api.set_property(row, "posting_datetime", posting_datetime)
                    posting_datetime = next(posting_datetimes)

                if row.posting_datetime.start < msk_today:
                    raise PostingDatetimeError(
                        "Unexcepteble error: posting_datetime is in the past!\n"
                        "Please, check table 3,\nevent title: {}\nevent id: {}.".format(
                            row.Title, row.Event_id
                        )
                    )

            if row.status != "Ready to post":
                raise ValueError(f"Unavailable posting status: {row.status}")

        notion_api.check_posting_datetime()  # in table 3


class MoveApproved(Task):
    def run(self, msk_today, *args) -> None:
        notion_api.update_table_views()

        self.log.info("Move approved events from table1 and table2 to table3")
        notion_api.move_approved()


class IsEmptyCheck(Task):
    def run(self, msk_today) -> None:
        self.log.info("Check for available events in table 3")

        not_published_count = notion_api.not_published_count()
        text = None

        if not_published_count == 1:
            text = "Warning: posting last event."

        elif not_published_count == 0:
            text = "Warning: not found events for posting."

        if text:
            telegram.send_message(text, channel="dev")


class PostingEvent(Task):
    def run(self, msk_today) -> None:

        self.log.info("Check posting status")

        event = notion_api.next_event_to_channel()

        if event is None:
            self.log.info("Skipping posting time")
            return

        self.log.info("Generating post.")
        telegram.send_post(event)

    def is_need_running(self, msk_today) -> bool:
        posting_time = notion_api.next_posting_time(msk_today)
        return posting_time is not None and msk_today == posting_time


class UpdateEvents(Task):
    def _remove_old(self, msk_today):
        self.log.info("Removing old events")
        notion_api.remove_old_events(msk_today + timedelta(hours=1))
        database.remove(msk_today + timedelta(hours=1))

    def _update_events(self, events, msk_today, table=None):
        self.log.info("Checking for existing events")

        new_events = notion_api.get_new_events(events)
        self.log.info(f"New evenst count = {len(new_events)}")

        self.log.info("Updating notion table")
        notion_api.add_events(new_events, msk_today, table=table)

    def run(self, msk_today, *args):
        self.log.info("Start updating events.")

        self._remove_old(msk_today)

        self.log.info("Getting events from approved organizations for next 7 days")
        approved_events = events.from_approved_organizations(days=7)
        self.log.info(f"Collected {len(approved_events)} approved events.")

        self._update_events(approved_events, msk_today, table=notion_api.table3)

        self.log.info("Getting new events from other organizations for next 7 days")
        other_events = events.from_not_approved_organizations(days=7)
        self.log.info(f"Collected {len(other_events)} events")

        self._update_events(other_events, msk_today, table=notion_api.table1)

        notion_count = notion_api.events_count()

        self.log.info(f"Events count in notion table: {notion_count}")

    def is_need_running(self, msk_today) -> bool:
        updating_time = notion_api.next_updating_time(msk_today)

        return updating_time is not None and msk_today == updating_time


def get_edges():
    return [
        MoveApproved(),
        CheckEventStatus(),
        IsEmptyCheck(),
        PostingEvent(),
        UpdateEvents(),
    ]
