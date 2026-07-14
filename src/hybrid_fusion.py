"""
Hybrid fusion giữa vector hits (ChromaDB) và graph hits (Neo4j).

Dùng Reciprocal Rank Fusion (RRF): với 1 item có rank r trong list nào đó,
score đóng góp là 1/(k + r). Các list khác nhau cộng score lại, rồi sort giảm dần.
"""

from loguru import logger

from .graph_extractor import _law_info_from_source


RRF_K = 60


def _vector_hit_key(hit: dict) -> tuple:
    """
    Định danh 1 vector hit theo (law_number, article_num) nếu có;
    ngược lại fallback theo chunk_id.
    """
    meta = hit.get("metadata", {})
    source = meta.get("source", "")
    info = _law_info_from_source(source) if source else {"doc_number": ""}
    law = meta.get("law_number") or info.get("doc_number") or ""
    art = str(meta.get("article_num") or "").strip()
    clause = str(meta.get("clause_num") or "").strip()
    if law and art and clause:
        return ("clause", law, art, clause)
    if law and art:
        return ("art", law, art, "")
    return ("chunk", hit.get("id") or meta.get("chunk_id") or str(id(hit)))


def _graph_hit_key(hit: dict) -> tuple:
    law = hit.get("law_number", "")
    art = str(hit.get("num", ""))
    clause = str(hit.get("clause_num") or "").strip()
    if (hit.get("target_type") == "clause") or clause:
        return ("clause", law, art, clause)
    return ("art", law, art, "")


def fuse(
    vector_hits: list[dict],
    graph_hits: list[dict],
    top_n: int = 10,
    vector_weight: float = 1.0,
    graph_weight: float = 0.8,
) -> list[dict]:
    """
    Trả về list đã fuse + sort, mỗi phần tử dạng:
      {
        "key": tuple,
        "content": str,                 # text dùng làm context
        "metadata": dict,
        "rrf_score": float,
        "sources": ["vector", "graph"],
        "vector_rank": int | None,
        "graph_rank": int | None,
        "graph_relation": str | None,
      }
    """
    scores: dict[tuple, dict] = {}

    for rank, hit in enumerate(vector_hits or [], start=1):
        k = _vector_hit_key(hit)
        contrib = vector_weight / (RRF_K + rank)
        entry = scores.setdefault(k, {
            "key": k,
            "content": hit.get("content", ""),
            "metadata": dict(hit.get("metadata", {})),
            "rrf_score": 0.0,
            "sources": [],
            "vector_rank": None,
            "graph_rank": None,
            "graph_relation": None,
        })
        entry["rrf_score"] += contrib
        entry["vector_rank"] = rank
        if "vector" not in entry["sources"]:
            entry["sources"].append("vector")
        if not entry["content"]:
            entry["content"] = hit.get("content", "")
        # Luôn giữ vector distance/score gốc
        if "distance" in hit:
            entry["metadata"]["_vector_distance"] = hit["distance"]

    for rank, hit in enumerate(graph_hits or [], start=1):
        k = _graph_hit_key(hit)
        contrib = graph_weight / (RRF_K + rank)
        full_text = hit.get("full_text", "") or ""
        clause = str(hit.get("clause_num") or "").strip()
        if clause:
            header = f"Điều {hit.get('num', '')}, Khoản {clause}".strip()
        else:
            header = f"Điều {hit.get('num', '')}. {hit.get('title', '') or ''}".strip()
        content = f"{header}\n{full_text}".strip() if header else full_text

        entry = scores.setdefault(k, {
            "key": k,
            "content": content,
            "metadata": {
                "law_number": hit.get("law_number", ""),
                "article_num": hit.get("num", ""),
                "clause_num": clause,
                "article_title": hit.get("title", ""),
                "chunk_type": "graph_clause" if clause else "graph_article",
            },
            "rrf_score": 0.0,
            "sources": [],
            "vector_rank": None,
            "graph_rank": None,
            "graph_relation": None,
        })
        entry["rrf_score"] += contrib
        entry["graph_rank"] = rank
        if not entry["content"] and content:
            entry["content"] = content
        if "graph" not in entry["sources"]:
            entry["sources"].append("graph")
        relation = hit.get("relation") or (hit.get("relations") and ",".join(hit["relations"]))
        if relation:
            entry["graph_relation"] = relation
        # ưu tiên bổ sung law_number/article_num vào metadata nếu vector thiếu
        entry["metadata"].setdefault("law_number", hit.get("law_number", ""))
        entry["metadata"].setdefault("article_num", hit.get("num", ""))
        if clause:
            entry["metadata"].setdefault("clause_num", clause)

    ranked = sorted(scores.values(), key=lambda x: x["rrf_score"], reverse=True)
    top = ranked[:top_n]
    logger.info(
        f"Fusion: {len(vector_hits or [])} vector + {len(graph_hits or [])} graph "
        f"→ {len(top)} unified (top {top_n})"
    )
    return top


def build_context(fused: list[dict], max_chars: int = 8000) -> str:
    """Gom các item đã fuse thành 1 chuỗi context cho LLM."""
    parts = []
    total = 0
    for i, item in enumerate(fused, start=1):
        meta = item.get("metadata", {})
        header_bits = []
        law = meta.get("law_number") or meta.get("doc_number") or ""
        art = meta.get("article_num") or ""
        if law:
            header_bits.append(f"Luật {law}")
        if art:
            header_bits.append(f"Điều {art}")
        if meta.get("clause_num"):
            header_bits.append(f"Khoản {meta['clause_num']}")
        header = " | ".join(header_bits) if header_bits else meta.get("source", "")

        src_tag = "+".join(item.get("sources", []))
        text = item.get("content", "").strip()
        if not text:
            continue
        block = f"[#{i} | {header} | nguồn: {src_tag}]\n{text}"

        if total + len(block) > max_chars and parts:
            break
        parts.append(block)
        total += len(block)

    return "\n\n---\n\n".join(parts)
