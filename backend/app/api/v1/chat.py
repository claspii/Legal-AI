"""
Chat API endpoints — query, streaming, sessions, history.
"""

import json
import sys
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from loguru import logger
from pydantic import BaseModel

from ...database import get_db, async_session_maker
from ...models.user import User
from ...models.chat import ChatSession, ChatMessage
from ...schemas.chat import (
    ChatRequest, ChatSessionCreate, ChatSessionResponse,
    ChatSessionListResponse, ChatMessageResponse, ChatMessagesListResponse,
)
from ...dependencies import get_current_user

# Add project root to path so we can import RAG core
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

router = APIRouter(prefix="/chat", tags=["Chat"])


# ---------------------------------------------------------------------------
# Public model pool (available to all authenticated users)
# ---------------------------------------------------------------------------
@router.get("/available-models")
async def available_models(user: User = Depends(get_current_user)):
    """Return active models from the admin-managed pool. No sensitive data."""
    pool_path = PROJECT_ROOT / "data" / "model_pool.json"
    if not pool_path.exists():
        return {"models": []}
    with open(pool_path, "r", encoding="utf-8") as f:
        pool = json.load(f)
    # Return only active models, strip sensitive fields for non-admin
    result = []
    for m in pool:
        if not m.get("is_active", True):
            continue
        result.append({
            "id": m["id"],
            "provider": m["provider"],
            "display_name": m.get("display_name", m.get("model_id", "")),
            "model_id": m.get("model_id", ""),
            "model_name": m.get("model_name", ""),
            "api_url": m.get("api_url", ""),
            "price_prompt": m.get("price_prompt", 0),
            "price_completion": m.get("price_completion", 0),
        })
    return {"models": result}


def _get_rag_engine():
    """Lazy-load the RAG engine singleton."""
    from src.api import get_engine
    return get_engine()


def _parse_thinking_content(text: str) -> tuple[str, str | None]:
    if not text:
        return "", None
    open_tag = "<think>"
    close_tag = "</think>"
    start = text.find(open_tag)
    end = text.find(close_tag)
    
    if start != -1 and end > start:
        thinking = text[start + len(open_tag):end].strip()
        answer = text[end + len(close_tag):].strip()
        return answer, thinking
    if start != -1 and end == -1:
        thinking = text[start + len(open_tag):].strip()
        return "", thinking
    return text, None


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@router.get("/sessions", response_model=ChatSessionListResponse)
async def list_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all chat sessions for current user."""
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc())
    )
    sessions = result.scalars().all()

    session_responses = []
    for s in sessions:
        # Count messages
        msg_count_result = await db.execute(
            select(func.count(ChatMessage.id)).where(ChatMessage.session_id == s.id)
        )
        msg_count = msg_count_result.scalar() or 0

        # Get last message preview
        last_msg_result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == s.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        last_msg = last_msg_result.scalar_one_or_none()

        session_responses.append(ChatSessionResponse(
            id=s.id,
            title=s.title,
            created_at=s.created_at,
            updated_at=s.updated_at,
            message_count=msg_count,
            last_message_preview=last_msg.content[:100] if last_msg else None,
        ))

    return ChatSessionListResponse(sessions=session_responses, total=len(session_responses))


@router.post("/sessions", response_model=ChatSessionResponse, status_code=201)
async def create_session(
    data: ChatSessionCreate = ChatSessionCreate(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new chat session."""
    session = ChatSession(user_id=user.id, title=data.title)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return ChatSessionResponse(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=0,
    )


