"""
Trích xuất nodes + edges cho knowledge graph từ các chunk văn bản luật.

Có 3 tầng:
  - Structural: dựa trên metadata chunk (Law / Chapter / Article / Clause)
  - References: regex tìm dẫn chiếu "Điều X", "khoản Y Điều X", "Bộ luật dân sự"...
  - Semantic: gọi LLM extract concepts / actors / actions (có cache file)
"""

import json
import re
import hashlib
import time
import random
from pathlib import Path
from loguru import logger

from . import config
from .document_processor import DocumentChunk


def _create_gemini_client(use_api_key_fallback: bool = False):
    from google import genai
    from google.genai.types import HttpOptions

    # Nếu force fallback sang API key (khi Vertex AI bị lỗi billing)
    if use_api_key_fallback and config.GOOGLE_API_KEY:
        return genai.Client(
            api_key=config.GOOGLE_API_KEY,
            http_options=HttpOptions(api_version="v1"),
        )

    if config.GEMINI_USE_VERTEXAI:
        return genai.Client(http_options=HttpOptions(api_version="v1"))
    return genai.Client(
        api_key=config.GOOGLE_API_KEY,
        http_options=HttpOptions(api_version="v1"),
    )


# Map từ tên file → mã luật + tiêu đề hiển thị
LAW_METADATA = {
    "Dansu": {
        "doc_number": "91/2015/QH13",
        "title": "Bộ luật Dân sự 2015",
        "short_name": "Bộ luật dân sự",
    },
    "Hinhsu": {
        "doc_number": "100/2015/QH13",
        "title": "Bộ luật Hình sự 2015",
        "short_name": "Bộ luật hình sự",
    },
    "Honnhan_giadinh": {
        "doc_number": "52/2014/QH13",
        "title": "Luật Hôn nhân và Gia đình 2014",
        "short_name": "Luật hôn nhân và gia đình",
    },
    "Laodong": {
        "doc_number": "45/2019/QH14",
        "title": "Bộ luật Lao động 2019",
        "short_name": "Bộ luật lao động",
    },
}


def _law_info_from_source(source: str) -> dict:
    """Tra bảng ở trên theo tên file (không kèm extension)."""
    stem = Path(source).stem
    return LAW_METADATA.get(stem, {
        "doc_number": stem,
        "title": stem,
        "short_name": stem.lower(),
    })


# ---------------------------------------------------------------------------
# 1. Structural extraction
# ---------------------------------------------------------------------------

def extract_structural(chunks: list[DocumentChunk]) -> dict:
    """
    Từ metadata các chunk, tạo ra:
      - laws: {doc_number: {title, source}}
      - chapters: [{law, num, title}]
      - articles: [{law, num, title, chapter_num, full_text}]
      - clauses: [{law, article_num, num, text}]
      - chunk_links: [{chunk_id, law, article_num, clause_num}]
    """
    laws: dict[str, dict] = {}
    chapters: dict[tuple, dict] = {}
    articles: dict[tuple, dict] = {}
    clauses: dict[tuple, dict] = {}
    chunk_links: list[dict] = []

    for ch in chunks:
        meta = ch.metadata
        source = meta.get("source", "")
        info = _law_info_from_source(source)
        law_num = info["doc_number"]

        if law_num not in laws:
            laws[law_num] = {
                "doc_number": law_num,
                "title": info["title"],
                "source_file": source,
            }

        chap_num = str(meta.get("chapter_num", "") or "").strip()
        chap_title = str(meta.get("chapter_title", "") or "").strip()
        if chap_num:
            key = (law_num, chap_num)
            if key not in chapters:
                chapters[key] = {
                    "law_number": law_num,
                    "num": chap_num,
                    "title": chap_title,
                }

        art_num = str(meta.get("article_num", "") or "").strip()
        if art_num:
            key = (law_num, art_num)
            if key not in articles:
                articles[key] = {
                    "law_number": law_num,
                    "num": art_num,
                    "title": str(meta.get("article_title", "") or "").strip(),
                    "chapter_num": chap_num,
                    "full_text": ch.content,
                }
            else:
                # Gom nhiều chunk cùng Điều (trường hợp hybrid_clause) lại
                existing = articles[key]["full_text"]
                if ch.content not in existing:
                    articles[key]["full_text"] = existing + "\n" + ch.content

        clause_num = str(meta.get("clause_num", "") or "").strip()
        if clause_num and art_num:
            key = (law_num, art_num, clause_num)
            if key not in clauses:
                clauses[key] = {
                    "law_number": law_num,
                    "article_num": art_num,
                    "num": clause_num,
                    "text": ch.content,
                }

        if art_num:
            chunk_links.append({
                "chunk_id": ch.id,
                "law_number": law_num,
                "article_num": art_num,
                "clause_num": clause_num or None,
            })

    logger.info(
        f"Structural: {len(laws)} laws, {len(chapters)} chapters, "
        f"{len(articles)} articles, {len(clauses)} clauses"
    )
    return {
        "laws": list(laws.values()),
        "chapters": list(chapters.values()),
        "articles": list(articles.values()),
        "clauses": list(clauses.values()),
        "chunk_links": chunk_links,
    }


