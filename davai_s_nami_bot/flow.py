import pytz
import time
from datetime import datetime

from .datetime_utils import MSK_UTCOFFSET, STRFTIME, get_msk_today
from . import notion_api


class Flow:
    def __init__(self, name, edges, log, bot):
        self._name = name
        self._edges = edges
        self.log = log.getChild("FlowRunner")
        self.bot = bot

    def run(self):
        while True:
            msk_today = get_msk_today()

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

            self.log.info("Starting flow run.")

    def _run(self, msk_today):
        for task in self._edges:
            task_name = task.__class__.__name__

            self.log.info(f"Task {task_name}: Starting task")

            if task.is_need_running(msk_today):
                self.log.info("Need running")

                try:
                    task.run(msk_today, self.bot)

                    self.log.info(
                        f"Task {task_name!r}: finished task run for task "
                        "with final state: Success"
                    )
                except Exception as e:
                    self.log.error(
                        f"Task {task.__class__.__name__} has failed. "
                        "Error msg:\n",
                        exc_info=True,
                    )


            else:
                self.log.info("No need running, skip")
