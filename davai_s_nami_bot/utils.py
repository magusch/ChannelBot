import os


HOST_URL = "https://channeltelegrambot.herokuapp.com/"
HOST_LOCAL_IP = "0.0.0.0"


def running_from_heroku():
    return "FROM_HEROKU" in list(os.environ.keys())


def get_token():
    return os.environ.get("BOT_TOKEN")
