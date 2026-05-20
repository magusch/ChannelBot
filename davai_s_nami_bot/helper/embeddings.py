# -*- coding: utf-8 -*-
"""Semantic event embeddings for RAG (similarity, dedup, few-shot moderation).

The same canonical input is used for both Events2Posts and EventsNotApproved
so that vectors between tables are directly comparable.

Default provider is Gemini (via its OpenAI-compatible endpoint, same pattern as
GeminiHelper). OpenAI is kept as an alternative — switch via EMBEDDING_PROVIDER
env var or constructor arg. Gemini free tier is tight (~5 RPM, ~30k TPM), so
batches are small and there is an inter-batch sleep.
"""
import logging
import os
import time

from bs4 import BeautifulSoup
from openai import OpenAI, OpenAIError, RateLimitError

log = logging.getLogger(__name__)


# --- Provider configs -------------------------------------------------------

PROVIDER_GEMINI = "gemini"
PROVIDER_OPENAI = "openai"

# Vector dimensions used everywhere (also in the DB column). Both providers
# support this size: gemini-embedding-001 via Matryoshka truncation,
# text-embedding-3-small natively. Stays under pgvector HNSW limit (2000).
EMBEDDING_DIMENSIONS = 1536

PROVIDER_CONFIGS = {
    PROVIDER_GEMINI: {
        "model": "gemini-embedding-001",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key_env": "GEMINI_API",
        # Free tier guardrails. ~50 texts × ~500 tokens = ~25k tokens (under 30k TPM).
        "batch_size": 50,
        # 5 RPM = one request every 12 s. 15 s gives margin.
        "inter_batch_sleep": 15,
        # Backoff base for 429 — exponential.
        "rate_limit_backoff_base": 30,
    },
    PROVIDER_OPENAI: {
        "model": "text-embedding-3-small",
        "base_url": None,
        "api_key_env": "OPENAI_API_KEY",
        # OpenAI tier-1 is generous (3000 RPM, 1M TPM); 100 per batch is fine
        # and the inter-batch sleep is not needed.
        "batch_size": 100,
        "inter_batch_sleep": 0,
        "rate_limit_backoff_base": 5,
    },
}

# Default provider — switch with EMBEDDING_PROVIDER env var (or pass to ctor).
DEFAULT_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", PROVIDER_GEMINI).lower()


def _provider_label(provider, model):
    """Stored in embedding_model column to detect provider+model changes."""
    return f"{provider}:{model}"


def current_embedding_model_label():
    cfg = PROVIDER_CONFIGS[DEFAULT_PROVIDER]
    return _provider_label(DEFAULT_PROVIDER, cfg["model"])


# --- Canonical input builder ------------------------------------------------

# ~2000 tokens for Russian text ≈ 6000 characters.
MAX_INPUT_CHARS = 6000

_WEEKDAYS_RU = [
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье",
]


def _clean_html(text):
    """Strip HTML tags, keep link text, collapse whitespace."""
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return " ".join(soup.get_text(separator=" ").split())


def _price_bucket(price_int):
    """Map price to a Russian word. None/-1 → None (line is skipped entirely)."""
    if price_int is None or price_int < 0:
        return None
    if price_int == 0:
        return "бесплатно"
    if price_int < 500:
        return "символическая цена"
    if price_int < 1100:
        return "небольшая цена"
    if price_int < 2000:
        return "средняя цена"
    if price_int < 4000:
        return "существенная цена"
    return "высокая цена"


def _part_of_day(dt):
    if dt is None:
        return None
    h = dt.hour
    if 5 <= h < 12:
        return "утро"
    if 12 <= h < 18:
        return "день"
    if 18 <= h < 23:
        return "вечер"
    return "ночь"


def _when_str(dt):
    if dt is None:
        return None
    parts = [_WEEKDAYS_RU[dt.weekday()], _part_of_day(dt)]
    return ", ".join(p for p in parts if p)


def _place_str(event):
    """Canonical place from DB OR raw address — never a mix of the two."""
    place = getattr(event, "place", None)
    place_id = getattr(event, "place_id", None)
    if place_id and place is not None:
        parts = [
            getattr(place, "place_name", None),
            getattr(place, "place_address", None),
        ]
        metro = getattr(place, "place_metro", None)
        if metro:
            parts.append(f"м. {metro}")
        joined = ", ".join(p for p in parts if p)
        return joined or None
    return getattr(event, "address", None) or None


def _body(event):
    """prepared_text (if present) → full_text → post. HTML is stripped."""
    for attr in ("prepared_text", "full_text", "post"):
        raw = getattr(event, attr, None)
        if raw:
            cleaned = _clean_html(raw)
            if cleaned:
                return cleaned
    return None


