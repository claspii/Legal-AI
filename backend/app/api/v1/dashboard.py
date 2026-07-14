"""
Dashboard statistics router.
Includes usage history with pagination and chatbot/API separation.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional

from ...database import get_db
from ...models.user import User
from ...models.chat import ChatSession, ChatMessage
from ...models.document import Document
from ...models.token_usage import TokenUsage
from ...models.api_key import ApiKey
from ...dependencies import get_current_user

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats")
async def get_dashboard_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve quick stats and token usage details for the user dashboard."""
    # Count user's chat sessions
    sessions_query = select(func.count(ChatSession.id)).where(ChatSession.user_id == user.id)
    sessions_result = await db.execute(sessions_query)
    total_sessions = sessions_result.scalar() or 0

    # Count user's chat messages
    messages_query = (
        select(func.count(ChatMessage.id))
        .join(ChatSession)
        .where(ChatSession.user_id == user.id)
    )
    messages_result = await db.execute(messages_query)
    total_messages = messages_result.scalar() or 0

    # Count total documents in system
    docs_query = select(func.count(Document.id))
    docs_result = await db.execute(docs_query)
    total_documents = docs_result.scalar() or 0

    # Count active API keys
    api_keys_query = select(func.count(ApiKey.id)).where(ApiKey.user_id == user.id)
    api_keys_result = await db.execute(api_keys_query)
    total_api_keys = api_keys_result.scalar() or 0

    # Sum user's token usage
    tokens_query = (
        select(
            func.sum(TokenUsage.prompt_tokens),
            func.sum(TokenUsage.completion_tokens),
            func.sum(TokenUsage.total_tokens)
        )
        .where(TokenUsage.user_id == user.id)
    )
    tokens_result = await db.execute(tokens_query)
    prompt_tokens, completion_tokens, total_tokens = tokens_result.fetchone() or (0, 0, 0)
    
    prompt_tokens = prompt_tokens or 0
    completion_tokens = completion_tokens or 0
    total_tokens = total_tokens or 0

    # Query recent token usage logs to make a small chart/timeline (last 7 days or last 10 usages)
    recent_usage_query = (
        select(TokenUsage)
        .where(TokenUsage.user_id == user.id)
        .order_by(TokenUsage.created_at.desc())
        .limit(10)
    )
    recent_usage_result = await db.execute(recent_usage_query)
    recent_usages = recent_usage_result.scalars().all()

    recent_usage_list = [
        {
            "id": u.id,
            "prompt_tokens": u.prompt_tokens,
            "completion_tokens": u.completion_tokens,
            "total_tokens": u.total_tokens,
            "model_name": u.model_name,
            "source": getattr(u, "source", "chatbot"),
            "cost": getattr(u, "cost", 0) or 0,
            "created_at": u.created_at.isoformat(),
        }
        for u in reversed(recent_usages)  # Chronological order for chart
    ]

    return {
        "stats": {
            "total_sessions": total_sessions,
            "total_messages": total_messages,
            "total_documents": total_documents,
            "total_api_keys": total_api_keys,
        },
        "token_usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "limit": 1000000,  # Simulated max token limit (quota)
            "history": recent_usage_list,
        }
    }


@router.get("/usage-history")
async def usage_history(
    source: Optional[str] = Query(None, description="Filter by source: 'chatbot' or 'api'"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Paginated usage history with detailed info."""
    # Base query
    base_filter = TokenUsage.user_id == user.id
    if source:
        base_filter = (TokenUsage.user_id == user.id) & (TokenUsage.source == source)

    # Count total
    count_q = select(func.count(TokenUsage.id)).where(base_filter)
    total = (await db.execute(count_q)).scalar() or 0

    # Fetch page
    offset = (page - 1) * per_page
    items_q = (
        select(TokenUsage)
        .where(base_filter)
        .order_by(TokenUsage.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(items_q)
    usages = result.scalars().all()

    items = []
    for u in usages:
        items.append({
            "id": u.id,
            "source": getattr(u, "source", "chatbot"),
            "model_name": u.model_name,
            "user_prompt": getattr(u, "user_prompt", None),
            "system_prompt": getattr(u, "system_prompt", None),
            "response_preview": getattr(u, "response_preview", None),
            "prompt_tokens": u.prompt_tokens,
            "completion_tokens": u.completion_tokens,
            "total_tokens": u.total_tokens,
            "cost": getattr(u, "cost", 0) or 0,
            "created_at": u.created_at.isoformat(),
        })

    pages = max(1, (total + per_page - 1) // per_page)

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
    }


@router.get("/usage-summary")
async def usage_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated usage summary split by source (chatbot vs api)."""
    result = {}

    for src in ["chatbot", "api"]:
        q = (
            select(
                func.count(TokenUsage.id),
                func.coalesce(func.sum(TokenUsage.prompt_tokens), 0),
                func.coalesce(func.sum(TokenUsage.completion_tokens), 0),
                func.coalesce(func.sum(TokenUsage.total_tokens), 0),
                func.coalesce(func.sum(TokenUsage.cost), 0),
            )
            .where(TokenUsage.user_id == user.id, TokenUsage.source == src)
        )
        row = (await db.execute(q)).fetchone()
        req_count, p_tok, c_tok, t_tok, total_cost = row or (0, 0, 0, 0, 0)

        result[src] = {
            "total_requests": req_count or 0,
            "prompt_tokens": p_tok or 0,
            "completion_tokens": c_tok or 0,
            "total_tokens": t_tok or 0,
            "total_cost": round(float(total_cost or 0), 6),
        }

    return result


@router.get("/usage-daily")
async def usage_daily(
    days: int = Query(14, ge=1, le=90),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Daily token usage for charts, split by source. Returns last N days."""
    from datetime import datetime, timedelta

    cutoff = datetime.utcnow() - timedelta(days=days)

    # Use func.date() which works with SQLite
    day_col = func.date(TokenUsage.created_at)

    result = {}
    for src in ["chatbot", "api"]:
        q = (
            select(
                day_col.label("day"),
                func.coalesce(func.sum(TokenUsage.prompt_tokens), 0),
                func.coalesce(func.sum(TokenUsage.completion_tokens), 0),
                func.coalesce(func.sum(TokenUsage.total_tokens), 0),
                func.coalesce(func.sum(TokenUsage.cost), 0),
                func.count(TokenUsage.id),
            )
            .where(
                TokenUsage.user_id == user.id,
                TokenUsage.source == src,
                TokenUsage.created_at >= cutoff,
            )
            .group_by(day_col)
            .order_by(day_col)
        )
        rows = (await db.execute(q)).fetchall()
        result[src] = [
            {
                "date": str(row[0]),
                "prompt_tokens": row[1] or 0,
                "completion_tokens": row[2] or 0,
                "total_tokens": row[3] or 0,
                "cost": round(float(row[4] or 0), 6),
                "requests": row[5] or 0,
            }
            for row in rows
        ]

    return result
