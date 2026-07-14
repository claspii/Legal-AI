"""
RAG Engine: kết hợp truy xuất vector (ChromaDB) với graph (Neo4j) và sinh câu trả lời từ LLM.
Hỗ trợ Google Gemini, OpenAI, hoặc chế độ retrieval-only.
"""

from dataclasses import dataclass, field
import re
import json
from loguru import logger

from . import config
from .vector_store import VectorStore
from .document_processor import process_all_documents


def _create_gemini_client():
    from google import genai
    from google.genai.types import HttpOptions

    if config.GEMINI_USE_VERTEXAI:
        return genai.Client(http_options=HttpOptions(api_version="v1"))
    return genai.Client(
        api_key=config.GOOGLE_API_KEY,
        http_options=HttpOptions(api_version="v1"),
    )


@dataclass
class RAGResponse:
    answer: str
    sources: list[dict]
    query: str
    llm_provider: str
    retrieval_mode: str = "vector"
    fusion_info: dict = field(default_factory=dict)


def _build_context_vector_only(retrieved: list[dict]) -> str:
    if not retrieved:
        return "Không tìm thấy tài liệu liên quan."

    parts = []
    for i, r in enumerate(retrieved, 1):
        meta = r["metadata"]
        source = meta.get("source", "N/A")
        doc_num = meta.get("doc_number", "")
        chapter = meta.get("chapter_title", "")
        article = meta.get("article_num", "")
        clause = meta.get("clause_num", "")

        ref_parts = [f"Nguồn: {source}"]
        if doc_num:
            ref_parts.append(f"Số hiệu: {doc_num}")
        if chapter:
            ref_parts.append(f"{chapter}")
        if article:
            ref_parts.append(f"Điều {article}")
        if clause:
            ref_parts.append(f"Khoản {clause}")

        ref_line = " | ".join(ref_parts)
        parts.append(
            f"--- Tài liệu {i} (Độ liên quan: {r['similarity']:.0%}) ---\n"
            f"{ref_line}\n\n"
            f"{r['content']}\n"
        )

    return "\n".join(parts)


def _get_effective_gemini_model(model_name: str) -> str:
    if not model_name:
        return "gemini-2.5-flash"
    
    # Map preview/newer models to stable/supported ones on Vertex AI
    if config.GEMINI_USE_VERTEXAI:
        if "gemini-3.5-flash" in model_name:
            return "gemini-2.5-flash"
        if "gemini-2.5-flash" in model_name:
            return "gemini-2.5-flash"
        if "gemini-2.5-pro" in model_name:
            return "gemini-2.5-pro"
        if "gemini-2.0-flash" in model_name:
            # Fallback for 2.0-flash which isn't on user's Vertex AI region/project
            return "gemini-2.5-flash"
            
    # Clean up preview models for standard API as well for better stability
    if "gemini-3.5-flash" in model_name:
        return "gemini-2.5-flash"
    if model_name == "gemini-2.5-flash-preview-05-20":
        return "gemini-2.5-flash"
    if model_name == "gemini-2.5-pro-preview-06-05":
        return "gemini-2.5-pro"
        
    return model_name


def _call_llm_raw(prompt: str, provider: str, custom_kwargs: dict = None) -> str:
    from . import config
    provider = provider or config.LLM_PROVIDER
    custom_kwargs = custom_kwargs or {}
    
    if provider == "custom_trained":
        import requests
        import json
        url = custom_kwargs.get("api_url", "https://nonrequirable-sherril-undescriptively.ngrok-free.dev/v1/chat/completions")
        if not url.endswith("/chat/completions"):
            if url.endswith("/v1") or url.endswith("/v1/"):
                url = url.rstrip("/") + "/chat/completions"
            elif "/v1/chat/completions" not in url:
                url = url.rstrip("/") + "/v1/chat/completions"
                
        headers = {"Content-Type": "application/json"}
        messages = [{"role": "user", "content": prompt}]
        data = {
            "model": custom_kwargs.get("model_name", "claspi2509/legal-AI-qwen3.5-q8-gguf"),
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 512,
        }
        try:
            res = requests.post(url, headers=headers, json=data, timeout=60)
            res.raise_for_status()
            return res.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"Error calling custom trained API in _call_llm_raw: {e}")
            raise
        
    elif provider == "gemini" and config.GEMINI_AVAILABLE:
        client = _create_gemini_client()
        model_id = _get_effective_gemini_model(custom_kwargs.get("gemini_model") or config.GEMINI_MODEL)
        try:
            response = client.models.generate_content(
                model=model_id,
                contents=prompt,
            )
            return response.text.strip()
        except Exception as e:
            logger.error(f"Error calling Gemini in _call_llm_raw: {e}")
            raise
        
    elif provider == "openai" and config.OPENAI_API_KEY:
        from openai import OpenAI
        client = OpenAI(api_key=config.OPENAI_API_KEY)
        try:
            response = client.chat.completions.create(
                model=config.OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=512,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Error calling OpenAI in _call_llm_raw: {e}")
            raise
        
    return ""


def _call_gemini(question: str, context: str, chat_history: list[dict] = None) -> str:
    from google.genai import types

    client = _create_gemini_client()

    if context is None:
        sys_prompt = "Bạn là trợ lý ảo pháp luật Việt Nam. Hãy trả lời câu hỏi trò chuyện thông thường này một cách lịch sự, thân thiện và tự nhiên. Hãy nhắc nhở nhẹ nhàng người dùng rằng bạn chuyên hỗ trợ về pháp lý nếu họ cần tra cứu luật."
        history_str = ""
        if chat_history:
            history_str = "\n".join([f"{'Người dùng' if m['role'] == 'user' else 'Trợ lý'}: {m['content']}" for m in chat_history])
            history_str = f"--- Lịch sử trò chuyện ---\n{history_str}\n\n"
        prompt = (
            f"{sys_prompt}\n\n"
            f"{history_str}"
            f"--- Câu hỏi mới ---\n{question}\n\n"
            f"--- Trả lời ---"
        )
    else:
        history_str = ""
        if chat_history:
            history_str = "\n".join([f"{'Người dùng' if m['role'] == 'user' else 'Trợ lý'}: {m['content']}" for m in chat_history])
            history_str = f"--- Lịch sử trò chuyện ---\n{history_str}\n\n"
        prompt = (
            f"{config.SYSTEM_PROMPT}\n\n"
            f"--- Tài liệu tham khảo ---\n{context}\n\n"
            f"{history_str}"
            f"--- Câu hỏi mới ---\n{question}\n\n"
            f"--- Trả lời ---"
        )

    model_id = _get_effective_gemini_model(config.GEMINI_MODEL)
    
    # Logging out to terminal
    logger.info(f"Calling Gemini Non-Stream Model: {model_id} | Vertex AI: {config.GEMINI_USE_VERTEXAI} | Location: {config.GOOGLE_CLOUD_LOCATION} | General Mode: {context is None}")

    max_retries = 2
    for attempt in range(1, max_retries + 2):
        try:
            response = client.models.generate_content(
                model=model_id,
                contents=prompt,
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(
                        include_thoughts=True,
                        thinking_budget=2048
                    ),
                ),
            )
            return response.text
        except Exception as e:
            from src.graph_extractor import _is_retryable_llm_error
            if attempt < max_retries + 1 and _is_retryable_llm_error(e):
                delay = 0.5 * attempt
                logger.warning(
                    f"Gemini non-stream generation gặp lỗi rate limit (attempt {attempt}/{max_retries + 1}): {e}. "
                    f"Retry sau {delay}s..."
                )
                import time
                time.sleep(delay)
                continue
            logger.error(f"Error calling Gemini in _call_gemini after all attempts: {e}")
            raise


