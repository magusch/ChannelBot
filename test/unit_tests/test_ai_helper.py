import datetime
import json

import pytest
from unittest.mock import MagicMock, Mock


@pytest.fixture
def mock_dsn():
    dsn = MagicMock()
    dsn.site_parameters.return_value = None
    return dsn


# --- Claude Helper ---

class TestClaudeHelper:
    def test_json_parse_relevant(self, mock_dsn):
        from davai_s_nami_bot.helper.ai.claude_helper import ClaudeHelper
        helper = ClaudeHelper(mock_dsn)
        helper.answer = [MagicMock(text=json.dumps({
            'title': '🎸 Концерт «Пасош»',
            'prepared_text': 'Группа Пасош выступит с новой программой.',
            'category': 'Концерты',
            'address': 'Бар Модус, Рубинштейна 20',
            'price': '500 рублей',
            'from_date': '2026-03-15T19:00',
            'to_date': None,
            'url': 'https://example.com',
            'relevant': True,
            'reject_reason': '',
        }, ensure_ascii=False))]

        result = helper.new_event_data({})
        assert result['title'] == '🎸 Концерт «Пасош»'
        assert result['prepared_text'] == 'Группа Пасош выступит с новой программой.'
        assert result['category'] == 'Концерты'
        assert result['ai_relevant'] is True
        assert result['ai_reject_reason'] == ''

    def test_json_parse_rejected(self, mock_dsn):
        from davai_s_nami_bot.helper.ai.claude_helper import ClaudeHelper
        helper = ClaudeHelper(mock_dsn)
        helper.answer = [MagicMock(text=json.dumps({
            'title': '💼 Конференция BizTech',
            'prepared_text': 'Бизнес-конференция.',
            'category': 'Без категории',
            'address': 'Отель',
            'price': '5000 рублей',
            'from_date': '2026-03-20T10:00',
            'to_date': None,
            'url': 'https://example.com',
            'relevant': False,
            'reject_reason': 'бизнес-мероприятие',
        }, ensure_ascii=False))]

        result = helper.new_event_data({})
        assert result['ai_relevant'] is False
        assert 'бизнес' in result['ai_reject_reason']

    def test_json_parse_past_event(self, mock_dsn):
        from davai_s_nami_bot.helper.ai.claude_helper import ClaudeHelper
        helper = ClaudeHelper(mock_dsn)
        helper.answer = [MagicMock(text=json.dumps({
            'title': '🎭 Спектакль «Чайка»',
            'prepared_text': 'Постановка уже состоялась.',
            'category': 'Театр',
            'address': 'БДТ',
            'price': '1000 рублей',
            'from_date': '2025-01-01T19:00',
            'to_date': None,
            'url': 'https://example.com',
            'relevant': False,
            'reject_reason': 'мероприятие уже прошло',
        }, ensure_ascii=False))]

        result = helper.new_event_data({})
        assert result['ai_relevant'] is False
        assert 'прошло' in result['ai_reject_reason']

    def test_fallback_old_format(self, mock_dsn):
        from davai_s_nami_bot.helper.ai.claude_helper import ClaudeHelper
        helper = ClaudeHelper(mock_dsn)
        old_text = (
            'заголовок => 🎸 Концерт группы;\n'
            'текст => ' + 'Описание мероприятия. ' * 10 + ';\n'
            'релевантно => да;\n'
            'категория => Концерты;'
        )
        helper.answer = [MagicMock(text=old_text)]

        result = helper.new_event_data({})
        assert result['title'] == '🎸 Концерт группы'
        assert result['ai_relevant'] == 'да'

    def test_json_with_markdown_fences(self, mock_dsn):
        from davai_s_nami_bot.helper.ai.claude_helper import ClaudeHelper
        helper = ClaudeHelper(mock_dsn)
        json_str = json.dumps({
            'title': 'Test', 'prepared_text': 'Text',
            'relevant': True, 'reject_reason': '',
        }, ensure_ascii=False)
        helper.answer = [MagicMock(text=f'```json\n{json_str}\n```')]

        result = helper.new_event_data({})
        assert result['title'] == 'Test'
        assert result['ai_relevant'] is True


