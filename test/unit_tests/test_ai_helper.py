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
