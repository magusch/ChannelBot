import os

from notion.client import NotionClient


NOTION_TOKEN_V2 = os.environ.get("NOTION_TOKEN_V2")
NOTION_EVENT_TABLE_URL = os.environ.get("NOTION_EVENT_TABLE_URL")

notion_client = NotionClient(token_v2=NOTION_TOKEN_V2)
events_table = notion_client.get_collection_view(NOTION_EVENT_TABLE_URL)

# 💫 some magic 💫
# (see issue https://github.com/jamalex/notion-py/issues/92)
print(events_table.collection.parent.views)


def add_events(events):
    for event in events:
        row = events_table.collection.add_row()

        for tag in event._fields:
            setattr(row, tag, getattr(event, tag))
