"""
Test all interactions with notion from each parser events.
"""
import os
from datetime import datetime

import pytest

from davai_s_nami_bot import events, notion_api
from davai_s_nami_bot.notion_api import (
    test_notion_table1,
    test_notion_table2,
    test_notion_table3,
)


def move_rows(from_table, to_table):
    for row in from_table.collection.get_rows():
        notion_api.move_row(row, to_table=to_table, with_remove=False)


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
    ],
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
        table=test_notion_table1,
    )


def test_move_from_dev_table1_to_dev_table2():
    """
    Required events in dev table 1 (from test 'test_add_to_notion_dev_table_1')
    """
    move_rows(test_notion_table1, test_notion_table2)


def test_move_from_dev_table1_to_dev_table3():
    """
    Required events in dev table 1 (from test 'test_add_to_notion_dev_table_1')
    """
    move_rows(test_notion_table1, test_notion_table3)


def test_post_event_from_dev_table3():
    """
    Required events in dev table 3 (from test 'test_move_from_dev_table_2_to_dev_table_3'
    or 'test_move_from_dev_table_1_to_dev_table_3').
    """
    for row in test_notion_table3.collection.get_rows():
        pass


def test_move_from_dev_table2_to_dev_table3():
    """
    Required events in dev table 2 (from test 'test_move_from_dev_table_1_to_dev_table2').
    """
    move_rows(test_notion_table2, test_notion_table3)


def test_remove_events_from_all_dev_tables():
    """
    Required events in dev table 1, 2 and 3.
    """
    all_rows = (
        list(test_notion_table1.collection.get_rows())
        + list(test_notion_table2.collection.get_rows())
        + list(test_notion_table3.collection.get_rows())
    )
    for row in all_rows:
        notion_api.remove_row(row)
