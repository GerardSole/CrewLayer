import hashlib
import json
from typing import Any

import httpx

from crewlayer.core.config import settings

EMBEDDING_DIM = 1536
_CACHE_TTL = 86400  # 24 hours


async def get_embedding(text: str, redis: Any = None) -> list[float]:
    """Return a 1536-dimensional embedding vector for the given text.

    Results are cached in Redis under key emb:{sha256[:16]} for 24 hours.
    Pass redis=None to skip the cache.
    """
    cache_key = f"emb:{hashlib.sha256(text.encode()).hexdigest()[:16]}"

    if redis is not None:
        cached = await redis.get(cache_key)
        if cached is not None:
            return json.loads(cached)  # type: ignore[no-any-return]

    if settings.EMBEDDING_PROVIDER == "local":
        vector = await _embed_local(text)
    else:
        vector = await _embed_voyage(text)

    # Normalise to exactly EMBEDDING_DIM
    if len(vector) < EMBEDDING_DIM:
        vector = vector + [0.0] * (EMBEDDING_DIM - len(vector))
    else:
        vector = vector[:EMBEDDING_DIM]

    if redis is not None:
        await redis.setex(cache_key, _CACHE_TTL, json.dumps(vector))

    return vector


async def _embed_voyage(text: str) -> list[float]:
    """Call Voyage AI (Anthropic's embedding service) using ANTHROPIC_API_KEY."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {settings.ANTHROPIC_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"input": [text], "model": "voyage-3"},
        )
        r.raise_for_status()
        data: list[float] = r.json()["data"][0]["embedding"]
        return data


_local_model = None


async def _embed_local(text: str) -> list[float]:
    """Generate embeddings locally using sentence-transformers (optional dependency)."""
    import asyncio

    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer
        _local_model = SentenceTransformer("all-MiniLM-L6-v2")

    model = _local_model
    loop = asyncio.get_event_loop()
    vec: list[float] = await loop.run_in_executor(None, lambda: model.encode(text).tolist())
    return vec
