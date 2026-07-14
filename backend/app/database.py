"""
SQLAlchemy async engine & session for SQLite.
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from .config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    connect_args={"check_same_thread": False},  # SQLite specific
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Alias for use outside FastAPI dependency injection (e.g. post-stream saves)
async_session_maker = AsyncSessionLocal



class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


async def get_db():
    """Dependency: yield an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Create all tables (called on startup)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Migrate: add new columns to token_usages if they don't exist
    await _migrate_token_usages()


async def _migrate_token_usages():
    """Add new columns to token_usages table for existing databases."""
    from sqlalchemy import text

    new_columns = [
        ("source", "VARCHAR(20) DEFAULT 'chatbot' NOT NULL"),
        ("system_prompt", "TEXT"),
        ("user_prompt", "TEXT"),
        ("response_preview", "TEXT"),
        ("api_key_id", "VARCHAR(36)"),
        ("cost", "FLOAT DEFAULT 0 NOT NULL"),
    ]

    async with engine.begin() as conn:
        for col_name, col_def in new_columns:
            try:
                await conn.execute(text(
                    f"ALTER TABLE token_usages ADD COLUMN {col_name} {col_def}"
                ))
            except Exception:
                # Column already exists — skip
                pass

        # Fix existing rows that may have NULL source
        try:
            await conn.execute(text(
                "UPDATE token_usages SET source = 'chatbot' WHERE source IS NULL"
            ))
        except Exception:
            pass
