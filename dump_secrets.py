import os

from davai_s_nami_bot.utils import CONSTANTS_FILE_NAME, REQUIRED_CONSTANT_NAMES

with open(CONSTANTS_FILE_NAME, "w") as file:
    for name in REQUIRED_CONSTANT_NAMES:
        file.write(f"{name} {os.environ.get(name)}\n")
