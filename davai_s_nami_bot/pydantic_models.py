from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from datetime import datetime, timezone
from typing import List, Optional


class EventOrderBy(StrEnum):
    """Sort keys ``crud.order_maping`` understands for Events2Posts."""

    title_asc = "title-asc"
    title_desc = "title-desc"
    date_asc = "date-asc"
    date_desc = "date-desc"
    price_asc = "price-asc"
    price_desc = "price-desc"
    ad_asc = "ad-asc"
    ad_desc = "ad-desc"
    score_asc = "score-asc"
    score_desc = "score-desc"
    id_asc = "id-asc"
    id_desc = "id-desc"


class PlaceOrderBy(StrEnum):
    """Sort keys ``crud.order_maping`` understands for Place."""

    title_asc = "title-asc"
    title_desc = "title-desc"
    metro_asc = "metro-asc"
    metro_desc = "metro-desc"
    id_asc = "id-asc"
    id_desc = "id-desc"


class EventScope(StrEnum):
    """What the ``status`` parameter really controls.

    It is not a status filter, despite its name: ``crud._apply_event_filters``
    only checks whether the value is ``all``. Any other value -- including an
    event status like "Posted" -- applies the same publicly-valid predicate
    (Posted / OnlyApi / prepared ReadyToPost).
    """

    public = "public"
    all = "all"


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
    status: EventScope = Field(
        EventScope.public,
        description="'public' = only publicly visible events, 'all' = no status filter",
    )
    price_max: Optional[int] = Field(None, description="Maximum price (RUB)")
    order_by: EventOrderBy = Field(
        EventOrderBy.date_asc, description="Sorting: '<field>-<direction>'"
    )

    def with_defaults(self):
        return self


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
    full_text: Optional[str] = None
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
    order_by: PlaceOrderBy = Field(
        PlaceOrderBy.id_asc, description="Sorting: '<field>-<direction>'"
    )
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
    # Home city; a user who never chose one gets the default city.
    city_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("city_id", mode="before")
    @classmethod
    def _default_city(cls, value):
        from .city_context import DEFAULT_CITY

        return value or DEFAULT_CITY


class UserLogin(BaseModel):
    nickname: str
    password: str


class UserUpdate(BaseModel):
    # password: str = Field(..., min_length=8)
    full_name: Optional[str] = None
    weekend_guide: Optional[bool] = False
    city_id: Optional[str] = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class FavouriteOut(BaseModel):
    type: str
    id: int
    detail: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class TelegramLoginData(BaseModel):
    init_data: str = Field(..., description="Raw initData string from Telegram WebApp")