def _truncate(text, max_chars=MAX_INPUT_CHARS):
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def build_embedding_input(event):
    """Canonical text for embedding. Empty fields skip their line entirely.

    Duck-typed: works for both Events2Posts and EventsNotApproved.
    """
    lines = []

    title = getattr(event, "title", None)
    if title:
        lines.append(title)
        lines.append("")

    metadata = [
        ("Категория", getattr(event, "category", None)),
        ("Место", _place_str(event)),
        ("Источник", getattr(event, "source", None)),
        ("Когда", _when_str(getattr(event, "from_date", None))),
        ("Цена", _price_bucket(getattr(event, "price_int", None))),
    ]
    for label, value in metadata:
        if value:
            lines.append(f"{label}: {value}")

    body = _body(event)
    if body:
        lines.append("")
        lines.append(body)

    return _truncate("\n".join(lines).strip())


# --- Embedding client -------------------------------------------------------

class EmbeddingClient:
    """OpenAI-SDK based client. Works for both OpenAI and Gemini (compat endpoint).

    Knobs (batch size, inter-batch sleep, backoff) come from PROVIDER_CONFIGS
    but can be overridden via constructor args.
    """

    def __init__(
        self,
        provider=None,
        model=None,
        dimensions=EMBEDDING_DIMENSIONS,
        batch_size=None,
        inter_batch_sleep=None,
        rate_limit_backoff_base=None,
    ):
        self.provider = (provider or DEFAULT_PROVIDER).lower()
        if self.provider not in PROVIDER_CONFIGS:
            raise ValueError(
                f"Unknown embedding provider {self.provider!r}, "
                f"expected one of {list(PROVIDER_CONFIGS)}"
            )
        cfg = PROVIDER_CONFIGS[self.provider]

        self.model = model or cfg["model"]
        self.dimensions = dimensions
        self.batch_size = batch_size if batch_size is not None else cfg["batch_size"]
        self.inter_batch_sleep = (
            inter_batch_sleep if inter_batch_sleep is not None else cfg["inter_batch_sleep"]
        )
        self.rate_limit_backoff_base = (
            rate_limit_backoff_base
            if rate_limit_backoff_base is not None
            else cfg["rate_limit_backoff_base"]
        )

        api_key = os.environ.get(cfg["api_key_env"])
        client_kwargs = {"api_key": api_key}
        if cfg["base_url"]:
            client_kwargs["base_url"] = cfg["base_url"]
        self.client = OpenAI(**client_kwargs)

    @property
    def model_label(self):
        """Provider-qualified model id, stored in embedding_model DB column."""
        return _provider_label(self.provider, self.model)

    def embed_batch(self, texts, max_retries=4):
        """texts -> list[list[float]] in input order. Chunked by batch_size with
        an inter-batch sleep to stay under RPM on tight free tiers.
        """
        if not texts:
            return []

        results = []
        chunks = [texts[i:i + self.batch_size] for i in range(0, len(texts), self.batch_size)]
        for idx, chunk in enumerate(chunks):
            results.extend(self._embed_with_retry(chunk, max_retries))
            if idx < len(chunks) - 1 and self.inter_batch_sleep > 0:
                time.sleep(self.inter_batch_sleep)
        return results

    def _embed_with_retry(self, chunk, max_retries):
        last_exc = None
        for attempt in range(max_retries):
            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=chunk,
                    dimensions=self.dimensions,
                )
                ordered = sorted(response.data, key=lambda d: d.index)
                return [item.embedding for item in ordered]
            except RateLimitError as e:
                last_exc = e
                # Heavy backoff for 429: 30s, 60s, 120s, 240s by default.
                backoff = self.rate_limit_backoff_base * (2 ** attempt)
                log.warning(
                    f"{self.provider} 429 rate limit (attempt {attempt + 1}/{max_retries}). "
                    f"Sleeping {backoff}s before retry."
                )
                time.sleep(backoff)
            except OpenAIError as e:
                last_exc = e
                backoff = 2 ** attempt
                log.warning(
                    f"{self.provider} embeddings error (attempt {attempt + 1}/{max_retries}): {e}. "
                    f"Retry in {backoff}s."
                )
                time.sleep(backoff)
        raise last_exc


# Stub for future consumers (moderation, dedup). Will be implemented in phase 2.
# def find_similar_events(event_id: int, k: int = 5, source_table: str = "events2posts"):
#     """ORDER BY embedding <=> :query LIMIT :k via pgvector."""
#     raise NotImplementedError
