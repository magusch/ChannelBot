import datetime
from datetime import timezone as tz, timedelta as td


STRFTIME = "%Y-%m-%dT%H:%M:%S"


def get_msk_today(replace_seconds=False):
    params = dict()

    if replace_seconds:
        params.update(
            dict(
                second=0,
                microsecond=0,
            )
        )

    return datetime.datetime.now(tz(td(hours=3))).replace(**params)
