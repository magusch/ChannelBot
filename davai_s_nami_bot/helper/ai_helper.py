import logging
import re

from .ai.perplexity_helper import PerplexityHelper
from .ai.open_ai_helper import OpenAIHelper
from .ai.claude_helper import ClaudeHelper
from .ai.gemini_helper import GeminiHelper

from .dsn_parameters import DSNParameters

log = logging.getLogger(__name__)

_CLICHE_PATTERN = re.compile(
    r"уникальн\w*|невероятн\w*|незабываем\w*|восхитительн\w*|потрясающ\w*",
    re.IGNORECASE,
)
_IMPERATIVE_PATTERN = re.compile(
    r"\bприготовьт\w*|\bприходи\w*|\bне пропусти\w*|\bпосети\w*|\bузнай\w*",
    re.IGNORECASE,
)


def lint_prepared_text(text: str) -> list[str]:
    """Return a list of violated-rule descriptions, or [] if text is clean."""
    if not text:
        return []
    issues = []
    cliches = set(m.group(0).lower() for m in _CLICHE_PATTERN.finditer(text))
    if cliches:
        issues.append(f"ad clichés: {sorted(cliches)}")
    imperatives = set(m.group(0).lower() for m in _IMPERATIVE_PATTERN.finditer(text))
    if imperatives:
        issues.append(f"imperative mood: {sorted(imperatives)}")
    return issues


class AIHelper:
    def __init__(self, model_name: str = None):
        dsn_param = DSNParameters()
        self.perplexity_helper = PerplexityHelper(dsn_param)
        self.openai_helper = OpenAIHelper(dsn_param)
        self.claude_helper = ClaudeHelper(dsn_param)
        self.gemini_helper = GeminiHelper(dsn_param)

        # Model in priority
        self.models = [
            ('gemini', self.gemini_helper),
            ('openai', self.openai_helper),
            ('claude', self.claude_helper),
            ('perplexity', self.perplexity_helper),
        ]

        self.current_model_index = 0
        self.current_model = self.models[self.current_model_index][1]

        if model_name or dsn_param.site_parameters('ai_model', last=1):
            self.set_model_by_name(model_name or dsn_param.site_parameters('ai_model', last=1))

    def set_model_by_name(self, model_name: str):
        """Set current model by name."""
        model_name = model_name.lower()
        for i, (name, model) in enumerate(self.models):
            if name == model_name:
                self.current_model_index = i
                self.current_model = model
                return
        
        self.current_model_index = 0
        self.current_model = self.models[0][1]


    def switch_to_next_model(self):
        """Switch on next model in list"""
        self.current_model_index = (self.current_model_index + 1) % len(self.models)
        model_name, model = self.models[self.current_model_index]
        self.current_model = model
        print(f"Switched on model: {model_name}")

    # def ai_balance(self):
    #     return self.perplexity_helper.ai_balance() + self.openai_helper.ai_balance() + self.claude_helper.ai_balance() + self.gemini_helper.ai_balance()

    def refactor_post(self, event):
        return self.current_model.refactor_post(event)

    def parse_ai_answer(self):
        return self.current_model.parse_ai_answer()
    
    def new_event_data(self, event):
        ai_event = self.current_model.new_event_data(event)
        issues = lint_prepared_text(ai_event.get('prepared_text'))
        if issues:
            model_name = self.models[self.current_model_index][0]
            log.warning(
                f"new_event_data: prepared_text for event_id={event.get('event_id')} "
                f"(model={model_name}) violates prompt rules: {issues}"
            )
        return ai_event

    def generate_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.7, max_tokens: int = 2000) -> str:
        """Universal text generation using the current model.

        Works with any provider (Claude, OpenAI, Gemini, Perplexity).
        Returns the raw text response.
        """
        model = self.current_model
        model_name = self.models[self.current_model_index][0]
        log.info(f"generate_text: using provider={model_name}")

        if isinstance(model, ClaudeHelper):
            message = model.client.messages.create(
                model=model.claude_model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            log.info(f"generate_text: Claude stop_reason={message.stop_reason}, "
                     f"usage=in:{message.usage.input_tokens}/out:{message.usage.output_tokens}")
            if message.stop_reason == 'max_tokens':
                log.warning("generate_text: response was truncated (max_tokens reached)")
            return message.content[0].text
        else:
            # OpenAI-compatible: OpenAI, Gemini, Perplexity
            model_id = getattr(model, 'model', None) or getattr(model, 'openai_model', None)
            completion = model.client.chat.completions.create(
                model=model_id,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            finish_reason = completion.choices[0].finish_reason
            log.info(f"generate_text: {model_name} finish_reason={finish_reason}")
            if finish_reason == 'length':
                log.warning("generate_text: response was truncated (max_tokens reached)")
            return completion.choices[0].message.content
