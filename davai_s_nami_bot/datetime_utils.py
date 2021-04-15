import pendulum

STRFTIME = "%Y-%m-%dT%H:%M:%S"

import pytz
utc_3 = pytz.timezone('Europe/Moscow')

def get_msk_today(replace_seconds=False):
    params = dict(tzinfo=utc_3)

    if replace_seconds:
        params["second"] = 00
        params["microsecond"] = 00

    utc_today = pendulum.now("utc")

    return utc_today.in_timezone("Europe/Moscow").replace(**params)
