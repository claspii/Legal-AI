"""
Backend configuration using Pydantic BaseSettings.
Reads from environment variables and .env file.
"""

import os
import secrets
from pathlib import Path
from pydantic_settings import BaseSettings

# Resolve project root (parent of backend/)
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()


class Settings(BaseSettings):
    """Application settings."""

    # --- App ---
    APP_NAME: str = "Legal RAG API"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False

    # --- Auth / JWT ---
    SECRET_KEY: str = secrets.token_urlsafe(32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- Database ---
    DATABASE_URL: str = f"sqlite+aiosqlite:///{PROJECT_ROOT / 'backend' / 'legal_rag.db'}"

    # --- CORS ---
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]

    # --- File Upload ---
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024  # 10 MB
    UPLOAD_DIR: str = str(PROJECT_ROOT / "backend" / "uploads")
    ALLOWED_EXTENSIONS: set[str] = {".txt", ".doc", ".docx", ".pdf"}

    # --- Rate Limiting ---
    RATE_LIMIT_PER_MINUTE: int = 100

    class Config:
        env_file = str(PROJECT_ROOT / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()

# Ensure upload directory exists
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
