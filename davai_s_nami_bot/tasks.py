from abc import abstractmethod
from datetime import timedelta

from . import notion_api


class Task:
    def __init__(self, log):
        self.log = log.getChild(self.__class__.__name__)

    @abstractmethod
    def run(self) -> None: pass

    @abstractmethod
    def is_need_running(self) -> bool: pass


class CheckEventStatus(Task):
    def is_weekday(self, dt):
        return dt.weekday() in [0, 1, 2, 3, 4]

    def datetimes_schecule(self, msk_today):
        weekday = notion_api.get_weekday_posting_times()
        weekend = notion_api.get_weekend_posting_times()

        current_day_datetimes = list()
        if self.is_weekday(msk_today):
            today_datetimes = weekday
        else:
            today_datetimes = weekend

        for dt in today_datetimes:
            if (
                dt.hour < msk_today.hour
                or (dt.hour == msk_today.hour and dt.minute < msk_today.minute)
            ):
                continue

            current_day_datetimes.append(
                dt.replace(year=msk_today.year, month=msk_today.month, day=msk_today.day)
            )

        if current_day_datetimes:
            yield current_day_datetimes

        while True:
            msk_today += timedelta(days=1)
            ymd = dict(year=msk_today.year, month=msk_today.month, day=msk_today.day)

            datetimes = weekday if self.is_weekday(msk_today) else weekend
            yield [i.replace(**ymd) for i in datetimes]

    def posting_datetimes(self, msk_today):
        datetimes_schecule = self.datetimes_schecule(msk_today)

        while True:
            day_schedule = next(datetimes_schecule)
            for posting_datetime in day_schedule:
                yield posting_datetime

    def run(self, msk_today) -> None:
        self.log.info("Check events posting status")

        posting_datetimes = self.posting_datetimes(msk_today)
        for row in notion_api.table3.collection.get_rows():
            if row.status is None or row.status == "Posted":
                continue

            elif row.status == "Skip posting time":
                next(posting_datetimes)  # skip time
                posting_datetime = next(posting_datetimes)
                notion_api.set_property(row, "status", "Ready to skiped posting time")

            elif row.status == "Ready to skiped posting time":
                dt = row.posting_datetime.start
                if dt.hour == msk_today.hour and dt.minute == msk_today.minute:
                    notion_api.set_property(row, "status", "Ready to post")
                    posting_datetime = next(posting_datetimes)

                else:
                    next(posting_datetimes)  # skip time
                    posting_datetime = next(posting_datetimes)

            elif row.status == "Ready to post":
                posting_datetime = next(posting_datetimes)

            else:
                raise ValueError(f"Unavailable posting status: {row.status}")

            notion_api.set_property(row, "posting_datetime", posting_datetime, log=self.log)


    def is_need_running(self, msk_today) -> bool:
        return True


class MoveApproved(Task):
    def run(self) -> None:
        self.log.debug("Running task")

    def is_need_running(self, msk_today) -> bool:
        """
        Running only in posting times.
        """
        # return msk_today == notion_api.next_posting_time()
        return True


class IsEmptyCheck(Task):
    def run(self) -> None:
        self.log.debug("Running task")

    def is_need_running(self, *args) -> bool:
        return True


class PostingEvent(Task):
    def run(self) -> None:
        self.log.debug("Running task")

    def is_need_running(self, msk_today) -> bool:
        return True


class UpdateEvents(Task):
    def run(self) -> None:
        self.log.debug("Running task")

    def is_need_running(self, msk_today) -> bool:
        return True


def get_edges(log):
    return [
        CheckEventStatus(log),
        MoveApproved(log),
        IsEmptyCheck(log),
        PostingEvent(log),
        UpdateEvents(log),
    ]
