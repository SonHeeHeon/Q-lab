"""Foreign-exchange REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.app.services.market_data.fx import FxRateError, get_fx_rate

router = APIRouter(prefix="/api/fx", tags=["fx"])


class FxRateResponse(BaseModel):
    base: str
    quote: str
    rate: float
    mid_rate: float
    as_of: datetime
    change_type: Literal["UP", "EQUAL", "DOWN"]


@router.get("/rate", response_model=FxRateResponse)
async def get_rate(
    base: str = Query(default="USD", min_length=3, max_length=3),
    quote: str = Query(default="KRW", min_length=3, max_length=3),
) -> FxRateResponse | JSONResponse:
    try:
        fx_rate = await get_fx_rate(base=base, quote=quote)
    except FxRateError as exc:
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "code": "FX_RATE_UNAVAILABLE",
                    "message": str(exc),
                }
            },
        )

    return FxRateResponse(
        base=fx_rate.base,
        quote=fx_rate.quote,
        rate=float(fx_rate.rate),
        mid_rate=float(fx_rate.mid_rate),
        as_of=fx_rate.as_of,
        change_type=cast(Literal["UP", "EQUAL", "DOWN"], fx_rate.change_type),
    )
