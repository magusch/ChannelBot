import datetime
import time
from typing import List

from . import clients
from . import logger
from . import tasks
from . import dsn_site
from .datetime_utils import STRFTIME, get_msk_today


log = logger.get_logger(__file__)
dev_channel = clients.DevClient()


class Flow:
    def __init__(self, edges: List[tasks.Task]):
        self._edges = edges

    def run(self) -> None:
        while True:
            msk_today = get_msk_today(replace_seconds=True)

            self._run(msk_today=msk_today)
            dev_channel.send_file(logger.LOG_FILE, mode="r+b", with_remove=True)

            next_time = dsn_site.next_task_time(
                msk_today=get_msk_today(replace_seconds=True)
            )

            period_to_next_time = next_time - get_msk_today()

            msg = "Next scheduled time in {time}".format(
                time=next_time.strftime(STRFTIME),
            )
            dev_channel.send_text(msg)

            naptime = max(period_to_next_time.total_seconds(), 0)

            time.sleep(naptime)

            log.info("Starting flow run.")

    def _run(self, msk_today: datetime.datetime) -> None:
        for task in self._edges:
            task_name = task.__class__.__name__

            log.info(f"Task {task_name}: Starting task")

            if task.is_need_running(msk_today):
                log.info("Need running")

                try:
                    task.run(msk_today)

                    log.info(
                        f"Task {task_name!r}: finished task run for task "
                        "with final state: Success"
                    )

                except Exception as e:  # noqa: F841
                    log.error(
                        f"Task {task.__class__.__name__} has failed. " "Error msg:\n",
                        exc_info=True,
                    )

            else:
                log.info("No need running, skip")
