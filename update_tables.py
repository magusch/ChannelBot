"""
Updating notion tables manually.
"""
from davai_s_nami_bot.logger import get_logger
from davai_s_nami_bot.tasks import CheckEventStatus, UpdateEvents
from davai_s_nami_bot.telegram import get_bot
from davai_s_nami_bot.datetime_utils import get_msk_today
from davai_s_nami_bot.notion_api import update_table_views


log = get_logger()
msk_today = get_msk_today(replace_seconds=True)
bot = get_bot()

update_table_views()
for task in [CheckEventStatus, UpdateEvents]:
    task(log).run(msk_today, bot)
