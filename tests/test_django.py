"""
Test all interactions with dsn_site database from each parser events.
"""
import os
from collections import namedtuple
from datetime import datetime, timedelta

import escraper
import psycopg2
import pytest

import davai_s_nami_bot
from davai_s_nami_bot import clients, database, events, utils, dsn_site


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
def test_add_to_dsn_site_dev_table_1(events):
    """
    Add 1 event from each parser to notion table 3.
    """
    if not events:
        return

    event = events[0]
    dsn_site.add_events(
        events=[event],
        explored_date=datetime.now(),
        table=3,
    )


def test_move_approved():
    """
    Required events in dev table 1 (from test 'test_add_to_notion_dev_table_1')
    """
    dsn_site.move_approved()


def test_post_event_from_dev_table3(environ_test_id):
    """
    Required events in dev table 3.
    """
    test_clients = clients.Clients()

    for event_dsn_site in dsn_site.next_event_to_channel(counts="3"):
        event = events.Event.from_dsn_site(event_dsn_site)

        if event.image:
            image_path = utils.prepare_image(event.image)
        elif event.post:
            return
        else:
            image_path = None

        if event.event_id in database.get_all()["id"].values:
            with pytest.raises(psycopg2.errors.UniqueViolation):
                test_clients.send_post(event, image_path)

        else:
            test_clients.send_post(event, image_path)
            database.remove_by_event_id(event.event_id)


def test_delete_old_events():
    msk_date = datetime.now()
    dsn_site.remove_old_events(msk_date)


@pytest.fixture
def environ_test_id(monkeypatch):
    telegram_constants = clients.Telegram.constants.copy()
    telegram_constants["prod"] = telegram_constants["dev"]
    monkeypatch.setattr(clients.Telegram, "constants", telegram_constants)

    vk_constants = davai_s_nami_bot.clients.VKRequests.constants.copy()
    vk_constants["prod"] = vk_constants["dev"]
    monkeypatch.setattr(davai_s_nami_bot.clients.VKRequests, "constants", vk_constants)
