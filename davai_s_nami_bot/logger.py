import logging
from datetime import datetime

from .datetime_utils import STRFTIME


LOG_FILE = "bot_logs.txt"


def get_logger():
    fmt_str = "[%(asctime)s] %(levelname)s - %(name)s | %(message)s"
    formatter = logging.Formatter(fmt=fmt_str, datefmt=STRFTIME)

    logging.basicConfig(level=logging.INFO, format=fmt_str)

    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(formatter)

    logger = logging.getLogger("DavaiSNami")
    logger.addHandler(file_handler)

    # change default root stream handler formater
    logger.parent.handlers[0].setFormatter(formatter)

    return logger
