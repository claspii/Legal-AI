"""
Sinh dataset Q&A pháp luật từ Gemini để fine-tune LLM của bạn.

Hai stage:
  1. questions: với mỗi unit (Khoản nếu có, fallback Điều), gọi Gemini sinh N câu hỏi tự nhiên.
  2. answers:   đọc câu hỏi, dùng RAGEngine (vector + graph) để retrieve + Gemini trả lời.

Output JSONL hỗ trợ 3 format:
  - sft:     {instruction, input="", output}
  - rag_sft: {instruction, input=context, output}
  - chatml:  {messages: [{role, content}, ...]}

Distillation:
  --with-reasoning  Bắt Gemini xuất {reasoning, answer} riêng.
  --reasoning-style tag      => output = "<think>\\n{reasoning}\\n</think>\\n\\n{answer}"
  --reasoning-style separate => reasoning ở meta.reasoning (sft/rag_sft)
                                hoặc messages[-1].thinking (chatml)
  --reasoning-style none     => bỏ reasoning, chỉ giữ answer

Usage:
  conda activate chatbot
  cd c:\\Users\\congl\\Downloads\\doan

  # Chạy cả 2 stage, giới hạn 50 unit, 2 câu/unit, format SFT
  python generate_training_data.py --stage all --mode all --questions-per-seed 2 \
      --limit 50 --format sft --resume

  # Sinh dataset distillation có reasoning (RAG context + <think>...</think>)
  python generate_training_data.py --stage answers \
      --questions-file data_gen/questions.jsonl \
      --output data_gen/distill_data.jsonl --format rag_sft \
      --with-reasoning --reasoning-style tag --resume

  # Chỉ sinh câu hỏi
  python generate_training_data.py --stage questions --mode clause --questions-per-seed 3 \
      --questions-file data_gen/questions.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from pathlib import Path

from loguru import logger

from src import config
from src.document_processor import process_all_documents
from src.graph_extractor import extract_structural
from src.rag_engine import RAGEngine, _build_context_vector_only


# ---------------------------------------------------------------------------
# Gemini helpers
# ---------------------------------------------------------------------------

def _gemini_client():
    from google import genai
    from google.genai.types import HttpOptions

    if config.GEMINI_USE_VERTEXAI:
        return genai.Client(http_options=HttpOptions(api_version="v1"))
    return genai.Client(
        api_key=config.GOOGLE_API_KEY,
        http_options=HttpOptions(api_version="v1"),
    )


LAW_TITLES = {
    "91/2015/QH13": "Bộ luật Dân sự 2015",
    "100/2015/QH13": "Bộ luật Hình sự 2015",
    "52/2014/QH13": "Luật Hôn nhân và Gia đình 2014",
    "45/2019/QH14": "Bộ luật Lao động 2019",
}


def _seed_id(law: str, art: str, clause: str | None = None) -> str:
    sid = f"{law}__art{art}"
    if clause:
        sid += f"__cl{clause}"
    return sid


def _qhash(q: str) -> str:
    return hashlib.md5(q.strip().lower().encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Stage 1 — sinh câu hỏi
# ---------------------------------------------------------------------------

QUESTION_PROMPT = """Bạn là chuyên gia pháp luật Việt Nam. Hãy soạn các câu hỏi tự nhiên mà người dùng thực có thể hỏi, dựa trên nội dung sau.

Văn bản: {law_title}
Đơn vị: {unit_header}

Nội dung:
{text}

Yêu cầu:
- Soạn đúng {n} câu hỏi tiếng Việt, đa dạng dạng, mỗi câu một góc khác nhau:
  (1) hỏi định nghĩa/quy định
  (2) hỏi tình huống thực tế (nêu kịch bản ngắn rồi hỏi áp dụng)
  (3) hỏi so sánh/áp dụng/quyền-nghĩa vụ giữa các bên
- KHÔNG sao chép nguyên văn điều luật.
- Câu hỏi phải có thể trả lời được dựa trên nội dung trên (có thể bổ sung dẫn chiếu khác nếu cần).
- KHÔNG tự trả lời.

