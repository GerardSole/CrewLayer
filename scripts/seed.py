"""Seed script: creates a demo tenant + API key for local onboarding.

Usage:
    python scripts/seed.py

Prints the tenant ID and API key. The key is only shown once — save it.
"""
import asyncio
import sys
import uuid
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from crewlayer.core.config import settings
from crewlayer.core.security import hash_key
from crewlayer.db.models import ApiKey, Base, Tenant


def _generate_key(key_id: uuid.UUID) -> str:
    import secrets
    return f"crwl_{key_id.hex}_{secrets.token_urlsafe(24)}"


async def seed() -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        tenant = Tenant(name="demo")
        db.add(tenant)
        await db.flush()

        key_id = uuid.uuid4()
        raw_key = _generate_key(key_id)
        api_key = ApiKey(
            id=key_id,
            tenant_id=tenant.id,
            name="default",
            scopes=[],
            key_hash=hash_key(raw_key),
        )
        db.add(api_key)
        await db.commit()
        await db.refresh(tenant)

    await engine.dispose()

    print("Demo tenant created")
    print(f"  Tenant ID : {tenant.id}")
    print(f"  API Key   : {raw_key}")
    print()
    print("Use the API key in the X-API-Key header:")
    print(f'  curl -H "X-API-Key: {raw_key}" http://localhost:8000/v1/agents')


if __name__ == "__main__":
    asyncio.run(seed())
