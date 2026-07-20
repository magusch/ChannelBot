import json, logging, time

from davai_s_nami_bot.celery_app import celery_app, redis_client

log = logging.getLogger(__name__)

_PARAMETERS_TTL = 90000


def fetch_and_store_parameters(parameters=None):
    """Fetch DSN parameters from Django, parse them, and store each site in Redis.

    Shared by the daily Celery ``update_parameters`` task and the reactive,
    synchronous refresh in ``DSNParameters.read_param``. The reactive path calls
    this directly (rather than dispatching the Celery task and polling Redis)
    because the caller may itself be the only worker that would run that task —
    send-task-and-wait then deadlocks until the 15s poll times out and we fall
    back to defaults.

    Returns the parsed ``{site: {param_name: [values]}}`` dict. Raises
    ``requests`` exceptions on transport failure and ``ValueError`` when the
    response isn't JSON (a stale session redirected to the HTML login page) so
    the Celery task's autoretry can heal a transient failure within the run.
    """
    # Imported lazily to keep this module free of the dsn_site_session import
    # (which reads BASE_URL at import time) during early/partial imports.
    from davai_s_nami_bot import dsn_site_session

    response = dsn_site_session.parameter_for_dsn_channel(parameters or {})
    try:
        parsed = response.json()
    except ValueError as e:
        log.error(
            f"fetch_and_store_parameters: Django response wasn't valid JSON "
            f"(status={response.status_code}), likely a stale/expired session "
            f"redirecting to the HTML login page: {e}"
        )
        raise

    dsn_parameters = {}
    for param in parsed:
        value = param["value"]

        full_value = str(param.get("full_value", "") or "").strip()
        if full_value:
            value += f"\n{full_value}"

        site = param["site"]
        name = param["parameter_name"]
        if site not in dsn_parameters:
            dsn_parameters[site] = {name: [value]}
        elif name not in dsn_parameters[site]:
            dsn_parameters[site][name] = [value]
        else:
            dsn_parameters[site][name].append(param["value"])

    for site, params in dsn_parameters.items():
        redis_client.setex(f'parameters:{site}', _PARAMETERS_TTL, json.dumps(params))

    return dsn_parameters


class DSNParameters:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DSNParameters, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        self.sites = {}
        self.update_interval = 3600
        self.start()

    def start(self):
        cached_site_params = redis_client.get(f'parameters:dsn_site')
        if not cached_site_params:
            self.update_parameters()

        self._wait_for_parameters()

    def _wait_for_parameters(self, timeout=15, interval=1):
        """
        Waits for parameters to appear in Redis for up to timeout seconds.
        Falls back to defaults if parameters do not appear.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            cached_site_params = redis_client.get(f'parameters:dsn_site')
            if cached_site_params:
                self._parameters_ready = True
                return
            time.sleep(interval)

        self._parameters_ready = False

    def default_params(self, site_name):
        list_params = {}
        if site_name == 'timepad':
            list_params = ['bad_keywords', 'approved_organization', 'boring_organization',
                           'exclude_categories', 'city', 'price_max']
        elif site_name == 'radario':
            list_params = ['city']
        elif site_name == 'ticketscloud':
            list_params = ['org_id']
        elif site_name == 'qtickets':
            list_params = ['city_id']
        elif site_name == 'vk':
            list_params = ['city', 'city_id']
        elif site_name == 'mts':
            list_params = ['city']
        elif site_name == 'culture':
            list_params = ['city']

        if site_name not in self.sites.keys():
            self.sites[site_name] = {"params": {}, "last_updated": time.time()}

        for key_param in list_params:
            if key_param not in self.sites[site_name]['params'].keys():
                self.sites[site_name]["params"][key_param] = []

    def site_parameters(self, key, last=0):
        site_params = self.read_param('dsn_site')
        if key in site_params.keys():
            if last == 1:
                return site_params[key][-1]
            else:
                return site_params[key]
        else:
            return None

    def read_param(self, site):
        if site not in self.sites.keys() or self._is_stale(site):
            cached_params = redis_client.get(f'parameters:{site}')
            if cached_params is None:
                log.warning(
                    f"DSNParameters: 'parameters:{site}' missing from Redis, "
                    f"refreshing synchronously from Django."
                )
                try:
                    fetch_and_store_parameters()
                except Exception as e:
                    # Transport failure / stale session / bad JSON — fall through
                    # to the in-memory or default fallback below.
                    log.error(
                        f"DSNParameters: synchronous refresh triggered by {site!r} "
                        f"failed: {e}"
                    )
                cached_params = redis_client.get(f'parameters:{site}')
                if cached_params is None:
                    now = time.time()
                    if site in self.sites and self.sites[site].get("params"):
                        log.warning(
                            f"DSNParameters: refresh for {site!r} failed, serving "
                            f"this process's stale in-memory copy until the next "
                            f"refresh window ({self.update_interval}s)."
                        )
                        self.sites[site]["last_updated"] = now
                        return self.sites[site]["params"]
                    log.warning(
                        f"DSNParameters: no parameters available for {site!r} "
                        f"(Redis empty, Django unreachable). site_parameters() will "
                        f"return None and callers fall back to their hardcoded "
                        f"defaults until the next refresh window "
                        f"({self.update_interval}s)."
                    )
                    self.sites[site] = {
                        "params": {},
                        "last_updated": now,
                        "is_default": True,
                    }
                    self.default_params(site)
                    return self.sites[site]["params"]

            self.sites[site] = {
                "params": json.loads(cached_params),
                "last_updated": time.time(),
                "is_default": False,
            }

        self.default_params(site)
        return self.sites[site]["params"]

    def _is_stale(self, site):
        last_updated = self.sites.get(site, {}).get("last_updated", 0)
        return (time.time() - last_updated) > self.update_interval

    def update_parameters(self):
        celery_app.send_task(
            'davai_s_nami_bot.celery_tasks.update_parameters',
        )


dsn_parameters = DSNParameters()