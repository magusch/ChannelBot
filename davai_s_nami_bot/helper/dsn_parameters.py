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
        self.start()


    def scrape_parameters(self):
        self.timepad_bad_keywords = self.read_param('timepad')['bad_keywords']
        self.timepad_approved_organizations = self.read_param('timepad')['approved_organization']
        self.timepad_boring_organizations = self.read_param('timepad')['boring_organization']

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
        if site not in self.sites.keys():
            cached_params = redis_client.getex(f'parameters:{site}')
            if cached_params is None:
                self.update_parameters()
                time.sleep(15)
                cached_params = redis_client.getex(f'parameters:{site}')
                if cached_params is None:
                    return {}
            self.sites[site] = json.loads(cached_params)
        return self.sites[site]

    def start(self):
        cached_site_params = redis_client.getex(f'parameters:dsn_site')
        if cached_site_params:
            return True
        else:
            self.update_parameters()

    def update_parameters(self):
        celery_app.send_task(
            'davai_s_nami_bot.celery_tasks.update_parameters',
        )


dsn_parameters = DSNParameters()