"""
Updating notion tab`l`es manually.
"""
from davai_s_nami_bot.datetime_utils import get_msk_today
from davai_s_nami_bot.notion_api import update_table_views
from davai_s_nami_bot.tasks import CheckEventStatus, UpdateEvents

msk_today = get_msk_today(replace_seconds=True)

update_table_views()
for task in [CheckEventStatus, UpdateEvents]:
    task().run(msk_today)
