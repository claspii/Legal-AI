"""
CLI build knowledge graph từ các văn bản luật trong thư mục data/.

Usage:
    python build_graph.py                        # structural + regex refs
    python build_graph.py --extract-semantic     # thêm LLM semantic (tốn token)
    python build_graph.py --clear                # xóa graph cũ trước khi build
    python build_graph.py --strategy article     # chunking strategy cụ thể
"""

import argparse
import time
from loguru import logger

from src import config
from src.document_processor import process_all_documents
from src.graph_store import GraphStore
from src.graph_extractor import (
    extract_structural,
    extract_references,
    extract_semantic_llm,
)


def build(
    strategy: str = "hybrid",
    extract_semantic: bool = False,
    clear: bool = False,
    max_semantic: int | None = None,
) -> dict:
    t0 = time.time()
    logger.info(f"Bắt đầu build graph (strategy={strategy})")
    if extract_semantic:
        logger.info(
            "LLM semantic: BẬT — sẽ gọi Gemini cho từng Điều SAU khi ghi Neo4j structural + REFERENCES "
            f"(cần GOOGLE_API_KEY trong .env). max_semantic={max_semantic or 'không giới hạn'}"
        )
    else:
        logger.info(
            "LLM semantic: TẮT — chỉ structural + regex REFERENCES. "
            "Thêm flag --extract-semantic để trích Concept/Actor/Action bằng LLM."
        )

    chunks = process_all_documents(config.DOCS_DIR, strategy=strategy)
    if not chunks:
        logger.error("Không có chunk nào, dừng build")
        return {"ok": False, "reason": "no_chunks"}

    store = GraphStore()
    if clear:
        store.clear()
    store.init_schema()

    data = extract_structural(chunks)
    n_art = len(data["articles"])
    n_cl = len(data["clauses"])
    n_lk = len(data["chunk_links"])
    clauses_by_article: dict[tuple[str, str], list[dict]] = {}
    for cl in data["clauses"]:
        key = (cl["law_number"], cl["article_num"])
        clauses_by_article.setdefault(key, []).append(cl)
    logger.info(
        f"Đang ghi Neo4j structural (mỗi bước nhiều round-trip, có thể vài phút): "
        f"{len(data['laws'])} laws, {len(data['chapters'])} chapters, {n_art} articles, "
        f"{n_cl} clauses, {n_lk} chunk links..."
    )

    # 1. Laws
    for law in data["laws"]:
        store.upsert_law(law["doc_number"], law["title"], law["source_file"])

    # 2. Chapters
    for i, ch in enumerate(data["chapters"]):
        store.upsert_chapter(ch["law_number"], ch["num"], ch["title"])
        if (i + 1) % 25 == 0:
            logger.info(f"  chapters {i + 1}/{len(data['chapters'])}")

    # 3. Articles
    for i, art in enumerate(data["articles"]):
        store.upsert_article(
            law_number=art["law_number"],
            num=art["num"],
            title=art["title"],
            full_text=art["full_text"],
            chapter_num=art.get("chapter_num") or None,
        )
        if (i + 1) % 200 == 0 or (i + 1) == n_art:
            logger.info(f"  articles upsert {i + 1}/{n_art}")

    # 4. Clauses
    for i, cl in enumerate(data["clauses"]):
        store.upsert_clause(
            law_number=cl["law_number"],
            article_num=cl["article_num"],
            clause_num=cl["num"],
            text=cl["text"],
        )
        if (i + 1) % 200 == 0 or (i + 1) == n_cl:
            logger.info(f"  clauses upsert {i + 1}/{n_cl}")

    # 5. Link chunks ↔ article/clause
    for i, link in enumerate(data["chunk_links"]):
        store.link_chunk(
            chunk_id=link["chunk_id"],
            law_number=link["law_number"],
            article_num=link["article_num"],
            clause_num=link.get("clause_num"),
        )
        if (i + 1) % 500 == 0 or (i + 1) == n_lk:
            logger.info(f"  chunk links {i + 1}/{n_lk}")

    logger.info("Đã import xong structural vào Neo4j. Đang trích dẫn chiếu (regex, nhiều cạnh)...")

    # 6. References (regex)
    ref_count = 0
    for ai, art in enumerate(data["articles"]):
        if (ai + 1) % 200 == 0 or (ai + 1) == n_art:
            logger.info(f"  REFERENCES scan Điều {ai + 1}/{n_art} (đã tạo ~{ref_count} cạnh)")
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
                ref_count += 1
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
                ref_count += 1
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
                ref_count += 1
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
                ref_count += 1
            for dst_law in refs["cross_laws"]:
                if dst_law == art["law_number"]:
                    continue
                store.add_cross_law_ref(
                    src_law=art["law_number"],
                    src_article=art["num"],
                    src_clause=src_clause,
                    dst_law_name=dst_law,
                )
                ref_count += 1

    logger.info(f"Đã thêm {ref_count} cạnh REFERENCES")

    # 7. Semantic via LLM (optional)
    if extract_semantic:
        if not config.GEMINI_AVAILABLE:
            logger.error(
                "Gemini chưa sẵn sàng — bỏ qua semantic extraction. "
                "Cần 1 trong 2 cách: "
                "(1) GOOGLE_API_KEY, hoặc "
                "(2) GOOGLE_GENAI_USE_VERTEXAI=True + GOOGLE_CLOUD_PROJECT (+ credentials)."
            )
        else:
            semantic_units = []
            for art in data["articles"]:
                cls = clauses_by_article.get((art["law_number"], art["num"]), [])
                if cls:
                    for cl in cls:
                        semantic_units.append({
                            "law_number": art["law_number"],
                            "article_num": art["num"],
                            "clause_num": cl.get("num"),
                            "text": cl.get("text", ""),
                        })
                else:
                    semantic_units.append({
                        "law_number": art["law_number"],
                        "article_num": art["num"],
                        "clause_num": None,
                        "text": art["full_text"],
                    })
            logger.info(
                "Bắt đầu LLM semantic extraction (Gemini, có cache .llm_cache/) — "
                f"~{min(max_semantic or len(semantic_units), len(semantic_units))} lần gọi API..."
            )
            total = len(semantic_units)
            for i, unit in enumerate(semantic_units):
                if max_semantic and i >= max_semantic:
                    break
                if i % 20 == 0:
                    logger.info(f"  semantic {i}/{total}")
                try:
                    sem = extract_semantic_llm(
                        law_number=unit["law_number"],
                        article_num=unit["article_num"],
                        clause_num=unit.get("clause_num"),
                        article_text=unit["text"],
                    )
                    store.add_semantic(
                        law_number=unit["law_number"],
                        article_num=unit["article_num"],
                        clause_num=unit.get("clause_num"),
                        concepts_defined=sem["concepts_defined"],
                        actors=sem["actors"],
                        actions=sem["actions"],
                        actor_actions=sem["actor_actions"],
                        related_concepts=sem["related_concepts"],
                    )
                except Exception as e:
                    logger.warning(
                        "Semantic lỗi "
                        f"art={unit['article_num']} clause={unit.get('clause_num') or '-'}: {e}"
                    )
            logger.info("Semantic extraction hoàn tất")

    stats = store.stats_simple()
    store.close()

    dt = time.time() - t0
    logger.info(f"Build graph xong trong {dt:.1f}s")
    logger.info(f"Stats: {stats}")
    return {"ok": True, "duration_sec": dt, "stats": stats}


def main():
    parser = argparse.ArgumentParser(description="Build knowledge graph từ data/")
    parser.add_argument("--strategy", default="hybrid",
                        choices=["chapter", "article", "clause", "hybrid"])
    parser.add_argument("--extract-semantic", action="store_true",
                        help="Bật LLM semantic extraction (tốn token)")
    parser.add_argument("--clear", action="store_true",
                        help="Xóa graph cũ trước khi build")
    parser.add_argument("--max-semantic", type=int, default=None,
                        help="Giới hạn số Điều cho semantic extract (debug)")
    args = parser.parse_args()

    result = build(
        strategy=args.strategy,
        extract_semantic=args.extract_semantic,
        clear=args.clear,
        max_semantic=args.max_semantic,
    )
    print(result)


if __name__ == "__main__":
    main()
