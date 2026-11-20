from dataclasses import asdict

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from .. import city as city_module
from ..city_context import DEFAULT_CITY
from .dependencies import verify_token
from .schemas import CitiesResponse, CitiesResult, CityOut

router = APIRouter(
    prefix="/cities",
    tags=["Cities"],
    dependencies=[Depends(verify_token)],
)


@router.get("/",
            summary="Cities", response_model=CitiesResponse,
            description="Cities for a city switcher (bot, web app), from `city_city`. ")
async def list_cities(include_inactive: bool = False):
    cities = await run_in_threadpool(city_module.all_cities)
    rows = sorted(cities.values(), key=lambda c: (c.sort_order, c.name))
    return CitiesResponse(result=CitiesResult(cities=[
        CityOut(**asdict(c), is_default=c.code == DEFAULT_CITY)
        for c in rows
        if include_inactive or c.is_active
    ]))
