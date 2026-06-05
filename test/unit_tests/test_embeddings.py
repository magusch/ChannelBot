from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import httpx
from openai import OpenAIError, RateLimitError

from davai_s_nami_bot.helper import embeddings


def _make_rate_limit_error(message="429"):
    """RateLimitError requires response/body kwargs."""
    response = httpx.Response(429, request=httpx.Request("POST", "https://example/"))
    return RateLimitError(message, response=response, body=None)


def _make_event(**overrides):
    """Duck-typed mock event with None defaults."""
    defaults = dict(
        title=None, category=None, source=None,
        price_int=None, from_date=None,
        full_text=None, prepared_text=None, post=None,
        address=None, place_id=None, place=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestPriceBucket:
    @pytest.mark.parametrize("price,expected", [
        (None, None),
        (-1, None),
        (0, "бесплатно"),
        (100, "символическая цена"),
        (499, "символическая цена"),
        (500, "небольшая цена"),
        (1099, "небольшая цена"),
        (1100, "средняя цена"),
        (1999, "средняя цена"),
        (2000, "существенная цена"),
        (3999, "существенная цена"),
        (4000, "высокая цена"),
        (100000, "высокая цена"),
    ])
    def test_buckets(self, price, expected):
        assert embeddings._price_bucket(price) == expected


class TestPartOfDay:
    @pytest.mark.parametrize("hour,expected", [
        (0, "ночь"),
        (4, "ночь"),
        (5, "утро"),
        (11, "утро"),
        (12, "день"),
        (17, "день"),
        (18, "вечер"),
        (22, "вечер"),
        (23, "ночь"),
    ])
    def test_hours(self, hour, expected):
        dt = datetime(2026, 5, 15, hour, 0)
        assert embeddings._part_of_day(dt) == expected

    def test_none(self):
        assert embeddings._part_of_day(None) is None


class TestCleanHtml:
    def test_strips_tags(self):
        html = "<p>Концерт <b>группы</b> в <a href='x'>клубе</a></p>"
        assert embeddings._clean_html(html) == "Концерт группы в клубе"

    def test_collapses_whitespace(self):
        assert embeddings._clean_html("a  b\n\nc\t\td") == "a b c d"

    def test_empty(self):
        assert embeddings._clean_html("") == ""
        assert embeddings._clean_html(None) == ""


class TestPlaceStr:
    def test_uses_place_relationship_when_id_set(self):
        place = SimpleNamespace(
            place_name="Лес", place_address="ул. Дерева, 1", place_metro="Лесная",
        )
        event = _make_event(place_id=1, place=place, address="мусорный адрес")
        assert embeddings._place_str(event) == "Лес, ул. Дерева, 1, м. Лесная"

    def test_falls_back_to_address_when_no_place_id(self):
        event = _make_event(place_id=None, place=None, address="ул. Невского, 5")
        assert embeddings._place_str(event) == "ул. Невского, 5"

    def test_none_when_all_empty(self):
        event = _make_event()
        assert embeddings._place_str(event) is None

    def test_place_without_metro(self):
        place = SimpleNamespace(
            place_name="X", place_address="ул. Y", place_metro=None,
        )
        event = _make_event(place_id=1, place=place)
        assert embeddings._place_str(event) == "X, ул. Y"


class TestBuildEmbeddingInput:
    def test_full_event(self):
        place = SimpleNamespace(
            place_name="Сцена", place_address="ул. А", place_metro="Спортивная",
        )
        event = _make_event(
            title="Концерт «Лес»",
            category="Концерты",
            source="timepad",
            price_int=1000,
            from_date=datetime(2026, 5, 16, 19, 0),  # Saturday, evening
            full_text="<p>Описание <b>концерта</b></p>",
            place_id=10, place=place,
        )
        result = embeddings.build_embedding_input(event)
        assert "Концерт «Лес»" in result
        assert "Категория: Концерты" in result
        assert "Место: Сцена, ул. А, м. Спортивная" in result
        assert "Источник: timepad" in result
        assert "Когда: суббота, вечер" in result
        assert "Цена: небольшая цена" in result
        assert "Описание концерта" in result

    def test_skips_empty_fields_entirely(self):
        """None fields must not produce 'Категория: —' or similar placeholders."""
        event = _make_event(title="Просто заголовок", price_int=None, category=None)
        result = embeddings.build_embedding_input(event)
        assert "Категория" not in result
        assert "Цена" not in result
        assert "—" not in result
        assert "None" not in result
        assert "Просто заголовок" in result

    def test_prefers_prepared_text_over_full_text(self):
        event = _make_event(
            title="X",
            prepared_text="Готовый текст",
            full_text="Сырой текст",
            post="Пост",
        )
        result = embeddings.build_embedding_input(event)
        assert "Готовый текст" in result
        assert "Сырой текст" not in result

    def test_falls_back_to_full_text_then_post(self):
        e1 = _make_event(title="X", full_text="полный", post="пост")
        assert "полный" in embeddings.build_embedding_input(e1)

        e2 = _make_event(title="X", post="пост")
        assert "пост" in embeddings.build_embedding_input(e2)

    def test_unknown_price_skipped(self):
        event = _make_event(title="X", price_int=-1)
        assert "Цена" not in embeddings.build_embedding_input(event)

    def test_free_price_word(self):
        event = _make_event(title="X", price_int=0)
        assert "Цена: бесплатно" in embeddings.build_embedding_input(event)

    def test_truncation(self):
        long_body = "а" * 10000
        event = _make_event(title="X", full_text=long_body)
        result = embeddings.build_embedding_input(event)
        assert len(result) <= embeddings.MAX_INPUT_CHARS

    def test_no_metadata_section_when_all_empty(self):
        event = _make_event(title="Только заголовок", full_text="Тело")
        result = embeddings.build_embedding_input(event)
        assert "Категория" not in result
        assert "Место" not in result
        assert "Только заголовок" in result
        assert "Тело" in result


class TestProviderConfig:
    def test_gemini_is_default(self):
        with patch("davai_s_nami_bot.helper.embeddings.OpenAI"):
            client = embeddings.EmbeddingClient(provider="gemini")
        assert client.provider == "gemini"
        assert client.model == "gemini-embedding-001"
        assert client.model_label == "gemini:gemini-embedding-001"
        assert client.batch_size == 50
        assert client.inter_batch_sleep == 15

    def test_openai_provider(self):
        with patch("davai_s_nami_bot.helper.embeddings.OpenAI"):
            client = embeddings.EmbeddingClient(provider="openai")
        assert client.provider == "openai"
        assert client.model == "text-embedding-3-small"
        assert client.model_label == "openai:text-embedding-3-small"
        assert client.batch_size == 100
        assert client.inter_batch_sleep == 0

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown embedding provider"):
            embeddings.EmbeddingClient(provider="anthropic")

    def test_overrides_win_over_config(self):
        with patch("davai_s_nami_bot.helper.embeddings.OpenAI"):
            client = embeddings.EmbeddingClient(
                provider="gemini", batch_size=10, inter_batch_sleep=2,
            )
        assert client.batch_size == 10
        assert client.inter_batch_sleep == 2

    def test_gemini_uses_compat_base_url(self):
        with patch("davai_s_nami_bot.helper.embeddings.OpenAI") as mock_openai:
            embeddings.EmbeddingClient(provider="gemini")
        _, kwargs = mock_openai.call_args
        assert kwargs["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai/"

    def test_openai_omits_base_url(self):
        with patch("davai_s_nami_bot.helper.embeddings.OpenAI") as mock_openai:
            embeddings.EmbeddingClient(provider="openai")
        _, kwargs = mock_openai.call_args
        assert "base_url" not in kwargs


class TestEmbeddingClient:
    def _fake_response(self, vectors):
        return SimpleNamespace(
            data=[SimpleNamespace(index=i, embedding=v) for i, v in enumerate(vectors)]
        )

    def _make_client(self, **overrides):
        overrides.setdefault("inter_batch_sleep", 0)
        with patch("davai_s_nami_bot.helper.embeddings.OpenAI"):
            client = embeddings.EmbeddingClient(provider="gemini", **overrides)
        client.client = MagicMock()
        return client

    def test_embed_batch_returns_vectors_in_order(self):
        client = self._make_client()
        client.client.embeddings.create.return_value = self._fake_response(
            [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
        )

        result = client.embed_batch(["a", "b", "c"])
        assert result == [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
        client.client.embeddings.create.assert_called_once_with(
            model="gemini-embedding-001",
            input=["a", "b", "c"],
            extra_body={"dimensions": embeddings.EMBEDDING_DIMENSIONS},
        )

    def test_embed_batch_chunks_with_inter_batch_sleep(self):
        client = self._make_client(batch_size=2, inter_batch_sleep=15)
        client.client.embeddings.create.side_effect = [
            self._fake_response([[1.0], [2.0]]),
            self._fake_response([[3.0]]),
        ]

        with patch.object(embeddings.time, "sleep") as mock_sleep:
            result = client.embed_batch(["a", "b", "c"])

        assert result == [[1.0], [2.0], [3.0]]
        assert client.client.embeddings.create.call_count == 2
        # Between 2 chunks → exactly one sleep of 15 s.
        mock_sleep.assert_called_once_with(15)

    def test_no_sleep_after_last_chunk(self):
        client = self._make_client(batch_size=2, inter_batch_sleep=15)
        client.client.embeddings.create.return_value = self._fake_response([[1.0], [2.0]])

        with patch.object(embeddings.time, "sleep") as mock_sleep:
            client.embed_batch(["a", "b"])

        mock_sleep.assert_not_called()

    def test_embed_batch_empty(self):
        client = self._make_client()
        assert client.embed_batch([]) == []
        client.client.embeddings.create.assert_not_called()

    def test_retry_on_openai_error(self):
        client = self._make_client()
        client.client.embeddings.create.side_effect = [
            OpenAIError("transient"),
            self._fake_response([[0.1]]),
        ]
        with patch.object(embeddings.time, "sleep"):
            result = client.embed_batch(["a"], max_retries=3)
        assert result == [[0.1]]
        assert client.client.embeddings.create.call_count == 2

    def test_retry_on_rate_limit_uses_long_backoff(self):
        client = self._make_client()
        client.client.embeddings.create.side_effect = [
            _make_rate_limit_error(),
            _make_rate_limit_error(),
            self._fake_response([[0.1]]),
        ]
        with patch.object(embeddings.time, "sleep") as mock_sleep:
            result = client.embed_batch(["a"], max_retries=4)
        assert result == [[0.1]]
        # Gemini base = 30: 30, 60.
        sleeps = [c.args[0] for c in mock_sleep.call_args_list]
        assert 30 in sleeps and 60 in sleeps

    def test_retry_exhausts_and_raises(self):
        client = self._make_client()
        client.client.embeddings.create.side_effect = OpenAIError("nope")
        with patch.object(embeddings.time, "sleep"), pytest.raises(OpenAIError):
            client.embed_batch(["a"], max_retries=2)
        assert client.client.embeddings.create.call_count == 2

    def test_preserves_response_order(self):
        """We rely on the API preserving input order (no explicit sort).
        Gemini-compat doesn't populate `.index`, so sorting by it would crash.
        """
        client = self._make_client()
        client.client.embeddings.create.return_value = SimpleNamespace(
            data=[
                SimpleNamespace(index=None, embedding=[0.1]),
                SimpleNamespace(index=None, embedding=[0.2]),
                SimpleNamespace(index=None, embedding=[0.3]),
            ]
        )
        result = client.embed_batch(["a", "b", "c"])
        assert result == [[0.1], [0.2], [0.3]]

    def test_openai_provider_uses_short_backoff(self):
        with patch("davai_s_nami_bot.helper.embeddings.OpenAI"):
            client = embeddings.EmbeddingClient(provider="openai")
        client.client = MagicMock()
        client.client.embeddings.create.side_effect = [
            _make_rate_limit_error(),
            SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.1])]),
        ]
        with patch.object(embeddings.time, "sleep") as mock_sleep:
            result = client.embed_batch(["a"], max_retries=2)
        assert result == [[0.1]]
        # OpenAI base = 5: first retry sleeps 5s.
        assert 5 in [c.args[0] for c in mock_sleep.call_args_list]
