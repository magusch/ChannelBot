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


# --- Answer parsing (shared by all providers) ---

class TestAnswerParser:
    GOOD = {
        'title': '🎸 Концерт «Пасош»',
        'prepared_text': 'Группа выступит с новой программой.',
        'category': 'Концерты',
        'relevant': True,
        'reject_reason': '',
    }

    def _json(self, **over):
        return json.dumps({**self.GOOD, **over}, ensure_ascii=False, indent=2)

    def test_plain_json(self):
        from davai_s_nami_bot.helper.ai.answer_parser import parse_event_answer
        data = parse_event_answer(self._json())
        assert data['title'] == '🎸 Концерт «Пасош»'
        assert data['full_answer']

    def test_markdown_fence(self):
        from davai_s_nami_bot.helper.ai.answer_parser import parse_event_answer
        data = parse_event_answer(f'```json\n{self._json()}\n```')
        assert data['prepared_text'] == self.GOOD['prepared_text']

    def test_truncated_tail_is_repaired(self):
        # Real prod shape (ids 15578, 15631, 15670): the closing brace is missing
        from davai_s_nami_bot.helper.ai.answer_parser import parse_event_answer
        data = parse_event_answer(self._json().rstrip().rstrip('}').rstrip())
        assert data['title'] == '🎸 Концерт «Пасош»'
        assert data['prepared_text'] == self.GOOD['prepared_text']

    def test_duplicated_closing_brace_is_ignored(self):
        # Real prod shape (id 15545): one brace too many
        from davai_s_nami_bot.helper.ai.answer_parser import parse_event_answer
        data = parse_event_answer(self._json() + '\n}')
        assert data['title'] == '🎸 Концерт «Пасош»'

    def test_truncated_mid_string(self):
        from davai_s_nami_bot.helper.ai.answer_parser import parse_event_answer
        cut = self._json().split('"category"')[0] + '"category": "Конце'
        data = parse_event_answer(cut)
        assert data['title'] == '🎸 Концерт «Пасош»'

    def test_prose_around_json(self):
        from davai_s_nami_bot.helper.ai.answer_parser import parse_event_answer
        data = parse_event_answer(f'Вот результат:\n{self._json()}\nГотово!')
        assert data['category'] == 'Концерты'

    def test_unparseable_json_returns_empty_not_raw_dump(self):
        # The bug this parser exists for: a raw blob must never reach prepared_text
        from davai_s_nami_bot.helper.ai.answer_parser import parse_event_answer
        assert parse_event_answer('{"title": "x", "prepared_text": }') == {}
        assert parse_event_answer(None) == {}
        assert parse_event_answer('') == {}

    def test_legacy_key_value_format_still_works(self):
        from davai_s_nami_bot.helper.ai.answer_parser import parse_event_answer
        answer = (
            'заголовок => 🎸 Концерт группы;\n'
            'текст => ' + 'Описание мероприятия. ' * 10 + ';\n'
            'релевантно => да;'
        )
        data = parse_event_answer(answer)
        assert data['заголовок'] == '🎸 Концерт группы'
        assert data['релевантно'] == 'да'


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
        from davai_s_nami_bot.helper.ai.prompts import format_event_info
        event = {
            'title': 'Test', 'full_text': 'Description',
            'post_date': '2026-03-10', 'queue': 5,
            'score': 72, 'score_breakdown': '{"total": 72}',
            'status': 'ReadyToPost', 'from_date': '2026-03-15',
            'price': '500', 'image_upload': 's3://bucket/img.jpg',
            'to_date': None,
        }
        info = format_event_info(event)

        for internal in ('post_date', 'queue', 'score', 'status', 'image_upload'):
            assert f'{internal}:' not in info
        assert 'title: Test' in info
        assert 'from_date: 2026-03-15' in info
        assert 'to_date' not in info  # None values are dropped


# --- Prompt assembly ---

