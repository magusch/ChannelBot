import pytz
import time
from datetime import datetime

from . import notion_api


MSK_TZ = pytz.timezone("Europe/Moscow")
MSK_UTCOFFSET = MSK_TZ.utcoffset(datetime.utcnow())
STRFTIME = "%Y-%m-%dT%H:%M:%S"


class Flow:
    def __init__(self, name, edges, log, bot):
        self._name = name
        self._edges = edges
        self.log = log
        self.bot = bot

    def run(self):
        while True:
            utc_today = datetime.utcnow().replace(second=00, microsecond=00)
            msk_today = utc_today + MSK_UTCOFFSET

            self._run(msk_today=msk_today)

            next_time = notion_api.next_task_time(msk_today)

            self.log.info(
                "Waiting next scheduled time in %s",
                next_time.strftime(STRFTIME)
            )

            naptime = (next_time - MSK_UTCOFFSET) - datetime.utcnow()
            if naptime.days < 0:
                naptime_seconds = 0
            else:
                naptime_seconds = naptime.seconds

            time.sleep(naptime_seconds)

    def _run(self, msk_today):
        for task in self._edges:
            if task.is_need_running(msk_today):
                task.run(msk_today, self.bot)
