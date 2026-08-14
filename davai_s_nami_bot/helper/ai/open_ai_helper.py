# -*- coding: utf-8 -*-
import logging

from openai import OpenAI

from .answer_parser import parse_event_answer
from .openai_models import DEFAULT_OPENAI_MODEL, chat_kwargs, create_chat_completion
from .prompts import build_user_message, resolve_prompts

log = logging.getLogger(__name__)

# Output budget for one prepared post. On gpt-5.x this is shared with hidden
# reasoning tokens, hence the headroom over the ~500 tokens the JSON needs.
_MAX_OUTPUT_TOKENS = 4000


class OpenAIHelper:
    def __init__(self, dsn_param):
        self.client = OpenAI()
        self.answer = None
        self.system_message, self.user_message = resolve_prompts(dsn_param, 'openai')
        self.openai_model = (
            dsn_param.site_parameters('openai_model', last=1) or DEFAULT_OPENAI_MODEL
        )
        # gpt-5.x knobs, optional Redis params. Copywriting needs no deep
        # reasoning, so keep the effort low (it is billed as output tokens) and
        # the answer terse — unsupported values are dropped automatically.
        self.reasoning_effort = (
            dsn_param.site_parameters('openai_reasoning_effort', last=1) or 'low'
        )
        self.verbosity = dsn_param.site_parameters('openai_verbosity', last=1) or 'low'

    def ai_balance(self):
        return 1

    def refactor_post(self, event):
        completion = create_chat_completion(
            self.client,
            self.openai_model,
            [
                {"role": "system", "content": self.system_message},
                {"role": "user", "content": build_user_message(self.user_message, event)},
            ],
            response_format={"type": "json_object"},
            **chat_kwargs(
                self.openai_model,
                temperature=0.5,
                max_tokens=_MAX_OUTPUT_TOKENS,
                reasoning_effort=self.reasoning_effort,
                verbosity=self.verbosity,
            ),
        )

        choice = completion.choices[0]
        usage = getattr(completion, 'usage', None)
        if usage is not None:
            details = getattr(usage, 'completion_tokens_details', None)
            log.info(
                f"refactor_post: model={self.openai_model} "
                f"tokens in:{usage.prompt_tokens}/out:{usage.completion_tokens} "
                f"(reasoning:{getattr(details, 'reasoning_tokens', 0)})"
            )
        if choice.finish_reason == 'length':
            # On reasoning models the budget is shared with hidden reasoning, so
            # a truncated answer means unparseable JSON — flag it loudly.
            log.warning(
                f"refactor_post: answer truncated at {_MAX_OUTPUT_TOKENS} tokens "
                f"(model={self.openai_model}, reasoning_effort={self.reasoning_effort})"
            )

        self.answer = choice.message.content

        return self.answer

    def parse_gpt_answer(self):
        return parse_event_answer(self.answer)

    # AIHelper calls parse_ai_answer() on whichever provider is current.
    parse_ai_answer = parse_gpt_answer

    def new_event_data(self, event):
        replace_phrases ={'текст': 'prepared_text', 'text': 'prepared_text',
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
