import os


HOST_URL = "https://xxx.herokuapp.com/"
HOST_LOCAL_IP = "0.0.0.0"


def running_from_heroku():
    return "BOT_TOKEN" in list(os.environ.keys())


def get_token():
    if running_from_heroku():
        BOT_TOKEN = os.environ.get("BOT_TOKEN")
    else:
        with open("misk") as misk:
            BOT_TOKEN, *_ = misk.read().split("\n")

    return BOT_TOKEN