# --- OpenAI Helper ---

class TestOpenAIHelper:
    def test_json_parse(self, mock_dsn):
        from davai_s_nami_bot.helper.ai.open_ai_helper import OpenAIHelper
        helper = OpenAIHelper(mock_dsn)
        helper.answer = json.dumps({
            'title': '🎬 Кинопоказ «Сталкер»',
            'prepared_text': 'Показ культового фильма.',
            'category': 'Кино',
            'address': 'Лендок',
            'price': 'Бесплатно',
            'from_date': '2026-03-15T20:00',
            'to_date': None,
            'url': 'https://example.com',
            'relevant': True,
            'reject_reason': '',
        }, ensure_ascii=False)

        result = helper.new_event_data({})
        assert result['title'] == '🎬 Кинопоказ «Сталкер»'
        assert result['ai_relevant'] is True

    def test_rejected(self, mock_dsn):
        from davai_s_nami_bot.helper.ai.open_ai_helper import OpenAIHelper
        helper = OpenAIHelper(mock_dsn)
        helper.answer = json.dumps({
            'title': 'Вебинар', 'prepared_text': 'Онлайн курс.',
            'category': 'Без категории', 'address': '', 'price': '',
            'from_date': None, 'to_date': None, 'url': '',
            'relevant': False, 'reject_reason': 'онлайн-вебинар',
        }, ensure_ascii=False)

        result = helper.new_event_data({})
        assert result['ai_relevant'] is False


# --- OpenAI model/param compatibility ---

class TestOpenAIModelParams:
    def test_reasoning_model_detection(self):
        from davai_s_nami_bot.helper.ai.openai_models import is_reasoning_model
        assert is_reasoning_model('gpt-5.4-mini')
        assert is_reasoning_model('gpt-5-mini')
        assert is_reasoning_model('o4-mini')
        assert not is_reasoning_model('gpt-4o')
        assert not is_reasoning_model('gemini-2.5-flash')
        assert not is_reasoning_model(None)

    def test_kwargs_for_new_model(self):
        from davai_s_nami_bot.helper.ai.openai_models import chat_kwargs
        kwargs = chat_kwargs(
            'gpt-5.4-mini', temperature=0.5, max_tokens=4000,
            reasoning_effort='low', verbosity='low',
        )
        # max_tokens renamed, temperature dropped, gpt-5 knobs added
        assert kwargs == {
            'max_completion_tokens': 4000,
            'reasoning_effort': 'low',
            'verbosity': 'low',
        }

    def test_kwargs_for_legacy_model_unchanged(self):
        from davai_s_nami_bot.helper.ai.openai_models import chat_kwargs
        # Gemini/Perplexity go through the same helper and must keep the old shape
        for model in ('gpt-4o', 'gemini-2.5-flash', 'sonar'):
            assert chat_kwargs(
                model, temperature=0.8, max_tokens=2000,
                reasoning_effort='low', verbosity='low',
            ) == {'max_tokens': 2000, 'temperature': 0.8}

    def test_rejected_param_is_dropped_and_retried(self):
        from openai import BadRequestError
        from davai_s_nami_bot.helper.ai.openai_models import create_chat_completion

        error = BadRequestError(
            "Unsupported value: 'verbosity' does not support 'low' with this model",
            response=MagicMock(status_code=400, headers={}),
            body={'param': 'verbosity'},
        )
        client = MagicMock()
        client.chat.completions.create.side_effect = [error, 'ok']

        result = create_chat_completion(
            client, 'gpt-5.4-mini', [{'role': 'user', 'content': 'hi'}],
            max_completion_tokens=100, verbosity='low',
        )
        assert result == 'ok'
        assert client.chat.completions.create.call_count == 2
        # the retry keeps everything except the rejected param
        retry_kwargs = client.chat.completions.create.call_args.kwargs
        assert 'verbosity' not in retry_kwargs
        assert retry_kwargs['max_completion_tokens'] == 100

    def test_unrelated_bad_request_propagates(self):
        from openai import BadRequestError
        from davai_s_nami_bot.helper.ai.openai_models import create_chat_completion

        error = BadRequestError(
            'Invalid value for messages',
            response=MagicMock(status_code=400, headers={}),
            body={'param': 'messages'},
        )
        client = MagicMock()
        client.chat.completions.create.side_effect = error

        with pytest.raises(BadRequestError):
            create_chat_completion(
                client, 'gpt-5.4-mini', [], max_completion_tokens=100, verbosity='low'
            )
        assert client.chat.completions.create.call_count == 1

    def test_default_model_is_used_when_redis_param_missing(self, mock_dsn):
        from davai_s_nami_bot.helper.ai.open_ai_helper import OpenAIHelper
        from davai_s_nami_bot.helper.ai.openai_models import DEFAULT_OPENAI_MODEL
        helper = OpenAIHelper(mock_dsn)
        assert helper.openai_model == DEFAULT_OPENAI_MODEL == 'gpt-5.4-mini'
        assert helper.reasoning_effort == 'low'


