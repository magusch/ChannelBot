import os
import requests


BASE_URL = os.environ.get("BASE_URL")
CHECK_EVENT_STATUS_URL = BASE_URL + "events/check_event_status/"
MOVE_APPROVED_URL = BASE_URL + "events/move_approved_events/"
REMOVE_OLD_URL = BASE_URL + "events/remove_old_events/"
UPDATE_ALL_URL = BASE_URL + "events/update_all/"
FILL_EMPTY_POST_TIME_URL = BASE_URL + "events/fill_empty_post_time/"
PARAMETERS_FOR_CHANNEL = BASE_URL + "events/parameters_for_channel/"
PLACE_ADDRESS = BASE_URL + "place/place_address/"
MAKE_POST = BASE_URL + "events/make_post/"
CSRFTOKEN = None
SESSION_ID = None

def create_session():
    global CSRFTOKEN
    global SESSION_ID

    login_url = BASE_URL + "login/"
    login_data = dict(
        username=os.environ.get("DSN_USERNAME"),
        password=os.environ.get("DSN_PASSWORD"),
        next=BASE_URL,
    )
    session = requests.session()
    session.get(login_url, headers=_headers())

    CSRFTOKEN = session.cookies["csrftoken"]

    login_data["csrfmiddlewaretoken"] = CSRFTOKEN
    response = session.post(login_url, data=login_data, headers=_headers())
    SESSION_ID = session.cookies["sessionid"]
    #assert response.ok


def _headers():
    return {"User-Agent": "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.2 (KHTML, like Gecko) Chrome/22.0.1216.0 Safari/537.2'"} #UserAgent().random}


def _current_session_get(url):
    session = requests.session()
    if CSRFTOKEN is None or SESSION_ID is None: create_session()

    session.cookies["csrfmiddlewaretoken"] = CSRFTOKEN
    session.cookies["sessionid"] = SESSION_ID
    return session.get(url, headers=_headers())

def check_event_status():
    _current_session_get(url=CHECK_EVENT_STATUS_URL)

def move_approved():
    _current_session_get(url=MOVE_APPROVED_URL)

def remove_old():
    _current_session_get(url=REMOVE_OLD_URL)

def fill_empty_post_time():
    _current_session_get(url=FILL_EMPTY_POST_TIME_URL)

def parameter_for_dsn_channel(parameters={}):
    query_parameters = '?'
    for p_key, p_value in parameters.items():
        query_parameters += f"{p_key}={p_value}&"
    return _current_session_get(url=PARAMETERS_FOR_CHANNEL + query_parameters)

def place_address(raw_address):
    url = f"{PLACE_ADDRESS}?address={raw_address}"
    return _current_session_get(url=url)

def make_post_text(ids):
    if type(ids) == list:
        ids_string = ','.join(map(str, ids))
    else:
        ids_string = ids
    url = f"{MAKE_POST}{ids_string}"
    _current_session_get(url=url)


