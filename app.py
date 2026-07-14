"""
Entry point: chạy Gradio UI + FastAPI server.
Usage: python app.py
"""

import json
import threading
import gradio as gr
import uvicorn
from loguru import logger

from src import config
from src.api import api, get_engine, start_background_loading, is_engine_ready
from src.openrouter import fetch_openrouter_models, stream_openrouter, get_openrouter_key
from src.rag_engine import _stream_custom_trained_api, _build_context_vector_only
from src import config as cfg

# ---- Global cache for OpenRouter model list ----
_openrouter_models_cache: list[dict] = []
_cache_lock = threading.Lock()


def do_index(strategy):
    if not is_engine_ready():
        return "Model đang được tải, vui lòng đợi..."
    engine = get_engine()
    result = engine.index_documents(strategy=strategy)
    stats = engine.get_stats()
    lines = [
        f"Indexing hoàn tất!",
        f"Chunks: {result['chunks_processed']}",
        f"Tổng trong store: {result['total_in_store']}",
        f"Chiến lược: {result['strategy']}",
        f"Số tài liệu: {stats['document_count']}",
        "",
        "Danh sách:",
    ]
    for doc in stats["documents"]:
        lines.append(f"  - {doc}")
    return "\n".join(lines)


def do_query(
    question,
    top_k,
    provider,
    use_graph,
    use_custom_api,
    custom_api_url,
    custom_model_name,
    temperature,
    max_tokens,
    top_p,
    top_k_llm,
    freq_penalty,
    pres_penalty,
    enable_thinking
):
    if not question or not question.strip():
        yield "Vui lòng nhập câu hỏi.", ""
        return

    if not is_engine_ready():
        yield "Model đang được tải, vui lòng đợi...", ""
        return

    engine = get_engine()
    if engine.store.collection.count() == 0:
        yield "Chưa có tài liệu nào. Vào tab Quản lý tài liệu để index trước.", ""
        return

    prov = provider.lower() if provider != "Tự động" else None
    if use_custom_api:
        prov = "custom_trained"

    custom_kwargs = {
        "api_url": custom_api_url,
        "model_name": custom_model_name,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": top_p,
        "top_k": top_k_llm,
        "frequency_penalty": freq_penalty,
        "presence_penalty": pres_penalty,
        "enable_thinking": enable_thinking
    }

    # Yield initial state
    yield "⏳ Đang kết nối mô hình và tìm kiếm tài liệu tham khảo...", ""

    try:
        # Stream results from RAG engine
        for partial_text, sources_md in engine.query_stream(
            question=question,
            top_k=int(top_k),
            provider=prov,
            use_graph=bool(use_graph),
            custom_kwargs=custom_kwargs
        ):
            yield partial_text, sources_md
    except Exception as e:
        logger.error(f"Error in do_query stream: {e}")
        yield f"Lỗi trong quá trình xử lý: {e}", ""


def do_clear():
    if not is_engine_ready():
        return "Model đang được tải..."
    get_engine().store.delete_collection()
    return "Đã xóa toàn bộ dữ liệu index."


def do_refresh_stats():
    if not is_engine_ready():
        return "Model đang được tải..."
    stats = get_engine().get_stats()
    return (
        f"Tổng chunks: {stats['total_chunks']}\n"
        f"Số tài liệu: {stats['document_count']}\n"
        f"Model: {stats['embedding_model']}\n"
        f"Collection: {stats['collection']}"
    )


def _gradio_list_laws():
    try:
        from src.graph_viz import list_laws
        laws = list_laws()
        choices = [(f"{doc} — {title}", doc) for doc, title in laws]
        return gr.update(choices=choices, value=laws[0][0] if laws else None)
    except Exception as e:
        return gr.update(choices=[], value=None, label=f"Lỗi: {e}")


def _gradio_render_law(law_doc_number):
    if not law_doc_number:
        return "<p>Chọn một Luật.</p>"
    try:
        from src.graph_viz import render_law_structure
        return render_law_structure(law_doc_number)
    except Exception as e:
        return f"<p>Lỗi: {e}. Đảm bảo Neo4j đang chạy và graph đã được build.</p>"


def _gradio_render_neighbors(node_type, node_id, depth):
    if not node_id or not node_id.strip():
        return "<p>Nhập id hoặc tên node.</p>"
    try:
        from src.graph_viz import render_neighbors
        if node_type in ("Concept", "Actor", "Action"):
            node_id = node_id.strip().lower()
        else:
            node_id = node_id.strip()
        return render_neighbors(node_type, node_id, depth=int(depth))
    except Exception as e:
        return f"<p>Lỗi: {e}</p>"


def _gradio_run_cypher(cypher):
    if not cypher or not cypher.strip():
        return {"error": "Nhập Cypher"}
    try:
        from src.graph_store import GraphStore
        store = GraphStore()
        try:
            rows = store.safe_read_cypher(cypher, {})
            return {"count": len(rows), "rows": rows[:100]}
        finally:
            store.close()
    except Exception as e:
        return {"error": str(e)}


def _gradio_build_graph(strategy, clear, extract_semantic, max_sem):
    try:
        from scripts.build_graph import build
        max_semantic = int(max_sem) if max_sem else None
        if max_semantic == 0:
            max_semantic = None
        return build(
            strategy=strategy,
            extract_semantic=bool(extract_semantic),
            clear=bool(clear),
            max_semantic=max_semantic,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _gradio_graph_stats():
    try:
        from src.graph_store import GraphStore
        from src.graph_viz import render_stats_bar
        store = GraphStore()
        try:
            stats = store.stats_simple()
        finally:
            store.close()
        return render_stats_bar(stats)
    except Exception as e:
        return f"<p>Lỗi: {e}. Hãy chắc rằng Neo4j đang chạy (docker-compose up -d neo4j).</p>"


EXAMPLE_QUESTIONS = [
    "Quyền và nghĩa vụ của người lao động được quy định như thế nào?",
    "Hợp đồng lao động có những loại nào?",
    "Quy định về kết hôn trong Luật Hôn nhân và Gia đình?",
    "Tội phạm được phân loại như thế nào theo Bộ luật Hình sự?",
    "Quyền sở hữu tài sản được quy định ra sao trong Bộ luật Dân sự?",
]

# ─────────────────────────────────────────────────────────────────────────────
# Model Comparison helper functions
# ─────────────────────────────────────────────────────────────────────────────

BASE_MODEL_ID = "__base_pretrained__"
BASE_MODEL_LABEL = "📦 Base Pretrained (Local/Cloud VM)"
CUSTOM_MODEL_ID = "__custom_trained__"
CUSTOM_MODEL_LABEL = "⚡ Custom Trained (Local/Cloud VM)"
GEMINI_MODEL_ID = "__gemini_2_5__"
GEMINI_MODEL_LABEL = "🔹 Gemini 2.5 Flash (Nội bộ)"
GEMINI_JUDGE_ID = "__gemini_judge__"
GEMINI_JUDGE_LABEL = "🔹 Gemini (gemini-3.5-flash) — nội bộ"


def _get_gemini_client():
    from google import genai as _genai
    from google.genai.types import HttpOptions
    if config.GEMINI_USE_VERTEXAI:
        return _genai.Client(http_options=HttpOptions(api_version="v1"))
    else:
        return _genai.Client(
            api_key=config.GOOGLE_API_KEY,
            http_options=HttpOptions(api_version="v1"),
        )


def _stream_gemini_compare_deltas(question: str, context: str, temperature: float = 0.7, max_tokens: int = 1024, enable_thinking: bool = False):
    """
    Stream Gemini 2.5 Flash response for comparison as deltas.
    Yields (reasoning_delta, content_delta) tuples.
    """
    from google.genai import types

    client = _get_gemini_client()

    prompt = (
        f"{config.SYSTEM_PROMPT}\n\n"
        f"--- Tài liệu tham khảo ---\n{context}\n\n"
        f"--- Câu hỏi ---\n{question}\n\n"
        f"--- Trả lời ---"
    ) if context else f"{config.SYSTEM_PROMPT}\n\n--- Câu hỏi ---\n{question}\n\n--- Trả lời ---"

    for chunk in client.models.generate_content_stream(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                include_thoughts=enable_thinking,
                thinking_budget=2048 if enable_thinking else 0
            ),
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    ):
        if chunk.candidates:
            for candidate in chunk.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        is_thought = getattr(part, 'thought', False)
                        text = getattr(part, 'text', '') or ''
                        if text:
                            if is_thought:
                                yield text, ""
                            else:
                                yield "", text


