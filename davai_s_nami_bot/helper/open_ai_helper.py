# -*- coding: utf-8 -*-
import datetime

from openai import OpenAI

from .dsn_parameters import DSNParameters


class OpenAIHelper:
    def __init__(self):
        self.client = OpenAI()
        self.answer = None
        param = DSNParameters()
        self.system_message = param.site_parameters('openai_system_message', last=1)
        self.user_message = param.site_parameters('openai_user_message', last=1)
        self.openai_model = param.site_parameters('openai_model', last=1) or 'gpt-4o'
        print(self.system_message)

    def refactor_post(self, event):
        if self.system_message is not None:
            system_message = self.system_message
        else:
            system_message = "Ты редактор-копирайтер для телеграм канала о мероприятиях в Санкт-Петербурге. У нас есть сырая информация по мероприятию необходимо адаптировать её для поста."

        if self.user_message is not None:
            user_message = self.user_message
        else:
            user_message = """Необходимо прочитать текст, заголовок и другую информацию и отредактировать их по следующим инструкциям:
                 Заголовок не должен содержать какие-то даты и упоминания места проведения мероприятия. Необходимо из текста понять какой тип мероприятия (лекция, кинопоказ, концерт, фестиваль и другие) (на кирилице), название мероприятия на кирилице нужно поставить в кавычки, если название мероприятия на латинице то кавычки не нужны. Добавить какое-нибудь яркое и необычное эмодзи в начале по смыслу или просто любое. В конечном итоге составить заголовк по шаблону "<ЭМОДЗИ> <Тип мероприятия> <Название мероприятия>". Пример (🚀 Лекция «Покорение космоса в СССР»).
                 Текст мероприятия адаптировать для того чтобы быстро понять суть мероприятия и завлечь читателей. Не делать текст слишком официальным и строгим. Также текст мероприятия не должен содержать какие-то точные даты, по возможности перевести их в указания дней недель или названия праздника. Убрать все ненужные ссылки, спец-символы и другие мешающие вещи из текста. Из всего текста выделить основную мысль и выложить её в одном абзаце (2-4 предложения). Стиль написания должен быть упрощённым и понятным, оставить капельку любопытсва если оно присутсововало в оригинальном тексте. Текст не должен быть от первого лица. Все местоимения перефразировать в третье лицо ("они что-то сделали"). В тексте также не надо использовать необязательную информацию по типу названия места проведения, график работы и стоимость входа, если нету необходимости увеличения количества символов в посте (к примеру оригинальный текст слишком короткий)."""

        event_info = "Мероприятие:\n"
        for key, value in event.items():
            event_info += f"{key} => {value}; \n"

        completion = self.client.chat.completions.create(
            model=self.openai_model,
            messages=[
                {"role": "system",
                 "content": system_message
                 },
                {"role": "user",
                 "content":
                 user_message +
                     f"""Обязательно выделить категорию мероприятия, можно взять из заголовка. Выделить несколько важных тегов мероприятия. Результат выдать в виде названия информации чётко как в примере (заголовок, текст, категория, адрес, стоимость, дата, ссылка, from_date, to_date) затем элемент в виде '=>', результат и в конце поставить точку с запятой (;).
                     Если какой-либо информации нету в тексте или она расплывчита, то включать в ответ её не нужно. Предпологать или искать где-то ещё тоже не надо. 
                     Цена должна быть в виде: цифры и валюты, если есть какие-то условия для студентов, то ставить черту / и также вписывать ещё цену. Если есть какие-то дополнительные условия сокращать её и ставить в скобку после цены. Если бесплатно – Бесплатно. 
                     Адрес должен состоять из названия места (театр, бар, музей и тд), дальше адрес, в конце метро если известно. Названия населённого пункта и района (город, область, республика) вставлять не надо.
                     Дата должна быть в формате '%Y-%m-%dT%h:%m' без какой-либо ещё информации. Сейчас {datetime.date.today().year} год. Также необходимо учитывать что заданная дата в utc+3 таймзоне.
                     Важно: ты должен предоставлять информацию только если уверен в ней и она есть в представленном ниже информации о мероприятиии! В конце проверь что информация в ответе есть в тексте.   
                 {event_info}
                 """}
            ]
        )

        self.answer = completion.choices[0].message.content

        return self.answer

    def parse_gpt_answer(self):
        if self.answer is None:
            return {}
        data = self.answer.split('\n')
        event_data = {}
        for d in data:
            if d.strip() == '':
                continue
            divided = d.split('=>')
            event_data[divided[0].strip().lower()] = divided[-1].strip().replace(';','')

        if 'текст' not in event_data or len(event_data['текст'].strip()) < 100:
            event_data['текст'] = self.answer
        event_data['full_answer'] = self.answer
        return event_data

    def new_event_data(self, event):
        replace_phrases = {'текст': 'full_text', 'заголовок': 'title',
                           'категория': 'category', 'дата': 'from_date',
                           'адрес': 'address', 'стоимость': 'price',
                           'ссылка': 'url'}
        if self.answer is None:
            self.refactor_post(event)
        ai_event_data = self.parse_gpt_answer()

        ai_event = {}
        for key, new_event_data in ai_event_data.items():
            if key in replace_phrases.keys():
                ai_event[replace_phrases[key]] = new_event_data
            else:
                ai_event[key] = new_event_data
        return ai_event