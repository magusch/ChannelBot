# -*- coding: utf-8 -*-
import datetime
import json
import re
from typing import List, Optional
from dataclasses import dataclass, asdict

from anthropic import Anthropic

from ..dsn_parameters import DSNParameters


@dataclass
class ExtractedEvent:
    """Structure of an extracted event."""
    title: str
    full_text: Optional[str] = None
    prepared_text: Optional[str] = None
    from_date: Optional[str] = None  # ISO format
    to_date: Optional[str] = None
    address: Optional[str] = None
    price: Optional[str] = None
    price_int: Optional[int] = None
    category: Optional[str] = None
    url: Optional[str] = None
    ticket_url: Optional[str] = None
    image: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class TokenUsage:
    """Token usage statistics."""
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "model": self.model
        }


@dataclass
class AnalysisResult:
    """Text analysis result."""
    is_event: bool
    events_count: int
    events: List[ExtractedEvent]
    raw_response: str = ""
    original_text: str = ""
    tokens: Optional[TokenUsage] = None

    def to_dict(self) -> dict:
        result = {
            "is_event": self.is_event,
            "events_count": self.events_count,
            "events": [e.to_dict() for e in self.events],
            "original_text": self.original_text
        }
        if self.tokens:
            result["tokens"] = self.tokens.to_dict()
        return result


