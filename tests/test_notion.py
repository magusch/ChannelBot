"""
Test all interactions with notion from each parser events.
"""
import os
from datetime import datetime

import psycopg2
import pytest

import davai_s_nami_bot
from davai_s_nami_bot import clients, database, events, notion_api, utils
from davai_s_nami_bot.notion_api import notion_client

test_table1 = notion_client.get_block(os.environ.get("NOTION_TEST_TABLE1_URL"))
test_table2 = notion_client.get_block(os.environ.get("NOTION_TEST_TABLE2_URL"))
test_table3 = notion_client.get_block(os.environ.get("NOTION_TEST_TABLE3_URL"))


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
        table=test_table1,
    )


def test_move_from_dev_table1_to_dev_table2():
    """
    Required events in dev table 1 (from test 'test_add_to_notion_dev_table_1')
    """
    move_rows(test_table1, test_table2)


def test_move_from_dev_table1_to_dev_table3():
    """
    Required events in dev table 1 (from test 'test_add_to_notion_dev_table_1')
    """
    move_rows(test_table1, test_table3)


@pytest.fixture
def environ_test_id(monkeypatch):
    telegram_constants = clients.Telegram.constants.copy()
    telegram_constants["prod"] = telegram_constants["dev"]
    monkeypatch.setattr(clients.Telegram, "constants", telegram_constants)

    vk_constants = davai_s_nami_bot.clients.VKRequests.constants.copy()
    vk_constants["prod"] = vk_constants["dev"]
    monkeypatch.setattr(davai_s_nami_bot.clients.VKRequests, "constants", vk_constants)


def test_post_event_from_dev_table3(environ_test_id):
    """
    Required events in dev table 3 (from test
    'test_move_from_dev_table_2_to_dev_table_3' or
    'test_move_from_dev_table_1_to_dev_table_3').
    """
    test_clients = clients.Clients()

    for row in test_table3.collection.get_rows():
        event = events.Event.from_notion_row(row)
        image_path = utils.prepare_image(event.image)

        if event.event_id in database.get_all()["id"].values:
            with pytest.raises(psycopg2.errors.UniqueViolation):
                test_clients.send_post(event, image_path)

        else:
            test_clients.send_post(event, image_path)
            database.remove_by_event_id(event.event_id)


def test_move_from_dev_table2_to_dev_table3():
    """
    Required events in dev table 2 (from test
    'test_move_from_dev_table_1_to_dev_table2').
    """
    move_rows(test_table2, test_table3)


def test_remove_events_from_all_dev_tables():
    """
    Required events in dev table 1, 2 and 3.
    """
    all_rows = (
        list(test_table1.collection.get_rows())
        + list(test_table2.collection.get_rows())
        + list(test_table3.collection.get_rows())
    )
    for row in all_rows:
        notion_api.remove_row(row)