# ---------------------------------------------------------------------------
# 2. References (regex)
# ---------------------------------------------------------------------------

# "Điều 123", "Điều 45a", "Điều 12 và Điều 13"
RE_ARTICLE_REF = re.compile(
    r"Điều\s+(\d+[a-z]?)",
    re.IGNORECASE,
)
# "khoản 2 Điều 45", "khoản 1, 2 Điều 45"
RE_CLAUSE_ARTICLE_REF = re.compile(
    r"khoản\s+([\d,\s và]+?)\s+Điều\s+(\d+[a-z]?)",
    re.IGNORECASE,
)
# "của Luật này" / "Bộ luật này" → cùng luật
RE_SAME_LAW = re.compile(r"(của|theo)\s+(luật|bộ\s+luật)\s+này", re.IGNORECASE)

# Các cụm tên luật phổ biến (map về doc_number đã biết)
CROSS_LAW_KEYWORDS = [
    (r"Bộ\s+luật\s+Dân\s+sự", "91/2015/QH13"),
    (r"Bộ\s+luật\s+Hình\s+sự", "100/2015/QH13"),
    (r"Luật\s+Hôn\s+nhân\s+và\s+Gia\s+đình", "52/2014/QH13"),
    (r"Bộ\s+luật\s+Lao\s+động", "45/2019/QH14"),
    (r"Luật\s+Tố\s+tụng", None),
    (r"Luật\s+Doanh\s+nghiệp", None),
    (r"Luật\s+Đất\s+đai", None),
]


def extract_references(article_text: str, self_law_number: str) -> dict:
    """
    Quét text của 1 Điều, trả về các dẫn chiếu.
    Quy ước:
      - "Điều X" hoặc "của Luật này" → cùng luật (self_law_number)
      - Có tên luật khác trong câu → dẫn chiếu sang luật đó
    Trả về:
      {
        "internal_articles": [art_num, ...],    # cùng luật
        "cross_law_articles": [(doc_number, art_num), ...],
        "cross_laws": [doc_number, ...],        # dẫn chiếu chung, không cụ thể Điều
      }
    """
    internal_articles: set[str] = set()
    internal_clause_articles: set[tuple[str, str]] = set()
    cross_law_articles: list[tuple[str, str]] = []
    cross_law_clause_articles: set[tuple[str, str, str]] = set()
    cross_laws: set[str] = set()

    # Tìm dẫn chiếu theo cụm có tên luật đi kèm
    # Cách đơn giản: với mỗi match luật khác, gom các Điều ở lân cận (±60 ký tự sau)
    for pattern, law_num in CROSS_LAW_KEYWORDS:
        for m in re.finditer(pattern, article_text, re.IGNORECASE):
            nearby = article_text[m.start(): m.end() + 80]
            found_arts = RE_ARTICLE_REF.findall(nearby)
            found_clause_refs = RE_CLAUSE_ARTICLE_REF.findall(nearby)
            if law_num:
                for clause_blob, art in found_clause_refs:
                    clause_nums = re.findall(r"\d+", clause_blob or "")
                    for cnum in clause_nums:
                        cross_law_clause_articles.add((law_num, art, cnum))
                if found_arts:
                    for a in found_arts:
                        cross_law_articles.append((law_num, a))
                else:
                    cross_laws.add(law_num)

    for clause_blob, art in RE_CLAUSE_ARTICLE_REF.findall(article_text):
        clause_nums = re.findall(r"\d+", clause_blob or "")
        for cnum in clause_nums:
            internal_clause_articles.add((art, cnum))

    # Tất cả "Điều X" khác (không nằm kề tên luật khác) coi như cùng luật
    # Loại trừ Điều nằm trong cross_law_articles
    cross_art_nums = {a for _, a in cross_law_articles}
    cross_clause_art_nums = {a for _, a, _ in cross_law_clause_articles}
    clause_art_nums = {a for a, _ in internal_clause_articles}
    for m in RE_ARTICLE_REF.finditer(article_text):
        art = m.group(1)
        if art not in cross_art_nums and art not in cross_clause_art_nums and art not in clause_art_nums:
            internal_articles.add(art)

    return {
        "internal_articles": sorted(internal_articles),
        "internal_clause_articles": sorted(internal_clause_articles),
        "cross_law_articles": list({t for t in cross_law_articles}),
        "cross_law_clause_articles": sorted(cross_law_clause_articles),
        "cross_laws": sorted(cross_laws),
    }


