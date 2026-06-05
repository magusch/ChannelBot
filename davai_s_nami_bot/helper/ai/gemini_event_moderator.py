import json
import logging
import os
import time

from openai import OpenAI, OpenAIError

from ..dsn_parameters import DSNParameters

log = logging.getLogger(__name__)


class GeminiEventModerator:
    def __init__(self, max_events_percent=30, max_moderate_percent=50):
        param = DSNParameters()
        api_key = os.environ.get("GEMINI_API")
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        self.system_message = param.site_parameters('openai_ev_moder_sys_mes', last=1)
        self.user_message = param.site_parameters('openai_ev_moder_usr_mes', last=1)
        self.ai_model = param.site_parameters('gemini_model', last=1) or "gemini-2.5-flash"
        self.answer = None

        self.max_events_percent = max_events_percent
        self.max_moderate_percent = max_moderate_percent

    def moderate_events(self, events_list=[], example_events=[]):
        filtered_event_list = [event for event in events_list if 'id' in event]
        if not filtered_event_list:
            raise ValueError("Список мероприятий пуст. Может быть в них отсутствовал ключ 'id'")

        max_events = self.max_events_percent * 0.01 * len(filtered_event_list)

        system_msg = self.system_message or (
            "Вы модератор мероприятий для платформы по интересным, движовым "
            "и молодёжным мероприям. Средний возраст читателей: 17-29 лет."
        )

        user_msg = ""
        if self.user_message:
            user_msg += self.user_message + "\n"
        user_msg += self._generate_prompt_with_events(filtered_event_list, max_events) + "\n"

        if not example_events:
            example_events = self.example_events()
        user_msg += self._generate_prompt_with_examples(example_events)

        answer = self._call_with_retry(system_msg, user_msg)
        if answer:
            return self._parse_response(answer)
        return []

    def _call_with_retry(self, system_msg, user_msg, max_retries=3):
        for attempt in range(max_retries):
            try:
                completion = self.client.chat.completions.create(
                    model=self.ai_model,
                    temperature=0.7,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg},
                    ],
                )
                return completion.choices[0].message.content
            except OpenAIError as e:
                if '429' in str(e) and attempt < max_retries - 1:
                    wait = 60 * (attempt + 1)
                    log.warning(f"Gemini rate limit hit, waiting {wait}s (attempt {attempt + 1})")
                    time.sleep(wait)
                else:
                    raise
        return None

    def _generate_prompt_with_events(self, events_list, max_events):
        instructions = (
            """Твоя задача — оценить каждое мероприятие по нескольким критериям на 10-балльной шкале. Вот критерии оценки:
                        1. Уникальность (1-10):  Насколько мероприятие предлагает что-то новое и необычное? События, которые часто повторяются, получают меньший балл. Пересмотри весь список, если в нём есть дублирующиеся мероприятия, снижай балл за уникальность. Если это выставка, то можно не занижать.
                        2. Доступность по цене (1-10):  Баллы снижаются за дороговизну.
                            - Бесплатно: 10 баллов
                            - До 500₽: 9 баллов
                            - 500-1500₽: 7-8 баллов
                            - 1500-3000₽: 5-6 баллов
                            - Свыше 3000₽: 1-4 балла
                        3. Интерактивность (1-10): Насколько активно участие аудитории. Концерты, мастер-классы - высокий балл; лекции - средний. Эксурсии, выставки - низкий балл.
                        4. Локация (1-10): Удобство и привлекательность места. Центр города, необычные площадки - больше баллов. Библиотеки, музеи, театры получают 5-6 баллов, культурные пространства, необычные локации ближе к центру города — 8-10.
                        5. Соответствие аудитории (1-10): Насколько мероприятие интересно аудитории канала? Аудитория это молодёжь и студенты, возраст 17-29 лет. Мероприятия для детей, пенсионеров, людей с ограниченными возможностями здоровья получают низкие баллы.
                        6. Актуальность (1-10): Связь с трендами, сезонностью, текущими событиями. Насколько мероприятие актуально в текущий момент? Сезонные и модные темы получают больше баллов.
                        7. Образовательная ценность (1-10): Интеллектуальная польза без излишней академичности.
                        """
            f"На основе оценки нужно выбрать подходящие мероприятия. Необходимо выбрать максимум {max_events} мероприятий. Если в списке мероприятий есть дублирующиеся, то нужно выбрать только одно из них. Также если в итоговом списке все мероприятия получают низкий бал, то ничего не выбирать. "
            "Выбирайте только мероприятия с общим баллом 6+ из 10."
            "Каждое мероприятие представлено в формате JSON с ключами, включая 'id'. "
            "В ответе верните ID мероприятий в формате JSON в виде массива чисел. Пример ответа:\n[12345, 67890].\n"
            "Ответ должен быть только в формате JSON, без символов ```json, без текста или комментариев."
        )
        events_data = "\n".join([f"{event}" for event in events_list])
        return f"{instructions}\n\nСписок мероприятий:\n{events_data}"

    def _generate_prompt_with_examples(self, examples):
        instructions = (
            "Обрати также внимания на примеры удачных мероприятий, которые уже были "
            "опубликованы в ближайшее время и учти их в своём критерии:"
        )
        events_data = "\n".join([f"{event}" for event in examples])
        return f"{instructions}\n\n{events_data}\n"

    def _parse_response(self, response_content):
        text = response_content.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1] if '\n' in text else text[3:]
            text = text.rsplit('```', 1)[0].strip()
        try:
            result = json.loads(text)
            if isinstance(result, list) and all(isinstance(item, int) for item in result):
                return result
            raise ValueError("Ответ не содержит валидный список ID.")
        except (json.JSONDecodeError, ValueError) as e:
            log.error(f"Ошибка при разборе ответа модератора: {e}\nОтвет: {response_content}")
            raise ValueError(f"Ошибка при разборе ответа: {e}")

    def example_events(self):
        return []
