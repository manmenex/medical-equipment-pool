from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

_engine_kwargs: dict = {"echo": settings.DEBUG, "pool_pre_ping": True}
if settings.DATABASE_URL.startswith("postgresql"):
    _engine_kwargs.update(pool_size=20, max_overflow=10)

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    # Roadmap PR14A transaction-boundary audit
    # (docs/audits/05-pr14a-transaction-boundary-audit.md): closing an
    # uncommitted session rolls back its transaction. That is the only
    # guarantee this dependency provides -- it does not commit on a clean
    # exit, does not retry or otherwise recover from a failure, and is not
    # a substitute for an explicit db.rollback() after a caught database
    # error. Every commit boundary is owned by the caller (endpoint,
    # service, or background job) that decided the request succeeded.
    async with AsyncSessionLocal() as session:
        yield session
