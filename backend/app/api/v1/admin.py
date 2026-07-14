"""
Admin API — user management and system statistics.
"""

import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ...database import get_db
from ...models.user import User
from ...models.chat import ChatSession, ChatMessage
from ...models.document import Document
from ...dependencies import get_current_admin
from ...schemas.auth import UserResponse
from ...schemas.chat import ChatRequest

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/stats")
async def system_stats(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Overall system statistics dashboard."""
    # Users
    total_users = (await db.execute(select(func.count(User.id)))).scalar()
    active_users = (await db.execute(select(func.count(User.id)).where(User.is_active == True))).scalar()
    admin_count = (await db.execute(select(func.count(User.id)).where(User.role == "admin"))).scalar()

    # Chat
    total_sessions = (await db.execute(select(func.count(ChatSession.id)))).scalar()
    total_messages = (await db.execute(select(func.count(ChatMessage.id)))).scalar()

    # Documents
    total_docs = (await db.execute(select(func.count(Document.id)))).scalar()
    indexed_docs = (await db.execute(select(func.count(Document.id)).where(Document.status == "indexed"))).scalar()

    # RAG stats
    rag_stats = {}
    try:
        from src.api import get_engine, is_engine_ready
        if is_engine_ready():
            rag_stats = get_engine().get_stats()
    except Exception:
        pass

    return {
        "users": {
            "total": total_users,
            "active": active_users,
            "admin_count": admin_count,
        },
        "chat": {
            "total_sessions": total_sessions,
            "total_messages": total_messages,
            "avg_messages_per_session": round(total_messages / max(total_sessions, 1), 1),
        },
        "documents": {
            "total": total_docs,
            "indexed": indexed_docs,
            "total_chunks": rag_stats.get("total_chunks", 0),
            "embedding_model": rag_stats.get("embedding_model", "N/A"),
        },
        "graph": {
            "enabled": rag_stats.get("graph_enabled", False),
        },
    }


@router.get("/users")
async def list_users(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    page: int = 1,
    per_page: int = 20,
):
    """List all users with pagination."""
    offset = (page - 1) * per_page
    result = await db.execute(
        select(User).order_by(User.created_at.desc()).offset(offset).limit(per_page)
    )
    users = result.scalars().all()
    total = (await db.execute(select(func.count(User.id)))).scalar()

    return {
        "users": [UserResponse.model_validate(u) for u in users],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    role: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Change a user's role (admin only)."""
    if role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="Role không hợp lệ. Dùng 'user' hoặc 'admin'.")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Người dùng không tồn tại.")

    user.role = role
    await db.commit()
    return UserResponse.model_validate(user)


@router.put("/users/{user_id}/status")
async def toggle_user_status(
    user_id: str,
    is_active: bool,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Activate or deactivate a user account."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Người dùng không tồn tại.")

    # Don't deactivate yourself
    if user.id == admin.id and not is_active:
        raise HTTPException(status_code=400, detail="Không thể tự vô hiệu hóa tài khoản của mình.")

    user.is_active = is_active
    await db.commit()
    return UserResponse.model_validate(user)


@router.post("/compare-stream")
async def compare_stream(
    data: ChatRequest,
    admin: User = Depends(get_current_admin),
):
    """
    Direct SSE stream for model comparison.
    Does not save to DB chat history.
    """
    custom_kwargs = {}
    if data.settings:
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
            'thinking_budget': thinking_budget,
            'enable_thinking': thinking_budget != 0,
            'gemini_model': data.settings.get('gemini_model', ''),
        }

    async def generate_sse():
        from src.api import get_engine
        engine = get_engine()
        try:
            from src import config as rag_config
            provider = data.provider or "custom_trained"
            if provider == "gemini" and not rag_config.GEMINI_AVAILABLE:
                yield f"event: error\ndata: {json.dumps({'message': 'Google Gemini chưa được cấu hình.'})}\n\n"
                return

            for partial_text, src_md in engine.query_stream(
                question=data.question,
                top_k=data.top_k,
                provider=provider,
                use_graph=data.use_graph,
                custom_kwargs=custom_kwargs,
                chat_history=[],
            ):
                yield f"event: answer\ndata: {json.dumps({'content': partial_text, 'done': False}, ensure_ascii=False)}\n\n"

            yield f"event: sources\ndata: {json.dumps({'content': src_md, 'done': True}, ensure_ascii=False)}\n\n"
            yield f"event: done\ndata: {json.dumps({'done': True})}\n\n"

        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/openrouter-models")