@router.get("/sessions/{session_id}/messages", response_model=ChatMessagesListResponse)
async def get_session_messages(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all messages in a chat session."""
    # Verify ownership
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Phiên chat không tồn tại.")

    messages_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = messages_result.scalars().all()

    msg_responses = []
    for m in messages:
        msg_responses.append(ChatMessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            sources=m.sources,
            reasoning=m.reasoning,
            metadata=m.metadata_extra,
            created_at=m.created_at,
        ))

    return ChatMessagesListResponse(
        session_id=session_id,
        messages=msg_responses,
        total=len(msg_responses),
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a chat session and all its messages."""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Phiên chat không tồn tại.")

    await db.delete(session)
    await db.commit()


# ---------------------------------------------------------------------------
# Chat / Query (SSE Streaming)
# ---------------------------------------------------------------------------

@router.post("/stream")
async def chat_stream(
    data: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Stream chat response as Server-Sent Events (SSE).
    Creates/uses a session and saves messages to DB.
    """
    # Get or create session
    session_id = data.session_id
    if session_id:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user.id,
            )
        )
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Phiên chat không tồn tại.")
    else:
        # Create new session with first few words as title
        title = data.question[:50] + ("..." if len(data.question) > 50 else "")
        session = ChatSession(user_id=user.id, title=title)
        db.add(session)
        await db.commit()
        await db.refresh(session)
        session_id = session.id

    # Save user message
    user_msg = ChatMessage(
        session_id=session_id,
        role="user",
        content=data.question,
    )
    db.add(user_msg)
    await db.commit()

    # Query chat history (excluding current user message)
    history_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id, ChatMessage.id != user_msg.id)
        .order_by(ChatMessage.created_at.asc())
    )
    history_messages = history_result.scalars().all()
    chat_history = [{"role": m.role, "content": m.content} for m in history_messages]

    # Build custom kwargs from settings
    custom_kwargs = {}
    if data.settings:
        # Convert reasoning_effort → thinking_budget
        EFFORT_BUDGET = {'off': 0, 'low': 512, 'medium': 2048, 'high': 8192, 'max': -1}
        effort = data.settings.get('reasoning_effort', 'off')
        thinking_budget = EFFORT_BUDGET.get(effort, 0)

        custom_kwargs = {
            'api_url': data.settings.get('api_url', ''),
            'model_name': data.settings.get('model_name', ''),
            'temperature': data.settings.get('temperature', 0.7),
            'max_tokens': data.settings.get('max_tokens', 2048),
            'top_p': data.settings.get('top_p', 0.95),
            'top_k': data.settings.get('top_k'),
            'frequency_penalty': data.settings.get('frequency_penalty', 0.0),
            'presence_penalty': data.settings.get('presence_penalty', 0.0),
            'thinking_budget': thinking_budget,
            'enable_thinking': thinking_budget != 0,   # compat
            'gemini_model': data.settings.get('gemini_model', ''),
        }

    async def generate_sse():
        """Generator that yields SSE events from RAG engine."""
        engine = _get_rag_engine()
        full_answer = ""
        sources_md = ""

        try:
            # Validate provider availability before streaming
            import sys
            sys.path.insert(0, str(PROJECT_ROOT))
            from src import config as rag_config

            provider = data.provider or "custom_trained"

            if provider == "gemini" and not rag_config.GEMINI_AVAILABLE:
                error_msg = (
                    "Google Gemini chưa được cấu hình. "
                    "Vui lòng đặt biến môi trường GOOGLE_API_KEY "
                    "hoặc chọn provider khác trong Settings."
                )
                yield f"event: error\ndata: {json.dumps({'message': error_msg})}\n\n"
                return

            # Send session_id first
            yield f"event: session\ndata: {json.dumps({'session_id': session_id})}\n\n"

            for partial_text, src_md in engine.query_stream(
                question=data.question,
                top_k=data.top_k,
                provider=provider,
                use_graph=data.use_graph,
                custom_kwargs=custom_kwargs,
                chat_history=chat_history,
            ):
                full_answer = partial_text
                sources_md = src_md
                yield f"event: answer\ndata: {json.dumps({'content': partial_text, 'done': False}, ensure_ascii=False)}\n\n"

            # Send sources
            yield f"event: sources\ndata: {json.dumps({'content': sources_md, 'done': True}, ensure_ascii=False)}\n\n"

            # Save assistant message to DB (fire-and-forget in sync context)
            # We'll do this after streaming completes
            yield f"event: done\ndata: {json.dumps({'session_id': session_id, 'done': True})}\n\n"

        except Exception as e:
            logger.error(f"SSE stream error: {e}")
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
            full_answer = f"Lỗi: {e}"

        # Save assistant message after stream — use a fresh session
        # (the request-scoped `db` may already be closed after streaming)
        if full_answer:
            try:
                from ...database import async_session_maker
                async with async_session_maker() as save_db:
                    async with save_db.begin():
                        ans, think = _parse_thinking_content(full_answer)
                        assistant_msg = ChatMessage(
                            session_id=session_id,
                            role="assistant",
                            content=ans,
                            reasoning=think,
                        )
                        save_db.add(assistant_msg)

                        # Record estimated token usage
                        from ...models.token_usage import TokenUsage
                        p_tokens = max(1, len(data.question) // 4)
                        c_tokens = max(1, len(full_answer) // 4)
                        total = p_tokens + c_tokens

                        provider = data.provider or "custom_trained"
                        model_name = data.settings.get('model_name') if data.settings else None
                        if provider == "gemini":
                            model_name = data.settings.get('gemini_model') if data.settings else "gemini-2.5-flash"
                        elif not model_name:
                            model_name = provider

                        # Lookup pricing and display_name from model pool
                        _pool_path = PROJECT_ROOT / "data" / "model_pool.json"
                        _cost = 0.0
                        _selected_pool_id = data.settings.get('selected_model_id', '') if data.settings else ''
                        try:
                            if _pool_path.exists():
                                import json as _json
                                with open(_pool_path, "r", encoding="utf-8") as _f:
                                    _pool = _json.load(_f)
                                for _m in _pool:
                                    # Match by selected_model_id first, then by model identifiers
                                    matched = False
                                    if _selected_pool_id and _m.get("id") == _selected_pool_id:
                                        matched = True
                                    elif _m.get("model_name") == model_name or _m.get("model_id") == model_name or _m.get("display_name") == model_name:
                                        matched = True
                                    if matched:
                                        _cost = (p_tokens * (_m.get("price_prompt", 0) or 0) / 1_000_000) + (c_tokens * (_m.get("price_completion", 0) or 0) / 1_000_000)
                                        # Use display_name for clearer usage logs
                                        model_name = _m.get("display_name") or model_name
                                        break
                        except Exception:
                            pass

                        token_usage = TokenUsage(
                            user_id=user.id,
                            source="chatbot",
                            prompt_tokens=p_tokens,
                            completion_tokens=c_tokens,
                            total_tokens=total,
                            model_name=model_name,
                            user_prompt=data.question[:2000],
                            response_preview=full_answer[:500],
                            cost=_cost,
                        )
                        save_db.add(token_usage)
            except Exception as e:
                logger.error(f"Failed to save assistant message: {e}")

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class MessageFeedbackRequest(BaseModel):
    rating: int  # 1: thumbs up, -1: thumbs down, 0: clear


@router.put("/messages/{message_id}/feedback")
async def save_message_feedback(
    message_id: str,
    data: MessageFeedbackRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Save rating/feedback for a message in a session owned by the user.
    Stores the rating in the message metadata_json column.
    """
    result = await db.execute(
        select(ChatMessage)
        .join(ChatSession)
        .where(
            ChatMessage.id == message_id,
            ChatSession.user_id == user.id,
        )
    )
    message = result.scalar_one_or_none()
    if not message:
        raise HTTPException(status_code=404, detail="Tin nhắn không tồn tại hoặc bạn không có quyền.")

    meta = message.metadata_extra or {}
    meta["rating"] = data.rating
    message.metadata_extra = meta

    await db.commit()
    return {"status": "ok", "message_id": message_id, "rating": data.rating}
