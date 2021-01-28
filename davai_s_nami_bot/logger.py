import logging
import math
from functools import lru_cache

from .clients import LogClient
from .datetime_utils import STRFTIME


class ChannelBotLogger(logging.Logger):
    LOG_FILE = "bot_logs.txt"  # TODO
    _client = LogClient()

    def send_log_file(self):
        self._client.send_log_file(self.LOG_FILE)

    def info_dev_channel(self, text):
        self._client.send_text(text)


@lru_cache()
def get_logger():
    logging.setLoggerClass(ChannelBotLogger)

    fmt_str = "[%(asctime)s] %(levelname)s - %(name)s | %(message)s"
    formatter = logging.Formatter(fmt=fmt_str, datefmt=STRFTIME)

    logging.basicConfig(level=logging.INFO, format=fmt_str)

    file_handler = logging.FileHandler(ChannelBotLogger.LOG_FILE)
    file_handler.setFormatter(formatter)

    logger = logging.getLogger("DavaiSNami")
    logger.addHandler(file_handler)

    # change default root stream handler formater
    logger.parent.handlers[0].setFormatter(formatter)

    return logger


log = get_logger().getChild("Exceptions")


def catch_exceptions(wrapped_func=None, max_attempts=5):
    """
    Usage:
    ------

    >>> @catch_exception
    ... def test_func(*args, **kwargs):
    ...     # do something

    With argument `max_attempts`:

    >>> @catch_exception(max_attempts=10)
    ... def test_func(*args, **kwargs):
    ...     # do something

    """
    if max_attempts is None:
        max_attempts = math.inf

    def wrapper(*args, **kwargs):
        attempts_count = 0
        while True:
            try:
                return wrapped_func(*args, **kwargs)
            except Exception as e:
                if attempts_count >= max_attempts:
                    raise e

                log.warning("Retry (raised exception)" + "\n", exc_info=True)
                attempts_count += 1

    if wrapped_func is not None:
        return wrapper

    return lambda func: catch_exceptions(wrapped_func=func, max_attempts=max_attempts)
