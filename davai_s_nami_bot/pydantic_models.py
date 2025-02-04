from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional


class EventRequestParameters(BaseModel):
    date_from: Optional[datetime] = Field(default_factory=datetime.utcnow)
    date_to: Optional[datetime] = None
    category: Optional[List[int]] = None
    place: Optional[List[int]] = None
    fields: Optional[List[str]] = None
    limit: Optional[int] = 20
    page: Optional[int] = None
    ids: Optional[List[int]] = None

    def with_defaults(self):
        if self.date_to is None:
            self.date_to = self.date_from
        return self

    def to_crud_dict(self):
        return {
            'date_from': self.date_from,
            'date_to': self.date_to,
            'category': self.category,
            'place': self.place_id,
            'fields': self.fields,
            'limit': self.limit,
            'page': self.page,
            'ids':  self.ids,
        }


class PlaceRequestParameters(BaseModel):
    metro: Optional[str] = None
    fields: Optional[List[str]] = None
    limit: Optional[int] = 20
    page: Optional[int] = None
    order_by: Optional[str] = 'tt-asc'
    ids: Optional[List[int]] = None


class UpdatePostingRequest(BaseModel):
    event_id: int
    scheduled_time: datetime