async def list_openrouter_models(
    admin: User = Depends(get_current_admin),
):
    """List available OpenRouter models. Free models sorted first."""
    from src.openrouter import fetch_openrouter_models
    models = fetch_openrouter_models()
    return {"models": models}


# ---------------------------------------------------------------------------
# Model Pool Management
# ---------------------------------------------------------------------------
import os
import uuid
from pathlib import Path as _Path

_MODEL_POOL_PATH = _Path(__file__).parent.parent.parent.parent.parent.resolve() / "data" / "model_pool.json"


def _load_model_pool():
    if not _MODEL_POOL_PATH.exists():
        return []
    with open(_MODEL_POOL_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_model_pool(pool):
    _MODEL_POOL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_MODEL_POOL_PATH, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)


@router.get("/model-pool")
async def get_model_pool(admin: User = Depends(get_current_admin)):
    """Get all models in the chatbot pool (admin only)."""
    return {"models": _load_model_pool()}


@router.post("/model-pool")
async def add_model_to_pool(
    data: dict,
    admin: User = Depends(get_current_admin),
):
    """Add a model to the chatbot pool (admin only)."""
    pool = _load_model_pool()

    model_entry = {
        "id": data.get("id") or str(uuid.uuid4())[:8],
        "provider": data["provider"],  # 'custom_trained' | 'gemini' | 'openrouter'
        "display_name": data.get("display_name", ""),
        "model_id": data.get("model_id", ""),
        "model_name": data.get("model_name", ""),
        "api_url": data.get("api_url", ""),
        "is_active": data.get("is_active", True),
        "price_prompt": float(data.get("price_prompt", 0)),
        "price_completion": float(data.get("price_completion", 0)),
    }

    # Prevent duplicates by id
    pool = [m for m in pool if m["id"] != model_entry["id"]]
    pool.append(model_entry)
    _save_model_pool(pool)
    return {"status": "ok", "model": model_entry}


@router.delete("/model-pool/{model_id}")
async def remove_model_from_pool(
    model_id: str,
    admin: User = Depends(get_current_admin),
):
    """Remove a model from the chatbot pool (admin only)."""
    pool = _load_model_pool()
    new_pool = [m for m in pool if m["id"] != model_id]
    if len(new_pool) == len(pool):
        raise HTTPException(status_code=404, detail="Model không tồn tại trong pool.")
    _save_model_pool(new_pool)
    return {"status": "ok"}


@router.patch("/model-pool/{model_id}")
async def update_model_in_pool(
    model_id: str,
    data: dict,
    admin: User = Depends(get_current_admin),
):
    """Update a model entry in the pool (admin only). Supports partial update."""
    pool = _load_model_pool()
    found = False
    for m in pool:
        if m["id"] == model_id:
            # Update allowed fields
            for field in ["display_name", "model_id", "model_name", "api_url",
                          "is_active", "price_prompt", "price_completion"]:
                if field in data:
                    if field in ("price_prompt", "price_completion"):
                        m[field] = float(data[field]) if data[field] is not None else 0
                    else:
                        m[field] = data[field]
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Model không tồn tại trong pool.")
    _save_model_pool(pool)
    return {"status": "ok", "model": next(m for m in pool if m["id"] == model_id)}


from pydantic import BaseModel as PydanticBaseModel
from typing import Optional


class CandidateModel(PydanticBaseModel):
    provider: str  # 'custom_trained' | 'gemini' | 'openrouter'
    model_id: str = ""
    api_url: str = ""
    model_name: str = ""


class ScoreRequest(PydanticBaseModel):
    question: str
    context: str = ""
    candidates: list[CandidateModel]
    judge: CandidateModel
    top_k: int = 5
    use_graph: bool = True
    settings: dict | None = None


