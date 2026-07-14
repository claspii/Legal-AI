"""
Documents API — admin-only endpoints for uploading and indexing documents.
"""

import os
import shutil
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from ...database import get_db
from ...models.user import User
from ...models.document import Document
from ...dependencies import get_current_user, get_current_admin
from ...config import settings

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.get("")
@router.get("/")
async def list_documents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = 1,
    page_size: int = 20,
):
    """List all indexed documents with pagination (all authenticated users can see)."""
    # Source of truth: ChromaDB + DB records merged together
    data_dir = PROJECT_ROOT / "data"
    uploads_dir = Path(settings.UPLOAD_DIR)

    # --- 1. Gather all DB records keyed by stem (lowercase) ---
    result = await db.execute(select(Document).order_by(Document.created_at.desc()))
    db_docs = result.scalars().all()
    db_by_stem: dict[str, Document] = {}
    for d in db_docs:
        stem = Path(d.filename).stem.lower()
        # Keep the newest record per stem
        if stem not in db_by_stem:
            db_by_stem[stem] = d

    # --- 2. Gather ALL sources from ChromaDB (single get call) ---
    chroma_counts: dict[str, int] = {}
    try:
        from src.api import get_engine
        engine = get_engine()
        store = engine.store
        if store and store.collection:
            all_data = store.collection.get(include=["metadatas"])
            for meta in (all_data.get("metadatas") or []):
                if meta:
                    source = meta.get("source", "unknown")
                    if source and source != "unknown":
                        chroma_counts[source] = chroma_counts.get(source, 0) + 1
    except Exception as e:
        logger.warning(f"Failed to fetch chroma counts: {e}")

    # --- 3. Also check data/ directory for .txt files not yet in Chroma ---
    data_file_sizes: dict[str, int] = {}
    try:
        for txt_file in data_dir.glob("*.txt"):
            data_file_sizes[txt_file.name] = txt_file.stat().st_size
            if txt_file.name not in chroma_counts:
                # File exists on disk but not indexed yet — still show it
                chroma_counts[txt_file.name] = 0
    except Exception as e:
        logger.warning(f"Failed scanning data dir: {e}")

    # --- 4. Also include DB-tracked docs not in Chroma (pending/error) ---
    for d in db_docs:
        txt_name = Path(d.filename).stem + ".txt"
        if d.filename not in chroma_counts and txt_name not in chroma_counts:
            # pending/error doc that hasn't been indexed yet
            chroma_counts[d.filename] = d.chunks_count or 0

    # --- 5. Build unified response list ---
    all_docs = []
    seen_stems: set[str] = set()

    for filename, chunk_count in chroma_counts.items():
        stem = Path(filename).stem.lower()
        if stem in seen_stems:
            continue
        seen_stems.add(stem)

        ext = Path(filename).suffix.lower() or ".txt"

        # Try to get file size
        fsize = data_file_sizes.get(filename, 0)
        if fsize == 0:
            for parent_dir in [data_dir, uploads_dir]:
                fpath = parent_dir / filename
                if fpath.exists():
                    fsize = os.path.getsize(fpath)
                    break

        # Check if we have a DB record for this file
        db_rec = db_by_stem.get(stem)
        
        # Determine status: if in Chroma with chunks → indexed, else use DB status
        if chunk_count > 0:
            status = "indexed"
        elif db_rec:
            status = db_rec.status
        else:
            status = "pending"

        # Reconcile chunk count: prefer Chroma count if available
        if chunk_count == 0 and db_rec and db_rec.chunks_count:
            chunk_count = db_rec.chunks_count

        doc_id = db_rec.id if db_rec else f"chroma::{filename}"
        original_name = (db_rec.original_name or filename) if db_rec else filename
        created_at = db_rec.created_at.isoformat() if db_rec else "2026-01-01T00:00:00"
        if db_rec and db_rec.file_size:
            fsize = db_rec.file_size

        all_docs.append({
            "id": doc_id,
            "filename": filename,
            "original_name": original_name,
            "file_type": ext,
            "file_size": fsize,
            "status": status,
            "chunks_count": chunk_count,
            "created_at": created_at,
        })

    # Sort by created_at desc (newest first), then filename
    all_docs.sort(key=lambda d: d["created_at"], reverse=True)

    total = len(all_docs)
    # Apply pagination
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    start = (page - 1) * page_size
    end = start + page_size
    paged = all_docs[start:end]

    return {
        "documents": paged,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 1,
    }