def _call_openai(question: str, context: str, chat_history: list[dict] = None) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=config.OPENAI_API_KEY)

    sys_prompt = (
        "Bạn là trợ lý ảo pháp luật Việt Nam. Hãy trả lời câu hỏi trò chuyện thông thường này một cách lịch sự, thân thiện và tự nhiên. Hãy nhắc nhở nhẹ nhàng người dùng rằng bạn chuyên hỗ trợ về pháp lý nếu họ cần tra cứu luật."
        if context is None
        else config.SYSTEM_PROMPT
    )
    messages = [{"role": "system", "content": sys_prompt}]
    
    if chat_history:
        for msg in chat_history:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
            
    if context is None:
        user_content = question
    else:
        user_content = f"Tài liệu tham khảo:\n{context}\n\nCâu hỏi: {question}"
        
    messages.append({"role": "user", "content": user_content})

    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=messages,
        temperature=0.1,
        max_tokens=4096,
    )
    return response.choices[0].message.content


def _retrieval_only(retrieved: list[dict]) -> str:
    if not retrieved:
        return "Không tìm thấy tài liệu liên quan đến câu hỏi của bạn."

    parts = ["**Các đoạn tài liệu liên quan:**\n"]
    for i, r in enumerate(retrieved, 1):
        meta = r["metadata"]
        source = meta.get("source", "N/A")
        article = meta.get("article_num", "")
        clause = meta.get("clause_num", "")

        ref = source
        if article:
            ref += f" - Điều {article}"
        if clause:
            ref += f", Khoản {clause}"

        parts.append(
            f"**{i}. {ref}** (Độ liên quan: {r.get('similarity', 0):.0%})\n"
            f"{r['content'][:500]}{'...' if len(r['content']) > 500 else ''}\n"
        )

    parts.append(
        "\n*Chế độ retrieval-only — cấu hình API key LLM để có câu trả lời tổng hợp.*"
    )
    return "\n".join(parts)


def _call_custom_trained_api(question: str, context: str, kwargs: dict, chat_history: list[dict] = None) -> str:
    import requests
    
    url = kwargs.get("api_url", "https://nonrequirable-sherril-undescriptively.ngrok-free.dev/v1/chat/completions")
    if not url.endswith("/chat/completions"):
        if url.endswith("/v1") or url.endswith("/v1/"):
            url = url.rstrip("/") + "/chat/completions"
        elif "/v1/chat/completions" not in url:
            url = url.rstrip("/") + "/v1/chat/completions"
            
    headers = {
        "Content-Type": "application/json"
    }
    
    sys_prompt = (
        "Bạn là trợ lý ảo pháp luật Việt Nam. Hãy trả lời câu hỏi trò chuyện thông thường này một cách lịch sự, thân thiện và tự nhiên. Hãy nhắc nhở nhẹ nhàng người dùng rằng bạn chuyên hỗ trợ về pháp lý nếu họ cần tra cứu luật."
        if context is None
        else config.SYSTEM_PROMPT
    )
    messages = [{"role": "system", "content": sys_prompt}]
    
    if chat_history:
        for msg in chat_history:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
            
    if context is None:
        user_content = question
    else:
        user_content = f"Tài liệu tham khảo:\n{context}\n\nCâu hỏi: {question}"
        
    messages.append({"role": "user", "content": user_content})
    
    data = {
        "model": kwargs.get("model_name", "claspi2509/legal-AI-qwen3.5-q8-gguf"),
        "messages": messages,
        "temperature": float(kwargs.get("temperature", 0.7)),
        "max_tokens": int(kwargs.get("max_tokens", 1024)),
        "top_p": float(kwargs.get("top_p", 0.95)),
        "chat_template_kwargs": {
            "enable_thinking": bool(kwargs.get("enable_thinking", False))
        }
    }
    
    if "top_k" in kwargs and kwargs["top_k"] is not None:
        data["top_k"] = int(kwargs["top_k"])
    if "frequency_penalty" in kwargs and kwargs["frequency_penalty"] is not None:
        data["frequency_penalty"] = float(kwargs["frequency_penalty"])
    if "presence_penalty" in kwargs and kwargs["presence_penalty"] is not None:
        data["presence_penalty"] = float(kwargs["presence_penalty"])
        
    logger.info(f"Calling Custom Trained Model API at: {url} with enable_thinking={data['chat_template_kwargs']['enable_thinking']} | General Mode: {context is None}")
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=180)
        response.raise_for_status()
        res_json = response.json()
        return res_json["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Error calling custom trained API: {e}")
        raise RuntimeError(f"Lỗi API Custom Trained: {e}")


def _stream_gemini(question: str, context: str, kwargs: dict = None, chat_history: list[dict] = None):
    from google.genai import types
    client = _create_gemini_client()
    kwargs = kwargs or {}
    
    if context is None:
        sys_prompt = "Bạn là trợ lý ảo pháp luật Việt Nam. Hãy trả lời câu hỏi trò chuyện thông thường này một cách lịch sự, thân thiện và tự nhiên. Hãy nhắc nhở nhẹ nhàng người dùng rằng bạn chuyên hỗ trợ về pháp lý nếu họ cần tra cứu luật."
        history_str = ""
        if chat_history:
            history_str = "\n".join([f"{'Người dùng' if m['role'] == 'user' else 'Trợ lý'}: {m['content']}" for m in chat_history])
            history_str = f"--- Lịch sử trò chuyện ---\n{history_str}\n\n"
        prompt = (
            f"{sys_prompt}\n\n"
            f"{history_str}"
            f"--- Câu hỏi mới ---\n{question}\n\n"
            f"--- Trả lời ---"
        )
    else:
        history_str = ""
        if chat_history:
            history_str = "\n".join([f"{'Người dùng' if m['role'] == 'user' else 'Trợ lý'}: {m['content']}" for m in chat_history])
            history_str = f"--- Lịch sử trò chuyện ---\n{history_str}\n\n"
        prompt = (
            f"{config.SYSTEM_PROMPT}\n\n"
            f"--- Tài liệu tham khảo ---\n{context}\n\n"
            f"{history_str}"
            f"--- Câu hỏi mới ---\n{question}\n\n"
            f"--- Trả lời ---"
        )
    
    # thinking_budget: 0=off, -1=unlimited, 512/2048/8192=limited
    thinking_budget = kwargs.get("thinking_budget", 0)
    raw_gemini_model = kwargs.get("gemini_model") or config.GEMINI_MODEL
    gemini_model = _get_effective_gemini_model(raw_gemini_model)

    # Logging out to terminal
    logger.info(f"Calling Gemini Stream Model: {gemini_model} | Vertex AI: {config.GEMINI_USE_VERTEXAI} | Location: {config.GOOGLE_CLOUD_LOCATION} | Thinking Budget: {thinking_budget} | General Mode: {context is None}")

    gen_config_kwargs = {}
    if thinking_budget == 0:
        # Tắt hoàn toàn reasoning
        gen_config_kwargs["thinking_config"] = types.ThinkingConfig(
            include_thoughts=False,
            thinking_budget=0
        )
    else:
        budget = thinking_budget if thinking_budget > 0 else 2048
        gen_config_kwargs["thinking_config"] = types.ThinkingConfig(
            include_thoughts=True,
            thinking_budget=budget
        )
    
    max_retries = 2
    response_iter = None
    first_chunk = None
    for attempt in range(1, max_retries + 2):
        try:
            response = client.models.generate_content_stream(
                model=gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(**gen_config_kwargs),
            )
            response_iter = iter(response)
            first_chunk = next(response_iter)
            break
        except StopIteration:
            return
        except Exception as e:
            from src.graph_extractor import _is_retryable_llm_error
            if attempt < max_retries + 1 and _is_retryable_llm_error(e):
                delay = 0.5 * attempt
                logger.warning(
                    f"Gemini stream generation gặp lỗi rate limit (attempt {attempt}/{max_retries + 1}): {e}. "
                    f"Retry sau {delay}s..."
                )
                import time
                time.sleep(delay)
                continue
            logger.error(f"Error calling Gemini in _stream_gemini after all attempts: {e}")
            raise

    accumulated_text = ""
    thinking_text = ""
    
    if first_chunk.candidates:
        candidate = first_chunk.candidates[0]
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if getattr(part, "thought", False) and part.text:
                    thinking_text += part.text
                    yield f"<think>{thinking_text}"
                elif part.text:
                    accumulated_text += part.text
                    if thinking_text:
                        yield f"<think>{thinking_text}</think>{accumulated_text}"
                    else:
                        yield accumulated_text

    for chunk in response_iter:
        if not chunk.candidates:
            continue
        candidate = chunk.candidates[0]
        if not candidate.content or not candidate.content.parts:
            continue
        for part in candidate.content.parts:
            # Thought part — Gemini thinking tokens
            if getattr(part, "thought", False) and part.text:
                thinking_text += part.text
                # Emit partial <think> (chưa đóng tag)
                yield f"<think>{thinking_text}"
            elif part.text:
                # Answer part
                accumulated_text += part.text
                if thinking_text:
                    # Đóng </think> và thêm answer
                    yield f"<think>{thinking_text}</think>{accumulated_text}"
                else:
                    yield accumulated_text