def _stream_gemini_judge(prompt: str, enable_thinking: bool = False):
    """
    Stream Gemini response for judge scoring.
    Yields (accumulated_thought, accumulated_content) tuples incrementally.
    """
    from google.genai import types

    client = _get_gemini_client()

    accumulated_thought = ""
    accumulated_content = ""
    for chunk in client.models.generate_content_stream(
        model="gemini-3.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                include_thoughts=enable_thinking,
                thinking_budget=2048 if enable_thinking else 0
            ),
            temperature=0.3,
            max_output_tokens=3000,
        ),
    ):
        if chunk.candidates:
            for candidate in chunk.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        is_thought = getattr(part, 'thought', False)
                        text = getattr(part, 'text', '') or ''
                        if text:
                            if is_thought:
                                accumulated_thought += text
                            else:
                                accumulated_content += text
        yield accumulated_thought, accumulated_content


def _do_rag_retrieval(question: str, top_k: int, use_graph: bool):
    """Run retrieval once, return (context_str, sources_md)."""
    if not is_engine_ready():
        return None, "Model đang được tải..."
    engine = get_engine()
    if engine.store.collection.count() == 0:
        return None, "Chưa có tài liệu nào. Vào tab Quản lý tài liệu để index trước."

    vector_hits = engine.store.query(question, top_k=int(top_k))
    fused = None
    graph_hits = []
    retrieval_mode = "vector"

    if use_graph and engine.graph_retriever is not None:
        try:
            graph_hits = engine.graph_retriever.retrieve(
                question=question, vector_hits=vector_hits
            )
            from src.hybrid_fusion import fuse, build_context
            fused = fuse(vector_hits, graph_hits, top_n=int(top_k) + 3)
            context = build_context(fused, max_chars=8000)
            retrieval_mode = "hybrid"
        except Exception as e:
            logger.warning(f"Graph fusion lỗi: {e}. Fallback vector-only.")
            context = _build_context_vector_only(vector_hits)
    else:
        context = _build_context_vector_only(vector_hits)

    sources = engine._build_sources(vector_hits, fused, graph_hits)
    sources_md = ""
    if sources:
        sources_md = "---\n### 📚 Nguồn tham khảo\n\n"
        for i, s in enumerate(sources, 1):
            ref_parts = []
            if s.get("doc_number"):
                ref_parts.append(f"Số hiệu: {s['doc_number']}")
            if s.get("chapter"):
                ref_parts.append(s["chapter"])
            if s.get("article"):
                ref_parts.append(f"Điều {s['article']}")
            if s.get("clause"):
                ref_parts.append(f"Khoản {s['clause']}")
            ref = " | ".join(ref_parts) if ref_parts else s.get("source", "")
            src_tags = "+".join(s.get("retrieval_sources", []) or ["vector"])
            sim = s.get("similarity", 0)
            sim_str = f"{sim:.2f}" if isinstance(sim, float) else str(sim)
            sources_md += (
                f"**{i}. {s.get('source', 'N/A')}** — [{src_tags}] score: {sim_str}\n\n"
                f"> {ref}\n\n"
            )
    sources_md += f"\n*Mode: {retrieval_mode}*"
    return context, sources_md


def _format_model_html(model_name: str, reasoning: str, answer: str, done: bool, error: str = "") -> str:
    """Render a model panel as HTML with collapsible reasoning section."""
    status_icon = "✅" if done else "⏳"
    if error:
        status_icon = "❌"

    reasoning_html = ""
    if reasoning:
        open_attr = "" if done else " open"
        reasoning_html = (
            f'<details{open_attr} class="reasoning-box">'
            f'<summary>🧠 <b>Reasoning</b> (click to toggle)</summary>'
            f'<div class="reasoning-content">{reasoning.replace(chr(10), "<br>")}</div>'
            f'</details>'
        )

    answer_html = ""
    if error:
        answer_html = f'<div class="answer-error">❌ {error}</div>'
    elif answer:
        import re
        # Simple markdown-like formatting for the answer
        safe = answer.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        safe = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', safe)
        safe = re.sub(r'\*(.+?)\*', r'<em>\1</em>', safe)
        safe = safe.replace("\n", "<br>")
        answer_html = f'<div class="answer-text">{safe}</div>'
    else:
        if not done:
            answer_html = '<div class="answer-text answer-typing">Đang trả lời...</div>'

    return (
        f'<div class="model-panel">'
        f'  <div class="model-header">{status_icon} <span class="model-name">{model_name}</span></div>'
        f'  {reasoning_html}'
        f'  {answer_html}'
        f'</div>'
    )


def _refresh_openrouter_models():
    """Fetch OpenRouter models and update global cache. Returns display list."""
    global _openrouter_models_cache
    key = get_openrouter_key()
    if not key or key == "your_openrouter_api_key_here":
        return [], "⚠️ Chưa cấu hình OPENROUTER_API_KEY trong file .env"
    models = fetch_openrouter_models()
    with _cache_lock:
        _openrouter_models_cache = models
    choices = []
    for m in models:
        tag = " 🆓" if m["is_free"] else ""
        label = f"{m['name']}{tag} [{m['id']}]"
        choices.append((label, m["id"]))
    return choices, f"✅ Tải thành công {len(models)} model từ OpenRouter"


def _stream_custom_raw(question: str, context: str, kwargs: dict):
    """
    Stream custom trained API, yielding (reasoning_delta, content_delta) tuples.
    Handles both reasoning_content field and <think>...</think> tags.
    """
    import requests as _requests
    import json as _json

    url = kwargs.get("api_url", "")
    if not url.endswith("/chat/completions"):
        if url.endswith("/v1") or url.endswith("/v1/"):
            url = url.rstrip("/") + "/chat/completions"
        elif "/v1/chat/completions" not in url:
            url = url.rstrip("/") + "/v1/chat/completions"

    messages = [
        {"role": "system", "content": config.SYSTEM_PROMPT},
        {"role": "user", "content": f"Tài liệu tham khảo:\n{context}\n\nCâu hỏi: {question}"},
    ]
    data = {
        "model": kwargs.get("model_name", ""),
        "messages": messages,
        "temperature": float(kwargs.get("temperature", 0.7)),
        "max_tokens": int(kwargs.get("max_tokens", 1024)),
        "top_p": float(kwargs.get("top_p", 0.95)),
        "stream": True,
        "chat_template_kwargs": {"enable_thinking": bool(kwargs.get("enable_thinking", False))},
    }
    if kwargs.get("frequency_penalty") is not None:
        data["frequency_penalty"] = float(kwargs["frequency_penalty"])
    if kwargs.get("presence_penalty") is not None:
        data["presence_penalty"] = float(kwargs["presence_penalty"])

    resp = _requests.post(url, json=data, stream=True, timeout=180)
    resp.raise_for_status()

    accumulated_content = ""
    in_think_tag = False  # tracking <think> mode
    think_buf = ""

    for line in resp.iter_lines():
        if not line:
            continue
        line_str = line.decode("utf-8").strip()
        if not line_str.startswith("data:"):
            continue
        payload = line_str[5:].strip()
        if payload == "[DONE]":
            break
        try:
            chunk = _json.loads(payload)
            delta = chunk["choices"][0]["delta"]
            reasoning_chunk = delta.get("reasoning_content", "") or ""
            content_chunk = delta.get("content", "") or ""

            # Case 1: model sends reasoning_content field directly
            if reasoning_chunk:
                yield reasoning_chunk, ""
                continue

            # Case 2: model embeds <think>...</think> inside content
            if content_chunk:
                accumulated_content += content_chunk
                # Check for <think> start
                while True:
                    if not in_think_tag:
                        if "<think>" in accumulated_content:
                            before, rest = accumulated_content.split("<think>", 1)
                            if before:
                                yield "", before
                            accumulated_content = rest
                            in_think_tag = True
                            think_buf = ""
                        else:
                            # No think tag – flush as normal content
                            if accumulated_content:
                                yield "", accumulated_content
                                accumulated_content = ""
                            break
                    else:  # inside <think>...</think>
                        if "</think>" in accumulated_content:
                            think_part, rest = accumulated_content.split("</think>", 1)
                            think_buf += think_part
                            yield think_buf, ""   # flush full reasoning
                            think_buf = ""
                            accumulated_content = rest
                            in_think_tag = False
                        else:
                            # Still accumulating inside think
                            think_buf += accumulated_content
                            yield accumulated_content, ""  # stream reasoning increments
                            accumulated_content = ""
                            break
        except Exception:
            pass

    # Flush any remaining
    if accumulated_content and not in_think_tag:
        yield "", accumulated_content


