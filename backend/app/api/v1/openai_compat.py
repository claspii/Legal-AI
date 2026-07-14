"""
OpenAI-Compatible API Router — Model routing gateway.

Endpoints:
  GET  /v1/models              — List available models (OpenAI format)
  POST /v1/chat/completions    — Chat completions (streaming & non-streaming)

Auth: Bearer token using API key (lr_xxx) from api_keys table.
"""

import json
import time
import uuid
import sys
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger
from pydantic import BaseModel, Field
from typing import Optional

# Ensure project root on path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ...database import get_db, async_session_maker
from ...models.user import User
from ...models.api_key import ApiKey
from ...models.token_usage import TokenUsage

router = APIRouter(tags=["OpenAI Compatible"])

_MODEL_POOL_PATH = PROJECT_ROOT / "data" / "model_pool.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_pool():
    if not _MODEL_POOL_PATH.exists():
        return []
    with open(_MODEL_POOL_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_model(model_name: str):
    """Find model in pool by display_name, id, model_name, or model_id."""
    pool = _load_pool()
    for m in pool:
        if not m.get("is_active", True):
            continue
        if (m.get("display_name") == model_name
                or m.get("id") == model_name
                or m.get("model_name") == model_name
                or m.get("model_id") == model_name):
            return m
    return None


async def _auth_by_api_key(request: Request) -> tuple:
    """Authenticate via Bearer API key. Returns (user, api_key) or raises 401."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header. Use: Bearer lr_xxx")
    
    token = auth[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty API key.")

    async with async_session_maker() as db:
        result = await db.execute(
            select(ApiKey).where(ApiKey.key == token, ApiKey.is_active == True)
        )
        api_key = result.scalar_one_or_none()
        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid or revoked API key.")

        result = await db.execute(select(User).where(User.id == api_key.user_id))
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="User account is inactive.")

        return user, api_key


def _calc_cost(prompt_tokens: int, completion_tokens: int, model_entry: dict) -> float:
    """Calculate cost based on model pricing ($/1M tokens)."""
    pp = model_entry.get("price_prompt", 0) or 0
    pc = model_entry.get("price_completion", 0) or 0
    return (prompt_tokens * pp / 1_000_000) + (completion_tokens * pc / 1_000_000)


# ---------------------------------------------------------------------------
# GET /v1/models
# ---------------------------------------------------------------------------

@router.get("/v1/models")
async def list_models(request: Request):
    """List available models in OpenAI format."""
    user, _ = await _auth_by_api_key(request)
    pool = _load_pool()
    
    models = []
    for m in pool:
        if not m.get("is_active", True):
            continue
        models.append({
            "id": m.get("display_name") or m.get("id"),
            "object": "model",
            "created": int(time.time()),
            "owned_by": m.get("provider", "system"),
            "permission": [],
            "root": m.get("model_id") or m.get("model_name") or m.get("id"),
            "parent": None,
        })
    
    return {"object": "list", "data": models}


# ---------------------------------------------------------------------------
# POST /v1/chat/completions
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 2048
    top_p: Optional[float] = 0.95
    frequency_penalty: Optional[float] = 0.0
    presence_penalty: Optional[float] = 0.0
    stream: Optional[bool] = False


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-compatible chat completions — streaming & non-streaming."""
    user, api_key = await _auth_by_api_key(request)
    
    body = await request.json()
    data = ChatCompletionRequest(**body)
    
    # Find model in pool
    model_entry = _find_model(data.model)
    if not model_entry:
        raise HTTPException(
            status_code=404,
            detail=f"Model '{data.model}' not found in pool. Use GET /v1/models to see available models."
        )
    
    provider = model_entry.get("provider", "")
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    messages_dicts = [{"role": m.role, "content": m.content} for m in data.messages]
    
    # Extract system/user prompts for logging
    system_prompt = next((m.content for m in data.messages if m.role == "system"), "")
    user_prompt = next((m.content for m in reversed(data.messages) if m.role == "user"), "")
    
    if data.stream:
        return StreamingResponse(
            _stream_response(
                completion_id=completion_id,
                model_entry=model_entry,
                provider=provider,
                messages=messages_dicts,
                data=data,
                user=user,
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        return await _non_stream_response(
            completion_id=completion_id,
            model_entry=model_entry,
            provider=provider,
            messages=messages_dicts,
            data=data,
            user=user,
            api_key=api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )


# ---------------------------------------------------------------------------
# Streaming response generator
# ---------------------------------------------------------------------------

async def _stream_response(
    completion_id, model_entry, provider, messages, data,
    user, api_key, system_prompt, user_prompt
):
    """SSE streaming in OpenAI format."""
    model_name = model_entry.get("display_name") or model_entry.get("id")
    full_content = ""
    
    try:
        if provider == "custom_trained":
            for chunk_text in _call_custom_stream(model_entry, messages, data):
                full_content += chunk_text
                sse_data = _make_chunk(completion_id, model_name, chunk_text)
                yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n"
        
        elif provider == "gemini":
            for chunk_text in _call_gemini_stream(model_entry, messages, data):
                full_content += chunk_text
                sse_data = _make_chunk(completion_id, model_name, chunk_text)
                yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n"
        
        elif provider == "openrouter":
            for chunk_text in _call_openrouter_stream(model_entry, messages, data):
                full_content += chunk_text
                sse_data = _make_chunk(completion_id, model_name, chunk_text)
                yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n"
        
        else:
            error_msg = f"Unsupported provider: {provider}"
            yield f"data: {json.dumps(_make_chunk(completion_id, model_name, error_msg), ensure_ascii=False)}\n\n"
            full_content = error_msg

    except Exception as e:
        logger.error(f"OpenAI compat stream error: {e}")
        error_chunk = _make_chunk(completion_id, model_name, f"\n\n[Error: {e}]")
        yield f"data: {json.dumps(error_chunk, ensure_ascii=False)}\n\n"
        full_content += f"\n\n[Error: {e}]"

    # Send [DONE]
    # Final chunk with finish_reason
    final = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"

    # Log usage
    await _log_usage(user, api_key, model_name, model_entry,
                     system_prompt, user_prompt, full_content)


# ---------------------------------------------------------------------------
# Non-streaming response
# ---------------------------------------------------------------------------

async def _non_stream_response(
    completion_id, model_entry, provider, messages, data,
    user, api_key, system_prompt, user_prompt
):
    """Non-streaming OpenAI-format response."""
    model_name = model_entry.get("display_name") or model_entry.get("id")
    full_content = ""
    
    try:
        if provider == "custom_trained":
            for chunk in _call_custom_stream(model_entry, messages, data):
                full_content += chunk
        elif provider == "gemini":
            for chunk in _call_gemini_stream(model_entry, messages, data):
                full_content += chunk
        elif provider == "openrouter":
            for chunk in _call_openrouter_stream(model_entry, messages, data):
                full_content += chunk
        else:
            full_content = f"Unsupported provider: {provider}"
    except Exception as e:
        logger.error(f"OpenAI compat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    p_tokens = max(1, sum(len(m["content"]) for m in messages) // 4)
    c_tokens = max(1, len(full_content) // 4)

    await _log_usage(user, api_key, model_name, model_entry,
                     system_prompt, user_prompt, full_content)

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": full_content},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": p_tokens,
            "completion_tokens": c_tokens,
            "total_tokens": p_tokens + c_tokens,
        },
    }


# ---------------------------------------------------------------------------
# Provider call helpers
# ---------------------------------------------------------------------------

def _call_custom_stream(model_entry, messages, data):
    """Stream from custom_trained (vLLM/llama.cpp) endpoint."""
    import requests

    api_url = model_entry.get("api_url", "")
    if not api_url:
        raise RuntimeError("Custom model API URL not configured in pool.")

    url = api_url.rstrip("/")
    if "/v1/chat/completions" not in url:
        if url.endswith("/v1"):
            url += "/chat/completions"
        else:
            url += "/v1/chat/completions"

    payload = {
        "model": model_entry.get("model_name") or model_entry.get("model_id", ""),
        "messages": messages,
        "temperature": data.temperature,
        "max_tokens": data.max_tokens,
        "top_p": data.top_p,
        "stream": True,
    }
    if data.frequency_penalty:
        payload["frequency_penalty"] = data.frequency_penalty
    if data.presence_penalty:
        payload["presence_penalty"] = data.presence_penalty

    logger.info(f"[Router] Custom stream → {url}")

    resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, stream=True, timeout=180)
    resp.raise_for_status()

    for line in resp.iter_lines():
        if not line:
            continue
        line_str = line.decode("utf-8").strip()
        if not line_str.startswith("data:"):
            continue
        payload_str = line_str[5:].strip()
        if payload_str == "[DONE]":
            break
        try:
            chunk = json.loads(payload_str)
            content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
            if content:
                yield content
        except Exception:
            pass


def _call_gemini_stream(model_entry, messages, data):
    """Stream from Google Gemini."""
    from google import genai
    from google.genai import types
    from src import config as rag_config

    # Build prompt from messages
    parts = []
    for m in messages:
        role_label = "System" if m["role"] == "system" else ("User" if m["role"] == "user" else "Assistant")
        parts.append(f"{role_label}: {m['content']}")
    prompt = "\n\n".join(parts)

    model_id = model_entry.get("model_id") or rag_config.GEMINI_MODEL

    # Create client
    if rag_config.GEMINI_USE_VERTEXAI:
        client = genai.Client(vertexai=True, project=rag_config.GOOGLE_CLOUD_PROJECT, location=rag_config.GOOGLE_CLOUD_LOCATION)
    else:
        client = genai.Client(api_key=rag_config.GOOGLE_API_KEY)

    gen_config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(include_thoughts=False, thinking_budget=0)
    )

    logger.info(f"[Router] Gemini stream → {model_id}")

    response = client.models.generate_content_stream(
        model=model_id,
        contents=prompt,
        config=gen_config,
    )

    for chunk in response:
        if not chunk.candidates:
            continue
        candidate = chunk.candidates[0]
        if not candidate.content or not candidate.content.parts:
            continue
        for part in candidate.content.parts:
            if part.text and not getattr(part, "thought", False):
                yield part.text


def _call_openrouter_stream(model_entry, messages, data):
    """Stream from OpenRouter."""
    from src.openrouter import stream_openrouter

    model_id = model_entry.get("model_id", "")
    logger.info(f"[Router] OpenRouter stream → {model_id}")

    for reasoning_delta, content_delta in stream_openrouter(
        model_id=model_id,
        messages=messages,
        temperature=data.temperature,
        max_tokens=data.max_tokens,
        top_p=data.top_p,
        frequency_penalty=data.frequency_penalty or 0.0,
        presence_penalty=data.presence_penalty or 0.0,
    ):
        if content_delta:
            yield content_delta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunk(completion_id: str, model: str, content: str) -> dict:
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {"content": content},
            "finish_reason": None,
        }],
    }


async def _log_usage(user, api_key, model_name, model_entry, system_prompt, user_prompt, full_content):
    """Save token usage to DB."""
    try:
        p_tokens = max(1, len(user_prompt) // 4)
        c_tokens = max(1, len(full_content) // 4)
        total = p_tokens + c_tokens
        cost = _calc_cost(p_tokens, c_tokens, model_entry)

        async with async_session_maker() as db:
            async with db.begin():
                usage = TokenUsage(
                    user_id=user.id,
                    source="api",
                    prompt_tokens=p_tokens,
                    completion_tokens=c_tokens,
                    total_tokens=total,
                    model_name=model_name,
                    system_prompt=system_prompt[:2000] if system_prompt else None,
                    user_prompt=user_prompt[:2000] if user_prompt else None,
                    response_preview=full_content[:500] if full_content else None,
                    api_key_id=api_key.id,
                    cost=cost,
                )
                db.add(usage)
    except Exception as e:
        logger.error(f"Failed to log API usage: {e}")
