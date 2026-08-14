# -*- coding: utf-8 -*-
import logging

from anthropic import Anthropic

from .answer_parser import parse_event_answer
from .prompts import build_user_message, resolve_prompts

log = logging.getLogger(__name__)


class ClaudeHelper:
    def __init__(self, dsn_param):
        self.client = Anthropic()
        self.answer = None
        self.system_message, self.user_message = resolve_prompts(dsn_param, 'claude')
        self.claude_model = dsn_param.site_parameters('claude_model', last=1) or "claude-sonnet-4-6"

    def ai_balance(self):
        self.client.billing.usage()

    def refactor_post(self, event):
        message = self.client.messages.create(
            model=self.claude_model,
            max_tokens=2000,
            temperature=0.5,
            system=self.system_message,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": build_user_message(self.user_message, event),
                        }
                    ],
                }
            ],
        )
        if message.stop_reason == 'max_tokens':
            log.warning(f"refactor_post: Claude answer truncated (model={self.claude_model})")

        self.answer = message.content

        return self.answer

    def parse_gpt_answer(self):
        if self.answer is None:
            return {}
        raw = self.answer[0].text if isinstance(self.answer, list) else self.answer
        return parse_event_answer(raw)

    # AIHelper calls parse_ai_answer() on whichever provider is current.
    parse_ai_answer = parse_gpt_answer

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
        ai_event_data = self.parse_gpt_answer()

        ai_event = {}
        for key, new_event_data in ai_event_data.items():
            if key in replace_phrases.keys():
                ai_event[replace_phrases[key]] = new_event_data
            else:
                ai_event[key] = new_event_data
        return ai_event
