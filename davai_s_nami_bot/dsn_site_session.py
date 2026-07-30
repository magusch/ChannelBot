import logging
import os
import requests

log = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 15

BASE_URL = os.environ.get("BASE_URL")
CHECK_EVENT_STATUS_URL = BASE_URL + "events/check_event_status/"
MOVE_APPROVED_URL = BASE_URL + "events/move_approved_events/"
REMOVE_OLD_URL = BASE_URL + "events/remove_old_events/"
UPDATE_ALL_URL = BASE_URL + "events/update_all/"
FILL_EMPTY_POST_TIME_URL = BASE_URL + "events/fill_empty_post_time/"
PARAMETERS_FOR_CHANNEL = BASE_URL + "events/parameters_for_channel/"
PLACE_ADDRESS = BASE_URL + "place/place_address/"
CSRFTOKEN = None
SESSION_ID = None

def create_session(force: bool = False):
    global CSRFTOKEN
    global SESSION_ID
    if not force and CSRFTOKEN is not None and SESSION_ID is not None: return

    login_url = BASE_URL + "login/"
    login_data = dict(
        username=os.environ.get("DSN_USERNAME"),
        password=os.environ.get("DSN_PASSWORD"),
        next=BASE_URL,
    )
    session = requests.session()

    response = session.get(login_url, headers=_headers(), timeout=_REQUEST_TIMEOUT)
    CSRFTOKEN = response.cookies.get('csrftoken') or session.cookies.get('csrftoken')
    login_data["csrfmiddlewaretoken"] = CSRFTOKEN
    response = session.post(
        login_url, data=login_data, headers=_headers(), timeout=_REQUEST_TIMEOUT
    )
    SESSION_ID = response.cookies.get("sessionid") or session.cookies.get("sessionid")
    #assert response.ok


def _headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.2 (KHTML, like Gecko) Chrome/22.0.1216.0 Safari/537.2'",
        "X-CSRFToken": CSRFTOKEN,
        "Referer": BASE_URL,
    }


def _current_session_get(url):
    """GET with the cached Django session, retried once with a forced
    re-login if the cached session turns out to be stale.

    CSRFTOKEN/SESSION_ID are module-level and only fetched once per process,
    so if Django invalidates the session later (restart, secret rotation,
    natural expiry) every subsequent call would otherwise keep sending the
    dead cookies forever and silently get redirected to the login page —
    parameter_for_dsn_channel would then fail .json() parsing on HTML, and
    callers relying on it (e.g. DSNParameters) would fall back to defaults
    with no visibility into why.
    """
    if CSRFTOKEN is None or SESSION_ID is None:
        create_session()

    for attempt in range(2):
        session = requests.session()
        session.cookies["csrfmiddlewaretoken"] = CSRFTOKEN
        session.cookies["sessionid"] = SESSION_ID
        session.cookies["csrftoken"] = CSRFTOKEN
        response = session.get(url, headers=_headers(), timeout=_REQUEST_TIMEOUT)

        if response.status_code not in (401, 403) and "login" not in response.url:
            return response

        if attempt == 0:
            log.warning(
                f"dsn_site_session: stale session detected on {url} "
                f"(status={response.status_code}), forcing re-login and retrying once."
            )
            create_session(force=True)
        else:
            log.error(
                f"dsn_site_session: {url} still unauthenticated after re-login."
            )
            return response

    return response


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


