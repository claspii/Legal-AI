"""
OpenRouter API client — sử dụng thư viện openai với base_url OpenRouter.
- Lấy danh sách model từ https://openrouter.ai/api/v1/models
- Stream chat completions với hỗ trợ reasoning
"""

import os
import requests
from loguru import logger
from openai import OpenAI


OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def get_openrouter_key() -> str:
    """Trả về OPENROUTER_API_KEY từ env."""
    return os.getenv("OPENROUTER_API_KEY", "")


def _make_client() -> OpenAI:
    """Tạo OpenAI client trỏ tới OpenRouter."""
    key = get_openrouter_key()
    if not key or key == "your_openrouter_api_key_here":
        raise RuntimeError("OPENROUTER_API_KEY chưa được cấu hình trong file .env")
    return OpenAI(
        api_key=key,
        base_url=OPENROUTER_BASE,
        default_headers={
            "HTTP-Referer": "https://legal-ai-vn.local",
            "X-Title": "Legal AI Vietnam",
        },
    )


def fetch_openrouter_models() -> list[dict]:
    """
    Lấy danh sách model từ OpenRouter, sort :free lên đầu.
    Trả về list dict: {id, name, is_free, context_length, description}
    """
    key = get_openrouter_key()
    headers = {"Content-Type": "application/json"}
    if key and key != "your_openrouter_api_key_here":
        headers["Authorization"] = f"Bearer {key}"

    try:
        resp = requests.get(f"{OPENROUTER_BASE}/models", headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json().get("data", [])
    except Exception as e:
        logger.error(f"Không thể lấy danh sách model OpenRouter: {e}")
        return []

    models = []
    for m in data:
        mid = m.get("id", "")
        is_free = mid.endswith(":free")
        models.append({
            "id": mid,
            "name": m.get("name", mid),
            "is_free": is_free,
            "context_length": m.get("context_length", 0),
            "description": m.get("description", ""),
        })

    # Sắp xếp: model free lên đầu, sau đó theo alphabet
    models.sort(key=lambda x: (0 if x["is_free"] else 1, x["id"].lower()))
    return models


def stream_openrouter(
    model_id: str,
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 1024,
    top_p: float = 0.95,
    frequency_penalty: float = 0.0,
    presence_penalty: float = 0.0,
):
    """
    Stream chat completion từ OpenRouter dùng thư viện openai.
    Yield tuple (reasoning_delta, content_delta) từng bước.
    reasoning_delta lấy từ delta.reasoning (hoặc delta.reasoning_content).
    """
    client = _make_client()

    logger.info(f"Streaming OpenRouter model: {model_id}")

    stream = client.chat.completions.create(
        model=model_id,
        messages=messages,
        stream=True,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
    )

    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta

        # Reasoning field (supported by some models on OpenRouter)
        reasoning = (
            getattr(delta, "reasoning", None)
            or getattr(delta, "reasoning_content", None)
            or ""
        )
        content = delta.content or ""

        if reasoning or content:
            yield reasoning, content
