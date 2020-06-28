import os

from notion.client import NotionClient


NOTION_TOKEN_V2 = os.environ.get("NOTION_TOKEN_V2")
NOTION_EVENT_TABLE_URL = os.environ.get("NOTION_EVENT_TABLE_URL")

notion_client = NotionClient(token_v2=NOTION_TOKEN_V2)
events_table = notion_client.get_collection_view(NOTION_EVENT_TABLE_URL)


def what_in_last_row():
    """Testing fuction"""
    rows = events_table.default_query().execute()
    row = rows[0]

    return row.get_all_properties()