@router.get("/system-chunks")
async def get_system_document_chunks(
    filename: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve chunks for a system-indexed document from ChromaDB."""
    try:
        from src.api import get_engine
        engine = get_engine()
        store = engine.store
        if not store or not store.collection:
            raise HTTPException(status_code=503, detail="Vector store không khả dụng.")
            
        # Get chunks from ChromaDB filtered by source
        result = store.collection.get(
            where={"source": filename},
            include=["documents", "metadatas"]
        )
        
        documents = result.get("documents", [])
        metadatas = result.get("metadatas", [])
        ids = result.get("ids", [])
        
        chunks = []
        for doc_text, meta, cid in zip(documents, metadatas, ids):
            # Parse chunk_index
            try:
                chunk_index = int(meta.get("chunk_index", 0))
            except (ValueError, TypeError):
                chunk_index = 0
                
            chunks.append({
                "id": cid,
                "content": doc_text,
                "chunk_index": chunk_index,
                "metadata": meta
            })
            
        # Sort chunks by chunk_index
        chunks.sort(key=lambda x: x["chunk_index"])
        return chunks
    except Exception as e:
        logger.error(f"Error fetching system chunks for {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Không thể lấy phân mảnh tài liệu: {str(e)}")



@router.post("/upload", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    auto_index: bool = Form(default=True),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Upload a new document (admin only)."""
    # Check file extension
    ext = Path(file.filename).suffix.lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"File type '{ext}' không được hỗ trợ. Các định dạng được phép: {settings.ALLOWED_EXTENSIONS}",
        )

    # Check file size
    contents = await file.read()
    if len(contents) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File quá lớn (tối đa 10MB).")

    # Save to uploads dir
    save_path = Path(settings.UPLOAD_DIR) / file.filename
    with open(save_path, "wb") as f:
        f.write(contents)

    # Also copy .txt files directly to data/ or extract text from doc/docx/pdf
    data_dir = PROJECT_ROOT / "data"
    txt_filename = file.filename
    text_extracted = False
    
    if ext == ".txt":
        shutil.copy2(save_path, data_dir / file.filename)
        text_extracted = True
    elif ext in (".doc", ".docx", ".pdf"):
        txt_filename = Path(file.filename).stem + ".txt"
        try:
            from .chat_extended import _extract_text_from_file
            extracted_text = _extract_text_from_file(save_path, ext)
            if extracted_text.strip():
                (data_dir / txt_filename).write_text(extracted_text, encoding="utf-8")
                logger.info(f"Extracted and saved text from {file.filename} to {txt_filename}")
                text_extracted = True
            else:
                logger.warning(f"No text extracted from {file.filename}")
        except Exception as e:
            logger.error(f"Failed to extract text from {file.filename}: {e}")

    # Create DB record
    doc = Document(
        filename=file.filename,
        original_name=file.filename,
        file_type=ext,
        file_size=len(contents),
        uploaded_by=admin.id,
        status="pending",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # Auto-index if requested and text was prepared
    if auto_index and text_extracted:
        try:
            import anyio
            from src.api import get_engine
            engine = get_engine()
            from src.document_processor import process_document
            chunks = await anyio.to_thread.run_sync(
                lambda: process_document(str(data_dir / txt_filename), strategy="hybrid")
            )
            if chunks:
                await anyio.to_thread.run_sync(engine.store.add_chunks, chunks)
                try:
                    await anyio.to_thread.run_sync(lambda: engine.add_to_graph(chunks, extract_semantic=True))
                except Exception as e:
                    logger.error(f"Failed to add uploaded document to Neo4j graph: {e}")
            doc.status = "indexed"
            doc.chunks_count = len(chunks)
            await db.commit()
            logger.info(f"Auto-indexed {file.filename}: {doc.chunks_count} chunks")
        except Exception as e:
            logger.error(f"Auto-index failed: {e}")
            doc.status = "error"
            await db.commit()

    return {
        "id": doc.id,
        "filename": doc.filename,
        "file_size": doc.file_size,
        "status": doc.status,
        "chunks_count": doc.chunks_count,
    }


@router.delete("/{doc_id}", status_code=204)
async def delete_document(
    doc_id: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a document record (admin only) from SQL, ChromaDB, Neo4j, and physical files.
    Works regardless of document status (pending, indexed, error).
    """
    filename = None
    doc = None
    
    if doc_id.startswith("chroma::"):
        filename = doc_id.split("::", 1)[1]
    else:
        result = await db.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            # Try to find by stem match in case ID is a UUID but doc was re-created
            raise HTTPException(status_code=404, detail="Tài liệu không tồn tại.")
        filename = doc.filename

    uploads_dir = Path(settings.UPLOAD_DIR)
    data_dir = PROJECT_ROOT / "data"
    stem = Path(filename).stem

    # 1. Delete physical files from uploads and data directories (all extensions)
    for parent_dir in [uploads_dir, data_dir]:
        for fpath in parent_dir.glob(f"{stem}.*"):
            try:
                fpath.unlink()
                logger.info(f"Deleted file: {fpath}")
            except Exception as e:
                logger.error(f"Failed to delete file {fpath}: {e}")

    # Derive txt filename used in ChromaDB/Neo4j
    txt_filename = stem + ".txt"

    # 2. Delete from ChromaDB (vector store) — always attempt even if pending
    try:
        import anyio
        from src.api import get_engine
        engine = get_engine()
        await anyio.to_thread.run_sync(engine.store.delete_document, txt_filename)
        logger.info(f"Deleted vector index for document: {txt_filename}")
    except Exception as e:
        logger.error(f"Failed to delete vector index for {txt_filename}: {e}")

    # 3. Delete from Neo4j (graph store) — always attempt even if pending
    try:
        import anyio
        from src.graph_store import GraphStore
        
        def _delete_neo4j(fname):
            g_store = GraphStore()
            g_store.delete_document(fname)
            g_store.close()
            
        await anyio.to_thread.run_sync(_delete_neo4j, txt_filename)
        logger.info(f"Deleted graph nodes and relations for document: {txt_filename}")
    except Exception as e:
        logger.error(f"Failed to delete Neo4j graph data for {txt_filename}: {e}")

    # 4. Delete ALL SQLite records with matching filename stem (handles duplicates)
    result2 = await db.execute(select(Document))
    all_docs = result2.scalars().all()
    for d in all_docs:
        if Path(d.filename).stem.lower() == stem.lower():
            await db.delete(d)
            logger.info(f"Deleted database record for document: {d.filename} (ID: {d.id})")
    await db.commit()


@router.get("/stats")
async def document_stats(admin: User = Depends(get_current_admin)):
    """Get vector store stats (admin only)."""
    try:
        from src.api import get_engine
        engine = get_engine()
        return engine.get_stats()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── Private user-uploaded documents (not indexed, chunked locally) ──

@router.post("/user-upload", status_code=201)
async def user_upload_document(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a private document to chunk and check legality (open to all users, not indexed)."""
    # Check file extension
    ext = Path(file.filename).suffix.lower()
    if ext not in {'.txt', '.pdf', '.doc', '.docx'}:
        raise HTTPException(
            status_code=415,
            detail=f"File type '{ext}' không được hỗ trợ. Các định dạng được phép: .txt, .pdf, .doc, .docx",
        )

    # Check file size
    contents = await file.read()
    if len(contents) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File quá lớn (tối đa 10MB).")

    # Save to uploads dir temporarily
    tmp_path = Path(settings.UPLOAD_DIR) / f"user_{user.id}_{file.filename}"
    with open(tmp_path, "wb") as f:
        f.write(contents)

    try:
        from .chat_extended import _extract_text_from_file
        doc_text = _extract_text_from_file(tmp_path, ext)
    except Exception as e:
        logger.error(f"Error extracting text: {e}")
        doc_text = ""
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    if not doc_text.strip():
        raise HTTPException(status_code=400, detail="Không thể trích xuất nội dung văn bản.")

    # Chunking: first try hybrid chunking for legal structures
    chunk_contents = []
    try:
        from src.document_processor import hybrid_chunk
        chunks = hybrid_chunk(doc_text, {"source": file.filename})
        chunk_contents = [c.content for c in chunks if c.content.strip()]
    except Exception as e:
        logger.warning(f"hybrid_chunk failed: {e}")

    # If it returns a single giant chunk (e.g. general document) or failed, use paragraph/size-based chunking
    if not chunk_contents or (len(chunk_contents) == 1 and len(doc_text) > 1200):
        logger.info(f"Document {file.filename} does not match legal structures or is general text. Using general text chunker.")
        if "\n\n" in doc_text:
            paragraphs = [p.strip() for p in doc_text.split("\n\n") if p.strip()]
        else:
            paragraphs = [p.strip() for p in doc_text.split("\n") if p.strip()]
            
        chunk_contents = []
        current_chunk = ""
        for para in paragraphs:
            if len(current_chunk) + len(para) < 1200:
                current_chunk += ("\n\n" if current_chunk else "") + para
            else:
                if current_chunk:
                    chunk_contents.append(current_chunk)
                # If a single paragraph is too large, split it by words to avoid losing data
                if len(para) >= 1200:
                    words = para.split(" ")
                    sub_chunk = []
                    sub_len = 0
                    for word in words:
                        if sub_len + len(word) + 1 < 1200:
                            sub_chunk.append(word)
                            sub_len += len(word) + 1
                        else:
                            chunk_contents.append(" ".join(sub_chunk))
                            sub_chunk = [word]
                            sub_len = len(word)
                    current_chunk = " ".join(sub_chunk)
                else:
                    current_chunk = para
        if current_chunk:
            chunk_contents.append(current_chunk)

    if not chunk_contents:
        chunk_contents = [doc_text]

    from ...models.user_document import UserDocument, UserDocumentChunk
    
    # Create DB records
    user_doc = UserDocument(
        filename=file.filename,
        file_type=ext,
        file_size=len(contents),
        user_id=user.id,
    )
    db.add(user_doc)
    await db.commit()
    await db.refresh(user_doc)

    for idx, content in enumerate(chunk_contents):
        chunk_obj = UserDocumentChunk(
            doc_id=user_doc.id,
            chunk_index=idx,
            content=content
        )
        db.add(chunk_obj)
    
    await db.commit()

    return {
        "id": user_doc.id,
        "filename": user_doc.filename,
        "file_size": user_doc.file_size,
        "chunks_count": len(chunk_contents)
    }


@router.get("/user-documents")
async def list_user_documents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List private documents uploaded by current user."""
    from ...models.user_document import UserDocument
    result = await db.execute(
        select(UserDocument)
        .where(UserDocument.user_id == user.id)
        .order_by(UserDocument.created_at.desc())
    )
    docs = result.scalars().all()
    
    resp = []
    for d in docs:
        from sqlalchemy import func
        from ...models.user_document import UserDocumentChunk
        count_res = await db.execute(
            select(func.count(UserDocumentChunk.id)).where(UserDocumentChunk.doc_id == d.id)
        )
        count = count_res.scalar() or 0
        resp.append({
            "id": d.id,
            "filename": d.filename,
            "file_type": d.file_type,
            "file_size": d.file_size,
            "created_at": d.created_at.isoformat(),
            "chunks_count": count
        })
    return resp


@router.get("/user-documents/{doc_id}/chunks")
async def list_user_document_chunks(
    doc_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve chunks for a specific user document."""
    from ...models.user_document import UserDocument, UserDocumentChunk
    result = await db.execute(
        select(UserDocument)
        .where(UserDocument.id == doc_id, UserDocument.user_id == user.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Tài liệu không tồn tại hoặc không thuộc quyền sở hữu của bạn.")

    chunks_result = await db.execute(
        select(UserDocumentChunk)
        .where(UserDocumentChunk.doc_id == doc_id)
        .order_by(UserDocumentChunk.chunk_index.asc())
    )
    chunks = chunks_result.scalars().all()
    
    return [
        {
            "id": c.id,
            "chunk_index": c.chunk_index,
            "content": c.content
        }
        for c in chunks
    ]


@router.post("/chunks/{chunk_id}/check-legality")
async def check_chunk_legality(
    chunk_id: str,
    provider: str = Form(default="custom_trained"),
    api_url: str = Form(default=""),
    model_name: str = Form(default=""),
    temperature: float = Form(default=0.7),
    max_tokens: int = Form(default=2048),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Stream SSE legality check analysis for a specific text chunk."""
    from fastapi.responses import StreamingResponse
    from ...models.user_document import UserDocumentChunk, UserDocument
    
    result = await db.execute(
        select(UserDocumentChunk)
        .join(UserDocument)
        .where(UserDocumentChunk.id == chunk_id, UserDocument.user_id == user.id)
    )
    chunk = result.scalar_one_or_none()
    if not chunk:
        raise HTTPException(status_code=404, detail="Đoạn văn bản không tồn tại hoặc không thuộc quyền sở hữu của bạn.")

    prompt = (
        f"Hãy kiểm tra tính pháp lý của đoạn văn bản sau đây. Hãy phân tích chi tiết xem đoạn văn bản này có tuân thủ đúng pháp luật Việt Nam hay không, chỉ ra các điều luật/quy định pháp lý liên quan và các điểm cần lưu ý hoặc vi phạm:\n\n"
        f"\"\"\"\n{chunk.content}\n\"\"\""
    )

    custom_kwargs = dict(
        api_url=api_url,
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        enable_thinking=False
    )

    async def stream():
        from .chat_extended import _get_engine, _sse
        engine = _get_engine()
        try:
            for partial, src_md in engine.query_stream(
                question=prompt,
                top_k=5,
                provider=provider,
                use_graph=True,
                custom_kwargs=custom_kwargs
            ):
                yield _sse("answer", {"content": partial, "done": False})
            yield _sse("sources", {"content": src_md, "done": True})
            yield _sse("done", {"done": True})
        except Exception as e:
            logger.error(f"check_chunk_legality stream error: {e}")
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.delete("/user-documents/{doc_id}", status_code=204)
async def delete_user_document(
    doc_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a user private document (and cascades its chunks)."""
    from ...models.user_document import UserDocument, UserDocumentChunk
    from sqlalchemy import delete
    
    result = await db.execute(
        select(UserDocument)
        .where(UserDocument.id == doc_id, UserDocument.user_id == user.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Tài liệu không tồn tại hoặc không thuộc quyền sở hữu của bạn.")

    # Explicitly delete all chunks first to avoid async lazy loading cascade error
    await db.execute(
        delete(UserDocumentChunk)
        .where(UserDocumentChunk.doc_id == doc_id)
    )

    await db.delete(doc)
    await db.commit()