def comparison_run(
    question,
    selected_models_json,
    include_base,
    include_custom,
    include_gemini,
    base_api_url,
    base_model_name,
    custom_api_url,
    custom_model_name,
    use_rag,
    top_k,
    use_graph,
    temperature,
    max_tokens,
    top_p,
    freq_penalty,
    pres_penalty,
    enable_thinking,
    gemini_thinking,
):
    """
    Generator: streams parallel answers from up to 4 models.
    Yields (panel1_html, panel2_html, panel3_html, panel4_html, sources_md).
    """
    import time

    if not question or not question.strip():
        yield "<p>Vui lòng nhập câu hỏi.</p>", "", "", "", ""
        return

    # ── Build selected model list ──
    selected_ids = []
    if include_base:
        selected_ids.append(BASE_MODEL_ID)
    if include_custom:
        selected_ids.append(CUSTOM_MODEL_ID)
    if include_gemini:
        selected_ids.append(GEMINI_MODEL_ID)
    try:
        extra_ids = json.loads(selected_models_json) if selected_models_json else []
        selected_ids.extend(extra_ids)
    except Exception:
        pass

    if not selected_ids:
        yield "<p>Chưa chọn model nào.</p>", "", "", "", ""
        return

    selected_ids = selected_ids[:4]

    # ── RAG Retrieval (once, shared) ──
    context = ""
    sources_md = ""
    if use_rag:
        yield "<p>⏳ Đang tìm kiếm tài liệu tham khảo (RAG)...</p>", "", "", "", ""
        context, sources_md = _do_rag_retrieval(question, int(top_k), bool(use_graph))
        if context is None:
            yield f"<p>{sources_md}</p>", "", "", "", ""
            return
    else:
        sources_md = "*RAG đã tắt — model trả lời dựa trên kiến thức nội tại.*"

    # ── Build messages ──
    user_content = (
        f"Tài liệu tham khảo:\n{context}\n\nCâu hỏi: {question}"
        if use_rag and context
        else f"Câu hỏi: {question}"
    )
    messages = [
        {"role": "system", "content": config.SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    # ── Per-model state ──
    states = {}
    for mid in selected_ids:
        if mid == BASE_MODEL_ID:
            label = BASE_MODEL_LABEL
        elif mid == CUSTOM_MODEL_ID:
            label = CUSTOM_MODEL_LABEL
        elif mid == GEMINI_MODEL_ID:
            label = GEMINI_MODEL_LABEL
        else:
            with _cache_lock:
                cached = {m["id"]: m for m in _openrouter_models_cache}
            label = cached.get(mid, {}).get("name", mid)
        states[mid] = {
            "label": label,
            "reasoning": "",
            "answer": "",
            "done": False,
            "error": "",
            "queue": [],
            "finished": False,
        }

    # ── Worker threads ──
    def _worker_base(mid):
        s = states[mid]
        try:
            kwargs = {
                "api_url": base_api_url,
                "model_name": base_model_name,
                "temperature": float(temperature),
                "max_tokens": int(max_tokens),
                "top_p": float(top_p),
                "frequency_penalty": float(freq_penalty),
                "presence_penalty": float(pres_penalty),
                "enable_thinking": bool(enable_thinking),
            }
            for r_delta, c_delta in _stream_custom_raw(question, context, kwargs):
                s["queue"].append((r_delta, c_delta))
        except Exception as e:
            s["error"] = str(e)
        s["finished"] = True

    def _worker_custom(mid):
        s = states[mid]
        try:
            kwargs = {
                "api_url": custom_api_url,
                "model_name": custom_model_name,
                "temperature": float(temperature),
                "max_tokens": int(max_tokens),
                "top_p": float(top_p),
                "frequency_penalty": float(freq_penalty),
                "presence_penalty": float(pres_penalty),
                "enable_thinking": bool(enable_thinking),
            }
            for r_delta, c_delta in _stream_custom_raw(question, context, kwargs):
                s["queue"].append((r_delta, c_delta))
        except Exception as e:
            s["error"] = str(e)
        s["finished"] = True

    def _worker_gemini_compare_thread(mid):
        s = states[mid]
        try:
            for r_delta, c_delta in _stream_gemini_compare_deltas(
                question=question,
                context=context,
                temperature=float(temperature),
                max_tokens=int(max_tokens),
                enable_thinking=bool(gemini_thinking),
            ):
                s["queue"].append((r_delta, c_delta))
        except Exception as e:
            s["error"] = str(e)
        s["finished"] = True

    def _worker_openrouter(mid):
        s = states[mid]
        try:
            for r_delta, c_delta in stream_openrouter(
                model_id=mid,
                messages=messages,
                temperature=float(temperature),
                max_tokens=int(max_tokens),
                top_p=float(top_p),
                frequency_penalty=float(freq_penalty),
                presence_penalty=float(pres_penalty),
            ):
                s["queue"].append((r_delta, c_delta))
        except Exception as e:
            s["error"] = str(e)
        s["finished"] = True

    for mid in selected_ids:
        if mid == BASE_MODEL_ID:
            fn = _worker_base
        elif mid == CUSTOM_MODEL_ID:
            fn = _worker_custom
        elif mid == GEMINI_MODEL_ID:
            fn = _worker_gemini_compare_thread
        else:
            fn = _worker_openrouter
        t = threading.Thread(target=fn, args=(mid,), daemon=True)
        t.start()

    def _render():
        panels = []
        for mid in selected_ids:
            s = states[mid]
            panels.append(
                _format_model_html(s["label"], s["reasoning"], s["answer"], s["done"], s["error"])
            )
        while len(panels) < 4:
            panels.append("")
        return panels[0], panels[1], panels[2], panels[3], sources_md

    # ── Stream loop ──
    while True:
        for mid in selected_ids:
            s = states[mid]
            while s["queue"]:
                r_d, c_d = s["queue"].pop(0)
                if r_d:
                    s["reasoning"] += r_d
                if c_d:
                    s["answer"] += c_d
            if s["finished"] and not s["done"]:
                s["done"] = True

        yield _render()
        if all(states[mid]["done"] for mid in selected_ids):
            break
        time.sleep(0.12)

    yield _render()


# Expose final answers for judge consumption
_last_comparison_states: dict = {}
_last_comparison_question: str = ""
_last_comparison_context: str = ""


def judge_run(
    question,
    selected_models_json,
    include_base,
    include_custom,
    include_gemini,
    judge_model_id,
    use_rag,
    top_k,
    use_graph,
    temperature,
    max_tokens,
    top_p,
    freq_penalty,
    pres_penalty,
    enable_thinking,
    base_api_url,
    base_model_name,
    custom_api_url,
    custom_model_name,
    gemini_thinking,
):
    """
    Run comparison + judge in sequence.
    First runs comparison_run(), then asks judge model to score all answers.
    Yields (panel1, panel2, panel3, panel4, sources_md, judge_html).
    """
    import time

    # ── Step 1: Run comparison, collect final answers ──
    final_panels = ["", "", "", ""]
    final_sources = ""

    if not question or not question.strip():
        yield "", "", "", "", "", "<p>Vui lòng nhập câu hỏi.</p>"
        return

    selected_ids = []
    if include_base:
        selected_ids.append(BASE_MODEL_ID)
    if include_custom:
        selected_ids.append(CUSTOM_MODEL_ID)
    if include_gemini:
        selected_ids.append(GEMINI_MODEL_ID)
    try:
        extra_ids = json.loads(selected_models_json) if selected_models_json else []
        selected_ids.extend(extra_ids)
    except Exception:
        pass
    selected_ids = selected_ids[:4]

    if not selected_ids:
        yield "", "", "", "", "", "<p>Chưa chọn model nào.</p>"
        return

    # RAG
    context = ""
    sources_md = ""
    if use_rag:
        yield "<p>⏳ Đang RAG...</p>", "", "", "", "", "⏳ Đang chuẩn bị..."
        context, sources_md = _do_rag_retrieval(question, int(top_k), bool(use_graph))
        if context is None:
            yield f"<p>{sources_md}</p>", "", "", "", "", ""
            return
    else:
        sources_md = "*RAG đã tắt.*"

    user_content = (
        f"Tài liệu tham khảo:\n{context}\n\nCâu hỏi: {question}"
        if use_rag and context else f"Câu hỏi: {question}"
    )
    messages = [
        {"role": "system", "content": config.SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    states = {}
    for mid in selected_ids:
        if mid == BASE_MODEL_ID:
            label = BASE_MODEL_LABEL
        elif mid == CUSTOM_MODEL_ID:
            label = CUSTOM_MODEL_LABEL
        elif mid == GEMINI_MODEL_ID:
            label = GEMINI_MODEL_LABEL
        else:
            with _cache_lock:
                cached = {m["id"]: m for m in _openrouter_models_cache}
            label = cached.get(mid, {}).get("name", mid)
        states[mid] = {
            "label": label, "reasoning": "", "answer": "",
            "done": False, "error": "", "queue": [], "finished": False,
        }

    def _worker_base_j(mid):
        s = states[mid]
        try:
            kw = {
                "api_url": base_api_url, "model_name": base_model_name,
                "temperature": float(temperature), "max_tokens": int(max_tokens),
                "top_p": float(top_p), "frequency_penalty": float(freq_penalty),
                "presence_penalty": float(pres_penalty), "enable_thinking": bool(enable_thinking),
            }
            for r_d, c_d in _stream_custom_raw(question, context, kw):
                s["queue"].append((r_d, c_d))
        except Exception as e:
            s["error"] = str(e)
        s["finished"] = True

    def _worker_custom_j(mid):
        s = states[mid]
        try:
            kw = {
                "api_url": custom_api_url, "model_name": custom_model_name,
                "temperature": float(temperature), "max_tokens": int(max_tokens),
                "top_p": float(top_p), "frequency_penalty": float(freq_penalty),
                "presence_penalty": float(pres_penalty), "enable_thinking": bool(enable_thinking),
            }
            for r_d, c_d in _stream_custom_raw(question, context, kw):
                s["queue"].append((r_d, c_d))
        except Exception as e:
            s["error"] = str(e)
        s["finished"] = True

    def _worker_gemini_j(mid):
        s = states[mid]
        try:
            for r_d, c_d in _stream_gemini_compare_deltas(
                question=question,
                context=context,
                temperature=float(temperature),
                max_tokens=int(max_tokens),
                enable_thinking=bool(gemini_thinking),
            ):
                s["queue"].append((r_d, c_d))
        except Exception as e:
            s["error"] = str(e)
        s["finished"] = True

    def _worker_or_j(mid):
        s = states[mid]
        try:
            for r_d, c_d in stream_openrouter(
                model_id=mid, messages=messages,
                temperature=float(temperature), max_tokens=int(max_tokens),
                top_p=float(top_p), frequency_penalty=float(freq_penalty),
                presence_penalty=float(pres_penalty),
            ):
                s["queue"].append((r_d, c_d))
        except Exception as e:
            s["error"] = str(e)
        s["finished"] = True

    for mid in selected_ids:
        if mid == BASE_MODEL_ID:
            fn = _worker_base_j
        elif mid == CUSTOM_MODEL_ID:
            fn = _worker_custom_j
        elif mid == GEMINI_MODEL_ID:
            fn = _worker_gemini_j
        else:
            fn = _worker_or_j
        threading.Thread(target=fn, args=(mid,), daemon=True).start()

    def _render_j(judge_html="⏳ Chờ các model hoàn thành..."):
        panels = []
        for mid in selected_ids:
            s = states[mid]
            panels.append(_format_model_html(s["label"], s["reasoning"], s["answer"], s["done"], s["error"]))
        while len(panels) < 4:
            panels.append("")
        return panels[0], panels[1], panels[2], panels[3], sources_md, judge_html

    # Stream comparison
    while True:
        for mid in selected_ids:
            s = states[mid]
            while s["queue"]:
                r_d, c_d = s["queue"].pop(0)
                if r_d:
                    s["reasoning"] += r_d
                if c_d:
                    s["answer"] += c_d
            if s["finished"] and not s["done"]:
                s["done"] = True
        yield _render_j()
        if all(states[mid]["done"] for mid in selected_ids):
            break
        time.sleep(0.12)

    yield _render_j()

    # ── Step 2: Judge scoring ──
    if not judge_model_id or judge_model_id == "none":
        yield _render_j("*(Chưa chọn model chấm điểm)*")
        return

    # Build judge prompt
    answers_block = ""
    for mid in selected_ids:
        s = states[mid]
        answers_block += f"### Model: {s['label']}\n{s['answer'] or '(không có câu trả lời)'}\n\n"

    context_note = f"\n\nNgữ cảnh tài liệu tham khảo (RAG):\n{context[:3000]}" if use_rag and context else ""
    judge_prompt = (
        f"Bạn là một chuyên gia pháp lý tối cao. Dưới đây là câu hỏi, ngữ cảnh tài liệu tham khảo RAG và các câu trả lời từ nhiều AI model khác nhau.\n"
        f"Hãy chấm điểm mỗi câu trả lời từ 1–10 dựa trên: độ chính xác pháp lý (so với ngữ cảnh RAG), tính đầy đủ, và độ rõ ràng.\n"
        f"QUY TẮC ĐẶC BIỆT QUAN TRỌNG: Các model tuyệt đối không được sử dụng hoặc bổ sung bất kỳ kiến thức pháp luật hay điều luật nào nằm ngoài ngữ cảnh tài liệu tham khảo RAG được cung cấp. Nếu bất kỳ model nào đưa vào các điều luật hoặc kiến thức luật không có trong ngữ cảnh RAG, hãy trừ điểm cực kỳ nặng của model đó hoặc chấm điểm 1.\n"
        f"Giải thích ngắn gọn lý do cho mỗi điểm. Cuối cùng chọn ra câu trả lời tốt nhất.{context_note}\n\n"
        f"## Câu hỏi:\n{question}\n\n"
        f"## Các câu trả lời cần chấm:\n{answers_block}"
    )
    judge_messages = [
        {"role": "system", "content": "Bạn là chuyên gia đánh giá câu trả lời pháp luật Việt Nam."},
        {"role": "user", "content": judge_prompt},
    ]

    judge_html = (
        '<div class="judge-panel">'
        '<div class="judge-header">⚖️ <b>Kết quả chấm điểm</b> '
        f'<span class="judge-model-tag">{judge_model_id}</span></div>'
        '<div class="judge-content" id="judge-content">⏳ Đang chấm điểm...'
    )

    acc_thought = ""
    acc_content = ""
    import re as _re

    def _fmt_judge_html(text: str, done: bool, thought: str = "") -> str:
        title = "Kết quả chấm điểm hoàn tất" if done else "Kết quả chấm điểm"
        safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        safe = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', safe)
        safe = _re.sub(r'### (.+)', r'<h4>\1</h4>', safe)
        safe = _re.sub(r'## (.+)', r'<h3>\1</h3>', safe)
        safe = safe.replace("\n", "<br>")
        
        thought_html = ""
        if thought:
            open_attr = "" if done else " open"
            thought_html = (
                f'<details{open_attr} class="reasoning-box">'
                f'<summary>🧠 <b>Reasoning</b> (click to toggle)</summary>'
                f'<div class="reasoning-content">{thought.replace(chr(10), "<br>")}</div>'
                f'</details>'
            )
            
        tag = GEMINI_JUDGE_LABEL if judge_model_id == GEMINI_JUDGE_ID else judge_model_id
        return (
            f'<div class="judge-panel">'
            f'<div class="judge-header">⚖️ <b>{title}</b> '
            f'<span class="judge-model-tag">{tag}</span></div>'
            f'{thought_html}'
            f'<div class="judge-content">{safe}</div></div>'
        )

    def _panels_now(done_flag=False):
        panels = []
        for mid in selected_ids:
            s = states[mid]
            panels.append(_format_model_html(s["label"], s["reasoning"], s["answer"], done_flag or s["done"], s["error"]))
        while len(panels) < 4:
            panels.append("")
        return panels

    try:
        if judge_model_id == GEMINI_JUDGE_ID:
            # ── Use Gemini (internal) ──
            if not config.GEMINI_AVAILABLE:
                raise RuntimeError("Gemini chưa được cấu hình (thiếu API key hoặc Vertex AI credentials)")
            judge_full_prompt = (
                f"Hệ thống: Bạn là chuyên gia đánh giá câu trả lời pháp luật Việt Nam.\n\n"
                + judge_prompt
            )
            for acc_thought, acc_content in _stream_gemini_judge(judge_full_prompt, enable_thinking=bool(gemini_thinking)):
                p = _panels_now()
                yield p[0], p[1], p[2], p[3], sources_md, _fmt_judge_html(acc_content, False, thought=acc_thought)
        else:
            # ── Use OpenRouter ──
            for r_d, c_d in stream_openrouter(
                model_id=judge_model_id,
                messages=judge_messages,
                temperature=0.3,
                max_tokens=2048,
                top_p=0.9,
            ):
                if c_d:
                    acc_content += c_d
                    p = _panels_now()
                    yield p[0], p[1], p[2], p[3], sources_md, _fmt_judge_html(acc_content, False)
    except Exception as e:
        error_html = (
            f'<div class="judge-panel"><div class="judge-header">⚖️ Chấm điểm</div>'
            f'<div class="answer-error">❌ Lỗi: {e}</div></div>'
        )
        p = _panels_now(True)
        yield p[0], p[1], p[2], p[3], sources_md, error_html
        return

    # ── Final yield ──
    p = _panels_now(True)
    yield p[0], p[1], p[2], p[3], sources_md, _fmt_judge_html(acc_content, True, thought=acc_thought)


# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# CSS for Model Comparison panels
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
COMPARISON_CSS = """
.model-panel {
    background: rgba(15,23,42,0.75);
    border: 1px solid rgba(99,102,241,0.3);
    border-radius: 14px;
    padding: 16px 18px;
    min-height: 180px;
    font-family: 'Outfit', 'Inter', sans-serif;
    color: #e2e8f0;
    transition: border-color 0.3s;
}
.model-panel:hover { border-color: rgba(139,92,246,0.6); }
.model-header {
    font-size: 1em;
    font-weight: 700;
    color: #a78bfa;
    margin-bottom: 10px;
    border-bottom: 1px solid rgba(255,255,255,0.07);
    padding-bottom: 6px;
}
.model-name { color: #e2e8f0; }
.reasoning-box {
    background: rgba(30,41,59,0.6);
    border: 1px solid rgba(99,102,241,0.2);
    border-radius: 8px;
    padding: 8px 12px;
    margin-bottom: 12px;
    font-size: 0.82em;
    color: #94a3b8;
    transition: all 0.3s;
}
.reasoning-box summary {
    cursor: pointer;
    color: #818cf8;
    font-weight: 600;
    user-select: none;
}
.reasoning-content {
    margin-top: 8px;
    max-height: 220px;
    overflow-y: auto;
    line-height: 1.6;
    white-space: pre-wrap;
}
.answer-text {
    line-height: 1.75;
    font-size: 0.93em;
    color: #e2e8f0;
}
.answer-typing {
    color: #64748b;
    font-style: italic;
}
.answer-error { color: #f87171; font-size: 0.9em; }
.judge-panel {
    background: linear-gradient(135deg, rgba(15,23,42,0.9) 0%, rgba(30,27,75,0.85) 100%);
    border: 1px solid rgba(139,92,246,0.45);
    border-radius: 14px;
    padding: 18px 22px;
    margin-top: 16px;
    font-family: 'Outfit', 'Inter', sans-serif;
    color: #e2e8f0;
}
.judge-header {
    font-size: 1.05em;
    font-weight: 700;
    color: #c4b5fd;
    margin-bottom: 12px;
    border-bottom: 1px solid rgba(139,92,246,0.25);
    padding-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.judge-model-tag {
    font-size: 0.72em;
    background: rgba(99,102,241,0.25);
    border: 1px solid rgba(99,102,241,0.4);
    border-radius: 20px;
    padding: 2px 10px;
    color: #a5b4fc;
    font-weight: 500;
}
.judge-content {
    line-height: 1.8;
    font-size: 0.92em;
    color: #e2e8f0;
}
.judge-content h3 { color: #a78bfa; margin: 10px 0 4px; }
.judge-content h4 { color: #818cf8; margin: 8px 0 4px; }
.judge-content strong { color: #f1f5f9; }
"""


def create_ui():
    css = """
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Inter:wght@300;400;500;600;700&display=swap');
    body, .gradio-container {
        font-family: 'Outfit', 'Inter', sans-serif !important;
    }
    .gradio-container {
        background: linear-gradient(135deg, #0f172a 0%, #020617 100%) !important;
        color: #f1f5f9 !important;
    }
    .block {
        background: rgba(15, 23, 42, 0.65) !important;
        backdrop-filter: blur(12px) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 16px !important;
        box-shadow: 0 4px 30px rgba(0, 0, 0, 0.35) !important;
    }
    .primary-btn {
        background: linear-gradient(90deg, #0ea5e9 0%, #8b5cf6 100%) !important;
        color: white !important;
        border: none !important;
        font-weight: 600 !important;
        transition: all 0.3s ease !important;
    }
    .primary-btn:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 4px 15px rgba(139, 92, 246, 0.45) !important;
    }
    .secondary-btn {
        background: rgba(30, 41, 59, 0.8) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        color: #f1f5f9 !important;
        transition: all 0.2s ease !important;
    }
    .secondary-btn:hover {
        background: rgba(51, 65, 85, 0.9) !important;
    }
    """
    css += COMPARISON_CSS
    
    with gr.Blocks(title="Trợ lý Pháp luật Việt Nam", css=css) as demo:
        gr.Markdown("# 🇻🇳 Trợ lý Pháp luật Việt Nam\nHệ thống hỏi đáp RAG kết hợp Vector DB & Knowledge Graph")

        with gr.Tabs():
            with gr.TabItem("Hỏi đáp"):
                with gr.Row():
                    with gr.Column(scale=2):
                        question_input = gr.Textbox(
                            label="Câu hỏi pháp luật",
                            placeholder="VD: Quyền của người lao động được quy định thế nào?",
                            lines=3,
                        )
                        with gr.Row():
                            top_k_slider = gr.Slider(
                                minimum=1, maximum=15, value=5, step=1,
                                label="Top-K Retrieval (Vector)",
                            )
                            provider_dropdown = gr.Dropdown(
                                choices=["Tự động", "gemini", "openai"],
                                value="Tự động",
                                label="LLM Fallback Provider",
                            )
                        use_graph_checkbox = gr.Checkbox(
                            value=config.ENABLE_GRAPH_RETRIEVAL,
                            label="Kích hoạt Knowledge Graph (Hybrid RAG)",
                        )
                        
                        # --- Custom Trained Model API Config Area ---
                        use_custom_api = gr.Checkbox(
                            value=True,
                            label="⚡ KÍCH HOẠT CUSTOM TRAINED API (CLOUD VM)",
                        )
                        
                        with gr.Accordion("⚙️ Cấu hình nâng cao (Custom API)", open=True):
                            custom_api_url = gr.Textbox(
                                label="URL API completions (ngrok / cloudflare)",
                                value="https://nonrequirable-sherril-undescriptively.ngrok-free.dev/v1/chat/completions",
                                placeholder="https://...",
                            )
                            custom_model_name = gr.Textbox(
                                label="Tên Model",
                                value="claspi2509/legal-AI-qwen3.5-q8-gguf",
                            )
                            with gr.Row():
                                temperature_slider = gr.Slider(
                                    minimum=0.0, maximum=1.5, value=0.7, step=0.1,
                                    label="Temperature",
                                )
                                max_tokens_slider = gr.Slider(
                                    minimum=64, maximum=8192, value=1024, step=64,
                                    label="Max Tokens",
                                )
                            with gr.Row():
                                top_p_slider = gr.Slider(
                                    minimum=0.0, maximum=1.0, value=0.95, step=0.05,
                                    label="Top-P",
                                )
                                top_k_llm_slider = gr.Slider(
                                    minimum=1, maximum=100, value=50, step=1,
                                    label="Top-K LLM",
                                )
                            with gr.Row():
                                freq_penalty_slider = gr.Slider(
                                    minimum=-2.0, maximum=2.0, value=0.0, step=0.1,
                                    label="Frequency Penalty",
                                )
                                pres_penalty_slider = gr.Slider(
                                    minimum=-2.0, maximum=2.0, value=0.0, step=0.1,
                                    label="Presence Penalty",
                                )
                            enable_thinking_checkbox = gr.Checkbox(
                                value=False,
                                label="🧠 Bật chế độ lập luận / suy nghĩ (Reasoning / Thinking)",
                            )
                        
                        ask_btn = gr.Button("Hỏi hệ thống", variant="primary", elem_classes="primary-btn")

                    with gr.Column(scale=3):
                        answer_output = gr.Markdown(label="Câu trả lời")
                        sources_output = gr.Markdown(label="Nguồn tham khảo")

                ask_btn.click(
                    fn=do_query,
                    inputs=[
                        question_input, 
                        top_k_slider, 
                        provider_dropdown, 
                        use_graph_checkbox,
                        use_custom_api,
                        custom_api_url,
                        custom_model_name,
                        temperature_slider,
                        max_tokens_slider,
                        top_p_slider,
                        top_k_llm_slider,
                        freq_penalty_slider,
                        pres_penalty_slider,
                        enable_thinking_checkbox
                    ],
                    outputs=[answer_output, sources_output],
                )
                question_input.submit(
                    fn=do_query,
                    inputs=[
                        question_input, 
                        top_k_slider, 
                        provider_dropdown, 
                        use_graph_checkbox,
                        use_custom_api,
                        custom_api_url,
                        custom_model_name,
                        temperature_slider,
                        max_tokens_slider,
                        top_p_slider,
                        top_k_llm_slider,
                        freq_penalty_slider,
                        pres_penalty_slider,
                        enable_thinking_checkbox
                    ],
                    outputs=[answer_output, sources_output],
                )

                gr.Markdown("**Câu hỏi mẫu:**")
                with gr.Row():
                    for q in EXAMPLE_QUESTIONS:
                        short_label = q[:40] + "..." if len(q) > 40 else q
                        btn = gr.Button(short_label, size="sm", variant="secondary", elem_classes="secondary-btn")
                        btn.click(fn=lambda x=q: x, outputs=[question_input])

            with gr.TabItem("Quản lý tài liệu"):
                with gr.Row():
                    strategy_dropdown = gr.Dropdown(
                        choices=["hybrid", "article", "chapter", "clause"],
                        value="hybrid",
                        label="Chiến lược chunking",
                    )
                    index_btn = gr.Button("Index tài liệu", variant="primary")
                    clear_btn = gr.Button("Xóa toàn bộ", variant="stop")
                    refresh_btn = gr.Button("Xem thống kê")

                index_output = gr.Textbox(label="Kết quả", lines=10, interactive=False)

                index_btn.click(fn=do_index, inputs=[strategy_dropdown], outputs=[index_output])
                clear_btn.click(fn=do_clear, outputs=[index_output])
                refresh_btn.click(fn=do_refresh_stats, outputs=[index_output])

            with gr.TabItem("Knowledge Graph"):
                gr.Markdown(
                    "### Knowledge Graph (Neo4j)\n"
                    "Graph gồm Law → Chapter → Article → Clause, "
                    "cộng với cạnh `REFERENCES` (dẫn chiếu) và `DEFINES/MENTIONS/REGULATES` (semantic từ LLM).\n"
                    "- Neo4j Aura: [console.neo4j.io](https://console.neo4j.io) — hoặc Neo4j local: [localhost:7474](http://localhost:7474)"
                )

                with gr.Tabs():
                    with gr.TabItem("Cấu trúc Luật"):
                        with gr.Row():
                            law_dropdown = gr.Dropdown(
                                label="Chọn Luật", choices=[], value=None, allow_custom_value=True,
                            )
                            refresh_laws_btn = gr.Button("Tải danh sách Luật", size="sm")
                            show_law_btn = gr.Button("Hiển thị", variant="primary")
                        law_graph_html = gr.HTML()

                    with gr.TabItem("Tra cứu Concept/Actor"):
                        with gr.Row():
                            node_type_dd = gr.Dropdown(
                                label="Loại node",
                                choices=["Concept", "Actor", "Action", "Article", "Law"],
                                value="Concept",
                            )
                            node_id_tb = gr.Textbox(
                                label="ID / Tên", placeholder="vd: hôn nhân / kết hôn / 91/2015/QH13",
                            )
                            depth_slider = gr.Slider(
                                minimum=1, maximum=3, value=2, step=1, label="Độ sâu",
                            )
                            show_nbrs_btn = gr.Button("Hiển thị neighbors", variant="primary")
                        nbrs_html = gr.HTML()

                    with gr.TabItem("Cypher Query"):
                        cypher_tb = gr.Textbox(
                            label="Cypher (read-only)",
                            value="MATCH (a:Article)-[:REFERENCES]->(b:Article) RETURN a.law_number, a.num, b.law_number, b.num LIMIT 25",
                            lines=4,
                        )
                        run_cypher_btn = gr.Button("Chạy", variant="primary")
                        cypher_out = gr.JSON(label="Kết quả")

                    with gr.TabItem("Cập nhật & Stats"):
                        with gr.Row():
                            build_strategy = gr.Dropdown(
                                label="Chiến lược", choices=["hybrid", "article", "chapter", "clause"],
                                value="hybrid",
                            )
                            build_clear = gr.Checkbox(label="Xóa graph cũ", value=False)
                            build_semantic = gr.Checkbox(label="Bật LLM semantic (tốn token)", value=False)
                            build_max_sem = gr.Number(label="Giới hạn semantic (0 = all)", value=0, precision=0)
                        build_btn = gr.Button("Build / Rebuild Graph", variant="primary")
                        build_out = gr.JSON(label="Kết quả build")

                        refresh_stats_btn = gr.Button("Refresh stats")
                        stats_html = gr.HTML()

                refresh_laws_btn.click(
                    fn=_gradio_list_laws,
                    outputs=[law_dropdown],
                )
                show_law_btn.click(
                    fn=_gradio_render_law,
                    inputs=[law_dropdown],
                    outputs=[law_graph_html],
                )
                show_nbrs_btn.click(
                    fn=_gradio_render_neighbors,
                    inputs=[node_type_dd, node_id_tb, depth_slider],
                    outputs=[nbrs_html],
                )
                run_cypher_btn.click(
                    fn=_gradio_run_cypher,
                    inputs=[cypher_tb],
                    outputs=[cypher_out],
                )
                build_btn.click(
                    fn=_gradio_build_graph,
                    inputs=[build_strategy, build_clear, build_semantic, build_max_sem],
                    outputs=[build_out],
                )
                refresh_stats_btn.click(
                    fn=_gradio_graph_stats,
                    outputs=[stats_html],
                )

            with gr.TabItem("🔍 So sánh Model"):
                gr.Markdown(
                    "## 🔍 So sánh Model\n"
                    "Hỏi cùng một câu, so sánh câu trả lời từ nhiều model (tối đa 4). "
                    "RAG Retrieval chỉ chạy **1 lần**, context dùng chung. "
                    "Bật **Judge** để model OpenRouter chấm điểm tự động."
                )

                with gr.Row():
                    with gr.Column(scale=3):
                        cmp_question = gr.Textbox(
                            label="📝 Câu hỏi pháp luật",
                            placeholder="Nhập câu hỏi để so sánh...",
                            lines=3,
                            elem_id="cmp_question",
                        )
                    with gr.Column(scale=1):
                        cmp_ask_btn = gr.Button(
                            "⚡ Trả lời & So sánh",
                            variant="primary",
                            elem_classes="primary-btn",
                            elem_id="cmp_ask_btn",
                        )

                # ── Model selection ──
                with gr.Accordion("🤖 Chọn Model", open=True):
                    with gr.Row():
                        cmp_include_base = gr.Checkbox(
                            value=True,
                            label=f"📦 Bao gồm {BASE_MODEL_LABEL}",
                            elem_id="cmp_include_base",
                        )
                        cmp_include_custom = gr.Checkbox(
                            value=True,
                            label=f"✅ Bao gồm {CUSTOM_MODEL_LABEL}",
                            elem_id="cmp_include_custom",
                        )
                        cmp_include_gemini = gr.Checkbox(
                            value=True,
                            label=f"🔹 Bao gồm {GEMINI_MODEL_LABEL}",
                            elem_id="cmp_include_gemini",
                        )
                    with gr.Row():
                        cmp_base_api_url = gr.Textbox(
                            label="URL API (Base Pretrained)",
                            value="https://game-powerful-kit.ngrok-free.app",
                            placeholder="https://...",
                            scale=3,
                            elem_id="cmp_base_api_url",
                        )
                        cmp_base_model_name = gr.Textbox(
                            label="Tên Model (Base Pretrained)",
                            value="unsloth/Qwen3.5-35B-A3B-GGUF",
                            scale=2,
                            elem_id="cmp_base_model_name",
                        )
                    with gr.Row():
                        cmp_custom_api_url = gr.Textbox(
                            label="URL API (Custom)",
                            value="https://nonrequirable-sherril-undescriptively.ngrok-free.dev/v1/chat/completions",
                            placeholder="https://...",
                            scale=3,
                            elem_id="cmp_custom_api_url",
                        )
                        cmp_custom_model_name = gr.Textbox(
                            label="Tên Model (Custom)",
                            value="claspi2509/legal-AI-qwen3.5-q8-gguf",
                            scale=2,
                            elem_id="cmp_custom_model_name",
                        )

                    gr.Markdown("---\n**Thêm model từ OpenRouter:**")
                    with gr.Row():
                        cmp_load_models_btn = gr.Button(
                            "🔄 Tải danh sách OpenRouter", size="sm", variant="secondary",
                            elem_id="cmp_load_btn",
                        )
                        cmp_load_status = gr.Markdown(value="*Nhấn để tải model list...*")

                    cmp_model_dropdown = gr.Dropdown(
                        choices=[], multiselect=True, max_choices=3,
                        label="Chọn model OpenRouter (tối đa 3, cộng Custom = 4)",
                        value=[], allow_custom_value=True, filterable=True,
                        elem_id="cmp_model_dropdown",
                    )
                    cmp_selected_json = gr.State(value="[]")

                # ── Shared Settings ──
                with gr.Accordion("⚙️ Cài đặt chung", open=False):
                    with gr.Row():
                        cmp_use_rag = gr.Checkbox(
                            value=True,
                            label="📚 Dùng RAG (Fusion Vector + Graph)",
                            elem_id="cmp_use_rag",
                        )
                        cmp_use_graph = gr.Checkbox(
                            value=config.ENABLE_GRAPH_RETRIEVAL,
                            label="🕸️ Kích hoạt Knowledge Graph",
                            elem_id="cmp_use_graph",
                        )
                        cmp_top_k = gr.Slider(
                            minimum=1, maximum=15, value=5, step=1,
                            label="Top-K Retrieval", elem_id="cmp_top_k",
                        )
                    with gr.Row():
                        cmp_temperature = gr.Slider(
                            minimum=0.0, maximum=1.5, value=0.7, step=0.05,
                            label="Temperature", elem_id="cmp_temperature",
                        )
                        cmp_max_tokens = gr.Slider(
                            minimum=64, maximum=8192, value=1024, step=64,
                            label="Max Tokens", elem_id="cmp_max_tokens",
                        )
                        cmp_top_p = gr.Slider(
                            minimum=0.0, maximum=1.0, value=0.95, step=0.05,
                            label="Top-P", elem_id="cmp_top_p",
                        )
                    with gr.Row():
                        cmp_freq_penalty = gr.Slider(
                            minimum=-2.0, maximum=2.0, value=0.0, step=0.1,
                            label="Frequency Penalty", elem_id="cmp_freq_pen",
                        )
                        cmp_pres_penalty = gr.Slider(
                            minimum=-2.0, maximum=2.0, value=0.0, step=0.1,
                            label="Presence Penalty", elem_id="cmp_pres_pen",
                        )
                        cmp_enable_thinking = gr.Checkbox(
                            value=False,
                            label="🧠 Bật Reasoning (Custom model)",
                            elem_id="cmp_thinking",
                        )
                        cmp_gemini_thinking = gr.Checkbox(
                            value=False,
                            label="🧠 Bật Reasoning (Gemini model)",
                            elem_id="cmp_gemini_thinking",
                        )

                # ── Judge Section ──
                with gr.Accordion("⚖️ Chấm điểm tự động (Judge Model)", open=False):
                    gr.Markdown(
                        "Sau khi các model trả lời xong, một model OpenRouter sẽ đọc tất cả "
                        "câu trả lời và chấm điểm 1–10 dựa trên độ chính xác pháp lý."
                    )
                    with gr.Row():
                        cmp_judge_enable = gr.Checkbox(
                            value=False,
                            label="✅ Bật chấm điểm tự động",
                            elem_id="cmp_judge_enable",
                        )
                        cmp_judge_model = gr.Dropdown(
                            choices=[(GEMINI_JUDGE_LABEL, GEMINI_JUDGE_ID)],
                            value=GEMINI_JUDGE_ID,
                            label="Model chấm điểm (Gemini mặc định, hoặc chọn từ OpenRouter)",
                            allow_custom_value=True, filterable=True,
                            elem_id="cmp_judge_model",
                            scale=3,
                        )

                # ── Output Grid ──
                gr.Markdown("### 📊 Kết quả So sánh")
                with gr.Row(equal_height=True):
                    cmp_out_1 = gr.HTML(elem_id="cmp_out_1")
                    cmp_out_2 = gr.HTML(elem_id="cmp_out_2")
                    cmp_out_3 = gr.HTML(elem_id="cmp_out_3")
                    cmp_out_4 = gr.HTML(elem_id="cmp_out_4")

                cmp_sources_out = gr.Markdown(label="📚 Nguồn tham khảo (chung)")

                # ── Judge Output ──
                cmp_judge_out = gr.HTML(elem_id="cmp_judge_out", visible=True)

                # ── Wire load models ──
                def _on_load_models():
                    choices, status = _refresh_openrouter_models()
                    # Gemini luôn ở đầu danh sách judge
                    gemini_choice = (GEMINI_JUDGE_LABEL, GEMINI_JUDGE_ID)
                    judge_choices = [gemini_choice] + choices
                    return gr.update(choices=choices), gr.update(choices=judge_choices, value=GEMINI_JUDGE_ID), status

                cmp_load_models_btn.click(
                    fn=_on_load_models,
                    outputs=[cmp_model_dropdown, cmp_judge_model, cmp_load_status],
                )

                def _update_selected_json(selected_values):
                    return json.dumps(selected_values if selected_values else [])

                cmp_model_dropdown.change(
                    fn=_update_selected_json,
                    inputs=[cmp_model_dropdown],
                    outputs=[cmp_selected_json],
                )

                # ── Common inputs ──
                cmp_common_inputs = [
                    cmp_question, cmp_selected_json,
                    cmp_include_base,
                    cmp_include_custom,
                    cmp_include_gemini,
                    cmp_base_api_url,
                    cmp_base_model_name,
                    cmp_custom_api_url,
                    cmp_custom_model_name,
                    cmp_use_rag, cmp_top_k, cmp_use_graph,
                    cmp_temperature, cmp_max_tokens, cmp_top_p,
                    cmp_freq_penalty, cmp_pres_penalty, cmp_enable_thinking,
                    cmp_gemini_thinking,
                ]

                def _dispatch_run(
                    question, selected_models_json,
                    include_base, include_custom, include_gemini,
                    base_api_url, base_model_name,
                    custom_api_url, custom_model_name,
                    use_rag, top_k, use_graph,
                    temperature, max_tokens, top_p,
                    freq_penalty, pres_penalty, enable_thinking,
                    gemini_thinking,
                    judge_enable, judge_model_id,
                ):
                    """Route to judge_run or comparison_run depending on judge_enable."""
                    base_args = (
                        question, selected_models_json,
                        include_base, include_custom, include_gemini,
                        base_api_url, base_model_name,
                        custom_api_url, custom_model_name,
                        use_rag, top_k, use_graph,
                        temperature, max_tokens, top_p,
                        freq_penalty, pres_penalty, enable_thinking,
                        gemini_thinking,
                    )
                    if judge_enable and judge_model_id:
                        for p1, p2, p3, p4, src, jhtml in judge_run(
                            question, selected_models_json,
                            include_base, include_custom, include_gemini,
                            judge_model_id, use_rag, top_k, use_graph,
                            temperature, max_tokens, top_p,
                            freq_penalty, pres_penalty, enable_thinking,
                            base_api_url, base_model_name,
                            custom_api_url, custom_model_name,
                            gemini_thinking,
                        ):
                            yield p1, p2, p3, p4, src, jhtml
                    else:
                        for p1, p2, p3, p4, src in comparison_run(*base_args):
                            yield p1, p2, p3, p4, src, ""

                dispatch_inputs = cmp_common_inputs + [cmp_judge_enable, cmp_judge_model]
                dispatch_outputs = [cmp_out_1, cmp_out_2, cmp_out_3, cmp_out_4, cmp_sources_out, cmp_judge_out]

                cmp_ask_btn.click(
                    fn=_dispatch_run,
                    inputs=dispatch_inputs,
                    outputs=dispatch_outputs,
                )
                cmp_question.submit(
                    fn=_dispatch_run,
                    inputs=dispatch_inputs,
                    outputs=dispatch_outputs,
                )

                gr.Markdown("**Câu hỏi mẫu:**")
                with gr.Row():
                    for q in EXAMPLE_QUESTIONS[:3]:
                        short_label = q[:38] + "..." if len(q) > 38 else q
                        btn = gr.Button(short_label, size="sm", variant="secondary", elem_classes="secondary-btn")
                        btn.click(fn=lambda x=q: x, outputs=[cmp_question])

            with gr.TabItem("Hướng dẫn"):
                gr.Markdown(
                    "### Cách sử dụng\n\n"
                    "1. Vào tab **Quản lý tài liệu** -> nhấn **Index tài liệu** (vector)\n"
                    "2. (Tùy chọn) Chạy Neo4j bằng `docker-compose up -d neo4j` rồi vào tab **Knowledge Graph** -> **Cập nhật & Stats** -> nhấn **Build / Rebuild Graph**\n"
                    "3. Quay lại tab **Hỏi đáp** -> nhập câu hỏi -> tick **Dùng Knowledge Graph** -> nhấn **Hỏi**\n\n"
                    "### Chiến lược chunking\n\n"
                    "| Chiến lược | Mô tả |\n"
                    "|---|---|\n"
                    "| hybrid | Điều nhỏ giữ nguyên, Điều lớn tách theo Khoản (khuyên dùng) |\n"
                    "| article | Mỗi Điều là một chunk |\n"
                    "| chapter | Mỗi Chương là một chunk |\n"
                    "| clause | Mỗi Khoản là một chunk |\n\n"
                    "### REST API\n\n"
                    "| Method | Endpoint | Mô tả |\n"
                    "|---|---|---|\n"
                    "| GET | /api/health | Kiểm tra trạng thái |\n"
                    "| POST | /api/query | Hỏi đáp (vector) |\n"
                    "| POST | /api/query_hybrid | Hỏi đáp hybrid (vector + graph) |\n"
                    "| POST | /api/index | Index tài liệu vector |\n"
                    "| GET | /api/stats | Thống kê |\n"
                    "| GET | /api/documents | Danh sách tài liệu |\n"
                    "| DELETE | /api/collection | Xóa vector store |\n"
                    "| POST | /api/graph/build | Build knowledge graph |\n"
                    "| GET | /api/graph/stats | Thống kê graph |\n"
                    "| POST | /api/graph/cypher | Chạy Cypher read-only |\n"
                    "| GET | /api/graph/neighbors/{type}/{id} | Subgraph quanh 1 node |\n\n"
                    "Swagger UI: http://localhost:7860/docs\n"
                    "Neo4j: https://console.neo4j.io (Aura) hoặc http://localhost:7474 (Docker)"
                )

    return demo


def main():
    logger.info("Starting server...")
    start_background_loading()

    demo = create_ui()
    demo.queue()
    app = gr.mount_gradio_app(api, demo, path="/")

    logger.info(f"UI: http://localhost:{config.PORT}")
    logger.info(f"API docs: http://localhost:{config.PORT}/docs")

    uvicorn.run(app, host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
