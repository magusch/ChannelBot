"""
Обновление таблиц на сайте dsn.
"""
from davai_s_nami_bot.datetime_utils import get_msk_today
from davai_s_nami_bot.tasks import CheckEventStatus, UpdateEvents


msk_today = get_msk_today(replace_seconds=True)

for task in [UpdateEvents]:
    task().run(msk_today)
