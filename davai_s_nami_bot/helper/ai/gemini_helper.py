# -*- coding: utf-8 -*-
import logging
import os
import time

from openai import OpenAI, OpenAIError

from .answer_parser import parse_event_answer
from .prompts import build_user_message, resolve_prompts

log = logging.getLogger(__name__)


class GeminiHelper:
    def __init__(self, dsn_param):
        self.client = OpenAI(
            api_key=os.environ.get('GEMINI_API'),
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        self.system_message, self.user_message = resolve_prompts(dsn_param, 'gemini')
        self.model = dsn_param.site_parameters('gemini_model', last=1) or "gemini-2.5-flash"
        self.answer = None

    def ai_balance(self):
        return 1

    def refactor_post(self, event):
        messages = [
            {"role": "system", "content": self.system_message},
            {"role": "user", "content": build_user_message(self.user_message, event)},
        ]

        for attempt in range(3):
            try:
                completion = self.client.chat.completions.create(
                    model=self.model,
                    temperature=0.8,
                    response_format={"type": "json_object"},
                    messages=messages,
                )
                choice = completion.choices[0]
                if choice.finish_reason == 'length':
                    log.warning(
                        f"refactor_post: Gemini answer truncated (model={self.model})"
                    )
                self.answer = choice.message.content
                return self.answer
            except OpenAIError as e:
                err_str = str(e)
                if attempt < 2:
                    if '429' in err_str:
                        wait = 60 * (attempt + 1)
                        log.warning(f"Gemini rate limit, waiting {wait}s (attempt {attempt + 1})")
                        time.sleep(wait)
                    elif '503' in err_str:
                        wait = 20 * (attempt + 1)
                        log.warning(f"Gemini unavailable (503), waiting {wait}s (attempt {attempt + 1})")
                        time.sleep(wait)
                    else:
                        raise
                else:
                    raise

    def parse_ai_answer(self):
        return parse_event_answer(self.answer)

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
