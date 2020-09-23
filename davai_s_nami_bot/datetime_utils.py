import pytz
from datetime import datetime


MSK_TZ = pytz.timezone("Europe/Moscow")
MSK_UTCOFFSET = MSK_TZ.utcoffset(datetime.utcnow())
STRFTIME = "%Y-%m-%dT%H:%M:%S"


def get_msk_today():
    utc_today = datetime.utcnow().replace(second=00, microsecond=00)
    return utc_today + MSK_UTCOFFSET