@router.post("/score-stream")
async def score_stream(
    data: ScoreRequest,
    admin: User = Depends(get_current_admin),
):
    """
    SSE stream for the Model Scoring Arena.
    1. Retrieve RAG context (if use_graph/top_k specified).
    2. Run inference streaming for each candidate in parallel.
    3. Run judge scoring streaming for each candidate sequentially.
    """
    import time

    settings = data.settings or {}
    temperature = float(settings.get('temperature', 0.3))
    max_tokens = int(settings.get('max_tokens', 8192))
    thinking_budget = int(settings.get('thinking_budget', 8192))

    async def generate_sse():
        from src.api import get_engine, is_engine_ready
        from src import config as rag_config

        # 1. Retrieve RAG context if question provided and no manual context
        rag_context = data.context.strip() if data.context.strip() else ""
        if not rag_context and data.question.strip():
            try:
                if is_engine_ready():
                    engine = get_engine()
                    vector_hits = engine.store.query(data.question, top_k=data.top_k)
                    from src.rag_engine import _build_context_vector_only
                    rag_context = _build_context_vector_only(vector_hits)
                    yield f"event: context\ndata: {json.dumps({'content': rag_context[:500] + '...' if len(rag_context) > 500 else rag_context}, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"event: context_error\ndata: {json.dumps({'message': str(e)})}\n\n"

        # 2. Run candidate inference in PARALLEL using threads
        import threading
        import queue as queue_mod

        candidate_answers = {}
        candidate_answers_lock = threading.Lock()
        sse_queue = queue_mod.Queue()
        num_candidates = len(data.candidates)

        def _run_candidate(idx, candidate):
            """Run a single candidate inference in a thread, push SSE events to queue."""
            try:
                answer_text = ""
                provider = candidate.provider
                sse_queue.put(f"event: candidate_start\ndata: {json.dumps({'index': idx})}\n\n")

                if provider == "gemini":
                    gemini_model = candidate.model_id or "gemini-2.5-flash"
                    custom_kwargs = {
                        'gemini_model': gemini_model,
                        'temperature': temperature,
                        'max_tokens': max_tokens,
                        'thinking_budget': thinking_budget,
                        'enable_thinking': True,
                    }
                    if is_engine_ready():
                        engine = get_engine()
                        for partial_text, _ in engine.query_stream(
                            question=data.question,
                            top_k=data.top_k,
                            provider="gemini",
                            use_graph=data.use_graph,
                            custom_kwargs=custom_kwargs,
                            chat_history=[],
                        ):
                            answer_text = partial_text
                            sse_queue.put(f"event: candidate_stream\ndata: {json.dumps({'index': idx, 'content': partial_text}, ensure_ascii=False)}\n\n")

                elif provider == "custom_trained":
                    custom_kwargs = {
                        'api_url': candidate.api_url,
                        'model_name': candidate.model_name,
                        'temperature': temperature,
                        'max_tokens': max_tokens,
                        'thinking_budget': thinking_budget,
                        'enable_thinking': True,
                    }
                    if is_engine_ready():
                        engine = get_engine()
                        for partial_text, _ in engine.query_stream(
                            question=data.question,
                            top_k=data.top_k,
                            provider="custom_trained",
                            use_graph=data.use_graph,
                            custom_kwargs=custom_kwargs,
                            chat_history=[],
                        ):
                            answer_text = partial_text
                            sse_queue.put(f"event: candidate_stream\ndata: {json.dumps({'index': idx, 'content': partial_text}, ensure_ascii=False)}\n\n")

                elif provider == "openrouter":
                    from src.openrouter import stream_openrouter
                    from src import config as rag_cfg

                    sys_prompt = rag_cfg.SYSTEM_PROMPT
                    user_content = f"Tài liệu tham khảo:\n{rag_context}\n\nCâu hỏi: {data.question}" if rag_context else data.question
                    messages = [
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user_content},
                    ]

                    accumulated_reasoning = ""
                    accumulated_content = ""
                    for reasoning_delta, content_delta in stream_openrouter(
                        model_id=candidate.model_id,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    ):
                        if reasoning_delta:
                            accumulated_reasoning += reasoning_delta
                        if content_delta:
                            accumulated_content += content_delta

                        if accumulated_reasoning and accumulated_content:
                            answer_text = f"<think>{accumulated_reasoning}</think>{accumulated_content}"
                        elif accumulated_reasoning:
                            answer_text = f"<think>{accumulated_reasoning}"
                        else:
                            answer_text = accumulated_content

                        sse_queue.put(f"event: candidate_stream\ndata: {json.dumps({'index': idx, 'content': answer_text}, ensure_ascii=False)}\n\n")

                with candidate_answers_lock:
                    candidate_answers[idx] = answer_text
                sse_queue.put(f"event: candidate_done\ndata: {json.dumps({'index': idx})}\n\n")

            except Exception as e:
                with candidate_answers_lock:
                    candidate_answers[idx] = f"Lỗi: {str(e)}"
                sse_queue.put(f"event: candidate_error\ndata: {json.dumps({'index': idx, 'message': str(e)})}\n\n")

        # Launch all candidate threads
        threads = []
        for idx, candidate in enumerate(data.candidates):
            t = threading.Thread(target=_run_candidate, args=(idx, candidate), daemon=True)
            threads.append(t)
            t.start()

        # Drain SSE queue while threads are running
        finished_count = 0
        while finished_count < num_candidates:
            try:
                event = sse_queue.get(timeout=0.1)
                yield event
                # Count done/error events
                if 'candidate_done' in event or 'candidate_error' in event:
                    finished_count += 1
            except queue_mod.Empty:
                # Check if all threads died
                if all(not t.is_alive() for t in threads):
                    # Drain remaining
                    while not sse_queue.empty():
                        event = sse_queue.get_nowait()
                        yield event
                        if 'candidate_done' in event or 'candidate_error' in event:
                            finished_count += 1
                    break

        # Wait for all threads to finish
        for t in threads:
            t.join(timeout=5)

        # 3. Judge scoring for each candidate
        JUDGE_PROMPT = """Bạn là một giám khảo chấm điểm câu trả lời pháp luật khách quan và nghiêm ngặt tại Việt Nam.
Nhiệm vụ của bạn là đánh giá câu trả lời của một mô hình AI dựa trên Câu hỏi và Tài liệu tham khảo (RAG Context) được cung cấp.

TÌNH HUỐNG VÀ TÀI LIỆU THAM KHẢO:
{context}

CÂU HỎI:
{question}

CÂU TRẢ LỜI CỦA MODEL CẦN ĐÁNH GIÁ:
{model_answer}

Quy tắc chấm điểm (Thang điểm 10):
1. Tính chính xác pháp lý (Tối đa 4.0 điểm):
   - Câu trả lời có đúng về mặt pháp lý không? Có áp dụng đúng các điều luật trong Tài liệu tham khảo không?
   - Có bị rò rỉ hoặc tự ý sử dụng kiến thức luật ngoài RAG không? (Bị trừ điểm rất nặng nếu đưa vào các điều luật, quy định hay kiến thức luật không có trong RAG Context).
2. Độ đầy đủ và chi tiết (Tối đa 3.0 điểm):
   - Có trả lời đầy đủ các câu hỏi phụ phát sinh không?
   - Có phân tích chi tiết lỗi, trách nhiệm pháp lý của các bên liên quan không?
3. Tính logic và lập luận (Tối đa 3.0 điểm):
   - Quá trình suy luận và lập luận từng bước có chặt chẽ, rõ ràng và mạch lạc không?

Hãy chấm điểm và trả về kết quả dưới dạng JSON có cấu trúc sau:
{{
  "accuracy_score": <điểm_số_thực_từ_0.0_đến_4.0>,
  "completeness_score": <điểm_số_thực_từ_0.0_đến_3.0>,
  "logic_score": <điểm_số_thực_từ_0.0_đến_3.0>,
  "total_score": <tổng_điểm_thực_từ_0.0_đến_10.0 - bằng tổng của 3 điểm trên>,
  "feedback": "<nhận_xét_ngắn_gọn_bằng_tiếng_Việt_về_ưu_và_nhược_điểm_của_câu_trả_lời>"
}}
"""
        JUDGE_SCHEMA = {
            "type": "object",
            "properties": {
                "accuracy_score": {"type": "number"},
                "completeness_score": {"type": "number"},
                "logic_score": {"type": "number"},
                "total_score": {"type": "number"},
                "feedback": {"type": "string"},
            },
            "required": ["accuracy_score", "completeness_score", "logic_score", "total_score", "feedback"]
        }

        def _parse_judge_response(text):
            import re as _re
            text = text or ""
            match = _re.search(r"```json\s*(.*?)\s*```", text, _re.DOTALL)
            if match:
                text = match.group(1)

            try:
                data = json.loads(text.strip() or "{}")
            except Exception:
                data = {}
                for key in ["accuracy_score", "completeness_score", "logic_score", "total_score"]:
                    pattern = rf'"{key}"\s*:\s*([0-9.]+)'
                    m = _re.search(pattern, text, _re.IGNORECASE)
                    if not m:
                        pattern = rf'{key}\s*:\s*([0-9.]+)'
                        m = _re.search(pattern, text, _re.IGNORECASE)
                    if m:
                        try:
                            data[key] = float(m.group(1))
                        except ValueError:
                            pass
                fb_pattern = r'"feedback"\s*:\s*"(.*?)"'
                m_fb = _re.search(fb_pattern, text, _re.DOTALL | _re.IGNORECASE)
                if not m_fb:
                    fb_pattern = r'feedback\s*:\s*"(.*?)"'
                    m_fb = _re.search(fb_pattern, text, _re.DOTALL | _re.IGNORECASE)
                if not m_fb:
                    fb_pattern = r'"feedback"\s*:\s*\'(.*?)\''
                    m_fb = _re.search(fb_pattern, text, _re.DOTALL | _re.IGNORECASE)
                if m_fb:
                    data["feedback"] = m_fb.group(1).strip()
                else:
                    fb_pattern = r'"feedback"\s*:\s*(.+)'
                    m_fb = _re.search(fb_pattern, text, _re.IGNORECASE)
                    if m_fb:
                        data["feedback"] = m_fb.group(1).strip().strip(',').strip('}').strip('"').strip("'")
                    else:
                        data["feedback"] = f"Trích xuất bằng regex (JSON gốc lỗi). Phản hồi gốc: {text[:250]}"
            required_keys = {
                "accuracy_score": 0.0,
                "completeness_score": 0.0,
                "logic_score": 0.0,
                "total_score": 0.0,
                "feedback": "Không có nhận xét."
            }
            for k, default_val in required_keys.items():
                if k not in data:
                    found = False
                    for dict_k in list(data.keys()):
                        if dict_k.lower().replace("_", "") == k.lower().replace("_", ""):
                            data[k] = data[dict_k]
                            found = True
                            break
                    if not found:
                        data[k] = default_val
                if k != "feedback":
                    try:
                        data[k] = float(data[k])
                    except (ValueError, TypeError):
                        data[k] = 0.0
            return data

        import re
        for idx, candidate in enumerate(data.candidates):
            raw_answer = candidate_answers.get(idx, "")
            if raw_answer.startswith("Lỗi:"):
                yield f"event: judge_error\ndata: {json.dumps({'index': idx, 'message': 'Bỏ qua chấm điểm do candidate bị lỗi.'})}\n\n"
                continue
            clean_answer = re.sub(r'<think>.*?</think>', '', raw_answer, flags=re.DOTALL).strip()
            if not clean_answer:
                clean_answer = raw_answer
            judge_prompt_filled = JUDGE_PROMPT.format(
                context=rag_context,
                question=data.question,
                model_answer=clean_answer,
            )
            yield f"event: judge_start\ndata: {json.dumps({'index': idx})}\n\n"
            try:
                judge_provider = data.judge.provider
                judge_text = ""
                scores_data = None
                if judge_provider == "gemini":
                    from google.genai import types as genai_types
                    from src.rag_engine import _create_gemini_client, _get_effective_gemini_model
                    client = _create_gemini_client()
                    judge_model_id = _get_effective_gemini_model(data.judge.model_id or "gemini-3.5-flash")
                    yield f"event: judge_stream\ndata: {json.dumps({'index': idx, 'content': f'Đang gọi {judge_model_id} chấm điểm...'}, ensure_ascii=False)}\n\n"
                    resp = client.models.generate_content(
                        model=judge_model_id,
                        contents=judge_prompt_filled,
                        config=genai_types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=JUDGE_SCHEMA,
                            temperature=0.1,
                            max_output_tokens=16384,
                        ),
                    )
                    judge_text = resp.text or ""
                    scores_data = _parse_judge_response(judge_text)
                elif judge_provider == "openrouter":
                    from src.openrouter import stream_openrouter
                    messages = [{"role": "user", "content": judge_prompt_filled}]
                    acc_reasoning = ""
                    acc_content = ""
                    for r_delta, c_delta in stream_openrouter(
                        model_id=data.judge.model_id,
                        messages=messages,
                        temperature=0.1,
                        max_tokens=16384,
                    ):
                        if r_delta: acc_reasoning += r_delta
                        if c_delta: acc_content += c_delta
                        if acc_reasoning and acc_content: judge_text = f"<think>{acc_reasoning}</think>{acc_content}"
                        elif acc_reasoning: judge_text = f"<think>{acc_reasoning}"
                        else: judge_text = acc_content
                        yield f"event: judge_stream\ndata: {json.dumps({'index': idx, 'content': judge_text}, ensure_ascii=False)}\n\n"
                    scores_data = _parse_judge_response(acc_content)
                elif judge_provider == "custom_trained":
                    import requests as req_lib
                    url = data.judge.api_url.rstrip("/")
                    if "/v1/chat/completions" not in url:
                        url = f"{url}/v1/chat/completions" if not url.endswith("/v1") else f"{url}/chat/completions"
                    req_data = {
                        "model": data.judge.model_name,
                        "messages": [{"role": "user", "content": judge_prompt_filled}],
                        "temperature": 0.1,
                        "max_tokens": 16384,
                        "stream": True,
                        "chat_template_kwargs": {"enable_thinking": True},
                    }
                    resp = req_lib.post(url, json=req_data, headers={"Content-Type": "application/json"}, stream=True, timeout=300)
                    resp.raise_for_status()
                    acc_text = ""
                    for line in resp.iter_lines(decode_unicode=True):
                        if not line or not line.startswith("data: "): continue
                        payload = line[6:]
                        if payload.strip() == "[DONE]": break
                        try:
                            chunk_data = json.loads(payload)
                            delta = chunk_data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "") or ""
                            reasoning = delta.get("reasoning_content", "") or ""
                            if reasoning or content:
                                acc_text += reasoning + content
                                judge_text = acc_text
                                yield f"event: judge_stream\ndata: {json.dumps({'index': idx, 'content': judge_text}, ensure_ascii=False)}\n\n"
                        except Exception: pass
                    scores_data = _parse_judge_response(acc_text)
                result_data = {'index': idx, 'content': judge_text}
                if scores_data: result_data['scores'] = scores_data
                yield f"event: judge_done\ndata: {json.dumps(result_data, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"event: judge_error\ndata: {json.dumps({'index': idx, 'message': str(e)})}\n\n"
        yield f"event: done\ndata: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Knowledge Graph Visualization Endpoints
