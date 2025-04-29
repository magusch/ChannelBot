import json, time

from davai_s_nami_bot.celery_app import celery_app, redis_client

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
        cached_site_params = redis_client.getex(f'parameters:dsn_site')
        if not cached_site_params:
            self.update_parameters()

        self._wait_for_parameters()

    def _wait_for_parameters(self, timeout=15, interval=1):
        """
        Ожидает появления параметров в Redis в течение timeout секунд.
        Если параметры не появляются, работает с дефолтными.
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
            cached_params = redis_client.getex(f'parameters:{site}')
            if cached_params is None:
                self.update_parameters()
                self._wait_for_parameters()
                cached_params = redis_client.getex(f'parameters:{site}')
                if cached_params is None:
                    return {}

            self.sites[site] = {
                "params": json.loads(cached_params),
                "last_updated": time.time(),
                'is_default': not self._parameters_ready
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