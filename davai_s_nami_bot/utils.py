import os
import warnings

REQUIRED_CONSTANT_NAMES = [
    "TIMEPAD_TOKEN",
    "BOT_TOKEN",
    "DATABASE_URL",
    "NOTION_TOKEN_V2",
    "NOTION_TABLE1_URL",
    "NOTION_TABLE2_URL",
    "NOTION_TABLE3_URL",
    "NOTION_POSTING_TIMES_URL",
    "NOTION_EVERYDAY_TIMES_URL",
    "NOTION_TEST_TABLE1_URL",
    "NOTION_TEST_TABLE2_URL",
    "NOTION_TEST_TABLE3_URL",
    "CHANNEL_ID",
    "DEV_CHANNEL_ID",
    "VK_TOKEN",
    "VK_USER_ID",
    "VK_GROUP_ID",
    "VK_ALBUM_ID"
]


def read_constants():
    if os.path.exists("prod_constants"):
        warnings.warn(
            message=(
                "Reading constants from file 'prod_constants' will be removed "
                "in future versions."
            ),
            category=DeprecationWarning,
        )

        missing_constants = set(REQUIRED_CONSTANT_NAMES)

        with open("prod_constants") as file:
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
