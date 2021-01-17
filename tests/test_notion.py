"""
Test all interactions with notion from each parser events.
"""
import os
from datetime import datetime

import pytest

from davai_s_nami_bot import events, notion_api


@pytest.mark.parametrize(
    "events",
    [
        events.timepad_approved_organizations(days=1),
        events.timepad_others_organizations(days=1),
        events.radario_others_organizations(days=1),
    ],
    ids=[
        "timepad_approved_organizations",
        "timepad_others_organizations",
        "radario_others_organizations",
    ]
)
def test_add_to_notion_dev_table_1(events):
    """
    Add 1 event from each parser to notion table 3.
    """
    if not events:
        return

    event = events[0]
    notion_api.add_events(
        events=[event],
        explored_date=datetime.now(),
        table=notion_api.test_notion_table1,
    )


def test_move_from_dev_table_1_to_dev_table2():
    """
    Required events in dev table 1 (from test 'test_add_to_notion_dev_table_1')
    """
    pass


def test_move_from_dev_table_1_to_dev_table_3():
    """
    Required events in dev table 1 (from test 'test_add_to_notion_dev_table_1')
    """
    pass


def test_move_from_dev_table_2_to_dev_table_3():
    """
    Required events in dev table 2 (from test 'test_move_from_dev_table_1_to_dev_table2').
    """
    pass


def test_post_event_from_dev_table_3():
    """
    Required events in dev table 3 (from test 'test_move_from_dev_table_2_to_dev_table_3'
    or 'test_move_from_dev_table_1_to_dev_table_3').
    """
    pass


def test_remove_events_from_all_dev_tables():
    """
    Required events in dev table 1, 2 and 3.
    """
    pass