class TestPrompts:
    def _dsn(self, **params):
        dsn = MagicMock()
        dsn.site_parameters.side_effect = lambda name, last=1: params.get(name)
        return dsn

    def test_shared_param_wins_over_provider_param(self):
        from davai_s_nami_bot.helper.ai.prompts import resolve_prompts
        dsn = self._dsn(ai_user_message='ОБЩИЙ', gemini_user_message='ПРОВАЙДЕРНЫЙ')
        _, editorial = resolve_prompts(dsn, 'gemini')
        assert editorial == 'ОБЩИЙ'

    def test_provider_param_is_the_legacy_fallback(self):
        from davai_s_nami_bot.helper.ai.prompts import resolve_prompts
        _, editorial = resolve_prompts(self._dsn(openai_user_message='СТАРЫЙ'), 'openai')
        assert editorial == 'СТАРЫЙ'

    def test_code_default_when_no_params(self):
        from davai_s_nami_bot.helper.ai.prompts import (
            default_editorial_message, resolve_prompts,
        )
        system, editorial = resolve_prompts(self._dsn(), 'openai')
        assert editorial == default_editorial_message()
        assert 'редактор-копирайтер' in system

    def test_extra_rules_are_appended_not_replacing(self):
        from davai_s_nami_bot.helper.ai.prompts import resolve_prompts
        dsn = self._dsn(ai_user_message='ОСНОВНОЙ', ai_extra_rules='Не используй слово «спикер».')
        _, editorial = resolve_prompts(dsn, 'openai')
        assert editorial.startswith('ОСНОВНОЙ')
        assert 'спикер' in editorial

    def test_blank_param_falls_through(self):
        from davai_s_nami_bot.helper.ai.prompts import resolve_prompts
        dsn = self._dsn(ai_user_message='   ', openai_user_message='СТАРЫЙ')
        _, editorial = resolve_prompts(dsn, 'openai')
        assert editorial == 'СТАРЫЙ'

    def test_all_providers_get_the_same_voice(self):
        from davai_s_nami_bot.helper.ai.prompts import resolve_prompts
        dsn = self._dsn(ai_user_message='ЕДИНЫЙ ГОЛОС')
        voices = {resolve_prompts(dsn, p)[1] for p in ('openai', 'gemini', 'claude')}
        assert voices == {'ЕДИНЫЙ ГОЛОС'}

    def test_contract_is_always_appended_and_lists_real_categories(self):
        from davai_s_nami_bot.helper.ai.prompts import build_user_message
        from davai_s_nami_bot.scoring import CATEGORY_ID_TO_NAME
        message = build_user_message('ГОЛОС', {'title': 'Лекция'}, today='2026-08-14')
        assert message.startswith('ГОЛОС')
        assert 'строго в формате JSON' in message
        assert 'title: Лекция' in message
        assert 'Спорт' not in message  # категории нет в БД
        for name in CATEGORY_ID_TO_NAME.values():
            assert name in message

    def test_param_read_failure_falls_back_to_default(self):
        from davai_s_nami_bot.helper.ai.prompts import (
            default_editorial_message, resolve_prompts,
        )
        dsn = MagicMock()
        dsn.site_parameters.side_effect = ConnectionError('redis is down')
        _, editorial = resolve_prompts(dsn, 'openai')
        assert editorial == default_editorial_message()


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


# --- Parameter cache invalidation ---

class TestParameterRevision:
    """A param edited in Django must reach a running worker without a restart."""

    def test_new_revision_forces_reload(self, monkeypatch):
        import json as _json
        from davai_s_nami_bot.helper import dsn_parameters as dp

        store = {
            'parameters:dsn_site': _json.dumps({'ai_model': ['gemini']}),
            'parameters:dsn_site:rev': '1',
        }
        monkeypatch.setattr(dp.redis_client, 'get', lambda key: store.get(key))

        params = dp.DSNParameters.__new__(dp.DSNParameters)
        params.sites = {}
        params.update_interval = 3600

        assert params.site_parameters('ai_model', last=1) == 'gemini'

        # Django edit + POST /api/param/ → new blob and a bumped revision
        store['parameters:dsn_site'] = _json.dumps({'ai_model': ['openai']})
        store['parameters:dsn_site:rev'] = '2'

        assert params.site_parameters('ai_model', last=1) == 'openai'

    def test_same_revision_serves_memory_copy(self, monkeypatch):
        import json as _json
        from davai_s_nami_bot.helper import dsn_parameters as dp

        store = {
            'parameters:dsn_site': _json.dumps({'ai_model': ['gemini']}),
            'parameters:dsn_site:rev': '1',
        }
        reads = []

        def fake_get(key):
            reads.append(key)
            return store.get(key)

        monkeypatch.setattr(dp.redis_client, 'get', fake_get)
        params = dp.DSNParameters.__new__(dp.DSNParameters)
        params.sites = {}
        params.update_interval = 3600

        params.site_parameters('ai_model', last=1)
        reads.clear()
        params.site_parameters('ai_model', last=1)

        # only the tiny revision key is re-read, not the 60KB blob
        assert reads == ['parameters:dsn_site:rev']

    def test_missing_revision_marker_is_not_outdated(self, monkeypatch):
        import json as _json
        from davai_s_nami_bot.helper import dsn_parameters as dp

        store = {'parameters:dsn_site': _json.dumps({'ai_model': ['gemini']})}
        monkeypatch.setattr(dp.redis_client, 'get', lambda key: store.get(key))
        params = dp.DSNParameters.__new__(dp.DSNParameters)
        params.sites = {}
        params.update_interval = 3600

        assert params.site_parameters('ai_model', last=1) == 'gemini'
        assert params._is_outdated('dsn_site', None) is False


class TestProviderSelection:
    def test_unknown_provider_logs_and_falls_back(self, caplog):
        from davai_s_nami_bot.helper.ai_helper import AIHelper

        helper = AIHelper.__new__(AIHelper)
        helper.models = [('gemini', 'G'), ('openai', 'O')]
        helper.current_model_index = 1
        helper.current_model = 'O'

        with caplog.at_level('WARNING'):
            helper.set_model_by_name('opeanai')  # typo

        assert helper.current_model == 'G'
        assert 'unknown provider' in caplog.text

    def test_whitespace_around_value_is_tolerated(self):
        from davai_s_nami_bot.helper.ai_helper import AIHelper

        helper = AIHelper.__new__(AIHelper)
        helper.models = [('gemini', 'G'), ('openai', 'O')]
        helper.current_model_index = 0
        helper.current_model = 'G'

        helper.set_model_by_name(' OpenAI\n')
        assert helper.current_model == 'O'
