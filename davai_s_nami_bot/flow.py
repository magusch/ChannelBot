import os
import pytz
import time

from .datetime_utils import STRFTIME, get_msk_today
from .exceptions import PostingDatetimeError
from . import logger
from . import notion_api


class Flow:
    def __init__(self, name, edges, log, bot):
        self._name = name
        self._edges = edges
        self.log = log.getChild("FlowRunner")
        self.bot = bot

        self.DEV_CHANNEL_ID = os.environ.get("DEV_CHANNEL_ID")

    def run(self):
        while True:
            msk_today = get_msk_today(replace_seconds=True)

            self._run(msk_today=msk_today)
            logger.send_logs(self.bot, self.DEV_CHANNEL_ID)

            # refresh today time
            next_time = notion_api.next_task_time(
                msk_today=get_msk_today(replace_seconds=True)
            )

            period_to_next_time = next_time - get_msk_today()

            self.bot.send_message(
                chat_id=self.DEV_CHANNEL_ID,
                text=(
                    "Waiting next scheduled time in {time},\n{delta} left"
                    .format(
                        time=next_time.strftime(STRFTIME),
                        delta=period_to_next_time.as_interval(),
                    )
                ),
            )

            naptime = max(period_to_next_time.total_seconds(), 0)

            time.sleep(naptime)

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
