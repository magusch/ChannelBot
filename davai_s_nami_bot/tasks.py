import datetime
from abc import abstractmethod
from datetime import timedelta
from typing import Generator, List

from . import clients
from . import database
from . import events
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
    def run(self, *args) -> None:
        dsn_site.check_event_status()


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
        posting_time = dsn_site.next_posting_time(msk_today)
        return posting_time is not None and abs(msk_today - posting_time).seconds < 60


class UpdateEvents(Task):
    def _update_events(
        self, events: List[events.Event], table: str, msk_today: datetime
    ) -> None:
        log.info("Checking for existing events")
        new_events = dsn_site.get_new_events(events)
        log.info(f"New events count = {len(new_events)}")

        log.info("Updating database")
        database.add_events(new_events, explored_date=msk_today, table=table)

        log.info("Fill empty post time")
        dsn_site.fill_empty_post_time()

    def run(self, msk_today: datetime.datetime, *args) -> None:
        log.info("Start updating events.")

        log.info("Remove old events")
        dsn_site.remove_old()

        log.info("Getting events from approved organizations for next 7 days")
        approved_events = events.from_approved_organizations(days=7)
        log.info(f"Collected {len(approved_events)} approved events.")

        self._update_events(
            approved_events,
            table="events_events2post",
            msk_today=msk_today,
        )

        log.info("Getting new events from other organizations for next 7 days")
        other_events = events.from_not_approved_organizations(days=7)
        log.info(f"Collected {len(other_events)} events")

        self._update_events(
            other_events,
            table="events_eventsnotapprovednew",
            msk_today=msk_today,
        )

        events_count = sum(
            [
                database.rows_number(table="events_eventsnotapprovednew"),
                database.rows_number(table="events_eventsnotapprovedold"),
                database.rows_number(table="events_events2post"),
            ]
        )

        log.info(f"Events count in database: {events_count}")

    def is_need_running(self, msk_today: datetime.datetime) -> bool:
        return True
        updating_time = dsn_site.next_updating_time(msk_today)

        return updating_time is not None and msk_today == updating_time


def get_edges() -> List[Task]:
    return [
        MoveApproved(),
        CheckEventStatus(),
        IsEmptyCheck(),
        PostingEvent(),
        UpdateEvents(),
    ]

def get_posting() -> List[Task]:
    return [
        CheckEventStatus(),
        IsEmptyCheck(),
        PostingEvent()
    ]
