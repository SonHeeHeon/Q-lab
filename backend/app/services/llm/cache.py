"""DB-backed LLM response cache."""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256

from sqlalchemy.dialects.sqlite import insert

from backend.app.core.config import settings
from backend.app.services.llm.client import LLMClient, get_llm_client
from shared.db.models import LLMCache
from shared.db.session import service_session


def cache_key(model: str, prompt: str) -> str:
    return sha256(f"{model}::{prompt}".encode("utf-8")).hexdigest()


async def complete_cached(
    prompt: str,
    *,
    model: str | None = None,
    max_tokens: int = 1024,
    ttl_hours: int | None = None,
    llm_client: LLMClient | None = None,
) -> str:
    """Return cached completion if valid; otherwise call the LLM and cache it."""

    selected_model = model or settings.LLM_MODEL
    ttl = ttl_hours if ttl_hours is not None else settings.LLM_CACHE_TTL_HOURS
    key = cache_key(selected_model, prompt)
    now = datetime.now()

    async with service_session() as session:
        cached = await session.get(LLMCache, key)
        if cached is not None and (
            cached.expires_at is None or cached.expires_at > now
        ):
            return cached.response

    client = llm_client or get_llm_client()
    response = await client.complete(prompt, model=selected_model, max_tokens=max_tokens)
    expires_at = now + timedelta(hours=ttl)

    async with service_session() as session:
        stmt = insert(LLMCache).values(
            cache_key=key,
            response=response,
            created_at=now,
            expires_at=expires_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[LLMCache.cache_key],
            set_={
                "response": stmt.excluded.response,
                "created_at": stmt.excluded.created_at,
                "expires_at": stmt.excluded.expires_at,
            },
        )
        await session.execute(stmt)
        await session.commit()

    return response
