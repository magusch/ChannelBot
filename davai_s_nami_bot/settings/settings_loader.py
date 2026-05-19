import json
import os


class Settings:
    def __init__(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        config_path = os.path.join(base_dir, os.getenv("CONFIG_PATH", "settings.json"))
        with open(config_path, 'r') as f:
            self.raw = json.load(f)

        self.celery_worker_enabled = self.raw['celery']['worker_enabled']
        self.celery_beat_enabled = self.raw['celery']['beat_enabled']

        self.task_event_post = self.raw['features']['task_event_post']
        self.task_digest_post = self.raw['features']['task_digest_post']
        self.city = self.raw['features']['city']
        self.timezone = self.raw['features']['timezone']
        self.escraper_parameters = self.raw['features']['escraper_parameters']
        self.content_generator = self.raw['features'].get('content_generator', {})
        self.scoring = self.raw['features'].get('scoring', {})
        self.vk_posting_enabled = self.raw['features'].get('vk_posting_enabled', False)
        self.prepare_events_limit = self.raw['features'].get('prepare_events_limit', 0)
        self.auto_route_to_api = self.raw['features'].get('auto_route_to_api', {})


settings = Settings()