Trả JSON đúng schema."""


QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["questions"],
}


def _is_retryable(exc: Exception) -> bool:
    msg = str(exc).upper()
    patterns = (
        "429", "RESOURCE_EXHAUSTED", "RATE_LIMIT",
        "UNAVAILABLE", "TIMEOUT", "DEADLINE_EXCEEDED",
        "500", "502", "503", "504",
        "INTERNAL",
        "CONNECTION", "CONNECTIONERROR", "CONNECTIONRESET",
        "NAME RESOLUTION", "NAMERESOLUTION", "GETADDRINFO",
        "MAX RETRIES EXCEEDED", "REMOTE END CLOSED",
        "SSL", "EOF OCCURRED IN VIOLATION",
        "TEMPORARILY UNAVAILABLE",
    )
    return any(p in msg for p in patterns)


def gen_questions(unit: dict, n: int = 3, max_retries: int = 5) -> list[str]:
    from google.genai import types

    text = (unit.get("text") or "").strip()[:3500]
    if not text:
        return []

    law = unit["law_number"]
    art = unit["article_num"]
    clause = unit.get("clause_num")
    header = f"Điều {art}"
    if clause:
        header += f", Khoản {clause}"
    law_title = LAW_TITLES.get(law, law)
    prompt = QUESTION_PROMPT.format(
        law_title=law_title, unit_header=header, text=text, n=n,
    )

    for attempt in range(1, max_retries + 1):
        try:
            client = _gemini_client()
            resp = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=QUESTION_SCHEMA,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            data = json.loads(resp.text or "{}")
            qs_raw = data.get("questions", []) or []
            qs: list[str] = []
            seen: set[str] = set()
            for q in qs_raw:
                s = str(q or "").strip()
                if len(s) < 12:
                    continue
                key = s.lower()
                if key in seen:
                    continue
                seen.add(key)
                qs.append(s)
            return qs[:n]
        except Exception as e:
            if attempt < max_retries and _is_retryable(e):
                delay = 1.5 * (2 ** (attempt - 1)) + random.uniform(0.0, 0.8)
                logger.warning(
                    f"gen_questions retry {attempt}/{max_retries} ({header}): {e}. sleep {delay:.1f}s"
                )
                time.sleep(delay)
                continue
            logger.warning(f"gen_questions thất bại ({header}): {e}")
            return []
    return []


def load_units(strategy: str, mode: str) -> list[dict]:
    chunks = process_all_documents(config.DOCS_DIR, strategy=strategy)
    data = extract_structural(chunks)

    clauses_by_art: dict[tuple, list[dict]] = {}
    for cl in data["clauses"]:
        clauses_by_art.setdefault((cl["law_number"], cl["article_num"]), []).append(cl)

    units: list[dict] = []
    for art in data["articles"]:
        key = (art["law_number"], art["num"])
        cls = clauses_by_art.get(key, [])
        if cls:
            if mode in ("clause", "all"):
                for cl in cls:
                    units.append({
                        "law_number": cl["law_number"],
                        "article_num": cl["article_num"],
                        "clause_num": cl["num"],
                        "text": cl.get("text", ""),
                        "article_title": art.get("title", ""),
                    })
        else:
            if mode in ("article", "all"):
                units.append({
                    "law_number": art["law_number"],
                    "article_num": art["num"],
                    "clause_num": None,
                    "text": art.get("full_text", ""),
                    "article_title": art.get("title", ""),
                })
    return units


def _read_done_seed_ids(path: Path) -> set[str]:
    done: set[str] = set()
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            sid = rec.get("seed_id")
            if sid:
                done.add(sid)
        except Exception:
            continue
    return done


def stage_questions(args) -> None:
    out_path = Path(args.questions_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    units = load_units(args.strategy, args.mode)
    if args.limit:
        units = units[: args.limit]

    done = _read_done_seed_ids(out_path) if args.resume else set()
    total_units = len(units)
    logger.info(
        f"Q-gen: {total_units} units (mode={args.mode}), đã có {len(done)} seed"
    )

    n_emitted = 0
    with out_path.open("a", encoding="utf-8") as f:
        for i, unit in enumerate(units, start=1):
            sid = _seed_id(unit["law_number"], unit["article_num"], unit.get("clause_num"))
            if sid in done:
                continue
            if i % 25 == 0 or i == total_units:
                logger.info(f"  q-gen {i}/{total_units} -> {sid} (emitted={n_emitted})")
            qs = gen_questions(unit, n=args.questions_per_seed)
            if not qs:
                continue
            for q in qs:
                rec = {
                    "seed_id": sid,
                    "seed_law": unit["law_number"],
                    "seed_article": unit["article_num"],
                    "seed_clause": unit.get("clause_num"),
                    "article_title": unit.get("article_title"),
                    "question": q,
                    "question_hash": _qhash(q),
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_emitted += 1
            f.flush()
            if args.sleep > 0:
                time.sleep(args.sleep)

    logger.info(f"Questions saved -> {out_path} (mới: {n_emitted})")


# ---------------------------------------------------------------------------
# Stage 2 — RAG + Gemini trả lời
# ---------------------------------------------------------------------------

# Markers chỉ dùng để reject khi không có trích dẫn Điều/Khoản kèm theo.
# Nếu câu trả lời có trích dẫn cụ thể (Điều X, Khoản Y) thì KHÔNG reject
# dù có chứa các cụm dưới đây — Gemini có thể nói "tài liệu không đủ về khoản cụ thể"
# nhưng vẫn cung cấp thông tin hữu ích từ các khoản liên quan.
REJECT_MARKERS = (
    "không tìm thấy",
    "tôi không biết",
    "chưa có dữ liệu",
)

# Marker mạnh: reject ngay cả khi có trích dẫn
REJECT_MARKERS_HARD = (
    "xin lỗi, tôi không thể",
    "tôi không có khả năng trả lời",
)

_HAS_CITATION_RE = __import__("re").compile(
    r"(điều\s*\d|khoản\s*\d|art\.?\s*\d|luật\s+số|\d{2,}/\d{4}/qh)",
    __import__("re").IGNORECASE,
)


def _is_reject(answer: str) -> bool:
    if not answer:
        return True
    a = answer.lower().strip()
    if len(a) < 40:
        return True
    # Hard reject — không thoả thuận nổi
    if any(m in a for m in REJECT_MARKERS_HARD):
        return True
    # Soft reject — chỉ reject khi không có trích dẫn Điều/Khoản cụ thể
    has_citation = bool(_HAS_CITATION_RE.search(a))
    if not has_citation and any(m in a for m in REJECT_MARKERS):
        return True
    return False


# ---------------------------------------------------------------------------
# Distillation: Gemini xuất reasoning + answer riêng (cho fine-tune model nhỏ)
# ---------------------------------------------------------------------------

DISTILL_PROMPT = """Bạn là chuyên gia pháp luật Việt Nam. Hãy trả lời câu hỏi dưới đây DỰA CHỦ YẾU vào "Tài liệu tham khảo" được cung cấp.

