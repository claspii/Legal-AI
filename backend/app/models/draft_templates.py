"""
DraftTemplate model to store legal document templates.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class DraftTemplate(Base):
    __tablename__ = "draft_templates"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    placeholders: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-encoded list of dicts
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