# ---------------------------------------------------------------------------

def _get_admin_graph_store():
    """Helper to retrieve the global GraphStore instance from the active RAG engine."""
    try:
        from src.api import get_engine
        engine = get_engine()
        store = getattr(engine, "graph_store", None)
        if store:
            return store
    except Exception:
        pass
    
    from src.graph_store import GraphStore
    return GraphStore()


def _get_relationships_between_nodes(store, node_ids: list[str]) -> list[dict]:
    """Fetch all relationships between a given set of node IDs from Neo4j."""
    if not node_ids:
        return []
    
    # Check if we should use numeric ID or elementId
    is_numeric = all(nid.isdigit() for nid in node_ids if nid)
    if is_numeric:
        numeric_ids = [int(nid) for nid in node_ids if nid]
        cypher = """
        MATCH (a)-[r]->(b)
        WHERE id(a) IN $ids AND id(b) IN $ids
        RETURN r, a, b
        """
        params = {"ids": numeric_ids}
    else:
        cypher = """
        MATCH (a)-[r]->(b)
        WHERE elementId(a) IN $ids AND elementId(b) IN $ids
        RETURN r, a, b
        """
        params = {"ids": node_ids}
        
    try:
        with store.session() as session:
            records = list(session.run(cypher, params))
        
        edges_list = []
        from neo4j.graph import Relationship, Node
        for record in records:
            r = record.get("r")
            a = record.get("a")
            b = record.get("b")
            if r is not None and isinstance(r, Relationship) and a is not None and b is not None:
                edge_id = r.element_id if hasattr(r, "element_id") else str(r.id)
                source_id = a.element_id if hasattr(a, "element_id") else str(a.id)
                target_id = b.element_id if hasattr(b, "element_id") else str(b.id)
                edges_list.append({
                    "id": edge_id,
                    "source": source_id,
                    "target": target_id,
                    "type": r.type,
                    "properties": dict(r.items())
                })
        return edges_list
    except Exception as e:
        try:
            from loguru import logger
            logger.error(f"Lỗi truy vấn mối quan hệ giữa các nút: {e}")
        except ImportError:
            print(f"Lỗi truy vấn mối quan hệ giữa các nút: {e}")
        return []


