import os

from davai_s_nami_bot import utils

with open("prod_constants", "w") as file:
    for name in utils.REQUIRED_CONSTANT_NAMES:
        file.write(f"{name} {os.environ.get(name)}\n")
