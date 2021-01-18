import os
from collections import namedtuple
from datetime import datetime, timedelta

import pytest

from davai_s_nami_bot import datetime_utils, notion_api
from davai_s_nami_bot.tasks import CheckEventStatus, Task

MSK_TODAY = datetime(year=1900, month=1, day=1, hour=00, minute=00)
HOUR_1 = timedelta(hours=1)


@pytest.fixture
def check_event_status():
    return CheckEventStatus()


@pytest.mark.parametrize(
    "msk_today, status, posting_datetime",
    [
        (MSK_TODAY, "Posted", MSK_TODAY),
        (MSK_TODAY, "Posted", None),
        (MSK_TODAY, "Ready to post", MSK_TODAY),
        (MSK_TODAY, "Ready to post", MSK_TODAY + HOUR_1),
        (MSK_TODAY, "Ready to post", None),
    ],
    ids=lambda args: f"{args}",
)
def test_check_event_status(
    monkeypatch, check_event_status, msk_today, status, posting_datetime
):
    class NotionRow:
        def __init__(self, status, posting_datetime=None):
            self.status = status

            if posting_datetime is None:
                self.posting_datetime = posting_datetime
            else:
                self.posting_datetime = namedtuple("test", ["start"])(
                    start=posting_datetime
                )

            self.Title = "test-title"
            self.Event_id = "test-id"

        def set_property(self, property_name, value):
            if property_name == "posting_datetime":
                self.posting_datetime = namedtuple("test", ["start"])(start=value)

            else:
                setattr(self, property_name, value)

    def get_rows():
        return [
            NotionRow(status=status, posting_datetime=posting_datetime),
        ]

    def check_posting_datetime():
        return

    monkeypatch.setattr(notion_api.table3.collection, "get_rows", get_rows)
    monkeypatch.setattr(notion_api, "check_posting_datetime", check_posting_datetime)

    check_event_status.run(msk_today)