def _stream_openai(question: str, context: str, chat_history: list[dict] = None):
    from openai import OpenAI
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    
    sys_prompt = (
        "Bạn là trợ lý ảo pháp luật Việt Nam. Hãy trả lời câu hỏi trò chuyện thông thường này một cách lịch sự, thân thiện và tự nhiên. Hãy nhắc nhở nhẹ nhàng người dùng rằng bạn chuyên hỗ trợ về pháp lý nếu họ cần tra cứu luật."
        if context is None
        else config.SYSTEM_PROMPT
    )
    messages = [{"role": "system", "content": sys_prompt}]
    
    if chat_history:
        for msg in chat_history:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
            
    if context is None:
        user_content = question
    else:
        user_content = f"Tài liệu tham khảo:\n{context}\n\nCâu hỏi: {question}"
        
    messages.append({"role": "user", "content": user_content})
    
    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=messages,
        temperature=0.1,
        max_tokens=4096,
        stream=True
    )
    
    accumulated_text = ""
    for chunk in response:
        content = chunk.choices[0].delta.content or ""
        if content:
            accumulated_text += content
            yield accumulated_text


def _stream_custom_trained_api(question: str, context: str, kwargs: dict, chat_history: list[dict] = None):
    import requests
    import json
    import os

    # Priority: kwargs from frontend → env var → raise error
    api_url = kwargs.get("api_url") or os.environ.get("CUSTOM_MODEL_URL", "").strip()

    if not api_url:
        raise RuntimeError(
            "Custom model API URL chưa được cấu hình.\n"
            "Vào ⚙️ Settings → nhập ngrok URL vào trường 'API URL (ngrok)', "
            "hoặc đặt biến môi trường CUSTOM_MODEL_URL."
        )

    # Normalise URL — append /v1/chat/completions if not already present
    url = api_url.rstrip("/")
    if not url.startswith("http://") and not url.startswith("https://"):
        raise RuntimeError(f"API URL không hợp lệ: '{url}'. URL phải bắt đầu bằng http:// hoặc https://")
    if "/v1/chat/completions" not in url:
        if url.endswith("/v1"):
            url = url + "/chat/completions"
        else:
            url = url + "/v1/chat/completions"
            
    headers = {
        "Content-Type": "application/json"
    }
    
    sys_prompt = (
        "Bạn là trợ lý ảo pháp luật Việt Nam. Hãy trả lời câu hỏi trò chuyện thông thường này một cách lịch sự, thân thiện và tự nhiên. Hãy nhắc nhở nhẹ nhàng người dùng rằng bạn chuyên hỗ trợ về pháp lý nếu họ cần tra cứu luật."
        if context is None
        else config.SYSTEM_PROMPT
    )
    messages = [{"role": "system", "content": sys_prompt}]
    
    if chat_history:
        for msg in chat_history:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
            
    if context is None:
        user_content = question
    else:
        user_content = f"Tài liệu tham khảo:\n{context}\n\nCâu hỏi: {question}"
        
    messages.append({"role": "user", "content": user_content})
    
    # thinking_budget: 0=off, >0=limited, -1=unlimited
    thinking_budget = kwargs.get("thinking_budget", 0)
    enable_thinking = thinking_budget != 0

    data = {
        "model": kwargs.get("model_name", "claspi2509/legal-AI-qwen3.5-q8-gguf"),
        "messages": messages,
        "temperature": float(kwargs.get("temperature", 0.7)),
        "max_tokens": int(kwargs.get("max_tokens", 1024)),
        "top_p": float(kwargs.get("top_p", 0.95)),
        "stream": True,
        "chat_template_kwargs": {
            "enable_thinking": enable_thinking
        }
    }

    
    if "top_k" in kwargs and kwargs["top_k"] is not None:
        data["top_k"] = int(kwargs["top_k"])
    if "frequency_penalty" in kwargs and kwargs["frequency_penalty"] is not None:
        data["frequency_penalty"] = float(kwargs["frequency_penalty"])
    if "presence_penalty" in kwargs and kwargs["presence_penalty"] is not None:
        data["presence_penalty"] = float(kwargs["presence_penalty"])
        
    logger.info(
        f"Streaming Custom Trained Model API from: {url} | "
        f"enable_thinking={enable_thinking} | thinking_budget={thinking_budget} | General Mode: {context is None}"
    )

    
    try:
        response = requests.post(url, headers=headers, json=data, stream=True, timeout=180)
        response.raise_for_status()

        # ── State (mirrors _stream_custom_raw in app.py / Gradio demo) ──
        accumulated_content = ""   # raw content chars (no <think> tags)
        thinking_acc = ""          # accumulated reasoning text
        answer_acc = ""            # accumulated answer text
        in_think_tag = False       # currently inside <think>...</think>
        think_buf = ""             # temporary buffer inside <think>

        for line in response.iter_lines():
            if not line:
                continue
            line_str = line.decode("utf-8").strip()
            if not line_str.startswith("data:"):
                continue
            payload = line_str[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
                delta = chunk["choices"][0]["delta"]

                # ── Case 1: server sends reasoning_content separately (vLLM) ──
                reasoning_chunk = delta.get("reasoning_content") or ""
                content_chunk   = delta.get("content") or ""

                if reasoning_chunk:
                    thinking_acc += reasoning_chunk
                    yield f"<think>{thinking_acc}"
                    continue

                # ── Case 2: llama.cpp — inline <think>...</think> in content ──
                if not content_chunk:
                    continue

                accumulated_content += content_chunk

                # ── Exact same while-loop as _stream_custom_raw (Gradio) ──
                while True:
                    if not in_think_tag:
                        if "<think>" in accumulated_content:
                            before, rest = accumulated_content.split("<think>", 1)
                            if before:
                                answer_acc += before
                            accumulated_content = rest
                            in_think_tag = True
                            think_buf = ""
                        else:
                            # No <think> tag — flush as answer
                            if accumulated_content:
                                answer_acc += accumulated_content
                                accumulated_content = ""
                                if thinking_acc:
                                    yield f"<think>{thinking_acc}</think>{answer_acc}"
                                else:
                                    yield answer_acc
                            break
                    else:  # inside <think>...</think>
                        if "</think>" in accumulated_content:
                            think_part, rest = accumulated_content.split("</think>", 1)
                            think_buf += think_part
                            thinking_acc += think_buf  # accumulate all thinking
                            think_buf = ""
                            accumulated_content = rest
                            in_think_tag = False
                            # Yield with </think> closed
                            yield f"<think>{thinking_acc}</think>{answer_acc}"
                        else:
                            # Still inside think — accumulate and stream incrementally
                            think_buf += accumulated_content
                            thinking_acc_partial = thinking_acc + think_buf
                            accumulated_content = ""
                            yield f"<think>{thinking_acc_partial}"
                            break

            except Exception as e:
                logger.debug(f"SSE parse error (skipping): {e}")
                pass

        # Flush any remaining buffered content
        if accumulated_content and not in_think_tag:
            answer_acc += accumulated_content
            if thinking_acc:
                yield f"<think>{thinking_acc}</think>{answer_acc}"
            else:
                yield answer_acc

    except Exception as e:
        logger.error(f"Error in streaming custom trained API: {e}")
        raise RuntimeError(f"Lỗi API Custom Trained: {e}")


def _rewrite_query(question: str, chat_history: list[dict], provider: str, custom_kwargs: dict) -> str:
    if not chat_history:
        return question

    # Format the chat history text
    history_lines = []
    for msg in chat_history:
        role_label = "Người dùng" if msg.get("role") == "user" else "Trợ lý"
        history_lines.append(f"{role_label}: {msg.get('content', '')}")
    history_text = "\n".join(history_lines)

    prompt = (
        "Bạn là một trợ lý AI chuyên nghiệp. Hãy đọc lịch sử trò chuyện và câu hỏi mới của người dùng.\n"
        "Nếu câu hỏi mới của người dùng có sử dụng các từ thay thế, đại từ, viết tắt hoặc có ngữ cảnh phụ thuộc vào các câu hỏi/trả lời trước đó trong lịch sử trò chuyện (ví dụ: \"nó là gì\", \"thủ tục như thế nào\", \"tại sao lại phạt\", \"đối tượng nào\", \"thế còn nam giới\", v.v.), hãy viết lại câu hỏi mới đó thành một câu hỏi độc lập, đầy đủ nghĩa, rõ ràng bằng tiếng Việt mà không cần tham chiếu đến lịch sử nữa.\n"
        "Nếu câu hỏi mới đã đầy đủ nghĩa và độc lập, hãy giữ nguyên câu hỏi ban đầu.\n\n"
        f"Lịch sử trò chuyện:\n{history_text}\n\n"
        f"Câu hỏi mới: {question}\n\n"
        "Hãy chỉ trả về câu hỏi đã viết lại (hoặc câu hỏi ban đầu nếu không cần viết lại), không thêm bất kỳ lời giải thích hay ký tự nào khác."
    )
    
    try:
        rewritten = _call_llm_raw(prompt, provider, custom_kwargs)
        if rewritten and rewritten.strip():
            logger.info(f"Original query: '{question}' -> Rewritten: '{rewritten.strip()}'")
            return rewritten.strip()
    except Exception as e:
        logger.error(f"Error during query rewriting: {e}. Falling back to original query.")
    
    return question


def _route_query(question: str, chat_history: list[dict], provider: str, custom_kwargs: dict) -> str:
    # We include history_text in routing to help classify contextual follow-ups as LEGAL/GENERAL
    history_text = ""
    if chat_history:
        history_lines = []
        for msg in chat_history:
            role_label = "Người dùng" if msg.get("role") == "user" else "Trợ lý"
            history_lines.append(f"{role_label}: {msg.get('content', '')}")
        history_text = "\n".join(history_lines)

    prompt = (
        "Bạn là một bộ định tuyến câu hỏi thông minh. Nhiệm vụ của bạn là xác định câu hỏi dưới đây của người dùng có liên quan đến pháp luật Việt Nam, các thủ tục hành chính tư pháp, quy định pháp lý, tranh chấp pháp luật hoặc cần tham chiếu đến văn bản pháp luật hay không.\n"
        "Hãy đọc câu hỏi và bối cảnh lịch sử trò chuyện (nếu có).\n\n"
        f"Lịch sử trò chuyện:\n{history_text}\n\n"
        f"Câu hỏi hiện tại: {question}\n\n"
        "Chỉ trả lời bằng một trong hai từ khóa sau:\n"
        "- \"LEGAL\" nếu câu hỏi liên quan đến pháp luật hoặc cần tra cứu luật.\n"
        "- \"GENERAL\" nếu câu hỏi là trò chuyện thông thường, chào hỏi xã giao, hoặc các chủ đề không liên quan đến pháp luật.\n\n"
        "Không giải thích gì thêm, chỉ trả về từ khóa \"LEGAL\" hoặc \"GENERAL\"."
    )
    
    try:
        routed = _call_llm_raw(prompt, provider, custom_kwargs).strip().upper()
        if "LEGAL" in routed:
            logger.info(f"Query routed as: LEGAL")
            return "LEGAL"
        elif "GENERAL" in routed:
            logger.info(f"Query routed as: GENERAL")
            return "GENERAL"
        else:
            logger.warning(f"Unexpected routing response: {routed}. Defaulting to LEGAL.")
    except Exception as e:
        logger.error(f"Error during query routing: {e}. Defaulting to LEGAL.")
        
    return "LEGAL"



class RAGEngine:
    def __init__(
        self,
        vector_store: VectorStore = None,
        enable_graph: bool = None,
    ):
        self.store = vector_store or VectorStore()
        self.enable_graph = (
            enable_graph if enable_graph is not None else config.ENABLE_GRAPH_RETRIEVAL
        )
        self.graph_retriever = None
        if self.enable_graph:
            self._try_init_graph()

    def _arabic_to_roman(self, n: int) -> str:
        val = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1]
        syb = ["M", "CM", "D", "CD", "C", "XC", "L", "XL", "X", "IX", "V", "IV", "I"]
        roman_num = ''
        i = 0
        while n > 0:
            for _ in range(n // val[i]):
                roman_num += syb[i]
                n -= val[i]
            i += 1
        return roman_num

    def _extract_exact_references(self, question: str, provider: str, custom_kwargs: dict) -> dict:
        """
        Sử dụng LLM trích xuất các thông tin dẫn chiếu cụ thể từ câu hỏi dựa trên các tài liệu hiện có trong hệ thống.
        """
        existing_docs = self.store.get_all_documents()
        if not existing_docs:
            return {}
            
        laws_list_str = ""
        for doc in existing_docs:
            from src.graph_extractor import _law_info_from_source
            info = _law_info_from_source(doc)
            title = info.get("title") or doc
            short_name = info.get("short_name") or doc
            laws_list_str += f"- Tên file: \"{doc}\", Tên hiển thị: \"{title}\", Tên viết tắt/tên thường gọi: \"{short_name}\"\n"
            
        prompt = f"""Bạn là một chuyên gia pháp luật Việt Nam. Hãy đọc câu hỏi của người dùng và trích xuất thông tin về điều luật hoặc khoản được nhắc tới.
Các bộ luật/tài liệu hiện có trong hệ thống:
{laws_list_str}

Câu hỏi người dùng: "{question}"

Hãy trả về một đối tượng JSON duy nhất có các trường sau:
- matched_law_source: Tên file chính xác của bộ luật khớp từ danh sách trên (ví dụ: "Hinhsu.txt" hoặc "Dansu.txt"). Nếu không khớp hoặc người dùng không nói cụ thể bộ luật/luật nào trong danh sách trên, hãy trả về null.
- articles: danh sách các số Điều được nhắc đến dưới dạng chuỗi (ví dụ: ["36"], ["105a"]). Nếu không nhắc đến điều cụ thể nào, trả về mảng rỗng [].
- clauses: danh sách các số Khoản được nhắc đến dưới dạng chuỗi (ví dụ: ["1", "2"]). Nếu không nhắc đến khoản cụ thể nào, trả về mảng rỗng [].
- chapter: số Chương được nhắc đến dưới dạng chuỗi nếu người dùng hỏi về cả Chương (ví dụ: "II" hoặc "2"). Nếu không hỏi về chương cụ thể nào, trả về null.
- is_multiple_or_chapter: true nếu người dùng hỏi về nhiều điều luật (từ 2 điều trở lên), hỏi về cả chương, hoặc có ý định hỏi toàn bộ/nhiều điều của chương đó. Ngược lại trả về false.

Chỉ trả về chuỗi JSON thô, không nằm trong block markdown (không dùng ```json), không giải thích gì thêm.

Ví dụ 1:
Câu hỏi: "nội dung của điều 36 bộ luật hình sự là gì"
Trả về: {{"matched_law_source": "Hinhsu.txt", "articles": ["36"], "clauses": [], "chapter": null, "is_multiple_or_chapter": false}}

Ví dụ 2:
Câu hỏi: "khoản 2 điều 105 bộ luật dân sự"
Trả về: {{"matched_law_source": "Dansu.txt", "articles": ["105"], "clauses": ["2"], "chapter": null, "is_multiple_or_chapter": false}}

Ví dụ 3:
Câu hỏi: "Chương II luật lao động gồm những điều nào"
Trả về: {{"matched_law_source": "Laodong.txt", "articles": [], "clauses": [], "chapter": "II", "is_multiple_or_chapter": true}}
"""

        max_retries = 2
        res_text = None
        for attempt in range(1, max_retries + 2):
            try:
                res_text = _call_llm_raw(prompt, provider, custom_kwargs)
                logger.info(f"LLM direct extraction response: '{res_text}'")
                break
            except Exception as e:
                from src.graph_extractor import _is_retryable_llm_error
                if attempt < max_retries + 1 and _is_retryable_llm_error(e):
                    delay = 0.5 * attempt
                    logger.warning(
                        f"LLM direct extraction gặp lỗi rate limit (attempt {attempt}/{max_retries + 1}): {e}. "
                        f"Retry sau {delay}s..."
                    )
                    import time
                    time.sleep(delay)
                    continue
                logger.error(f"Error during LLM direct reference extraction after all attempts: {e}")
                return {}

        try:
            cleaned = res_text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```[a-zA-Z0-9]*\n", "", cleaned)
                cleaned = re.sub(r"\n```$", "", cleaned)
            cleaned = cleaned.strip()
            
            data = json.loads(cleaned)
            return {
                "matched_law_source": data.get("matched_law_source"),
                "articles": [str(a).strip() for a in data.get("articles", []) if a],
                "clauses": [str(c).strip() for c in data.get("clauses", []) if c],
                "chapter": str(data.get("chapter")).strip() if data.get("chapter") else None,
                "is_multiple_or_chapter": bool(data.get("is_multiple_or_chapter", False))
            }
        except Exception as e:
            logger.error(f"Error during parsing direct reference extraction response: {e}")
            return {}

    def _retrieve_exact_chunks(
        self,
        matched_law_source: str,
        articles: list[str],
        clauses: list[str],
        chapter: str = None,
    ) -> list[dict]:
        """
        Truy xuất trực tiếp các chunks từ ChromaDB bằng metadata filter.
        """
        direct_hits = []
        
        # 1. Truy xuất theo Chương nếu có và không có danh sách Điều cụ thể
        if chapter and not articles:
            chapters_to_try = [str(chapter).strip()]
            if str(chapter).strip().isdigit():
                roman = self._arabic_to_roman(int(chapter))
                chapters_to_try.append(roman)
                
            for c in chapters_to_try:
                try:
                    res = self.store.collection.get(
                        where={"$and": [{"source": matched_law_source}, {"chapter_num": str(c)}]},
                        include=["documents", "metadatas"]
                    )
                    docs = res.get("documents", []) or []
                    metas = res.get("metadatas", []) or []
                    ids = res.get("ids", []) or []
                    
                    if docs:
                        for doc_id, doc_text, meta in zip(ids, docs, metas):
                            direct_hits.append({
                                "id": doc_id,
                                "content": doc_text,
                                "metadata": meta,
                                "similarity": 1.0,
                                "sources": ["direct"]
                            })
                        break
                except Exception as e:
                    logger.warning(f"Lỗi truy xuất theo chương {c}: {e}")
                    
        # 2. Truy xuất theo Điều
        for art in articles:
            try:
                res = self.store.collection.get(
                    where={"$and": [{"source": matched_law_source}, {"article_num": str(art)}]},
                    include=["documents", "metadatas"]
                )
                docs = res.get("documents", []) or []
                metas = res.get("metadatas", []) or []
                ids = res.get("ids", []) or []
                
                if not docs:
                    continue
                    
                art_hits = []
                for doc_id, doc_text, meta in zip(ids, docs, metas):
                    art_hits.append({
                        "id": doc_id,
                        "content": doc_text,
                        "metadata": meta,
                        "similarity": 1.0,
                        "sources": ["direct"]
                    })
                    
                if clauses:
                    clause_matched = []
                    for hit in art_hits:
                        hit_clause = str(hit["metadata"].get("clause_num") or "").strip()
                        if hit_clause in clauses:
                            clause_matched.append(hit)
                            
                    if clause_matched:
                        direct_hits.extend(clause_matched)
                    else:
                        fallback = [h for h in art_hits if not str(h["metadata"].get("clause_num") or "").strip()]
                        if fallback:
                            direct_hits.extend(fallback)
                        else:
                            direct_hits.extend(art_hits)
                else:
                    direct_hits.extend(art_hits)
            except Exception as e:
                logger.warning(f"Lỗi truy xuất theo điều {art}: {e}")
                
        def _get_sort_key(hit):
            meta = hit.get("metadata", {})
            art_str = str(meta.get("article_num") or "").strip()
            art_num = 999999
            if art_str:
                num_match = re.match(r"\d+", art_str)
                if num_match:
                    art_num = int(num_match.group(0))
            
            clause_str = str(meta.get("clause_num") or "").strip()
            clause_num = 999999
            if clause_str:
                num_match = re.match(r"\d+", clause_str)
                if num_match:
                    clause_num = int(num_match.group(0))
                    
            chunk_idx = int(meta.get("chunk_index") or 0)
            return (art_num, clause_num, chunk_idx)
            
        direct_hits.sort(key=_get_sort_key)
        return direct_hits

    def _try_init_graph(self):
        try:
            from .graph_retriever import GraphRetriever
            self.graph_retriever = GraphRetriever()
            logger.info("Graph retriever đã kết nối Neo4j")
        except Exception as e:
            logger.warning(f"Graph retriever không khởi tạo được: {e}. Tiếp tục chỉ dùng vector.")
            self.graph_retriever = None

    def add_to_graph(self, chunks: list, extract_semantic: bool = False):
        """Trích xuất và nạp cấu trúc, dẫn chiếu và ngữ nghĩa của các chunk vào Neo4j."""
        from src.graph_store import GraphStore
        from src.graph_extractor import (
            extract_structural,
            extract_references,
            extract_semantic_llm,
        )
        
        try:
            store = GraphStore()
        except Exception as e:
            logger.warning(f"Không thể khởi tạo GraphStore để nạp đồ thị: {e}")
            return

        try:
            store.init_schema()
            
            # Fetch existing laws in Neo4j to avoid redundant upserts
            with store.session() as s:
                records = s.run("MATCH (l:Law) RETURN l.source_file AS source_file").data()
            existing_sources = {r["source_file"] for r in records if r.get("source_file")}
            
            data = extract_structural(chunks)
            
            # Filter to only keep laws that are not already in Neo4j
            laws_to_upsert = [law for law in data["laws"] if law["source_file"] not in existing_sources]
            if not laws_to_upsert:
                logger.info("Tất cả các tài liệu đã tồn tại trong đồ thị tri thức Neo4j. Bỏ qua nạp cấu trúc.")
                return
                
            doc_nums_to_upsert = {law["doc_number"] for law in laws_to_upsert}
            
            # Filter structural entities
            chapters_to_upsert = [ch for ch in data["chapters"] if ch["law_number"] in doc_nums_to_upsert]
            articles_to_upsert = [art for art in data["articles"] if art["law_number"] in doc_nums_to_upsert]
            clauses_to_upsert = [cl for cl in data["clauses"] if cl["law_number"] in doc_nums_to_upsert]
            links_to_upsert = [link for link in data["chunk_links"] if link["law_number"] in doc_nums_to_upsert]
            
            logger.info(
                f"Nạp đồ thị cấu trúc cho {len(laws_to_upsert)} luật mới: "
                f"{len(chapters_to_upsert)} chapters, {len(articles_to_upsert)} articles, "
                f"{len(clauses_to_upsert)} clauses, {len(links_to_upsert)} links..."
            )
            
            # 1. Laws
            for law in laws_to_upsert:
                store.upsert_law(law["doc_number"], law["title"], law["source_file"])

            # 2. Chapters
            for ch in chapters_to_upsert:
                store.upsert_chapter(ch["law_number"], ch["num"], ch["title"])

            # 3. Articles
            for art in articles_to_upsert:
                store.upsert_article(
                    law_number=art["law_number"],
                    num=art["num"],
                    title=art["title"],
                    full_text=art["full_text"],
                    chapter_num=art.get("chapter_num") or None,
                )

            # 4. Clauses
            for cl in clauses_to_upsert:
                store.upsert_clause(
                    law_number=cl["law_number"],
                    article_num=cl["article_num"],
                    clause_num=cl["num"],
                    text=cl["text"],
                )

            # 5. Link chunks ↔ article/clause
            for link in links_to_upsert:
                store.link_chunk(
                    chunk_id=link["chunk_id"],
                    law_number=link["law_number"],
                    article_num=link["article_num"],
                    clause_num=link.get("clause_num"),
                )

            # 6. References
            logger.info("Quét trích xuất các quan hệ dẫn chiếu (REFERENCES)...")
            clauses_by_article = {}
            for cl in clauses_to_upsert:
                key = (cl["law_number"], cl["article_num"])
                clauses_by_article.setdefault(key, []).append(cl)

            for art in articles_to_upsert:
                src_clauses = clauses_by_article.get((art["law_number"], art["num"]), [])
                units = src_clauses or [{
                    "law_number": art["law_number"],
                    "article_num": art["num"],
                    "num": None,
                    "text": art["full_text"],
                }]
                for unit in units:
                    src_clause = unit.get("num")
                    refs = extract_references(unit["text"], art["law_number"])
                    for dst_art in refs["internal_articles"]:
                        if dst_art == art["num"] and not src_clause:
                            continue
                        store.add_reference(
                            src_law=art["law_number"],
                            src_article=art["num"],
                            src_clause=src_clause,
                            dst_law=art["law_number"],
                            dst_article=dst_art,
                            ref_type="internal",
                        )
                    for dst_art, dst_clause in refs.get("internal_clause_articles", []):
                        store.add_reference(
                            src_law=art["law_number"],
                            src_article=art["num"],
                            src_clause=src_clause,
                            dst_law=art["law_number"],
                            dst_article=dst_art,
                            dst_clause=dst_clause,
                            ref_type="internal_clause",
                        )
                    for dst_law, dst_art in refs["cross_law_articles"]:
                        if dst_law == art["law_number"]:
                            continue
                        store.add_reference(
                            src_law=art["law_number"],
                            src_article=art["num"],
                            src_clause=src_clause,
                            dst_law=dst_law,
                            dst_article=dst_art,
                            ref_type="cross_law",
                        )
                    for dst_law, dst_art, dst_clause in refs.get("cross_law_clause_articles", []):
                        if dst_law == art["law_number"]:
                            continue
                        store.add_reference(
                            src_law=art["law_number"],
                            src_article=art["num"],
                            src_clause=src_clause,
                            dst_law=dst_law,
                            dst_article=dst_art,
                            dst_clause=dst_clause,
                            ref_type="cross_law_clause",
                        )
                    for dst_law in refs["cross_laws"]:
                        if dst_law == art["law_number"]:
                            continue
                        store.add_cross_law_ref(
                            src_law=art["law_number"],
                            src_article=art["num"],
                            src_clause=src_clause,
                            dst_law_name=dst_law,
                        )

            # 7. Semantic (Gemini)
            if extract_semantic and config.GEMINI_AVAILABLE:
                logger.info("Bắt đầu trích xuất Semantic (Concept, Actor, Action) bằng Gemini...")
                for art in articles_to_upsert:
                    cls = clauses_by_article.get((art["law_number"], art["num"]), [])
                    units = cls or [{
                        "law_number": art["law_number"],
                        "article_num": art["num"],
                        "clause_num": None,
                        "text": art["full_text"],
                    }]
                    for u in units:
                        try:
                            sem = extract_semantic_llm(
                                law_number=u["law_number"],
                                article_num=u["article_num"],
                                clause_num=u.get("clause_num"),
                                article_text=u["text"],
                            )
                            store.add_semantic(
                                law_number=u["law_number"],
                                article_num=u["article_num"],
                                clause_num=u.get("clause_num"),
                                concepts_defined=sem["concepts_defined"],
                                actors=sem["actors"],
                                actions=sem["actions"],
                                actor_actions=sem["actor_actions"],
                                related_concepts=sem["related_concepts"],
                            )
                        except Exception as sem_err:
                            logger.warning(
                                f"Lỗi trích xuất semantic Điều {u['article_num']}: {sem_err}"
                            )
            
            logger.info("Đã cập nhật dữ liệu tài liệu vào Neo4j thành công")
        finally:
            store.close()

    def index_documents(self, docs_dir: str = None, strategy: str = "hybrid") -> dict:
        docs_dir = docs_dir or config.DOCS_DIR
        chunks = process_all_documents(docs_dir, strategy=strategy)
        if chunks:
            self.store.add_chunks(chunks)
            try:
                self.add_to_graph(chunks, extract_semantic=True)
            except Exception as e:
                logger.error(f"Failed to add indexed documents to Neo4j graph: {e}")
        return {
            "chunks_processed": len(chunks),
            "total_in_store": self.store.collection.count(),
            "strategy": strategy,
        }

    def query(
        self,
        question: str,
        top_k: int = None,
        provider: str = None,
        use_graph: bool = None,
        custom_kwargs: dict = None,
        chat_history: list[dict] = None,
    ) -> RAGResponse:
        provider = provider or config.LLM_PROVIDER
        use_graph = (
            use_graph if use_graph is not None
            else (self.enable_graph and self.graph_retriever is not None)
        )
        chat_history = chat_history or []

        # A. Query Rewriting (if history exists)
        processed_question = _rewrite_query(question, chat_history, provider, custom_kwargs)

        # B. Topic Routing
        route = _route_query(processed_question, chat_history, provider, custom_kwargs)

        if route == "GENERAL":
            context = None
            sources = []
            fusion_info = {
                "vector_count": 0,
                "graph_count": 0,
                "fused_count": 0,
                "mode": "none",
            }
            retrieval_mode = "none"
            
            try:
                if provider == "custom_trained":
                    kwargs = custom_kwargs or {}
                    answer = _call_custom_trained_api(processed_question, context, kwargs, chat_history)
                    used_provider = f"custom_trained ({kwargs.get('model_name', 'claspi2509/legal-AI-qwen3.5-q8-gguf')})"
                elif provider == "gemini" and config.GEMINI_AVAILABLE:
                    answer = _call_gemini(processed_question, context, chat_history)
                    used_provider = "gemini"
                elif provider == "openai" and config.OPENAI_API_KEY:
                    answer = _call_openai(processed_question, context, chat_history)
                    used_provider = "openai"
                else:
                    logger.warning(f"Không có API key cho '{provider}', dùng default message")
                    answer = "Chế độ RAG đã bị bỏ qua vì câu hỏi không liên quan đến pháp luật Việt Nam."
                    used_provider = "none"
            except Exception as e:
                logger.error(f"LLM error: {e}")
                answer = f"Lỗi LLM: {e}"
                used_provider = "error"
        else:
            # Direct extraction pipeline
            direct_hits = []
            has_more_clarification = False
            
            try:
                extracted = self._extract_exact_references(processed_question, provider, custom_kwargs)
                matched_law = extracted.get("matched_law_source")
                
                if matched_law and (extracted.get("articles") or extracted.get("chapter")):
                    raw_direct = self._retrieve_exact_chunks(
                        matched_law_source=matched_law,
                        articles=extracted.get("articles", []),
                        clauses=extracted.get("clauses", []),
                        chapter=extracted.get("chapter")
                    )
                    
                    if raw_direct:
                        for h in raw_direct:
                            h["is_direct"] = True
                            
                        if extracted.get("is_multiple_or_chapter") and len(raw_direct) > 5:
                            direct_hits = raw_direct[:5]
                            has_more_clarification = True
                        else:
                            direct_hits = raw_direct
                            
                        logger.info(f"Direct retrieval success: found {len(direct_hits)} direct chunks (limit was applied: {has_more_clarification})")
            except Exception as e:
                logger.error(f"Error in direct extraction retrieval pipeline: {e}")

            # 1. Vector retrieval
            vector_hits = self.store.query(processed_question, top_k=top_k)
            
            # Deduplicate vector hits if we have direct hits
            if direct_hits:
                direct_ids = {h["id"] for h in direct_hits if "id" in h}
                direct_contents = {h["content"].strip() for h in direct_hits}
                
                filtered_vector_hits = []
                for h in vector_hits:
                    hid = h.get("id")
                    hcontent = h.get("content", "").strip()
                    chunk_id = h.get("metadata", {}).get("chunk_id")
                    if hid in direct_ids or chunk_id in direct_ids or hcontent in direct_contents:
                        continue
                    filtered_vector_hits.append(h)
                vector_hits = filtered_vector_hits

            # 2. Graph retrieval (nếu bật)
            fused = None
            graph_hits = []
            retrieval_mode = "vector"

            if use_graph and self.graph_retriever is not None:
                try:
                    graph_hits = self.graph_retriever.retrieve(
                        question=processed_question,
                        vector_hits=vector_hits + direct_hits,
                    )
                    from .hybrid_fusion import fuse, build_context
                    fused = fuse(vector_hits, graph_hits, top_n=(top_k or config.TOP_K) + 3)
                    
                    # Prepend direct hits to fused list!
                    if direct_hits:
                        direct_fused = []
                        for hit in direct_hits:
                            meta = hit["metadata"]
                            law = meta.get("law_number") or ""
                            art = meta.get("article_num") or ""
                            clause = meta.get("clause_num") or ""
                            if law and art and clause:
                                k = ("clause", law, art, clause)
                            elif law and art:
                                k = ("art", law, art, "")
                            else:
                                k = ("chunk", hit.get("id") or str(id(hit)))
                                
                            direct_fused.append({
                                "key": k,
                                "content": hit["content"],
                                "metadata": meta,
                                "rrf_score": 9999.0, # High score
                                "sources": ["direct"],
                                "vector_rank": 1,
                                "graph_rank": None,
                                "graph_relation": None,
                                "is_direct": True
                            })
                        direct_keys = {df["key"] for df in direct_fused}
                        fused = direct_fused + [f for f in fused if f["key"] not in direct_keys]
                        
                    context = build_context(fused, max_chars=8000)
                    retrieval_mode = "hybrid"
                except Exception as e:
                    logger.warning(f"Graph retrieval/fusion lỗi: {e}. Fallback vector-only.")
                    vector_hits = direct_hits + vector_hits
                    context = _build_context_vector_only(vector_hits)
            else:
                vector_hits = direct_hits + vector_hits
                context = _build_context_vector_only(vector_hits)

            # Xây sources trả về cho UI/API
            sources = self._build_sources(vector_hits, fused, graph_hits)
            
            # Append clarification instruction to context
            if has_more_clarification:
                context += "\n\nLưu ý quan trọng: Hệ thống chỉ hiển thị tối đa 5 điều luật đầu tiên. Hãy giải thích ngắn gọn 5 điều luật này. Cuối câu trả lời, hãy hỏi người dùng xem họ có muốn xem thêm các điều luật khác không."

            # 3. Gọi LLM
            try:
                if provider == "custom_trained":
                    kwargs = custom_kwargs or {}
                    answer = _call_custom_trained_api(processed_question, context, kwargs, chat_history)
                    used_provider = f"custom_trained ({kwargs.get('model_name', 'claspi2509/legal-AI-qwen3.5-q8-gguf')})"
                elif provider == "gemini" and config.GEMINI_AVAILABLE:
                    answer = _call_gemini(processed_question, context, chat_history)
                    used_provider = "gemini"
                elif provider == "openai" and config.OPENAI_API_KEY:
                    answer = _call_openai(processed_question, context, chat_history)
                    used_provider = "openai"
                else:
                    logger.warning(f"Không có API key cho '{provider}', dùng retrieval-only")
                    answer = _retrieval_only(vector_hits)
                    used_provider = "retrieval-only"
            except Exception as e:
                logger.error(f"LLM error: {e}")
                answer = _retrieval_only(vector_hits) + f"\n\nLỗi LLM: {e}"
                used_provider = "retrieval-only (error)"

            fusion_info = {
                "vector_count": len(vector_hits),
                "graph_count": len(graph_hits),
                "fused_count": len(fused) if fused else 0,
                "mode": retrieval_mode,
            }

        return RAGResponse(
            answer=answer,
            sources=sources,
            query=processed_question,
            llm_provider=used_provider,
            retrieval_mode=retrieval_mode,
            fusion_info=fusion_info,
        )

    def query_stream(
        self,
        question: str,
        top_k: int = None,
        provider: str = None,
        use_graph: bool = None,
        custom_kwargs: dict = None,
        chat_history: list[dict] = None,
    ):
        provider = provider or config.LLM_PROVIDER
        use_graph = (
            use_graph if use_graph is not None
            else (self.enable_graph and self.graph_retriever is not None)
        )
        chat_history = chat_history or []

        # A. Query Rewriting (if history exists)
        processed_question = _rewrite_query(question, chat_history, provider, custom_kwargs)

        # B. Topic Routing
        route = _route_query(processed_question, chat_history, provider, custom_kwargs)

        if route == "GENERAL":
            # GENERAL: Bypass RAG and return empty sources
            context = None
            sources_payload = {
                "items": [],
                "fusion": {
                    "vector_count": 0,
                    "graph_count": 0,
                    "fused_count": 0,
                    "mode": "none",
                }
            }
            try:
                if provider == "custom_trained":
                    kwargs = custom_kwargs or {}
                    for text in _stream_custom_trained_api(processed_question, context, kwargs, chat_history):
                        yield text, sources_payload
                elif provider == "gemini" and config.GEMINI_AVAILABLE:
                    for text in _stream_gemini(processed_question, context, kwargs=custom_kwargs, chat_history=chat_history):
                        yield text, sources_payload
                elif provider == "openai" and config.OPENAI_API_KEY:
                    for text in _stream_openai(processed_question, context, chat_history=chat_history):
                        yield text, sources_payload
                else:
                    logger.warning(f"Không có API key cho '{provider}', dùng default message")
                    yield "Chế độ RAG đã bị bỏ qua vì câu hỏi không liên quan đến pháp luật Việt Nam.", sources_payload
            except Exception as e:
                logger.error(f"LLM stream error: {e}")
                yield f"\n\nLỗi LLM: {e}", sources_payload

        else:
            # LEGAL: Execute RAG using processed_question
            # Direct extraction pipeline
            direct_hits = []
            has_more_clarification = False
            
            try:
                extracted = self._extract_exact_references(processed_question, provider, custom_kwargs)
                matched_law = extracted.get("matched_law_source")
                
                if matched_law and (extracted.get("articles") or extracted.get("chapter")):
                    raw_direct = self._retrieve_exact_chunks(
                        matched_law_source=matched_law,
                        articles=extracted.get("articles", []),
                        clauses=extracted.get("clauses", []),
                        chapter=extracted.get("chapter")
                    )
                    
                    if raw_direct:
                        for h in raw_direct:
                            h["is_direct"] = True
                            
                        if extracted.get("is_multiple_or_chapter") and len(raw_direct) > 5:
                            direct_hits = raw_direct[:5]
                            has_more_clarification = True
                        else:
                            direct_hits = raw_direct
                            
                        logger.info(f"Direct retrieval stream success: found {len(direct_hits)} direct chunks (limit was applied: {has_more_clarification})")
            except Exception as e:
                logger.error(f"Error in direct extraction retrieval pipeline (stream): {e}")

            # 1. Vector retrieval
            vector_hits = self.store.query(processed_question, top_k=top_k)
            
            # Deduplicate vector hits if we have direct hits
            if direct_hits:
                direct_ids = {h["id"] for h in direct_hits if "id" in h}
                direct_contents = {h["content"].strip() for h in direct_hits}
                
                filtered_vector_hits = []
                for h in vector_hits:
                    hid = h.get("id")
                    hcontent = h.get("content", "").strip()
                    chunk_id = h.get("metadata", {}).get("chunk_id")
                    if hid in direct_ids or chunk_id in direct_ids or hcontent in direct_contents:
                        continue
                    filtered_vector_hits.append(h)
                vector_hits = filtered_vector_hits

            # 2. Graph retrieval
            fused = None
            graph_hits = []
            retrieval_mode = "vector"

            if use_graph and self.graph_retriever is not None:
                try:
                    graph_hits = self.graph_retriever.retrieve(
                        question=processed_question,
                        vector_hits=vector_hits + direct_hits,
                    )
                    from .hybrid_fusion import fuse, build_context
                    fused = fuse(vector_hits, graph_hits, top_n=(top_k or config.TOP_K) + 3)
                    
                    # Prepend direct hits to fused list!
                    if direct_hits:
                        direct_fused = []
                        for hit in direct_hits:
                            meta = hit["metadata"]
                            law = meta.get("law_number") or ""
                            art = meta.get("article_num") or ""
                            clause = meta.get("clause_num") or ""
                            if law and art and clause:
                                k = ("clause", law, art, clause)
                            elif law and art:
                                k = ("art", law, art, "")
                            else:
                                k = ("chunk", hit.get("id") or str(id(hit)))
                                
                            direct_fused.append({
                                "key": k,
                                "content": hit["content"],
                                "metadata": meta,
                                "rrf_score": 9999.0,
                                "sources": ["direct"],
                                "vector_rank": 1,
                                "graph_rank": None,
                                "graph_relation": None,
                                "is_direct": True
                            })
                        direct_keys = {df["key"] for df in direct_fused}
                        fused = direct_fused + [f for f in fused if f["key"] not in direct_keys]
                        
                    context = build_context(fused, max_chars=8000)
                    retrieval_mode = "hybrid"
                except Exception as e:
                    logger.warning(f"Graph retrieval/fusion lỗi: {e}. Fallback vector-only.")
                    vector_hits = direct_hits + vector_hits
                    context = _build_context_vector_only(vector_hits)
            else:
                vector_hits = direct_hits + vector_hits
                context = _build_context_vector_only(vector_hits)

            # Build sources payload for RAG
            sources = self._build_sources(vector_hits, fused, graph_hits)
            fusion_info = {
                "vector_count": len(vector_hits),
                "graph_count": len(graph_hits),
                "fused_count": len(fused) if fused else 0,
                "mode": retrieval_mode,
            }
            sources_payload = {
                "items": sources,
                "fusion": fusion_info,
            }
            
            # Append clarification instruction to context
            if has_more_clarification:
                context += "\n\nLưu ý quan trọng: Hệ thống chỉ hiển thị tối đa 5 điều luật đầu tiên. Hãy giải thích ngắn gọn 5 điều luật này. Cuối câu trả lời, hãy hỏi người dùng xem họ có muốn xem thêm các điều luật khác không."

            # 3. Stream Gọi LLM
            try:
                if provider == "custom_trained":
                    kwargs = custom_kwargs or {}
                    for text in _stream_custom_trained_api(processed_question, context, kwargs, chat_history):
                        yield text, sources_payload
                elif provider == "gemini" and config.GEMINI_AVAILABLE:
                    for text in _stream_gemini(processed_question, context, kwargs=custom_kwargs, chat_history=chat_history):
                        yield text, sources_payload
                elif provider == "openai" and config.OPENAI_API_KEY:
                    for text in _stream_openai(processed_question, context, chat_history=chat_history):
                        yield text, sources_payload
                else:
                    logger.warning(f"Không có API key cho '{provider}', dùng retrieval-only")
                    yield _retrieval_only(vector_hits), sources_payload
            except Exception as e:
                logger.error(f"LLM stream error: {e}")
                yield _retrieval_only(vector_hits) + f"\n\nLỗi LLM: {e}", sources_payload

    def _build_sources(self, vector_hits, fused, graph_hits) -> list[dict]:
        """Ưu tiên hiển thị sources đã fused; fallback sang vector hits.
        
        relevance_pct: điểm liên quan 0–100 đã chuẩn hóa, dùng để hiển thị UI.
        - vector hit: cosine similarity gốc × 100
        - fused item có vector_rank: lấy similarity từ vector hit tương ứng
        - graph-only item: normalize rank trong danh sách
        """
        if fused:
            # Build lookup: vector_rank → cosine similarity gốc
            vec_sim_by_rank = {}
            for rank, vhit in enumerate(vector_hits or [], start=1):
                vec_sim_by_rank[rank] = vhit.get("similarity", 0)

            # Normalize rrf_score nếu không có cosine sim
            all_rrf = [item.get("rrf_score", 0) for item in fused]
            max_rrf = max(all_rrf) if all_rrf else 1
            min_rrf = min(all_rrf) if all_rrf else 0
            rrf_range = max(max_rrf - min_rrf, 1e-9)

            out = []
            for item in fused:
                meta = item.get("metadata", {})
                full_content = item.get("content", "") or ""

                # Ưu tiên cosine similarity từ vector hit gốc (chính xác nhất)
                v_rank = item.get("vector_rank")
                if item.get("is_direct"):
                    relevance_pct = 100
                elif v_rank is not None and v_rank in vec_sim_by_rank:
                    raw_sim = vec_sim_by_rank[v_rank]
                    relevance_pct = round(raw_sim * 100)
                else:
                    # Graph-only: không có cosine similarity thật → không hiển thị %
                    relevance_pct = None

                out.append({
                    "source": meta.get("source", ""),
                    "doc_number": meta.get("law_number") or meta.get("doc_number", ""),
                    "chapter": meta.get("chapter_title", ""),
                    "article": meta.get("article_num", ""),
                    "clause": meta.get("clause_num", ""),
                    "relevance_pct": relevance_pct,
                    "content": full_content,
                    "preview": full_content[:200],
                    "retrieval_sources": item.get("sources", []),
                    "graph_relation": item.get("graph_relation"),
                })
            return out

        return [
            {
                "source": r["metadata"].get("source", ""),
                "doc_number": r["metadata"].get("doc_number", ""),
                "chapter": r["metadata"].get("chapter_title", ""),
                "article": r["metadata"].get("article_num", ""),
                "clause": r["metadata"].get("clause_num", ""),
                "relevance_pct": round(r.get("similarity", 0) * 100),
                "content": r["content"],
                "preview": r["content"][:200],
                "retrieval_sources": r.get("sources", ["vector"]),
            }
            for r in vector_hits
        ]


    def get_stats(self) -> dict:
        stats = self.store.get_stats()
        stats["graph_enabled"] = bool(self.graph_retriever is not None)
        return stats