# ---------------------------------------------------------------------------
# 3. Semantic extraction (LLM)
# ---------------------------------------------------------------------------

SEMANTIC_PROMPT = """Bạn là chuyên gia pháp luật Việt Nam. Trích xuất các thực thể từ điều luật sau.

Điều luật:
{text}

Trả về JSON đúng schema:
- concepts_defined: danh sách thuật ngữ được ĐỊNH NGHĨA trong điều này (chỉ áp dụng nếu điều nói "X là..." hoặc "X được hiểu là..."). Nếu không có, trả về mảng rỗng.
- actors: danh sách chủ thể pháp lý xuất hiện (vd: "vợ", "chồng", "tòa án", "người lao động", "người sử dụng lao động", "cơ quan nhà nước"...).
- actions: danh sách hành vi pháp lý được quy định (vd: "kết hôn", "ly hôn", "giao kết hợp đồng", "bồi thường"...).
- actor_actions: các cặp (actor, action) trong đó actor thực hiện action theo văn bản.
- related_concepts: các cặp khái niệm pháp lý có quan hệ chặt trong điều này.

Chỉ trích từ văn bản, KHÔNG bịa. Dùng tiếng Việt viết thường. Tối đa 8 phần tử mỗi danh sách."""


SEMANTIC_SCHEMA = {
    "type": "object",
    "properties": {
        "concepts_defined": {"type": "array", "items": {"type": "string"}},
        "actors": {"type": "array", "items": {"type": "string"}},
        "actions": {"type": "array", "items": {"type": "string"}},
        "actor_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "actor": {"type": "string"},
                    "action": {"type": "string"},
                },
                "required": ["actor", "action"],
            },
        },
        "related_concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "a": {"type": "string"},
                    "b": {"type": "string"},
                },
                "required": ["a", "b"],
            },
        },
    },
    "required": [
        "concepts_defined", "actors", "actions",
        "actor_actions", "related_concepts",
    ],
}


