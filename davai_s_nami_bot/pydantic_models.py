from pydantic import BaseModel, EmailStr, Field
from datetime import datetime, timezone
from typing import List, Optional


class EventRequestParameters(BaseModel):
    """Event request parameters with filters, pagination, and sorting."""

    date_from: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Period start (defaults to now)",
    )
    date_to: Optional[datetime] = Field(None, description="Period end")
    category: Optional[List[int]] = Field(None, description="Filter by category IDs")
    place: Optional[List[int]] = Field(None, description="Filter by place IDs")
    fields: Optional[List[str]] = Field(
        None, description="List of fields to return (defaults to all)"
    )
    limit: Optional[int] = Field(20, description="Number of results per page")
    page: Optional[int] = Field(None, description="Page number")
    ids: Optional[List[int]] = Field(None, description="Retrieve specific events by ID")
    status: Optional[str] = Field(
        None, description="Filter by status: ReadyToPost, Posted"
    )
    price_max: Optional[int] = Field(None, description="Maximum price (RUB)")
    order_by: Optional[str] = Field(
        'date-asc', description="Sorting: date-asc, date-desc"
    )

    def with_defaults(self):
        return self

    def to_crud_dict(self):
        return {
            'date_from': self.date_from,
            'date_to': self.date_to,
            'category': self.category,
            'place': self.place,
            'fields': self.fields,
            'limit': self.limit,
            'page': self.page,
            'ids': self.ids,
            'status': self.status,
        }


class EventFeedParameters(EventRequestParameters):
    """Parameters for the diversified event feed (POST /api/events/feed/).

    Same filters as EventRequestParameters, plus diversity caps. The pool is
    always ranked by score desc; ``order_by`` is ignored here.
    """

    per_category: Optional[int] = Field(
        None, description="Max events per category (None = no cap)"
    )
    per_day: Optional[int] = Field(
        None, description="Max events per calendar day (None = auto: ceil(limit/days))"
    )


class EventOut(BaseModel):
    id: int
    event_id: str
    title: str
    post: str
    full_text: str
    url: str
    ticket_url: Optional[str] = None
    from_date: datetime
    to_date: datetime
    place_id: Optional[int] = None
    image: Optional[str] = None
    price: Optional[str] = None
    price_int: Optional[int] = None
    category: Optional[str] = None
    address: Optional[str] = None


class PlaceRequestParameters(BaseModel):
    """Place request parameters."""

    metro: Optional[str] = Field(None, description="Filter by metro")
    fields: Optional[List[str]] = Field(None, description="List of fields to return")
    limit: Optional[int] = Field(20, description="Number of results per page")
    page: Optional[int] = Field(None, description="Page number")
    order_by: Optional[str] = Field('tt-asc', description="Sorting")
    ids: Optional[List[int]] = Field(None, description="Retrieve specific places by ID")


class UpdatePostingRequest(BaseModel):
    event_id: int
    scheduled_time: datetime


class UserCreate(BaseModel):
    nickname: str
    password: str = Field(..., min_length=8)
    email: EmailStr

    full_name: Optional[str] = None


class UserOut(BaseModel):
    id: int
    email: EmailStr
    nickname: str
    full_name: Optional[str] = None
    telegram_id: Optional[int] = None
    telegram_nickname: Optional[str] = None
    balance: Optional[int] = None
    weekend_guide: Optional[bool] = False
    is_active: bool = False
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserLogin(BaseModel):
    nickname: str
    password: str


class UserUpdate(BaseModel):
    # password: str = Field(..., min_length=8)
    full_name: Optional[str] = None
    weekend_guide: Optional[bool] = False


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class FavouriteOut(BaseModel):
    type: str
    id: int
    detail: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TelegramLoginData(BaseModel):
    init_data: str = Field(..., description="Raw initData string from Telegram WebApp")
