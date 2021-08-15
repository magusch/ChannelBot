import os
import warnings
from io import BytesIO

import PIL
import requests
from PIL import Image


CONSTANTS_FILE_NAME = "prod_constants"
WEEKNAMES = {
    0: "Пн",
    1: "Вт",
    2: "Ср",
    3: "Чт",
    4: "Пт",
    5: "Сб",
    6: "Вск",
}
MONTHNAMES = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}
IMG_MAXSIZE = (1920, 1080)
REQUIRED_CONSTANT_NAMES = [
    "TIMEPAD_TOKEN",
    "BOT_TOKEN",
    "DATABASE_URL",
    "CHANNEL_ID",
    "DEV_CHANNEL_ID",
    "VK_TOKEN",
    "VK_USER_ID",
    "VK_GROUP_ID",
    "VK_DEV_GROUP_ID",
    "DSN_USERNAME",
    "DSN_PASSWORD",
]


def read_constants():
    if os.path.exists(CONSTANTS_FILE_NAME):
        warnings.warn(
            message=(
                "Reading constants from file 'prod_constants' will be removed "
                "in future versions."
            ),
            category=DeprecationWarning,
        )

        missing_constants = set(REQUIRED_CONSTANT_NAMES)

        with open(CONSTANTS_FILE_NAME) as file:
            for line in file:
                tag, value = line.split()

                if tag not in REQUIRED_CONSTANT_NAMES:
                    raise ValueError(f"Unexpected constant: {tag}")

                os.environ[tag] = value

                missing_constants -= {tag}

        if missing_constants:
            raise ValueError(
                "Some constants in 'prod_constants' are missing: {}".format(
                    ", ".join(missing_constants)
                )
            )

    else:
        for key in REQUIRED_CONSTANT_NAMES:
            if key not in os.environ:
                raise ValueError(f"Constant {key} not found in environ.")


def prepare_image(image_url):
    if image_url is None or isinstance(image_url, list) or image_url=='':
        image_path = None

    else:
        with Image.open(BytesIO(requests.get(image_url).content)) as img:
            image_name = "img"
            img.thumbnail(IMG_MAXSIZE, PIL.Image.ANTIALIAS)

            if img.mode != "RGB":
                img = img.convert("RGB")

            # TODO: if line above work fine, this isn't necessary
            if img.mode == "CMYK":
                # can't save CMYK as PNG
                img.save(image_name + ".jpg", "jpeg")
                image_path = image_name + ".jpg"

            else:
                img.save(image_name + ".png", "png")
                img.save(image_name + ".jpg", "jpeg")

                image_size = os.path.getsize(image_name + ".png") / 1_000_000

                if image_size > 5:
                    image_path = image_name + ".jpg"
                else:
                    image_path = image_name + ".png"

    return image_path
