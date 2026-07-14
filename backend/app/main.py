"""
FastAPI application entry point.
Run: uvicorn backend.app.main:app --reload --port 8000
"""

import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

# Ensure project root is on sys.path so `src.*` imports work
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from .config import settings
from .database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("🚀 Starting Legal RAG Backend v2...")

    # Create database tables
    await init_db()
    logger.info("✅ Database tables created/verified")

    # Seed default draft templates
    from .database import AsyncSessionLocal
    from .utils.seed_templates import seed_templates
    async with AsyncSessionLocal() as db_session:
        await seed_templates(db_session)

    # Pre-load RAG engine in background
    import threading
    def _preload():
        try:
            from src.api import start_background_loading
            start_background_loading()
            logger.info("✅ RAG engine background loading started")
        except Exception as e:
            logger.warning(f"RAG engine preload skipped: {e}")

    threading.Thread(target=_preload, daemon=True).start()

    # Seed admin user if not exists
    await _seed_admin()

    yield  # App is running

    logger.info("👋 Shutting down...")


async def _seed_admin():
    """Create default admin user if no admin exists."""
    from sqlalchemy import select
    from .database import AsyncSessionLocal
    from .models.user import User
    from .utils.security import hash_password

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.role == "admin"))
        if result.scalar_one_or_none() is None:
            admin = User(
                email="admin@legalrag.vn",
                username="admin",
                hashed_password=hash_password("admin123"),
                role="admin",
            )
            db.add(admin)
            await db.commit()
            logger.info("✅ Default admin created: admin@legalrag.vn / admin123")


# ---------------------------------------------------------------------------
# Create app
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="API hỏi đáp tài liệu pháp luật Việt Nam — React + FastAPI v2",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Register routers
# ---------------------------------------------------------------------------

from .api.v1.auth import router as auth_router
from .api.v1.chat import router as chat_router
from .api.v1.chat_extended import router as chat_extended_router
from .api.v1.documents import router as documents_router
from .api.v1.admin import router as admin_router
from .api.v1.api_keys import router as api_keys_router
from .api.v1.dashboard import router as dashboard_router
from .api.v1.openai_compat import router as openai_compat_router
from .api.v1.drafting import router as drafting_router

app.include_router(auth_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(chat_extended_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(api_keys_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(drafting_router, prefix="/api/v1")
app.include_router(openai_compat_router)  # No prefix — /v1/models, /v1/chat/completions


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": settings.APP_VERSION}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