def _cache_path(law_number: str, art_num: str, clause_num: str = None) -> Path:
    cache_dir = Path(config.LLM_CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe_law = law_number.replace("/", "_")
    if clause_num:
        return cache_dir / f"{safe_law}__art{art_num}__cl{clause_num}.json"
    return cache_dir / f"{safe_law}__art{art_num}.json"


def _empty_semantic() -> dict:
    return {
        "concepts_defined": [],
        "actors": [],
        "actions": [],
        "actor_actions": [],
        "related_concepts": [],
    }


def _is_retryable_llm_error(exc: Exception) -> bool:
    msg = str(exc).upper()
    retry_markers = [
        "429",
        "RESOURCE_EXHAUSTED",
        "RATE_LIMIT",
        "TOO MANY REQUESTS",
        "UNAVAILABLE",
        "TIMEOUT",
    ]
    return any(marker in msg for marker in retry_markers)


def _is_billing_error(exc: Exception) -> bool:
    """Trả True nếu lỗi là do billing/permission Vertex AI (nên fallback sang API key)."""
    msg = str(exc).upper()
    billing_markers = [
        "403",
        "PERMISSION_DENIED",
        "DUNNING",
        "BILLING",
        "FORBIDDEN",
        "CLOUD_BILLING",
    ]
    return any(marker in msg for marker in billing_markers)


def extract_semantic_llm(
    law_number: str,
    article_num: str,
    article_text: str,
    clause_num: str = None,
    use_cache: bool = True,
) -> dict:
    """Gọi Gemini structured output, có cache vào file JSON."""
    cache_file = _cache_path(law_number, article_num, clause_num)
    if use_cache and cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    if not article_text.strip():
        return _empty_semantic()

    # Cắt bớt để prompt không quá dài
    snippet = article_text[:4000]

    max_retries = 5
    base_delay = 1.5
    data = None
    for attempt in range(1, max_retries + 1):
        try:
            from google.genai import types

            client = _create_gemini_client()
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=SEMANTIC_PROMPT.format(text=snippet),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=SEMANTIC_SCHEMA,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            raw = response.text or "{}"
            data = json.loads(raw)
            break
        except Exception as e:
            if attempt < max_retries and _is_retryable_llm_error(e):
                delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0.0, 0.8)
                logger.warning(
                    "LLM semantic extract lỗi tạm thời "
                    f"(law={law_number}, art={article_num}, clause={clause_num or '-'}, attempt={attempt}/{max_retries}): {e}. "
                    f"Retry sau {delay:.1f}s..."
                )
                time.sleep(delay)
                continue

            logger.warning(
                f"LLM semantic extract thất bại (law={law_number}, art={article_num}, "
                f"clause={clause_num or '-'}, attempt={attempt}/{max_retries}): {e}"
            )
            return _empty_semantic()

    if data is None:
        return _empty_semantic()

    # Chuẩn hóa format
    result = {
        "concepts_defined": [str(x).strip() for x in data.get("concepts_defined", []) if x],
        "actors": [str(x).strip() for x in data.get("actors", []) if x],
        "actions": [str(x).strip() for x in data.get("actions", []) if x],
        "actor_actions": [
            (item["actor"].strip(), item["action"].strip())
            for item in data.get("actor_actions", [])
            if item.get("actor") and item.get("action")
        ],
        "related_concepts": [
            (item["a"].strip(), item["b"].strip())
            for item in data.get("related_concepts", [])
            if item.get("a") and item.get("b")
        ],
    }

    try:
        cache_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"Không ghi được cache {cache_file}: {e}")

    return result


def _regex_extract_entities(question: str) -> dict:
    """
    Fallback: trích entity bằng regex + keyword matching khi LLM không khả dụng.
    """
    # Lấy các khái niệm pháp lý phổ biến
    concept_kw = [
        "hợp đồng", "tài sản", "ly hôn", "kết hôn", "thừa kế", "bồi thường",
        "trách nhiệm", "nghĩa vụ", "quyền", "tội phạm", "hình phạt",
        "tù giam", "phạt tiền", "giải quyết tranh chấp", "khiếu nại",
        "hợp đồng lao động", "sa thải", "tiền lương", "bảo hiểm",
        "quyền sở hữu", "đất đai", "nhà ở",
    ]
    actor_kw = [
        "vợ", "chồng", "người lao động", "người sử dụng lao động",
        "tòa án", "cơ quan nhà nước", "bị cáo", "bị hại",
        "doanh nghiệp", "công ty", "cá nhân", "tổ chức",
        "người mua", "người bán", "người cho vay", "người vay",
    ]
    action_kw = [
        "ly hôn", "kết hôn", "giao kết", "bồi thường", "khiếu kiện",
        "tranh chấp", "xem xét", "cấm", "có quyền", "có nghĩa vụ",
        "bị xử lý", "xử phạt", "tạm giam", "khởi tố",
    ]
    q_lower = question.lower()
    concepts = [k for k in concept_kw if k in q_lower]
    actors = [k for k in actor_kw if k in q_lower]
    actions = [k for k in action_kw if k in q_lower]
    return {
        "concepts": concepts[:5],
        "actors": actors[:5],
        "actions": actions[:5],
    }


