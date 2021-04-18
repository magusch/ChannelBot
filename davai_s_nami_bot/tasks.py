import datetime
from abc import abstractmethod
from datetime import timedelta
from typing import Generator, List

from . import clients
from . import database
from . import events
from . import notion_api
from . import utils
from . import dsn_site
from .exceptions import PostingDatetimeError
from .logger import get_logger


log = get_logger(__file__)
dev_channel = clients.DevClient()


class Task:
    @abstractmethod
    def run(self, msk_today: datetime.datetime) -> None:
        """
        Running task.
        """

    def is_need_running(self, msk_today: datetime.datetime) -> bool:
        """
        By default is True.
        """
        return True


class CheckEventStatus(Task):
    def _is_weekday(self, dt: datetime.datetime) -> bool:
        return dt.weekday() in [0, 1, 2, 3, 4]

    def _in_past(self, dt: datetime.datetime, msk_today: datetime.datetime) -> bool:
        return dt.hour < msk_today.hour or (
            dt.hour == msk_today.hour and dt.minute < msk_today.minute
        )

    def _datetimes_schecule(
        self, msk_today: datetime.datetime
    ) -> Generator[None, datetime.datetime, None]:
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

    def _posting_datetimes(
        self, msk_today: datetime.datetime
    ) -> Generator[None, datetime.datetime, None]:
        datetimes_schecule = self._datetimes_schecule(msk_today)

        while True:
            day_schedule = next(datetimes_schecule)
            yield from day_schedule

    def run(self, msk_today: datetime.datetime, *args) -> None:
        log.info("Check events posting status")

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
    """
    Перемещение выбранных меропритяий из таблиц 1 и 2 в таблицу 3.
    """

    def run(self, *args) -> None:
        log.info("Move approved events")
        dsn_site.move_approved()

        log.info("Fill empty post time")
        dsn_site.fill_empty_post_time()


class IsEmptyCheck(Task):
    def run(self, msk_today: datetime.datetime) -> None:
        log.info("Check for available events in table 3")

        not_published_count = dsn_site.not_published_count()
        text = None

        if not_published_count == 1:
            text = "Warning: posting last event."

        elif not_published_count == 0:
            text = "Warning: not found events for posting."

        if text:
            dev_channel.send_text(text)


class PostingEvent(Task):
    def __init__(self):
        self._clients = clients.Clients()

    def run(self, msk_today: datetime.datetime) -> None:
        log.info("Check posting status")

        event = dsn_site.next_event_to_channel()

        if event is not None:
            image_path = utils.prepare_image(event.image)
            self._clients.send_post(event=event, image_path=image_path)

        else:
            log.info("Skipping posting time")

    def is_need_running(self, msk_today: datetime.datetime) -> bool:
        return True
        posting_time = dsn_site.next_posting_time(msk_today)
        return posting_time is not None and msk_today == posting_time


class UpdateEvents(Task):
    def _remove_old(self, msk_today: datetime.datetime) -> None:
        log.info("Removing old events")
        dsn_site.remove_old_events(msk_today + timedelta(hours=1))
        database.remove(msk_today + timedelta(hours=1))

    def _update_events(
        self,
        events: List[events.Event],
        msk_today: datetime.datetime,
        table: int = 1,
    ) -> None:
        log.info("Checking for existing events")

        new_events = dsn_site.get_new_events(events)
        log.info(f"New events count = {len(new_events)}")

        log.info("Updating database")
        database.add_events(new_events)

    def run(self, msk_today: datetime.datetime, *args) -> None:
        pass
        # log.info("Start updating events.")

        # self._remove_old(msk_today)

        # log.info("Getting events from approved organizations for next 7 days")
        # approved_events = events.from_approved_organizations(days=7)
        # log.info(f"Collected {len(approved_events)} approved events.")

        # self._update_events(approved_events, msk_today, table=3)

        # log.info("Getting new events from other organizations for next 7 days")
        # other_events = events.from_not_approved_organizations(days=7)
        # log.info(f"Collected {len(other_events)} events")

        # self._update_events(other_events, msk_today, table=1)

        # dsn_site_count = dsn_site.events_count()

        # log.info(f"Events count in notion table: {dsn_site_count}")

    def is_need_running(self, msk_today: datetime.datetime) -> bool:
        return True
        # updating_time = dsn_site.next_updating_time(msk_today)

        # return updating_time is not None and msk_today == updating_time


def get_edges() -> List[Task]:
    return [
        MoveApproved(),
        # CheckEventStatus(),
        IsEmptyCheck(),
        PostingEvent(),
        UpdateEvents(),
    ]
