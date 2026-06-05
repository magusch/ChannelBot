"""
Pytest интеграционные тесты для content_generator_services с реальными объектами моделей
"""

import pytest
from unittest.mock import patch, Mock
from datetime import datetime

from davai_s_nami_bot.content_generator.services import GeneratorPost
from davai_s_nami_bot.content_generator.models import (
    ContentGeneratorPostTemplate,
    ContentGeneratorEventSelection,
    ContentGeneratorEventSelectionSelectedEvents,
    ContentGeneratorGeneratedPost
)


class TestGeneratorPostIntegration:
    
    @pytest.fixture
    def generator(self):
        """Fixture для создания экземпляра GeneratorPost"""
        return GeneratorPost()
    
    @pytest.fixture
    def real_post_template(self):
        """Fixture для реального шаблона поста"""
        return ContentGeneratorPostTemplate(
            id=1,
            name="Концерты недели",
            template_text="🎵 {title}\n💰 Цена: {price}\n📍 Адрес: {address}\n📝 {prepared_text}",
            variables="{}",
            is_active=True,
            created_at=datetime.now()
        )
    
    @pytest.fixture
    def real_event_selection(self):
        """Fixture для реального выбора событий"""
        return ContentGeneratorEventSelection(
            id=1,
            name="Тестовое событие",
            status="active",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            generation_settings="{}",
            created_by_id=123,
            filter_set_id=1
        )
    
    @pytest.fixture
    def real_selected_event(self):
        """Fixture для реального выбранного события"""
        return ContentGeneratorEventSelectionSelectedEvents(
            id=1,
            eventselection_id=1,
            events2post_id=100
        )
    
    @pytest.fixture
    def real_generated_post(self):
        """Fixture для реального созданного поста"""
        return ContentGeneratorGeneratedPost(
            id=1,
            title="Тестовое событие",
            content="Сгенерированный контент",
            status="draft",
            tags="[]",
            media_files="[]",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            event_selection_id=1,
            generated_by_id=123,
            post_template_id=1
        )

    @patch('davai_s_nami_bot.content_generator.services.crud')
    def test_integration_with_mocked_crud(
        self, 
        mock_crud, 
        generator, 
        real_post_template, 
        real_event_selection, 
        real_selected_event, 
        real_generated_post
    ):
        """Интеграционный тест с мокированными CRUD операциями"""
        
        # Настраиваем моки
        mock_crud.get_post_template.return_value = real_post_template
        mock_crud.get_event_selection.return_value = real_event_selection
        mock_crud.get_selected_events.return_value = [real_selected_event]
        mock_crud.create_generated_post.return_value = real_generated_post
        
        # Мокаем generate_post метод
        with patch.object(generator, 'generate_post') as mock_generate_post:
            mock_generate_post.return_value = "Сгенерированный контент"
            
            # Вызываем тестируемый метод
            result = generator.generate_post_by_template(
                event_selection_id=1,
                post_template_id=1
            )
            
            # Проверяем результат
            assert isinstance(result, dict)
            assert result['id'] == 1
            assert result['title'] == "Тестовое событие"
            assert result['content'] == "Сгенерированный контент"
            assert result['status'] == "draft"

    def test_generate_post_with_real_template_formatting(self, generator, real_post_template):
        """Тест генерации поста с реальным форматированием шаблона"""
        
        # Создаем мок события
        mock_event = Mock()
        mock_event.title = "Джазовый вечер"
        mock_event.price = "1500 руб"
        mock_event.prepared_text = "Вечер джазовой музыки в уютной атмосфере"
        mock_event.address = "Джаз-клуб 'Блюз'"
        
        # Создаем мок для event_selection
        mock_event_selection = Mock()
        mock_event_selection.selected_events = [mock_event]
        
        # Вызываем метод
        result = generator.generate_post(real_post_template, mock_event_selection)
        
        # Проверяем результат
        expected_content = f"**{real_post_template.name}**\n\n"
        expected_content += real_post_template.template_text.format(
            title=mock_event.title,
            price=mock_event.price,
            prepared_text=mock_event.prepared_text,
            address=mock_event.address
        ) + "\n\n"
        
        assert result == expected_content

    @patch('davai_s_nami_bot.content_generator.services.crud')
    def test_error_handling_integration(self, mock_crud, generator):
        """Тест обработки ошибок в интеграционном сценарии"""
        
        # Тест с отсутствующим шаблоном
        mock_crud.get_post_template.return_value = None
        
        with pytest.raises(ValueError, match="Post template not found"):
            generator.generate_post_by_template(
                event_selection_id=1,
                post_template_id=999
            )
        
        # Тест с отсутствующим выбором событий
        mock_crud.get_post_template.return_value = Mock()
        mock_crud.get_event_selection.return_value = None
        
        with pytest.raises(ValueError, match="Selected Events not found for the event selection"):
            generator.generate_post_by_template(
                event_selection_id=999,
                post_template_id=1
            )

    def test_template_variables_formatting(self, generator):
        """Тест форматирования переменных в шаблоне"""
        
        # Создаем шаблон с различными переменными
        post_template = ContentGeneratorPostTemplate(
            id=1,
            name="Тестовый шаблон",
            template_text="Заголовок: {title}\nЦена: {price}\nАдрес: {address}\nОписание: {prepared_text}",
            variables="{}",
            is_active=True,
            created_at=datetime.now()
        )
        
        # Создаем событие с специальными символами
        mock_event = Mock()
        mock_event.title = "Концерт с символами: !@#$%"
        mock_event.price = "1000 руб."
        mock_event.prepared_text = "Описание с переносами\nстрок"
        mock_event.address = "ул. Ленина, д. 1, кв. 5"
        
        # Создаем мок для event_selection
        mock_event_selection = Mock()
        mock_event_selection.selected_events = [mock_event]
        
        # Вызываем метод
        result = generator.generate_post(post_template, mock_event_selection)
        
        # Проверяем, что все переменные корректно подставлены
        assert "Заголовок: Концерт с символами: !@#$%" in result
        assert "Цена: 1000 руб." in result
        assert "Адрес: ул. Ленина, д. 1, кв. 5" in result
        assert "Описание: Описание с переносами\nстрок" in result

    def test_multiple_events_in_template(self, generator):
        """Тест обработки нескольких событий в шаблоне"""
        
        # Создаем шаблон
        post_template = ContentGeneratorPostTemplate(
            id=1,
            name="События недели",
            template_text="• {title} - {price}",
            variables="{}",
            is_active=True,
            created_at=datetime.now()
        )
        
        # Создаем несколько событий
        mock_event1 = Mock()
        mock_event1.title = "Концерт 1"
        mock_event1.price = "500 руб"
        mock_event1.prepared_text = "Описание 1"
        mock_event1.address = "Адрес 1"
        
        mock_event2 = Mock()
        mock_event2.title = "Концерт 2"
        mock_event2.price = "1000 руб"
        mock_event2.prepared_text = "Описание 2"
        mock_event2.address = "Адрес 2"
        
        # Создаем мок для event_selection с несколькими событиями
        mock_event_selection = Mock()
        mock_event_selection.selected_events = [mock_event1, mock_event2]
        
        # Вызываем метод
        result = generator.generate_post(post_template, mock_event_selection)
        
        # Проверяем, что оба события включены
        assert "• Концерт 1 - 500 руб" in result
        assert "• Концерт 2 - 1000 руб" in result
        
        # Проверяем порядок событий
        event1_index = result.find("• Концерт 1 - 500 руб")
        event2_index = result.find("• Концерт 2 - 1000 руб")
        assert event1_index < event2_index

    def test_template_with_emoji_and_special_characters(self, generator):
        """Тест шаблона с эмодзи и специальными символами"""
        
        # Создаем шаблон с эмодзи
        post_template = ContentGeneratorPostTemplate(
            id=1,
            name="🎭 Культурные события",
            template_text="🎪 {title}\n💸 Стоимость: {price}\n🏛️ Место: {address}\n📖 {prepared_text}",
            variables="{}",
            is_active=True,
            created_at=datetime.now()
        )
        
        # Создаем событие
        mock_event = Mock()
        mock_event.title = "Балет 'Лебединое озеро' 🦢"
        mock_event.price = "2000-5000 ₽"
        mock_event.prepared_text = "Классический балет в постановке Мариинского театра"
        mock_event.address = "Мариинский театр, Театральная пл., 1"
        
        # Создаем мок для event_selection
        mock_event_selection = Mock()
        mock_event_selection.selected_events = [mock_event]
        
        # Вызываем метод
        result = generator.generate_post(post_template, mock_event_selection)
        
        # Проверяем результат
        assert "🎭 Культурные события" in result
        assert "🎪 Балет 'Лебединое озеро' 🦢" in result
        assert "💸 Стоимость: 2000-5000 ₽" in result
        assert "🏛️ Место: Мариинский театр, Театральная пл., 1" in result
        assert "📖 Классический балет в постановке Мариинского театра" in result

    def test_empty_template_variables(self, generator):
        """Тест обработки пустых переменных в шаблоне"""
        
        # Создаем шаблон
        post_template = ContentGeneratorPostTemplate(
            id=1,
            name="Тестовый шаблон",
            template_text="Название: {title}\nЦена: {price}\nАдрес: {address}",
            variables="{}",
            is_active=True,
            created_at=datetime.now()
        )
        
        # Создаем событие с пустыми значениями
        mock_event = Mock()
        mock_event.title = ""
        mock_event.price = ""
        mock_event.prepared_text = ""
        mock_event.address = ""
        
        # Создаем мок для event_selection
        mock_event_selection = Mock()
        mock_event_selection.selected_events = [mock_event]
        
        # Вызываем метод
        result = generator.generate_post(post_template, mock_event_selection)
        
        # Проверяем, что пустые значения корректно обрабатываются
        assert "Название: " in result
        assert "Цена: " in result
        assert "Адрес: " in result