def extract_entities_from_query(question: str) -> dict:
    """
    Extract entities từ câu hỏi người dùng để graph retrieval.
    Chiến lược 3 tầng:
      1. Thử Vertex AI (nếu cấu hình)
      2. Fallback sang Google API Key nếu Vertex bị 403/billing error
      3. Fallback regex NLP nếu cả 2 LLM đều thất bại
    """
    if not question.strip():
        return {
            "concepts": [], "actors": [], "actions": [],
            "article_refs": [], "clause_article_refs": [],
        }

    # Lấy luôn các "Điều X" trong câu hỏi bằng regex (không cần LLM)
    art_refs = RE_ARTICLE_REF.findall(question)
    clause_refs = []
    for clause_blob, art in RE_CLAUSE_ARTICLE_REF.findall(question):
        for cnum in re.findall(r"\d+", clause_blob or ""):
            clause_refs.append({"article_num": art, "clause_num": cnum})

    if not config.GEMINI_AVAILABLE:
        # Không có Gemini nào → dùng regex ngay
        regex_data = _regex_extract_entities(question)
        return {
            **regex_data,
            "article_refs": list(set(art_refs)),
            "clause_article_refs": clause_refs,
        }

    prompt = f"""Trích entities từ câu hỏi pháp luật sau. Chỉ liệt kê các từ xuất hiện trong câu.

Câu hỏi: {question}

Trả JSON với:
- concepts: các khái niệm pháp lý (vd: "tài sản chung", "hợp đồng lao động")
- actors: chủ thể (vd: "vợ", "người lao động")
- actions: hành vi pháp lý (vd: "ly hôn", "bồi thường")
Tiếng Việt viết thường, tối đa 5 phần tử mỗi danh sách."""

    schema = {
        "type": "object",
        "properties": {
            "concepts": {"type": "array", "items": {"type": "string"}},
            "actors": {"type": "array", "items": {"type": "string"}},
            "actions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["concepts", "actors", "actions"],
    }

    data = None
    max_retries = 2
    # ── Attempt 1: Vertex AI (hoặc API key nếu không dùng Vertex) ──
    for attempt in range(1, max_retries + 2):
        try:
            from google.genai import types
            client = _create_gemini_client(use_api_key_fallback=False)
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            data = json.loads(response.text or "{}")
            break
        except Exception as e1:
            if attempt < max_retries + 1 and _is_retryable_llm_error(e1):
                delay = 0.5 * attempt
                logger.warning(
                    f"Vertex AI extract entity gặp lỗi rate limit (attempt {attempt}/{max_retries + 1}): {e1}. "
                    f"Retry sau {delay}s..."
                )
                time.sleep(delay)
                continue
                
            if _is_billing_error(e1) and config.GEMINI_USE_VERTEXAI and config.GOOGLE_API_KEY:
                # ── Attempt 2: Fallback sang direct API key ──
                logger.info(
                    f"Vertex AI bị từ chối (billing/403), fallback sang Google API Key để extract entity..."
                )
                for attempt2 in range(1, max_retries + 2):
                    try:
                        from google.genai import types
                        client2 = _create_gemini_client(use_api_key_fallback=True)
                        response2 = client2.models.generate_content(
                            model=config.GEMINI_MODEL,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json",
                                response_schema=schema,
                                thinking_config=types.ThinkingConfig(thinking_budget=0),
                            ),
                        )
                        data = json.loads(response2.text or "{}")
                        break
                    except Exception as e2:
                        if attempt2 < max_retries + 1 and _is_retryable_llm_error(e2):
                            delay = 0.5 * attempt2
                            logger.warning(
                                f"API Key extract entity gặp lỗi rate limit (attempt {attempt2}/{max_retries + 1}): {e2}. "
                                f"Retry sau {delay}s..."
                            )
                            time.sleep(delay)
                            continue
                        logger.warning(
                            f"API Key fallback cũng thất bại, dùng regex NLP: {e2}"
                        )
            else:
                logger.warning(
                    f"Không extract được entity từ query (LLM), dùng regex NLP: {e1}"
                )
            break

    # ── Attempt 3: Regex NLP fallback ──
    if data is None:
        data = _regex_extract_entities(question)

    return {
        "concepts": [s.strip().lower() for s in data.get("concepts", []) if s],
        "actors": [s.strip().lower() for s in data.get("actors", []) if s],
        "actions": [s.strip().lower() for s in data.get("actions", []) if s],
        "article_refs": list(set(art_refs)),
        "clause_article_refs": clause_refs,
    }