class RawTextEventExtractor:
    """
    Raw text analyzer for extracting event information.
    Works with HTML and plain text from any source.
    """

    CATEGORIES = [
        "Концерты", "Кино", "Лекции", "Культура", "Фестивали",
        "Театр", "Вечеринки", "Перфомансы", "Стэндап", "Выставки",
        "Спорт", "Мастер-классы", "Экскурсии", "Без категории"
    ]

    def __init__(self, dsn_param: DSNParameters = None):
        self.client = Anthropic()
        self.dsn_param = dsn_param or DSNParameters()
        self.claude_model = self.dsn_param.site_parameters('claude_model', last=1) or "claude-sonnet-4-6"

    def analyze_text(self, text: str, source: str = "unknown") -> AnalysisResult:
        """
        Analyzes text and extracts events.

        Parameters
        ----------
        text : str
            Raw text (HTML or plain text).
        source : str
            Text source (telegram, instagram, vk, etc.).

        Returns
        -------
        AnalysisResult
            Analysis result with extracted events.
        """
        if not text or not text.strip():
            return AnalysisResult(
                is_event=False,
                events_count=0,
                events=[],
                original_text=text
            )

        system_message = self._get_system_message()
        user_message = self._get_user_message(text, source)

        try:
            response = self.client.messages.create(
                model=self.claude_model,
                max_tokens=4000,
                temperature=0.3,
                system=system_message,
                messages=[{"role": "user", "content": user_message}]
            )

            raw_response = response.content[0].text
            tokens = TokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                model=self.claude_model
            )
            return self._parse_response(raw_response, text, tokens)

        except Exception as e:
            print(f"Error analyzing text: {e}")
            return AnalysisResult(
                is_event=False,
                events_count=0,
                events=[],
                raw_response=str(e),
                original_text=text
            )

    def _get_system_message(self) -> str:
        """System message for Claude."""
        custom_message = self.dsn_param.site_parameters('raw_text_extractor_system', last=1)
        if custom_message:
            return custom_message

        return """Ты эксперт по анализу текстов и извлечению информации о мероприятиях.
Твоя задача - определить, содержит ли текст информацию о мероприятии (концерт, лекция, выставка, фестиваль, вечеринка и т.д.) и извлечь структурированные данные.

Важно:
- Текст может содержать несколько мероприятий - извлеки все
- Текст может быть в HTML формате - извлекай данные из тегов, сохраняй ссылки
- Если это НЕ мероприятие (реклама, новости, просто текст) - укажи is_event: false
- Даты указывай в формате ISO: YYYY-MM-DDTHH:MM
- Цену переводи в числовой формат для price_int (только число без валюты)
- Категорию выбирай строго из списка"""

    def _get_user_message(self, text: str, source: str) -> str:
        """Builds the user message."""
        current_year = datetime.date.today().year
        categories_str = ", ".join(self.CATEGORIES)

        return f"""Проанализируй следующий текст из источника "{source}" и определи, является ли он мероприятием.

Текст для анализа:
---
{text}
---

Если это мероприятие (или несколько мероприятий), извлеки данные в JSON формате:
{{
    "is_event": true,
    "events_count": <число мероприятий>,
    "events": [
        {{
            "title": "<Эмодзи> <Тип> «<Название>»",
            "prepared_text": "<Краткое описание 2-4 предложения, завлекающее, без дат и адресов>",
            "from_date": "<YYYY-MM-DDTHH:MM или null>",
            "to_date": "<YYYY-MM-DDTHH:MM или null>",
            "address": "<Место, улица, метро или null>",
            "price": "<Цена текстом: 500₽, Бесплатно, от 1000₽ или null>",
            "price_int": <число или null>,
            "category": "<одна из: {categories_str}>",
            "url": "<ссылка на мероприятие или null>",
            "ticket_url": "<ссылка на билеты или null>"
        }}
    ]
}}

Если это НЕ мероприятие:
{{
    "is_event": false,
    "events_count": 0,
    "events": []
}}

Правила:
1. Текущий год: {current_year}. Если год не указан - используй текущий.
2. Таймзона: UTC+3 (Москва).
3. title должен быть в формате: "<Эмодзи> <Тип мероприятия> «<Название>»". Пример: "🎸 Концерт «Название группы»"
4. prepared_text - краткое завлекающее описание БЕЗ дат, адресов и цен.
5. Извлекай ВСЕ ссылки из HTML (href атрибуты).
6. Отвечай ТОЛЬКО валидным JSON без markdown-обёртки."""

    def _parse_response(self, raw_response: str, original_text: str, tokens: TokenUsage = None) -> AnalysisResult:
        """Parses the Claude response."""
        try:
            # Strip possible markdown wrappers
            cleaned = raw_response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            data = json.loads(cleaned)

            events = []
            for event_data in data.get("events", []):
                event = ExtractedEvent(
                    title=event_data.get("title", "Без названия"),
                    full_text=original_text,
                    prepared_text=event_data.get("prepared_text"),
                    from_date=event_data.get("from_date"),
                    to_date=event_data.get("to_date"),
                    address=event_data.get("address"),
                    price=event_data.get("price"),
                    price_int=event_data.get("price_int"),
                    category=event_data.get("category", "Без категории"),
                    url=event_data.get("url"),
                    ticket_url=event_data.get("ticket_url"),
                    image=event_data.get("image")
                )
                events.append(event)

            return AnalysisResult(
                is_event=data.get("is_event", False),
                events_count=data.get("events_count", len(events)),
                events=events,
                raw_response=raw_response,
                original_text=original_text,
                tokens=tokens
            )

        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e}")
            return self._fallback_parse(raw_response, original_text, tokens)

    def _fallback_parse(self, raw_response: str, original_text: str, tokens: TokenUsage = None) -> AnalysisResult:
        """Fallback parsing when JSON is invalid."""
        is_event = '"is_event": true' in raw_response.lower() or '"is_event":true' in raw_response.lower()

        return AnalysisResult(
            is_event=is_event,
            events_count=0,
            events=[],
            raw_response=raw_response,
            original_text=original_text,
            tokens=tokens
        )

    def extract_urls_from_html(self, html_text: str) -> List[str]:
        """Extracts all URLs from HTML text."""
        pattern = r'href=[\'"]?([^\'" >]+)'
        urls = re.findall(pattern, html_text)
        return urls

    def analyze_texts_batch(
        self,
        texts: List[dict],
        source: str = "unknown"
    ) -> tuple:
        """
        Analyzes multiple texts in a single AI request (saves tokens).

        Parameters
        ----------
        texts : List[dict]
            List of texts: [{"id": 1, "text": "..."}, {"id": 2, "text": "..."}]
        source : str
            Source of the texts.

        Returns
        -------
        tuple
            (List[AnalysisResult], TokenUsage) - results and total batch token usage.
        """
        if not texts:
            return [], None

        # Limit batch size (to avoid exceeding the context window)
        MAX_BATCH_SIZE = 10
        texts = texts[:MAX_BATCH_SIZE]

        system_message = self._get_system_message()
        user_message = self._get_batch_user_message(texts, source)

        try:
            response = self.client.messages.create(
                model=self.claude_model,
                max_tokens=8000,
                temperature=0.3,
                system=system_message,
                messages=[{"role": "user", "content": user_message}]
            )

            raw_response = response.content[0].text
            tokens = TokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                model=self.claude_model
            )
            results = self._parse_batch_response(raw_response, texts)
            return results, tokens

        except Exception as e:
            print(f"Error in batch analysis: {e}")
            # Fallback: analyze one by one (tokens will be in each individual result)
            results = [self.analyze_text(t["text"], source) for t in texts]
            # Sum tokens from fallback results
            total_tokens = TokenUsage(model=self.claude_model)
            for r in results:
                if r.tokens:
                    total_tokens.input_tokens += r.tokens.input_tokens
                    total_tokens.output_tokens += r.tokens.output_tokens
            return results, total_tokens

    def _get_batch_user_message(self, texts: List[dict], source: str) -> str:
        """Builds the message for batch analysis."""
        current_year = datetime.date.today().year
        categories_str = ", ".join(self.CATEGORIES)

        texts_block = ""
        for item in texts:
            texts_block += f"""
---TEXT_ID:{item['id']}---
{item['text']}
---END_TEXT---
"""

        return f"""Проанализируй несколько текстов из источника "{source}".
Для КАЖДОГО текста определи, является ли он мероприятием.

Тексты для анализа:
{texts_block}

Ответь JSON массивом, где каждый элемент соответствует тексту по порядку:
[
    {{
        "text_id": <id текста>,
        "is_event": true/false,
        "events_count": <число>,
        "events": [
            {{
                "title": "<Эмодзи> <Тип> «<Название>»",
                "prepared_text": "<Описание 2-4 предложения>",
                "from_date": "<YYYY-MM-DDTHH:MM или null>",
                "to_date": "<YYYY-MM-DDTHH:MM или null>",
                "address": "<адрес или null>",
                "price": "<цена текстом или null>",
                "price_int": <число или null>,
                "category": "<категория>",
                "url": "<ссылка или null>",
                "ticket_url": "<ссылка на билеты или null>"
            }}
        ]
    }}
]

Правила:
1. Год по умолчанию: {current_year}
2. Категории: {categories_str}
3. Отвечай ТОЛЬКО валидным JSON массивом без markdown."""

    def _parse_batch_response(
        self,
        raw_response: str,
        original_texts: List[dict]
    ) -> List[AnalysisResult]:
        """Parses the batch request response."""
        try:
            cleaned = raw_response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            data = json.loads(cleaned)

            results = []
            text_map = {item["id"]: item["text"] for item in original_texts}

            for item in data:
                text_id = item.get("text_id")
                original_text = text_map.get(text_id, "")

                events = []
                for event_data in item.get("events", []):
                    event = ExtractedEvent(
                        title=event_data.get("title", "Без названия"),
                        full_text=original_text,
                        prepared_text=event_data.get("prepared_text"),
                        from_date=event_data.get("from_date"),
                        to_date=event_data.get("to_date"),
                        address=event_data.get("address"),
                        price=event_data.get("price"),
                        price_int=event_data.get("price_int"),
                        category=event_data.get("category", "Без категории"),
                        url=event_data.get("url"),
                        ticket_url=event_data.get("ticket_url")
                    )
                    events.append(event)

                results.append(AnalysisResult(
                    is_event=item.get("is_event", False),
                    events_count=item.get("events_count", len(events)),
                    events=events,
                    raw_response=raw_response,
                    original_text=original_text
                ))

            return results

        except json.JSONDecodeError:
            # Fallback: return empty results
            return [
                AnalysisResult(is_event=False, events_count=0, events=[], original_text=t["text"])
                for t in original_texts
            ]

    def save_events_to_db(
        self,
        result: AnalysisResult,
        source: str,
        image: str = None
    ) -> List[int]:
        """
        Saves extracted events to the EventsNotApproved table.
        """
        if not result.is_event or not result.events:
            return []

        from ... import crud

        created_ids = []
        now = datetime.datetime.now()

        for idx, event in enumerate(result.events):
            event_id = f"{source}_{now.strftime('%Y%m%d%H%M%S')}_{idx}"
            event_data = {
                "event_id": event_id,
                "title": event.title,
                "full_text": event.full_text,
                "url": event.url or f"extracted_{event_id}",
                "ticket_url": event.ticket_url or "",
                "price": event.price,
                "price_int": event.price_int,
                "address": event.address,
                "from_date": self._parse_datetime(event.from_date),
                "to_date": self._parse_datetime(event.to_date),
                "category": event.category,
                "source": source,
                "image": image or event.image,
                "status": "new"
            }
            created_id = crud.create_not_approved_event(event_data)
            created_ids.append(created_id)

        return created_ids

    def analyze_and_save(
        self,
        text: str,
        source: str,
        image: str = None
    ) -> dict:
        """
        Full pipeline: analyze text and save to the database.

        Parameters
        ----------
        text : str
            Raw text to analyze.
        source : str
            Text source.
        image : str, optional
            Image URL.

        Returns
        -------
        dict
            Result with information about created records.
        """
        result = self.analyze_text(text, source)

        if not result.is_event:
            return {
                "success": True,
                "is_event": False,
                "message": "Текст не содержит мероприятий",
                "created_ids": []
            }

        try:
            created_ids = self.save_events_to_db(result, source, image)
            return {
                "success": True,
                "is_event": True,
                "events_count": result.events_count,
                "created_ids": created_ids,
                "events": [e.to_dict() for e in result.events]
            }
        except Exception as e:
            return {
                "success": False,
                "is_event": True,
                "error": str(e),
                "events": [e.to_dict() for e in result.events]
            }

    def _parse_datetime(self, date_str: Optional[str]) -> Optional[datetime.datetime]:
        """Parses a datetime from an ISO string."""
        if not date_str:
            return None

        formats = [
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d"
        ]

        for fmt in formats:
            try:
                return datetime.datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        return None

    def save_events_to_posts(
        self,
        result: AnalysisResult,
        source: str,
        image: str = None,
        status: str = "draft"
    ) -> List[int]:
        """
        Saves extracted events to the Events2Posts table.
        """
        if not result.is_event or not result.events:
            return []

        from ... import crud

        now = datetime.datetime.now()
        events_data = []

        for idx, event in enumerate(result.events):
            event_id = f"{source}_{now.strftime('%Y%m%d%H%M%S')}_{idx}"
            events_data.append({
                "event_id": event_id,
                "title": event.title,
                "full_text": event.full_text,
                "prepared_text": event.prepared_text,
                "url": event.url or f"extracted_{event_id}",
                "ticket_url": event.ticket_url or "",
                "price": event.price,
                "price_int": event.price_int,
                "address": event.address,
                "from_date": self._parse_datetime(event.from_date),
                "to_date": self._parse_datetime(event.to_date),
                "category": event.category,
                "source": source,
                "image": image or event.image,
                "status": status
            })

        return crud.create_events_to_posts_bulk(events_data)

    def analyze_and_save_to_posts(
        self,
        text: str,
        source: str,
        image: str = None,
        status: str = "draft"
    ) -> dict:
        """
        Full pipeline: analyze text and save to Events2Posts.

        Parameters
        ----------
        text : str
            Raw text to analyze.
        source : str
            Text source.
        image : str, optional
            Image URL.
        status : str
            Status: 'draft', 'ReadyToPost'.

        Returns
        -------
        dict
            Result with information about created records.
        """
        result = self.analyze_text(text, source)

        if not result.is_event:
            return {
                "success": True,
                "is_event": False,
                "message": "Текст не содержит мероприятий",
                "created_ids": [],
                "table": "Events2Posts"
            }

        try:
            created_ids = self.save_events_to_posts(result, source, image, status=status)
            return {
                "success": True,
                "is_event": True,
                "events_count": result.events_count,
                "created_ids": created_ids,
                "events": [e.to_dict() for e in result.events],
                "table": "Events2Posts"
            }
        except Exception as e:
            return {
                "success": False,
                "is_event": True,
                "error": str(e),
                "events": [e.to_dict() for e in result.events],
                "table": "Events2Posts"
            }

    def process_not_approved_event(self, event_id: int) -> dict:
        """
        Processes an event from EventsNotApproved:
        - AI analyzes full_text
        - If it is an event → enriches the record (title, address, price, category)
          and sets status='extracted'. Stays in NotApproved.
        - If not an event → status='not_event'.

        Transfer from NotApproved to Events2Posts happens later via the common moderation logic.
        """
        from ... import crud

        event = crud.get_not_approved_event_by_id(event_id)
        if not event:
            return {"success": False, "error": f"Event {event_id} not found"}

        if not event.get("full_text"):
            return {"success": False, "error": "Event has no full_text"}

        result = self.analyze_text(event["full_text"], event["source"])

        if not result.is_event:
            crud.update_not_approved_event_status(event_id, "not_event")
            return {
                "success": True,
                "is_event": False,
                "message": "Marked as not an event",
                "tokens": result.tokens.to_dict() if result.tokens else None,
            }

        # Enrich the original NotApproved record with data from AI
        # Take the first extracted event (primary one)
        extracted = result.events[0]
        enriched_data = {
            "title": extracted.title,
            "address": extracted.address,
            "price": extracted.price,
            "price_int": extracted.price_int,
            "category": extracted.category,
            "from_date": self._parse_datetime(extracted.from_date),
            "to_date": self._parse_datetime(extracted.to_date),
            "url": extracted.url,
            "ticket_url": extracted.ticket_url,
        }
        crud.enrich_not_approved_event(event_id, enriched_data)
        crud.update_not_approved_event_status(event_id, "extracted")
        crud.recalculate_event_score(event_id, table="events_eventsnotapprovednew")

        # If AI found multiple events in one post —
        # create additional records in NotApproved
        extra_ids = []
        if len(result.events) > 1:
            extra_ids = self.save_events_to_db(
                AnalysisResult(
                    is_event=True,
                    events_count=len(result.events) - 1,
                    events=result.events[1:],
                    original_text=result.original_text,
                ),
                source=event["source"],
                image=event.get("image"),
            )

        return {
            "success": True,
            "is_event": True,
            "original_id": event_id,
            "extra_ids": extra_ids,
            "events_count": len(result.events),
            "tokens": result.tokens.to_dict() if result.tokens else None,
        }
