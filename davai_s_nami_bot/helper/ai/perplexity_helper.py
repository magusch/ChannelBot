import datetime
import os
import requests

from ...settings.settings_loader import settings


class PerplexityHelper:
    def __init__(self, dsn_param):
        self.api_key = os.environ.get("PERPLEXITY_API")
        self.system_message = dsn_param.site_parameters('openai_system_message', last=1)
        self.user_message = dsn_param.site_parameters('openai_user_message', last=1)
        self.model = dsn_param.site_parameters('perplexity_model', last=1) or "sonar-pro"
        self.answer = None

    def ai_balance(self):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        url = "https://api.perplexity.ai/dashboard/billing/credit_grants"
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return -1
        data = response.json()
        available = data.get("total_available", 0)
        return available


        

    def refactor_post(self, event):
        system_message = self.system_message or f"Ты редактор-копирайтер для телеграм канала о мероприятиях в {settings.city_name_loc}. " \
                             "У нас есть сырая информация по мероприятию необходимо адаптировать её для поста."
        user_message = self.user_message or """Необходимо прочитать текст, заголовок и другую информацию и отредактировать их по следующим инструкциям:
                 Заголовок не должен содержать какие-то даты и упоминания места проведения мероприятия. Необходимо из текста понять какой тип мероприятия (лекция, кинопоказ, концерт, фестиваль и другие) (на кирилице), название мероприятия на кирилице нужно поставить в кавычки, если название мероприятия на латинице то кавычки не нужны. Добавить какое-нибудь яркое и необычное эмодзи в начале по смыслу или просто любое. В конечном итоге составить заголовк по шаблону "<ЭМОДЗИ> <Тип мероприятия> <Название мероприятия>". Пример (🚀 Лекция «Покорение космоса в СССР»).
                 Текст мероприятия адаптировать для того чтобы быстро понять суть мероприятия и завлечь читателей. Не делать текст слишком официальным и строгим. Также текст мероприятия не должен содержать какие-то точные даты, по возможности перевести их в указания дней недель или названия праздника. Убрать все ненужные ссылки, спец-символы и другие мешающие вещи из текста. Из всего текста выделить основную мысль и выложить её в одном абзаце (2-4 предложения). Стиль написания должен быть упрощённым и понятным, оставить капельку любопытсва если оно присутсововало в оригинальном тексте. Текст не должен быть от первого лица. Все местоимения перефразировать в третье лицо ("они что-то сделали"). В тексте также не надо использовать необязательную информацию по типу названия места проведения, график работы и стоимость входа, если нету необходимости увеличения количества символов в посте (к примеру оригинальный текст слишком короткий).
                 """

        event_info = "Мероприятие:\n"
        for key, value in event.items():
            event_info += f"{key} => {value}; \n"

        instruction_text = f""" На основе предоставленной информации о мероприятии, адаптируй её для поста в соответствии со следующими правилами:
                                        1) Категория мероприятия: Определи категорию мероприятия на основе заголовка или текста, используя только заданные ключевые слова (например, "Концерт", "Выставка", "Лекция").
                                        2) Теги: Выдели несколько важных тегов мероприятия (минимум 3), ориентируясь на ключевые слова.
                                        3) Категория, теги, дата, адрес и стоимость — строго по правилам, только если информация точно указана.

                                        4) Формат вывода: Результат должен быть представлен в виде:
                                        заголовок => ;
                                        текст => ;
                                        категория => ;
                                        адрес => ;
                                        стоимость => ;
                                        дата => ;
                                        ссылка => ;
                                        from_date => ;
                                        to_date => ;
                                        После каждого элемента поставь знак '=>', затем напиши соответствующую информацию. В конце результата поставь точку с запятой (;).
                                        4) Цена:
                                         - Если цена указана – формат: "цифры + валюта".
                                         - Если есть скидка для студентов – используй формат: "основная цена / цена для студентов (сокращённая информация о скидке)".
                                         - Если мероприятие бесплатно – просто напиши "Бесплатно".
                                         - Важно: если информация о цене расплывчата или отсутствует, не включай её в ответ.
                                        5) Адрес:
                                         - Должен содержать название места, адрес, и название ближайшей станции метро (если указано или ты сможешь её найти для этого места).
                                         - Исключи упоминания населённого пункта и района.
                                        6) Дата:
                                         - Укажи дату в формате '%Y-%m-%dT%h:%m' без дополнительной информации.
                                         - Дата должна быть в UTC+3 таймзоне.
                                         - Указывай только те даты, которые явно указаны в исходной информации.
                                         - Важно: указывай только достоверные данные. Сегодняшний год:  {datetime.date.today().year}.
                                        7) Точность:
                                         - Включай в результат только ту информацию, в которой уверен и которая есть в исходных данных.
                                         - Проверь, что все данные в ответе присутствуют в исходной информации или ты смог найти в интернете подверждающую информацию.
                                        Завершив, убедись, что все ключевые слова и форматы соблюдены.   

                                        Важно: исходная информация о мероприятии предоставлена ниже и находится в виде словаря. Используй эту информацию для выдачи результата:\n 
                                 """

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message + instruction_text + f"{event_info}"}
        ]

        url = "https://api.perplexity.ai/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 1000,
            "temperature": 1
        }

        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        self.answer = response.json()["choices"][0]["message"]["content"]
        return self.answer

    def parse_ai_answer(self):
        if self.answer is None:
            return {}
        data = self.answer.split('\n')
        event_data = {}
        for d in data:
            if d.strip() == '':
                continue
            divided = d.split('=>')
            e_value = divided[-1].strip().replace(';', '')
            e_key = divided[0].strip().lower()
            if e_value.strip == '':
                continue

            event_data[e_key] = e_value

        if 'текст' not in event_data or len(event_data['текст'].strip()) < 100:
            event_data['текст'] = self.answer
        event_data['full_answer'] = self.answer
        return event_data

    def new_event_data(self, event):
        replace_phrases = {'текст': 'prepared_text', 'text': 'prepared_text',
                           'заголовок': 'title',
                           'категория': 'category', 'дата': 'from_date',
                           'адрес': 'address', 'стоимость': 'price',
                           'ссылка': 'url'}
        if self.answer is None:
            self.refactor_post(event)
        ai_event_data = self.parse_ai_answer()

        ai_event = {}
        for key, new_event_data in ai_event_data.items():
            if key in replace_phrases.keys():
                ai_event[replace_phrases[key]] = new_event_data
            else:
                ai_event[key] = new_event_data
        return ai_event