# --- Gemini Helper ---

class TestGeminiHelper:
    def test_json_parse(self, mock_dsn):
        from davai_s_nami_bot.helper.ai.gemini_helper import GeminiHelper
        helper = GeminiHelper(mock_dsn)
        helper.answer = json.dumps({
            'title': '🎪 Фестиваль уличной еды',
            'prepared_text': 'Фестиваль с фудтраками.',
            'category': 'Фестивали',
            'address': 'Севкабель Порт',
            'price': 'Бесплатно',
            'from_date': '2026-04-01T12:00',
            'to_date': '2026-04-01T22:00',
            'url': 'https://example.com',
            'relevant': True,
            'reject_reason': '',
        }, ensure_ascii=False)

        result = helper.new_event_data({})
        assert result['title'] == '🎪 Фестиваль уличной еды'
        assert result['ai_relevant'] is True

    def test_rejected(self, mock_dsn):
        from davai_s_nami_bot.helper.ai.gemini_helper import GeminiHelper
        helper = GeminiHelper(mock_dsn)
        helper.answer = json.dumps({
            'title': 'Детский праздник', 'prepared_text': 'Для детей.',
            'category': 'Без категории', 'address': '', 'price': '',
            'from_date': None, 'to_date': None, 'url': '',
            'relevant': False, 'reject_reason': 'детское мероприятие',
        }, ensure_ascii=False)

        result = helper.new_event_data({})
        assert result['ai_relevant'] is False
        assert 'детское' in result['ai_reject_reason']


# --- SKIP_FIELDS ---

class TestSkipFields:
    def test_skip_internal_fields(self):
        from davai_s_nami_bot.helper.ai.claude_helper import _SKIP_FIELDS
        event = {
            'title': 'Test', 'full_text': 'Description',
            'post_date': '2026-03-10', 'queue': 5,
            'score': 72, 'score_breakdown': '{"total": 72}',
            'status': 'ReadyToPost', 'from_date': '2026-03-15',
            'price': '500', 'image_upload': 's3://bucket/img.jpg',
        }
        filtered = {k: v for k, v in event.items()
                    if k not in _SKIP_FIELDS and v is not None}

        assert 'post_date' not in filtered
        assert 'queue' not in filtered
        assert 'score' not in filtered
        assert 'status' not in filtered
        assert 'image_upload' not in filtered
        assert 'title' in filtered
        assert 'from_date' in filtered
        assert 'full_text' in filtered


# --- Relevance check in update_event ---

class TestRelevanceCheck:
    @pytest.mark.parametrize("value,should_reject", [
        (False, True),
        ('нет', True),
        ('no', True),
        ('false', True),
        (True, False),
        ('да', False),
        ('yes', False),
    ])
    def test_relevance_values(self, value, should_reject):
        is_reject = value is False or str(value).strip().lower() in ('нет', 'no', 'false')
        assert is_reject == should_reject
