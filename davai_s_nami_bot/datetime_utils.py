import pendulum


STRFTIME = "%Y-%m-%dT%H:%M:%S"

def get_msk_today(replace_seconds=False):
    params = dict()

    if replace_seconds:
        params.update(dict(
            second=0,
            microsecond=0,
        ))

    return pendulum.now("Europe/Moscow").replace(**params)
