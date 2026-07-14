"""
Xử lý và phân đoạn (chunking) văn bản luật tiếng Việt.

File .doc được convert sang .txt bằng convert_docs.ps1 trước,
module này đọc .txt rồi tách theo cấu trúc Chương/Điều/Khoản.

Có 4 chiến lược chunking:
  - chapter: mỗi Chương là 1 chunk
  - article: mỗi Điều là 1 chunk
  - clause:  mỗi Khoản là 1 chunk
  - hybrid:  Điều ngắn giữ nguyên, Điều dài tách ra theo Khoản
"""

import re
from pathlib import Path
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class DocumentChunk:
    content: str
    metadata: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        src = self.metadata.get("source", "unknown")
        chap = self.metadata.get("chapter_num", "")
        art = self.metadata.get("article_num", "")
        clause = self.metadata.get("clause_num", "")
        idx = self.metadata.get("chunk_index", 0)
        return f"{src}__ch{chap}_art{art}_cl{clause}_idx{idx}"


# Regex cho cấu trúc văn bản luật VN
RE_DOC_NUMBER = re.compile(
    r"(\d+/\d{4}/QH\d+|Luật\s+số\s+\d+/\d{4}/QH\d+)", re.IGNORECASE
)
RE_CHAPTER = re.compile(
    r"(?:^|\n)\s*(Chương\s+([IVXLCDM]+|\d+)[.:]?\s*\n?\s*(.*?))\s*(?=\n)",
    re.MULTILINE | re.IGNORECASE,
)
RE_SECTION = re.compile(
    r"(?:^|\n)\s*(Mục\s+(\d+)[.:]?\s*(.*?))\s*(?=\n)", re.MULTILINE | re.IGNORECASE
)
RE_ARTICLE = re.compile(
    r"(?:^|\n)\s*(Điều\s+(\d+[a-z]?)[.:]?\s*(.*?))\s*(?=\n)", re.MULTILINE | re.IGNORECASE
)
RE_CLAUSE = re.compile(r"(?:^|\n)\s*(\d+)\.\s+", re.MULTILINE)
RE_POINT = re.compile(r"(?:^|\n)\s*([a-zđ])\)\s+", re.MULTILINE)


def read_document(filepath: str) -> str:
    """Đọc file .txt, thử nhiều encoding phổ biến."""
    p = Path(filepath)
    logger.info(f"Reading {p.name}")

    for enc in ("utf-8-sig", "utf-8", "utf-16", "cp1252"):
        try:
            return p.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return p.read_text(encoding="utf-8", errors="replace")


def extract_doc_metadata(filepath: str, text: str) -> dict:
    """Trích metadata từ tên file và nội dung đầu văn bản."""
    fname = Path(filepath).stem
    parts = fname.split("_")

    meta = {"source": Path(filepath).name, "filepath": str(filepath)}

    if len(parts) >= 3:
        meta["doc_number"] = f"{parts[0]}/{parts[1]}/{parts[2]}"

    m = RE_DOC_NUMBER.search(text[:2000])
    if m:
        meta["doc_number_from_text"] = m.group(1)

    first_lines = text[:500].strip().split("\n")
    for line in first_lines:
        line = line.strip()
        if len(line) > 10 and not line.upper().startswith("CHƯƠNG"):
            if any(kw in line.upper() for kw in ["LUẬT", "BỘ LUẬT", "NGHỊ ĐỊNH"]):
                meta["doc_title"] = line
                break

    return meta


def _clean_text(text: str) -> str:
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\r", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _split_at_pattern(pattern: re.Pattern, text: str) -> list[tuple[str, str, int]]:
    """Tách text theo regex, trả về [(header, body, position), ...]"""
    matches = list(pattern.finditer(text))
    if not matches:
        return []

    results = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        header = m.group(1).strip()
        body = text[m.end() : end].strip()
        results.append((header, body, start))
    return results


def chunk_by_chapters(text: str, base_meta: dict) -> list[DocumentChunk]:
    """Mỗi Chương thành 1 chunk."""
    text = _clean_text(text)
    chapters = _split_at_pattern(RE_CHAPTER, text)

    if not chapters:
        return [DocumentChunk(content=text, metadata={**base_meta, "chunk_type": "full_doc", "chunk_index": 0})]

    chunks = []
    for i, (header, body, _) in enumerate(chapters):
        chap_match = re.match(r"Chương\s+([IVXLCDM]+|\d+)", header, re.IGNORECASE)
        chap_num = chap_match.group(1) if chap_match else str(i + 1)

        content = f"{header}\n\n{body}"
        meta = {
            **base_meta,
            "chunk_type": "chapter",
            "chapter_num": chap_num,
            "chapter_title": header,
            "chunk_index": i,
        }
        chunks.append(DocumentChunk(content=content, metadata=meta))

    return chunks


