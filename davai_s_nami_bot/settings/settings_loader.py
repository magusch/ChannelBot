import json
import os

_CITY_FORMS = {
    "spb": {
        "nom": "Санкт-Петербург",
        "gen": "Санкт-Петербурга",
        "loc": "Санкт-Петербурге",
    },
    "kzn": {"nom": "Казань", "gen": "Казани", "loc": "Казани"},
    "msk": {"nom": "Москва", "gen": "Москвы", "loc": "Москве"},
}
_DEFAULT_CITY_FORMS = _CITY_FORMS["spb"]


class Settings:
    def __init__(self):
        base_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        config_path = os.path.join(base_dir, os.getenv("CONFIG_PATH", "settings.json"))
        with open(config_path, 'r') as f:
            self.raw = json.load(f)

        self.celery_worker_enabled = self.raw['celery']['worker_enabled']
        self.celery_beat_enabled = self.raw['celery']['beat_enabled']

        self.task_event_post = self.raw['features']['task_event_post']
        self.task_digest_post = self.raw['features']['task_digest_post']
        self.city = self.raw['features']['city']
        _forms = _CITY_FORMS.get(self.city, _DEFAULT_CITY_FORMS)
        self.city_name = self.raw['features'].get('city_name') or _forms["nom"]
        self.city_name_gen = self.raw['features'].get('city_name_gen') or _forms["gen"]
        self.city_name_loc = self.raw['features'].get('city_name_loc') or _forms["loc"]
        self.timezone = self.raw['features']['timezone']
        self.escraper_parameters = self.raw['features']['escraper_parameters']
        self.content_generator = self.raw['features'].get('content_generator', {})
        self.scoring = self.raw['features'].get('scoring', {})
        self.vk_posting_enabled = self.raw['features'].get('vk_posting_enabled', False)
        self.prepare_events_limit = self.raw['features'].get('prepare_events_limit', 0)
        self.auto_route_to_api = self.raw['features'].get('auto_route_to_api', {})
        self.route_unschedulable = self.raw['features'].get('route_unschedulable', {})
        self.query_analyzer = self.raw['features'].get('query_analyzer', {})
        self.metro_adjacency = self.raw['features'].get('metro_adjacency', {})


settings = Settings()
