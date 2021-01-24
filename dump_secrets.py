import os

from davai_s_nami_bot.utils import REQUIRED_CONSTANT_NAMES

with open("prod_constants", "w") as file:
    for name in REQUIRED_CONSTANT_NAMES:
        file.write(f"{name} {os.environ.get(name)}\n")
