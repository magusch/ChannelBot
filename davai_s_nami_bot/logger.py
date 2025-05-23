import logging
import math
from typing import Callable

from .datetime_utils import STRFTIME


LOG_FILE = "bot_logs.txt"


def get_logger(name: str):
    fmt_str = "[%(asctime)s] %(levelname)s - %(name)s | %(message)s"
    formatter = logging.Formatter(fmt=fmt_str, datefmt=STRFTIME)

    logging.basicConfig(level=logging.INFO, format=fmt_str)

    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.addHandler(file_handler)

    # change default root stream handler formater
    logger.parent.handlers[0].setFormatter(formatter)

    return logger

log = get_logger(__name__)


def log_task(func):
    def wrapper(*args, **kwargs):
        task_name = func.__name__
        log.info(f"Task {task_name}: Starting task")
        result = func(*args, **kwargs)
        log.info(f"Task {task_name}: Task completed")
        return result
    return wrapper



log = get_logger("Exceptions")


def catch_exceptions(wrapped_func: Callable = None, max_attempts: int = 5):
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
