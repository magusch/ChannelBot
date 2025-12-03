from pydantic import BaseModel, EmailStr, Field
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
    status: Optional[str] = None

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
            'ids':  self.ids,
            'status': self.status
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


class UserCreate(BaseModel):
    nickname: str
    password: str = Field(..., min_length=8)
    email: EmailStr

    full_name: Optional[str] = None
    telegram_nickname: Optional[str] = None


class UserOut(BaseModel):
    id: int
    email: EmailStr
    nickname: str
    full_name: Optional[str] = None
    telegram_nickname: Optional[str] = None
    is_active: bool = False
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserLogin(BaseModel):
    nickname: str
    password: str


class UserUpdate(BaseModel):
    #password: str = Field(..., min_length=8)
    full_name: Optional[str] = None
    telegram_nickname: Optional[str] = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