Yêu cầu trả về JSON gồm 2 trường:
- reasoning: trình bày quá trình suy luận từng bước (xác định vấn đề pháp lý, tìm điều khoản liên quan trong tài liệu, áp dụng vào tình huống, đối chiếu/loại trừ, kết luận). 4-8 bước, ngắn gọn rõ ràng, có nêu Điều/Khoản khi cần.
- answer: câu trả lời cuối cùng cho người dùng bằng tiếng Việt, rõ ràng, mạch lạc, có trích dẫn cụ thể Điều/Khoản và số hiệu văn bản. KHÔNG được lặp lại nguyên văn phần "reasoning".

Quy tắc FORMAT bắt buộc cho "reasoning":
- Mỗi bước PHẢI nằm trên MỘT DÒNG RIÊNG, phân tách bằng ký tự xuống dòng "\\n".
- Mỗi dòng bắt đầu bằng số thứ tự + dấu ".", ví dụ: "1. ...", "2. ...".
- Tuyệt đối KHÔNG viết liền nhiều bước trên cùng 1 dòng.
- Ví dụ format mong muốn của trường reasoning (đã escape \\n trong JSON):
  "1. Xác định vấn đề: ...\\n2. Tìm điều khoản: ...\\n3. Áp dụng: ...\\n4. Kết luận: ..."

Quy tắc nội dung:
- Tuyệt đối KHÔNG được sử dụng hoặc bổ sung bất kỳ kiến thức, điều luật hay văn bản pháp luật nào nằm ngoài các tài liệu được cung cấp trong phần "Tài liệu tham khảo". KHÔNG bịa nội dung pháp luật ngoài tài liệu.
- Nếu tài liệu KHÔNG đủ căn cứ, "answer" phải nói rõ điều đó (và "reasoning" giải thích vì sao).
- Trong "answer", giữa các đoạn/ý lớn cũng phải có khoảng trắng hoặc xuống dòng (không viết dính 2 câu).

--- Tài liệu tham khảo ---
{context}

