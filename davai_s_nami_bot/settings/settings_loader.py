import copy
import json
import logging
import os

from davai_s_nami_bot import city_context

log = logging.getLogger(__name__)

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

CITY_SCHEDULE_OFFSET_MINUTES = 90


def _city_is_active(code) -> bool:
    try:
        from davai_s_nami_bot import city as city_module

        info = city_module.get_city(code)
    except Exception as e:  # noqa: BLE001 — unreadable DB means "not active"
        log.warning(f"settings: cannot read city_city for {code!r}: {e}")
        return False
    return bool(info and info.is_active)


def deep_merge(base, override):
    """``override`` on top of ``base``: dicts merge key by key, anything else
    (lists included) is replaced. Neither argument is modified."""
    if not isinstance(base, dict) or not isinstance(override, dict):
        return copy.deepcopy(override)
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


class _Feature:
    """A ``features`` key read for the current city.

    Assignable, for tests and one-off scripts: an assigned value wins for every
    city until it is deleted or set back to what the descriptor computes
    (monkeypatch undo does exactly that).
    """

    def __init__(self, key, default=None, required=False):
        self.key, self.default, self.required = key, default, required

    def __set_name__(self, owner, name):
        self.name = name

    def _computed(self, obj):
        features = obj.features
        if self.required:
            return features[self.key]
        return features.get(self.key, self.default)

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        if self.name in obj._overrides:
            return obj._overrides[self.name]
        return self._computed(obj)

    def __set__(self, obj, value):
        try:
            computed = self._computed(obj)
        except KeyError:
            computed = None
        if value is computed:
            obj._overrides.pop(self.name, None)
        else:
            obj._overrides[self.name] = value

    def __delete__(self, obj):
        obj._overrides.pop(self.name, None)


class Settings:
    """``settings.json`` with a per-city layer.

    ``features`` holds the shared defaults; ``cities.<code>`` overrides any of them
    for one city (deep merge, lists replace). Every attribute below resolves
    against the *current* city (``city_context.current_city()``), so code that
    reads ``settings.escraper_parameters`` inside ``use_city('kzn')`` gets Kazan's
    scrapers without knowing about cities.

    ``cities`` keys are also the cities the beat schedules (see
    ``scheduled_cities``). Without a ``cities`` section the default city alone
    is scheduled — the single-city behaviour before multicity.
    """

    def __init__(self):
        base_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        config_path = os.path.join(base_dir, os.getenv("CONFIG_PATH", "settings.json"))
        with open(config_path, 'r') as f:
            self.raw = json.load(f)

        self.celery_worker_enabled = self.raw['celery']['worker_enabled']
        self.celery_beat_enabled = self.raw['celery']['beat_enabled']

        base = self.raw.get('features', {})
        default_city = base.get('default_city') or base.get('city')
        if default_city:
            city_context.DEFAULT_CITY = city_context.normalize_city(default_city)
        self._merged = {}
        self._overrides = {}

    # --- per-city resolution -------------------------------------------------

    @property
    def cities_config(self) -> dict:
        return self.raw.get('cities') or {}

    def scheduled_cities(self) -> list:
        """Cities the beat runs the pipeline for, default city first.

        The default city always runs. Any other city needs both switches: an
        explicit ``"enabled": true`` in its ``cities.<code>`` section and
        ``city_city.is_active``. A section alone (config prepared in advance) or
        an admin flipping ``is_active`` alone schedules nothing — a half-set-up
        city would post into a channel it has not got, or scrape SPb (see
        ``scraper_configured``).
        """
        default = city_context.DEFAULT_CITY
        codes = [default]
        for code, section in self.cities_config.items():
            code = city_context.normalize_city(code)
            if code == default or code in codes:
                continue
            if not (isinstance(section, dict) and section.get('enabled') is True):
                continue
            if not _city_is_active(code):
                log.warning(
                    f"settings: city {code!r} is enabled in settings but not active "
                    f"in city_city (or city_city is unreadable) — not scheduled"
                )
                continue
            codes.append(code)
        return codes

    def beat_offset_minutes(self, city=None) -> int:
        """How far this city's daily beat entries are moved after the default
        city's: ``cities.<code>.beat_offset_minutes``, else
        ``CITY_SCHEDULE_OFFSET_MINUTES`` × position in ``scheduled_cities``."""
        city = city or city_context.current_city()
        cities = self.scheduled_cities()
        if city not in cities or cities.index(city) == 0:
            return 0
        explicit = (self.cities_config.get(city) or {}).get('beat_offset_minutes')
        if explicit is not None:
            return int(explicit)
        return cities.index(city) * CITY_SCHEDULE_OFFSET_MINUTES

    def scraper_configured(self, name, city=None) -> bool:
        """May ``name`` scrape for ``city``?

        The default city: always (its config is ``features``). Any other city:
        only when its own ``cities.<code>.escraper_parameters`` names the scraper.
        Merged settings are not enough — the base section carries SPb's slugs
        («Санкт-Петербург», ``saint-petersburg``, cfg's SPb venues), and every
        scraper falls back to SPb in code, so an unlisted scraper would quietly
        fill Kazan with Petersburg events.
        """
        city = city or city_context.current_city()
        if city == city_context.DEFAULT_CITY:
            return True
        own = (self.cities_config.get(city) or {}).get('escraper_parameters') or {}
        return name in own

    def features_for(self, city=None) -> dict:
        city = city or city_context.current_city()
        base = self.raw.setdefault('features', {})
        override = self.cities_config.get(city)
        if not override:
            # No overlay: the live dict, so edits to `raw` show up immediately.
            return base
        if city not in self._merged:
            self._merged[city] = deep_merge(base, override)
        return self._merged[city]

    @property
    def features(self) -> dict:
        return self.features_for()

    # --- feature attributes (all per current city) ---------------------------

    task_event_post = _Feature('task_event_post', required=True)
    task_digest_post = _Feature('task_digest_post', required=True)
    timezone = _Feature('timezone', required=True)
    escraper_parameters = _Feature('escraper_parameters', required=True)
    content_generator = _Feature('content_generator', {})
    scoring = _Feature('scoring', {})
    vk_posting_enabled = _Feature('vk_posting_enabled', False)
    prepare_events_limit = _Feature('prepare_events_limit', 0)
    auto_route_to_api = _Feature('auto_route_to_api', {})
    route_unschedulable = _Feature('route_unschedulable', {})
    auto_moderate_sample_size = _Feature('auto_moderate_sample_size', 0)
    route_mid_score_to_api = _Feature('route_mid_score_to_api', {})
    query_analyzer = _Feature('query_analyzer', {})
    metro_adjacency = _Feature('metro_adjacency', {})

    @property
    def city(self):
        return city_context.current_city()

    def _city_forms(self):
        """Name forms of the current city: city_city row first, then code map."""
        city = self.city
        forms = None
        try:
            from davai_s_nami_bot import city as city_module

            forms = city_module.city_name_forms(city)
        except Exception as e:  # noqa: BLE001 — DB/import trouble must not break prompts
            log.debug(f"settings: city forms for {city!r} from DB unavailable: {e}")
        return forms or _CITY_FORMS.get(city, _DEFAULT_CITY_FORMS)

    @property
    def city_name(self):
        return self.features.get('city_name') or self._city_forms()["nom"]

    @property
    def city_name_gen(self):
        return self.features.get('city_name_gen') or self._city_forms()["gen"]

    @property
    def city_name_loc(self):
        return self.features.get('city_name_loc') or self._city_forms()["loc"]


settings = Settings()
