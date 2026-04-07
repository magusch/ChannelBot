import datetime
import json
import logging
import os
import time

from openai import OpenAI, OpenAIError

log = logging.getLogger(__name__)

# Fields that should NOT be sent to AI (internal/confusing)
_SKIP_FIELDS = {
    'post_date', 'post_url', 'queue', 'is_ready', 'status',
    'score', 'score_breakdown', 'explored_date', 'image_upload',
}

_JSON_SCHEMA = {
    "title": "<ЭМОДЗИ> <Тип> <Название>",
    "prepared_text": "<Текст 2-4 предложения>",
    "category": "<Категория>",
    "address": "<Место, адрес, метро>",
    "price": "<Цена или Бесплатно>",
    "from_date": "<YYYY-MM-DDTHH:MM>",
    "to_date": "<YYYY-MM-DDTHH:MM или null>",
    "url": "<ссылка>",
    "relevant": True,
    "reject_reason": "",
}


class GeminiHelper:
    def __init__(self, dsn_param):
        api_key = os.environ.get('GEMINI_API')
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
        )

        self.system_message = dsn_param.site_parameters('gemini_system_message', last=1)
        self.user_message = dsn_param.site_parameters('gemini_user_message', last=1)
        self.model = dsn_param.site_parameters('gemini_model', last=1) or "gemini-2.5-flash"
        self.answer = None

    def ai_balance(self):
        return 1

    def refactor_post(self, event):
        system_message = self.system_message or "Ты редактор-копирайтер для телеграм канала о мероприятиях в Санкт-Петербурге. " \
                             "У нас есть сырая информация по мероприятию необходимо адаптировать её для поста."
        user_message = self.user_message or """Необходимо прочитать текст, заголовок и другую информацию и отредактировать их по следующим инструкциям:
                 Заголовок не должен содержать какие-то даты и упоминания места проведения мероприятия. Необходимо из текста понять какой тип мероприятия (лекция, кинопоказ, концерт, фестиваль и другие) (на кирилице), название мероприятия на кирилице нужно поставить в кавычки, если название мероприятия на латинице то кавычки не нужны. Добавить какое-нибудь яркое и необычное эмодзи в начале по смыслу или просто любое. В конечном итоге составить заголовк по шаблону "<ЭМОДЗИ> <Тип мероприятия> <Название мероприятия>". Пример (🚀 Лекция «Покорение космоса в СССР»).
                 Текст мероприятия адаптировать для того чтобы быстро понять суть мероприятия и завлечь читателей. Не делать текст слишком официальным и строгим. Также текст мероприятия не должен содержать какие-то точные даты, по возможности перевести их в указания дней недель или названия праздника. Убрать все ненужные ссылки, спец-символы и другие мешающие вещи из текста. Из всего текста выделить основную мысль и выложить её в одном абзаце (2-4 предложения). Стиль написания должен быть упрощённым и понятным, оставить капельку любопытсва если оно присутствовало в оригинальном тексте. Текст не должен быть от первого лица. Все местоимения перефразировать в третье лицо ("они что-то сделали"). В тексте также не надо использовать необязательную информацию по типу названия места проведения, график работы и стоимость входа, если нету необходимости увеличения количества символов в посте (к примеру оригинальный текст слишком короткий).
                 """

        today = datetime.date.today().isoformat()

        event_info = "Мероприятие:\n"
        for key, value in event.items():
            if key in _SKIP_FIELDS or value is None:
                continue
            event_info += f"{key}: {value}\n"

        messages = [
                {"role": "system", "content": system_message},
                {"role": "user", "content":
                     user_message +
                     f"""
                     На основе предоставленной информации о мероприятии, адаптируй её для поста.

                        Верни результат строго в формате JSON:
                        {json.dumps(_JSON_SCHEMA, ensure_ascii=False, indent=2)}

                        Правила заполнения полей:
                        1) title — заголовок по шаблону "<ЭМОДЗИ> <Тип мероприятия> <Название>".
                        2) prepared_text — краткое описание 2-4 предложения, завлекающее, без дат и адресов.
                        3) category — одна из: Концерты, Кино, Лекции, Культура, Фестивали, Театр, Вечеринки, Перфомансы, Стэндап, Выставки, Спорт, Мастер-классы, Экскурсии, Без категории. Можно использовать другую категорию если это обширная не учтённая категория
                        4) price — если указана: "цифры + валюта". Скидка для студентов: "цена / студ.цена (инфо)". Бесплатно: "Бесплатно". Если не указана — null.
                        5) address — название места, адрес, станция метро (если знаешь). Без города и района.
                        6) from_date, to_date — формат YYYY-MM-DDTHH:MM, UTC+3. Только из исходных данных.
                        7) url — ссылка на мероприятие из исходных данных.
                        8) relevant — false если мероприятие: корпоратив, бизнес-мероприятие, детское, платный курс/тренинг, реклама без события, онлайн-вебинар, или мероприятие уже прошло (from_date < {today}).
                          Ну и в общем мероприятие должно быть релевантно для аудитории 17-29 лет
                           true во всех остальных случаях.
                        9) reject_reason — причина если relevant=false, иначе пустая строка.

                        Сегодняшняя дата: {today}. Используй её для определения прошло ли мероприятие.
                        Включай только достоверные данные из исходной информации.

                        Исходная информация:
                        {event_info}
                         """
                 }
            ]

        for attempt in range(3):
            try:
                completion = self.client.chat.completions.create(
                    model=self.model,
                    temperature=0.5,
                    response_format={"type": "json_object"},
                    messages=messages,
                )
                self.answer = completion.choices[0].message.content
                return self.answer
            except OpenAIError as e:
                if '429' in str(e) and attempt < 2:
                    wait = 60 * (attempt + 1)
                    log.warning(f"Gemini rate limit hit, waiting {wait}s (attempt {attempt + 1})")
                    time.sleep(wait)
                else:
                    raise

    def parse_ai_answer(self):
        if self.answer is None:
            return {}

        # Try JSON first
        try:
            text = self.answer.strip()
            if text.startswith('```'):
                text = text.split('\n', 1)[1] if '\n' in text else text[3:]
                text = text.rsplit('```', 1)[0]
            data = json.loads(text)
            data['full_answer'] = self.answer
            return data
        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback to key => value parsing
        log.warning("JSON parse failed, falling back to key=>value parsing")
        data = self.answer.split('\n')
        event_data = {}
        for d in data:
            if d.strip() == '':
                continue
            divided = d.split('=>')
            if len(divided) >= 2:
                e_value = divided[-1].strip().replace(';', '')
                e_key = divided[0].strip().lower()
                if e_value == '':
                    continue
                event_data[e_key] = e_value
        if 'текст' not in event_data or len(event_data.get('текст', '').strip()) < 100:
            event_data['текст'] = self.answer
        event_data['full_answer'] = self.answer
        return event_data

    def new_event_data(self, event):
        replace_phrases = {'текст': 'prepared_text', 'text': 'prepared_text',
                           'заголовок': 'title',
                           'категория': 'category', 'дата': 'from_date',
                           'адрес': 'address', 'стоимость': 'price',
                           'ссылка': 'url',
                           'релевантно': 'ai_relevant', 'relevant': 'ai_relevant',
                           'причина': 'ai_reject_reason', 'reason': 'ai_reject_reason',
                           'reject_reason': 'ai_reject_reason'}
        if self.answer is None:
            self.refactor_post(event)
        ai_event_data = self.parse_ai_answer()
        ai_event = {}
        for key, new_value in ai_event_data.items():
            if key in replace_phrases:
                ai_event[replace_phrases[key]] = new_value
            else:
                ai_event[key] = new_value
        return ai_event
