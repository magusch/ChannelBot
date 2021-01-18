from datetime import datetime

import pendulum
import pytz

STRFTIME = "%Y-%m-%dT%H:%M:%S"


def get_msk_today(replace_seconds=False):
    params = dict(tzinfo=None)

    if replace_seconds:
        params["second"] = 00
        params["microsecond"] = 00

    utc_today = pendulum.now("utc")

    return utc_today.in_timezone("Europe/Moscow").replace(**params)