--- Câu hỏi ---
{question}
"""


DISTILL_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "answer": {"type": "string"},
    },
    "required": ["reasoning", "answer"],
}


def _call_gemini_reasoning(
    question: str, context: str, max_retries: int = 5
) -> tuple[str, str]:
    """Gọi Gemini ép JSON {reasoning, answer}. Trả ('', '') nếu thất bại."""
    from google.genai import types

    prompt = DISTILL_PROMPT.format(question=question, context=context)
    for attempt in range(1, max_retries + 1):
        try:
            client = _gemini_client()
            resp = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=DISTILL_SCHEMA,
                    thinking_config=types.ThinkingConfig(thinking_budget=-1),
                ),
            )
            data = json.loads(resp.text or "{}")
            reasoning = str(data.get("reasoning") or "").strip()
            answer = str(data.get("answer") or "").strip()
            return reasoning, answer
        except Exception as e:
            if attempt < max_retries and _is_retryable(e):
                delay = 1.5 * (2 ** (attempt - 1)) + random.uniform(0.0, 0.8)
                logger.warning(
                    f"distill retry {attempt}/{max_retries}: {e}. sleep {delay:.1f}s"
                )
                time.sleep(delay)
                continue
            logger.warning(f"distill Gemini lỗi: {e}")
            return "", ""
    return "", ""


def _dedupe_fused_by_article(fused: list[dict]) -> list[dict]:
    """
    Bỏ trùng theo (law_number, article_num).
    - Nếu cùng 1 Điều có nhiều entry (vd 1 cả Điều + nhiều Khoản; hoặc Khoản từ vector + cả Điều từ graph),
      giữ entry có rrf_score cao NHẤT.
    - Entry không xác định được (law, art) (vd chỉ có chunk_id) thì giữ nguyên.
    Bảo toàn thứ tự theo rrf_score giảm dần.
    """
    if not fused:
        return fused
    by_art: dict[tuple, dict] = {}
    misc: list[dict] = []
    for item in fused:
        meta = item.get("metadata", {})
        law = (meta.get("law_number") or meta.get("doc_number") or "").strip()
        art = str(meta.get("article_num") or "").strip()
        if not law or not art:
            misc.append(item)
            continue
        k = (law, art)
        cur = by_art.get(k)
        if cur is None or item.get("rrf_score", 0.0) > cur.get("rrf_score", 0.0):
            by_art[k] = item
    out = list(by_art.values()) + misc
    out.sort(key=lambda x: x.get("rrf_score", 0.0), reverse=True)
    return out


# Map tên file -> law_number (dùng để lọc Chroma by metadata)
_SOURCE_TO_LAW = {
    "Dansu.txt": "91/2015/QH13",
    "Hinhsu.txt": "100/2015/QH13",
    "Honnhan_giadinh.txt": "52/2014/QH13",
    "Laodong.txt": "45/2019/QH14",
}


def _fetch_seed_chunks_from_chroma(
    store,
    seed_law: str,
    seed_article: str,
    seed_clause: str | None,
) -> list[str]:
    """
    Lấy trực tiếp từ Chroma các chunk thuộc đúng (law, article[, clause]) của seed.
    Dùng where filter trên metadata. Trả list nội dung chunk.
    """
    if not seed_law or not seed_article:
        return []
    # Tìm source file tương ứng
    source_file = None
    for fname, law in _SOURCE_TO_LAW.items():
        if law == seed_law:
            source_file = fname
            break
    if source_file is None:
        return []
    try:
        where: dict = {
            "$and": [
                {"source": {"$eq": source_file}},
                {"article_num": {"$eq": seed_article}},
            ]
        }
        if seed_clause:
            where["$and"].append({"clause_num": {"$eq": seed_clause}})
        results = store.collection.get(
            where=where,
            include=["documents", "metadatas"],
            limit=5,
        )
        return results.get("documents") or []
    except Exception as e:
        logger.debug(f"Fetch seed chunk lỗi: {e}")
        return []


def _retrieve_only(
    engine: RAGEngine,
    question: str,
    seed_law: str | None = None,
    seed_article: str | None = None,
    seed_clause: str | None = None,
) -> tuple[str, list[dict], str]:
    """
    Dùng RAGEngine để retrieve (vector + graph + fuse) nhưng KHÔNG gọi LLM của engine.
    Nếu có seed_law/article/clause, inject thêm chunk của đúng seed vào đầu context
    để đảm bảo Gemini có đủ tài liệu cho câu hỏi cụ thể đó.
    Trả (context_text, sources, retrieval_mode).
    """
    vector_hits = engine.store.query(question)
    graph_hits: list[dict] = []
    fused = None
    mode = "vector"
    context = ""
    if engine.graph_retriever is not None:
        try:
            graph_hits = engine.graph_retriever.retrieve(
                question=question, vector_hits=vector_hits
            )
            from src.hybrid_fusion import fuse, build_context
            fused = fuse(vector_hits, graph_hits, top_n=config.TOP_K + 5)
            fused = _dedupe_fused_by_article(fused)[: config.TOP_K + 3]
            context = build_context(fused, max_chars=8000)
            mode = "hybrid"
        except Exception as e:
            logger.warning(f"Retrieve hybrid lỗi, fallback vector-only: {e}")
            context = _build_context_vector_only(vector_hits)
            mode = "vector"
    else:
        context = _build_context_vector_only(vector_hits)

    # Inject seed chunk nếu chưa có trong context
    if seed_law and seed_article:
        seed_chunks = _fetch_seed_chunks_from_chroma(
            engine.store, seed_law, seed_article, seed_clause
        )
        for chunk_text in seed_chunks:
            if chunk_text[:80] not in context:
                header = f"[Seed | Luật {seed_law} | Điều {seed_article}"
                if seed_clause:
                    header += f" | Khoản {seed_clause}"
                header += "]"
                context = header + "\n" + chunk_text + "\n\n---\n\n" + context
                logger.debug(f"Injected seed chunk: Luật {seed_law} Điều {seed_article} Khoản {seed_clause}")
                break  # chỉ cần 1 chunk seed là đủ

    sources = engine._build_sources(vector_hits, fused, graph_hits)
    return context, sources, mode


def _context_from_sources(sources: list[dict]) -> str:
    parts: list[str] = []
    for s in sources or []:
        bits = []
        if s.get("doc_number"):
            bits.append(f"Luật {s['doc_number']}")
        if s.get("article"):
            bits.append(f"Điều {s['article']}")
        if s.get("clause"):
            bits.append(f"Khoản {s['clause']}")
        head = " | ".join(bits) if bits else s.get("source", "")
        text = (s.get("preview") or "").strip()
        if not text:
            continue
        parts.append(f"[{head}]\n{text}")
    return "\n\n---\n\n".join(parts)


def _format_record(record: dict, fmt: str, reasoning_style: str = "none") -> dict:
    meta = {
        "law": record.get("seed_law"),
        "article": record.get("seed_article"),
        "clause": record.get("seed_clause"),
        "article_title": record.get("article_title"),
        "retrieval_mode": record.get("retrieval_mode"),
        "sources": record.get("sources", []),
        "question_hash": record.get("question_hash"),
    }
    reasoning = (record.get("reasoning") or "").strip()
    answer = (record.get("answer") or "").strip()

    if reasoning and reasoning_style == "tag":
        output_text = f"<think>\n{reasoning}\n</think>\n\n{answer}"
    elif reasoning and reasoning_style == "separate":
        output_text = answer
        meta["reasoning"] = reasoning
    else:
        output_text = answer

    if fmt == "sft":
        return {
            "instruction": record["question"],
            "input": "",
            "output": output_text,
            "meta": meta,
        }
    if fmt == "rag_sft":
        return {
            "instruction": record["question"],
            "input": record.get("context", ""),
            "output": output_text,
            "meta": meta,
        }
    if fmt == "chatml":
        if reasoning and reasoning_style == "separate":
            return {
                "messages": [
                    {"role": "system", "content": config.SYSTEM_PROMPT},
                    {"role": "user", "content": record["question"]},
                    {
                        "role": "assistant",
                        "content": answer,
                        "thinking": reasoning,
                    },
                ],
                "meta": meta,
            }
        return {
            "messages": [
                {"role": "system", "content": config.SYSTEM_PROMPT},
                {"role": "user", "content": record["question"]},
                {"role": "assistant", "content": output_text},
            ],
            "meta": meta,
        }
    raise ValueError(f"Format không hỗ trợ: {fmt}")


def _read_done_qhashes(path: Path) -> set[str]:
    done: set[str] = set()
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            meta = rec.get("meta") or {}
            h = meta.get("question_hash")
            if not h:
                instr = rec.get("instruction") or ""
                if not instr and rec.get("messages"):
                    for m in rec["messages"]:
                        if m.get("role") == "user":
                            instr = m.get("content", "")
                            break
                if instr:
                    h = _qhash(instr)
            if h:
                done.add(h)
        except Exception:
            continue
    return done


def stage_answers(args) -> None:
    in_path = Path(args.questions_file)
    if not in_path.exists():
        logger.error(f"Không có file câu hỏi: {in_path}. Chạy stage questions trước.")
        return

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    done = _read_done_qhashes(out_path) if args.resume else set()
    logger.info(f"A-gen: đã có {len(done)} answer, format={args.format}")

    engine = RAGEngine()
    n_ok = 0
    n_skip = 0
    n_err = 0

    with in_path.open("r", encoding="utf-8") as fin, out_path.open("a", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                qrec = json.loads(line)
            except Exception:
                continue
            q = (qrec.get("question") or "").strip()
            if not q:
                continue
            qhash = qrec.get("question_hash") or _qhash(q)
            if qhash in done:
                continue
            reasoning = ""
            answer = ""
            context_text = ""
            sources: list[dict] = []
            mode = ""
            try:
                if args.with_reasoning:
                    context_text, sources, mode = _retrieve_only(
                        engine, q,
                        seed_law=qrec.get("seed_law"),
                        seed_article=qrec.get("seed_article"),
                        seed_clause=qrec.get("seed_clause"),
                    )
                    reasoning, answer = _call_gemini_reasoning(q, context_text)
                else:
                    resp = engine.query(question=q, provider="gemini")
                    answer = (resp.answer or "").strip()
                    sources = resp.sources or []
                    mode = resp.retrieval_mode
                    context_text = _context_from_sources(sources)
            except Exception as e:
                n_err += 1
                logger.warning(f"RAG/distill lỗi q={q[:60]}: {e}")
                continue

            if _is_reject(answer):
                n_skip += 1
                continue
            if args.with_reasoning and len(reasoning) < 40:
                n_skip += 1
                continue

            record = {
                "seed_law": qrec.get("seed_law"),
                "seed_article": qrec.get("seed_article"),
                "seed_clause": qrec.get("seed_clause"),
                "article_title": qrec.get("article_title"),
                "question": q,
                "question_hash": qhash,
                "reasoning": reasoning,
                "answer": answer,
                "context": context_text,
                "sources": sources,
                "retrieval_mode": mode,
            }
            item = _format_record(record, args.format, args.reasoning_style)
            fout.write(json.dumps(item, ensure_ascii=False) + "\n")
            fout.flush()
            done.add(qhash)
            n_ok += 1

            if n_ok % 25 == 0:
                logger.info(f"  answers ok={n_ok} skip_refuse={n_skip} err={n_err}")
            if args.sleep > 0:
                time.sleep(args.sleep)
            if args.limit and n_ok >= args.limit:
                break

    logger.info(
        f"Answers saved -> {out_path} (ok={n_ok}, refuse={n_skip}, err={n_err})"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Q&A training data for legal LLM.")
    parser.add_argument("--stage", choices=["questions", "answers", "all"], default="all")
    parser.add_argument(
        "--mode", choices=["clause", "article", "all"], default="all",
        help="clause: chỉ Khoản; article: chỉ Điều không có Khoản; all: clause ưu tiên, fallback article",
    )
    parser.add_argument("--questions-per-seed", type=int, default=3)
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Giới hạn unit (stage questions) hoặc số answer (stage answers)",
    )
    parser.add_argument("--strategy", default="hybrid",
                        choices=["hybrid", "article", "clause", "chapter"])
    parser.add_argument("--questions-file", default="data_gen/questions.jsonl")
    parser.add_argument("--output", default="data_gen/training_data.jsonl")
    parser.add_argument("--format", choices=["sft", "rag_sft", "chatml"], default="sft")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.0,
                        help="Sleep giữa các call API (giây) để tránh 429")
    parser.add_argument(
        "--with-reasoning", action="store_true",
        help="Bắt Gemini xuất reasoning + answer riêng (phục vụ distillation).",
    )
    parser.add_argument(
        "--reasoning-style", choices=["tag", "separate", "none"], default="tag",
        help="Cách đóng gói reasoning trong output:\n"
             " - tag: nhúng <think>...</think> trước answer (giống DeepSeek-R1 distill)\n"
             " - separate: giữ reasoning ở field riêng (meta.reasoning / messages[].thinking)\n"
             " - none: bỏ reasoning khi format (chỉ giữ answer)",
    )
    args = parser.parse_args()

    if args.stage in ("questions", "all"):
        stage_questions(args)
    if args.stage in ("answers", "all"):
        stage_answers(args)


if __name__ == "__main__":
    main()