def chunk_by_articles(text: str, base_meta: dict) -> list[DocumentChunk]:
    """Mỗi Điều thành 1 chunk, kèm context Chương."""
    text = _clean_text(text)

    chapters = _split_at_pattern(RE_CHAPTER, text)
    current_chapter = {"num": "", "title": ""}

    articles = list(RE_ARTICLE.finditer(text))
    if not articles:
        return chunk_by_chapters(text, base_meta)

    chunks = []
    for i, m in enumerate(articles):
        art_num = m.group(2)
        art_title = m.group(3).strip()

        start = m.end()
        end = articles[i + 1].start() if i + 1 < len(articles) else len(text)
        body = text[start:end].strip()

        for ch_header, ch_body, ch_pos in chapters:
            if ch_pos <= m.start():
                ch_match = re.match(r"Chương\s+([IVXLCDM]+|\d+)", ch_header, re.IGNORECASE)
                current_chapter = {
                    "num": ch_match.group(1) if ch_match else "",
                    "title": ch_header,
                }

        header_line = f"Điều {art_num}. {art_title}" if art_title else f"Điều {art_num}."
        context_prefix = f"[{current_chapter['title']}]\n" if current_chapter["title"] else ""
        content = f"{context_prefix}{header_line}\n{body}"

        meta = {
            **base_meta,
            "chunk_type": "article",
            "article_num": art_num,
            "article_title": art_title,
            "chapter_num": current_chapter["num"],
            "chapter_title": current_chapter["title"],
            "chunk_index": i,
        }
        chunks.append(DocumentChunk(content=content, metadata=meta))

    return chunks


def chunk_by_clauses(text: str, base_meta: dict, max_size: int = 1500) -> list[DocumentChunk]:
    """Mỗi Khoản thành 1 chunk (trong từng Điều)."""
    text = _clean_text(text)
    article_chunks = chunk_by_articles(text, base_meta)

    fine_chunks = []
    for art_chunk in article_chunks:
        art_text = art_chunk.content
        art_meta = art_chunk.metadata

        clause_matches = list(RE_CLAUSE.finditer(art_text))
        if not clause_matches or len(art_text) <= max_size:
            fine_chunks.append(art_chunk)
            continue

        art_header_end = clause_matches[0].start()
        art_header = art_text[:art_header_end].strip()

        for j, cm in enumerate(clause_matches):
            cl_num = cm.group(1)
            cl_start = cm.start()
            cl_end = clause_matches[j + 1].start() if j + 1 < len(clause_matches) else len(art_text)
            cl_body = art_text[cl_start:cl_end].strip()

            content = f"{art_header}\n{cl_body}" if art_header else cl_body
            meta = {
                **art_meta,
                "chunk_type": "clause",
                "clause_num": cl_num,
                "chunk_index": len(fine_chunks),
            }
            fine_chunks.append(DocumentChunk(content=content, metadata=meta))

    return fine_chunks


def hybrid_chunk(text: str, base_meta: dict, max_size: int = 10000) -> list[DocumentChunk]:
    """
    Chiến lược hybrid (khuyên dùng):
    Điều ngắn (<= max_size) giữ nguyên, Điều dài tách theo từng Khoản.
    """
    text = _clean_text(text)
    article_chunks = chunk_by_articles(text, base_meta)

    result = []
    for art_chunk in article_chunks:
        art_text = art_chunk.content
        art_meta = art_chunk.metadata

        if len(art_text) <= max_size:
            art_meta["chunk_type"] = "hybrid_article"
            art_meta["chunk_index"] = len(result)
            result.append(DocumentChunk(content=art_text, metadata=art_meta))
            continue

        clause_matches = list(RE_CLAUSE.finditer(art_text))
        if not clause_matches:
            art_meta["chunk_type"] = "hybrid_article"
            art_meta["chunk_index"] = len(result)
            result.append(DocumentChunk(content=art_text, metadata=art_meta))
            continue

        art_header_end = clause_matches[0].start()
        art_header = art_text[:art_header_end].strip()

        for j, cm in enumerate(clause_matches):
            cl_num = cm.group(1)
            cl_start = cm.start()
            cl_end = clause_matches[j + 1].start() if j + 1 < len(clause_matches) else len(art_text)
            cl_body = art_text[cl_start:cl_end].strip()

            content = f"{art_header}\n{cl_body}"

            meta = {
                **art_meta,
                "chunk_type": "hybrid_clause",
                "clause_num": cl_num,
                "chunk_index": len(result),
            }
            result.append(DocumentChunk(content=content, metadata=meta))

    return result


CHUNKING_STRATEGIES = {
    "chapter": chunk_by_chapters,
    "article": chunk_by_articles,
    "clause": chunk_by_clauses,
    "hybrid": hybrid_chunk,
}


def process_document(filepath: str, strategy: str = "hybrid") -> list[DocumentChunk]:
    """Pipeline: đọc .txt -> trích metadata -> chunk."""
    text = read_document(filepath)
    base_meta = extract_doc_metadata(filepath, text)

    chunker = CHUNKING_STRATEGIES.get(strategy, hybrid_chunk)
    chunks = chunker(text, base_meta)

    logger.info(f"{Path(filepath).name}: {len(chunks)} chunks (strategy={strategy})")
    return chunks


def discover_documents(docs_dir: str) -> list[str]:
    """Tìm tất cả file .txt trong thư mục."""
    docs_path = Path(docs_dir)
    return sorted(str(f) for f in docs_path.glob("*.txt"))


def process_all_documents(docs_dir: str, strategy: str = "hybrid") -> list[DocumentChunk]:
    """Xử lý toàn bộ file .txt trong thư mục."""
    files = discover_documents(docs_dir)
    if not files:
        logger.warning(f"Không tìm thấy file .txt trong {docs_dir}")
        return []

    all_chunks = []
    for f in files:
        try:
            chunks = process_document(f, strategy)
            all_chunks.extend(chunks)
        except Exception as e:
            logger.error(f"Lỗi xử lý {f}: {e}")

    logger.info(f"Tổng: {len(all_chunks)} chunks từ {len(files)} tài liệu")
    return all_chunks