@router.get("/graph/stats")
async def get_graph_stats(
    admin: User = Depends(get_current_admin)
):
    """Get Neo4j knowledge graph statistics (admin only)."""
    try:
        store = _get_admin_graph_store()
        return store.stats_simple()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Không thể kết nối Neo4j: {str(e)}")


@router.post("/graph/data")
async def get_graph_data(
    data: dict = None,
    admin: User = Depends(get_current_admin)
):
    """Retrieve a subset of the graph database for visualization (admin only)."""
    data = data or {}
    limit = int(data.get("limit", 150))
    labels = data.get("labels", ["Law", "Chapter", "Article"])
    
    label_filter_n = " OR ".join(f"n:{l}" for l in labels) if labels else ""
    label_filter_m = " OR ".join(f"m:{l}" for l in labels) if labels else ""
    
    # Primary query: match connected subgraphs within the selected labels to avoid isolated singletons
    if labels and len(labels) > 1:
        cypher = f"""
        MATCH (n)-[r]->(m)
        WHERE ({label_filter_n}) AND ({label_filter_m})
        RETURN n, r, m LIMIT {limit}
        """
    else:
        # Fallback query for single label or no labels
        cypher = f"""
        MATCH (n)
        {f"WHERE {label_filter_n}" if label_filter_n else ""}
        WITH n LIMIT {limit}
        OPTIONAL MATCH (n)-[r]->(m)
        {f"WHERE {label_filter_m}" if label_filter_m else ""}
        RETURN n, r, m LIMIT {limit * 2}
        """
    
    try:
        store = _get_admin_graph_store()
        with store.session() as session:
            records = list(session.run(cypher))
        
        nodes_dict = {}
        edges_list = []
        
        from neo4j.graph import Node, Relationship
        
        for record in records:
            n = record.get("n")
            r = record.get("r")
            m = record.get("m")
            
            if n is not None and isinstance(n, Node):
                node_id = n.element_id if hasattr(n, "element_id") else str(n.id)
                nodes_dict[node_id] = {
                    "id": node_id,
                    "labels": list(n.labels),
                    "properties": dict(n.items())
                }
            if m is not None and isinstance(m, Node):
                node_id = m.element_id if hasattr(m, "element_id") else str(m.id)
                nodes_dict[node_id] = {
                    "id": node_id,
                    "labels": list(m.labels),
                    "properties": dict(m.items())
                }
            if r is not None and isinstance(r, Relationship) and n is not None and m is not None:
                edge_id = r.element_id if hasattr(r, "element_id") else str(r.id)
                source_id = n.element_id if hasattr(n, "element_id") else str(n.id)
                target_id = m.element_id if hasattr(m, "element_id") else str(m.id)
                edges_list.append({
                    "id": edge_id,
                    "source": source_id,
                    "target": target_id,
                    "type": r.type,
                    "properties": dict(r.items())
                })
                
        # Fetch all relationships between the retrieved nodes to ensure we don't miss any links
        node_ids = list(nodes_dict.keys())
        all_edges = _get_relationships_between_nodes(store, node_ids)
        
        edges_map = {e["id"]: e for e in edges_list}
        for edge in all_edges:
            edges_map[edge["id"]] = edge
            
        return {
            "nodes": list(nodes_dict.values()),
            "edges": list(edges_map.values())
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi truy vấn đồ thị: {str(e)}")


@router.post("/graph/neighbors")
async def get_graph_neighbors(
    data: dict,
    admin: User = Depends(get_current_admin)
):
    """Retrieve neighbors for a specific node (admin only)."""
    node_id = data.get("node_id")
    if not node_id:
        raise HTTPException(status_code=400, detail="Thiếu node_id")
    
    is_numeric_id = False
    try:
        int(node_id)
        is_numeric_id = True
    except ValueError:
        pass

    if is_numeric_id:
        cypher = """
        MATCH (n) WHERE id(n) = $nid
        MATCH (n)-[r]-(m)
        RETURN n, r, m LIMIT 150
        """
        params = {"nid": int(node_id)}
    else:
        cypher = """
        MATCH (n) WHERE elementId(n) = $nid
        MATCH (n)-[r]-(m)
        RETURN n, r, m LIMIT 150
        """
        params = {"nid": node_id}
        
    try:
        store = _get_admin_graph_store()
        with store.session() as session:
            records = list(session.run(cypher, params))
        
        nodes_dict = {}
        edges_list = []
        
        from neo4j.graph import Node, Relationship
        
        for record in records:
            n = record.get("n")
            r = record.get("r")
            m = record.get("m")
            
            if n is not None and isinstance(n, Node):
                n_id = n.element_id if hasattr(n, "element_id") else str(n.id)
                nodes_dict[n_id] = {
                    "id": n_id,
                    "labels": list(n.labels),
                    "properties": dict(n.items())
                }
            if m is not None and isinstance(m, Node):
                m_id = m.element_id if hasattr(m, "element_id") else str(m.id)
                nodes_dict[m_id] = {
                    "id": m_id,
                    "labels": list(m.labels),
                    "properties": dict(m.items())
                }
            if r is not None and isinstance(r, Relationship) and n is not None and m is not None:
                edge_id = r.element_id if hasattr(r, "element_id") else str(r.id)
                source_id = r.start_node.element_id if hasattr(r.start_node, "element_id") else str(r.start_node.id)
                target_id = r.end_node.element_id if hasattr(r.end_node, "element_id") else str(r.end_node.id)
                edges_list.append({
                    "id": edge_id,
                    "source": source_id,
                    "target": target_id,
                    "type": r.type,
                    "properties": dict(r.items())
                })
                
        existing_node_ids = data.get("existing_node_ids", [])
        
        # Fetch all relationships between the queried nodes and existing nodes
        queried_node_ids = list(nodes_dict.keys())
        all_node_ids = list(set(queried_node_ids + existing_node_ids))
        all_edges = _get_relationships_between_nodes(store, all_node_ids)
        
        edges_map = {e["id"]: e for e in edges_list}
        for edge in all_edges:
            edges_map[edge["id"]] = edge
            
        return {
            "nodes": list(nodes_dict.values()),
            "edges": list(edges_map.values())
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi truy vấn nút lân cận: {str(e)}")


@router.post("/graph/query")
async def run_custom_cypher(
    data: dict,
    admin: User = Depends(get_current_admin)
):
    """Execute a custom read-only Cypher query and return formatted results (admin only)."""
    cypher = data.get("cypher")
    if not cypher:
        raise HTTPException(status_code=400, detail="Thiếu câu lệnh cypher")
        
    # Validate read-only query
    forbidden = [
        "CREATE", "DELETE", "DETACH", "MERGE", "SET ", "REMOVE",
        "DROP", "CALL DB.CLEAR", "FOREACH",
    ]
    upper = cypher.upper()
    for kw in forbidden:
        if kw in upper:
            raise HTTPException(status_code=400, detail=f"Cypher chứa keyword bị cấm: {kw.strip()}")

    try:
        store = _get_admin_graph_store()
        with store.session() as session:
            records = list(session.run(cypher))
        
        nodes_dict = {}
        edges_list = []
        rows = []
        
        from neo4j.graph import Node, Relationship, Path
        
        for record in records:
            row_data = {}
            for key, value in record.items():
                if isinstance(value, Node):
                    n_id = value.element_id if hasattr(value, "element_id") else str(value.id)
                    nodes_dict[n_id] = {
                        "id": n_id,
                        "labels": list(value.labels),
                        "properties": dict(value.items())
                    }
                    row_data[key] = f"Node({list(value.labels)})"
                elif isinstance(value, Relationship):
                    edge_id = value.element_id if hasattr(value, "element_id") else str(value.id)
                    source_id = value.start_node.element_id if hasattr(value.start_node, "element_id") else str(value.start_node.id)
                    target_id = value.end_node.element_id if hasattr(value.end_node, "element_id") else str(value.end_node.id)
                    edges_list.append({
                        "id": edge_id,
                        "source": source_id,
                        "target": target_id,
                        "type": value.type,
                        "properties": dict(value.items())
                    })
                    row_data[key] = f"Relationship({value.type})"
                elif isinstance(value, Path):
                    for node in value.nodes:
                        n_id = node.element_id if hasattr(node, "element_id") else str(node.id)
                        nodes_dict[n_id] = {
                            "id": n_id,
                            "labels": list(node.labels),
                            "properties": dict(node.items())
                        }
                    for rel in value.relationships:
                        edge_id = rel.element_id if hasattr(rel, "element_id") else str(rel.id)
                        source_id = rel.start_node.element_id if hasattr(rel.start_node, "element_id") else str(rel.start_node.id)
                        target_id = rel.end_node.element_id if hasattr(rel.end_node, "element_id") else str(rel.end_node.id)
                        edges_list.append({
                            "id": edge_id,
                            "source": source_id,
                            "target": target_id,
                            "type": rel.type,
                            "properties": dict(rel.items())
                        })
                    row_data[key] = "Path"
                else:
                    row_data[key] = value
            rows.append(row_data)
            
        # Fetch all relationships between the returned nodes
        node_ids = list(nodes_dict.keys())
        all_edges = _get_relationships_between_nodes(store, node_ids)
        
        edges_map = {e["id"]: e for e in edges_list}
        for edge in all_edges:
            edges_map[edge["id"]] = edge
            
        return {
            "nodes": list(nodes_dict.values()),
            "edges": list(edges_map.values()),
            "rows": rows
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

