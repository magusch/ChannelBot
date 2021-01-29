import os

from davai_s_nami_bot.utils import REQUIRED_CONSTANT_NAMES, CONSTANTS_FILE_NAME

with open(CONSTANTS_FILE_NAME, "w") as file:
    for name in REQUIRED_CONSTANT_NAMES:
        file.write(f"{name} {os.environ.get(name)}\n")
