"""
Extended chat endpoints: file-based legal check and image query.
Appended to the chat router.
"""

import base64
import sys
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import json
from loguru import logger

from ...database import get_db
from ...models.user import User
from ...models.chat import ChatSession, ChatMessage
from ...dependencies import get_current_user
from ...config import settings

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

router = APIRouter(prefix="/chat", tags=["Chat Extended"])

ALLOWED_DOC_EXTS = {'.txt', '.pdf', '.doc', '.docx'}
ALLOWED_IMG_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_engine():
    from src.api import get_engine
    return get_engine()


def _parse_thinking_content(text: str) -> tuple[str, str | None]:
    if not text:
        return "", None
    open_tag = "<think>"
    close_tag = "</think>"
    start = text.find(open_tag)
    end = text.find(close_tag)
    
    if start != -1 and end > start:
        thinking = text[start + len(open_tag):end].strip()
        answer = text[end + len(close_tag):].strip()
        return answer, thinking
    if start != -1 and end == -1:
        thinking = text[start + len(open_tag):].strip()
        return "", thinking
    return text, None


def _extract_text_from_file(file_path: Path, ext: str) -> str:
    """Extract plain text from uploaded document."""
    if ext == '.txt':
        return file_path.read_text(encoding='utf-8', errors='ignore')
    elif ext == '.pdf':
        text = ""
        # 1. Try pdfplumber
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
        except Exception as e:
            logger.warning(f"pdfplumber extraction failed: {e}")
            
        # 2. Try pypdf if text is empty/too short
        if len(text.strip()) < 100:
            try:
                import pypdf
                reader = pypdf.PdfReader(file_path)
                text = '\n'.join(page.extract_text() or '' for page in reader.pages)
            except Exception as e:
                logger.warning(f"pypdf extraction failed: {e}")

        # 3. Try fitz (PyMuPDF) if text is still empty/too short
        if len(text.strip()) < 100:
            try:
                import fitz
                doc = fitz.open(str(file_path))
                text = '\n'.join(page.get_text() for page in doc)
            except Exception as e:
                logger.warning(f"fitz extraction failed: {e}")

        if not text.strip():
            return f"[Không thể đọc PDF — tài liệu trống hoặc không có nội dung chữ trích xuất được]"
            
        return text
    elif ext in ('.doc', '.docx'):
        try:
            import docx
            d = docx.Document(str(file_path))
            return '\n'.join(p.text for p in d.paragraphs)
        except ImportError:
            try:
                import zipfile
                import xml.etree.ElementTree as ET
                
                texts = []
                with zipfile.ZipFile(file_path) as docx_zip:
                    xml_content = docx_zip.read('word/document.xml')
                    root = ET.fromstring(xml_content)
                    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                    for p in root.findall('.//w:p', ns):
                        p_texts = []
                        for t in p.findall('.//w:t', ns):
                            if t.text:
                                p_texts.append(t.text)
                        if p_texts:
                            texts.append(''.join(p_texts))
                return '\n'.join(texts)
            except Exception as e:
                return f"[Không thể đọc DOCX — cài python-docx hoặc lỗi: {e}]"
    return ''


@router.post("/upload-check")
async def upload_check(
    file: UploadFile = File(...),
    question: str = Form(default="Phân tích tài liệu này có vi phạm pháp luật không?"),
    session_id: str = Form(default=None),
    top_k: int = Form(default=5),
    use_graph: bool = Form(default=True),
    provider: str = Form(default='custom_trained'),
    api_url: str = Form(default=''),
    model_name: str = Form(default=''),
    temperature: float = Form(default=0.7),
    max_tokens: int = Form(default=2048),
    enable_thinking: bool = Form(default=False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a doc/pdf/txt and check for legal issues via streaming SSE."""
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_DOC_EXTS:
        raise HTTPException(415, f"File type '{ext}' không được hỗ trợ.")

    contents = await file.read()
    if len(contents) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(413, "File quá lớn (tối đa 10MB).")

    # Save temporarily
    tmp_path = Path(settings.UPLOAD_DIR) / f"tmp_{file.filename}"
    tmp_path.write_bytes(contents)

    try:
        doc_text = _extract_text_from_file(tmp_path, ext)
    finally:
        tmp_path.unlink(missing_ok=True)

    if not doc_text.strip():
        raise HTTPException(400, "Không thể trích xuất nội dung từ file.")

    # Build combined question
    combined_question = (
        f"[TÀI LIỆU UPLOAD: {file.filename}]\n\n"
        f"{doc_text[:6000]}"
        f"\n\n---\n\nCÂU HỎI: {question}"
    )

    # Get/create session
    from sqlalchemy import select
    if session_id:
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(404, "Phiên chat không tồn tại.")
    else:
        session = ChatSession(user_id=user.id, title=f"Check: {file.filename}")
        db.add(session)
        await db.commit()
        await db.refresh(session)

    # Save user message
    user_msg = ChatMessage(session_id=session.id, role="user",
                           content=f"📎 {file.filename}\n\n{question}")
    db.add(user_msg)
    await db.commit()

    custom_kwargs = dict(api_url=api_url, model_name=model_name, temperature=temperature,
                         max_tokens=max_tokens, enable_thinking=enable_thinking)

    async def stream():
        engine = _get_engine()
        yield _sse("session", {"session_id": session.id})
        full_answer = ""
        try:
            for partial, src_md in engine.query_stream(
                question=combined_question, top_k=top_k,
                provider=provider, use_graph=use_graph, custom_kwargs=custom_kwargs,
            ):
                full_answer = partial
                yield _sse("answer", {"content": partial, "done": False})
            yield _sse("sources", {"content": src_md, "done": True})
            yield _sse("done", {"session_id": session.id, "done": True})
        except Exception as e:
            logger.error(f"upload-check stream error: {e}")
            yield _sse("error", {"message": str(e)})
            full_answer = f"Lỗi: {e}"

        try:
            from ...database import AsyncSessionLocal
            async with AsyncSessionLocal() as new_db:
                async with new_db.begin():
                    ans, think = _parse_thinking_content(full_answer)
                    new_db.add(ChatMessage(
                        session_id=session.id, role="assistant", content=ans, reasoning=think
                    ))

                    # Record estimated token usage
                    from ...models.token_usage import TokenUsage
                    p_tokens = max(1, len(combined_question) // 4)
                    c_tokens = max(1, len(full_answer) // 4)
                    total = p_tokens + c_tokens

                    token_usage = TokenUsage(
                        user_id=user.id,
                        source="chatbot",
                        prompt_tokens=p_tokens,
                        completion_tokens=c_tokens,
                        total_tokens=total,
                        model_name=provider or "custom_trained",
                        user_prompt=combined_question[:2000],
                        response_preview=full_answer[:500],
                    )
                    new_db.add(token_usage)
        except Exception as e:
            logger.error(f"Failed saving assistant msg: {e}")

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/query-with-image")
async def query_with_image(
    image: UploadFile = File(...),
    question: str = Form(default="Hình ảnh này liên quan đến luật gì?"),
    session_id: str = Form(default=None),
    top_k: int = Form(default=5),
    use_graph: bool = Form(default=True),
    provider: str = Form(default='custom_trained'),
    api_url: str = Form(default=''),
    model_name: str = Form(default=''),
    temperature: float = Form(default=0.7),
    max_tokens: int = Form(default=2048),
    enable_thinking: bool = Form(default=False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send image + question to the custom multimodal model via streaming SSE."""
    ext = Path(image.filename).suffix.lower()
    if ext not in ALLOWED_IMG_EXTS:
        raise HTTPException(415, f"Image type '{ext}' không được hỗ trợ.")

    contents = await image.read()
    if len(contents) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(413, "Ảnh quá lớn (tối đa 10MB).")

    # Encode image as base64
    img_b64 = base64.b64encode(contents).decode()
    mime_type = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
        '.webp': 'image/webp', '.gif': 'image/gif',
    }.get(ext, 'image/jpeg')

    # Get/create session
    from sqlalchemy import select
    if session_id:
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(404, "Phiên chat không tồn tại.")
    else:
        session = ChatSession(user_id=user.id, title=f"🖼️ {image.filename}")
        db.add(session)
        await db.commit()
        await db.refresh(session)

    user_msg = ChatMessage(session_id=session.id, role="user",
                           content=f"🖼️ {image.filename}\n\n{question}")
    db.add(user_msg)
    await db.commit()

    custom_kwargs = dict(
        api_url=api_url, model_name=model_name, temperature=temperature,
        max_tokens=max_tokens, enable_thinking=enable_thinking,
        # Pass image data to the engine
        image_data=img_b64, image_mime=mime_type,
    )

    async def stream():
        engine = _get_engine()
        yield _sse("session", {"session_id": session.id})
        full_answer = ""
        try:
            for partial, src_md in engine.query_stream(
                question=question, top_k=top_k,
                provider=provider, use_graph=use_graph, custom_kwargs=custom_kwargs,
            ):
                full_answer = partial
                yield _sse("answer", {"content": partial, "done": False})
            yield _sse("sources", {"content": src_md, "done": True})
            yield _sse("done", {"session_id": session.id, "done": True})
        except Exception as e:
            logger.error(f"image-query stream error: {e}")
            yield _sse("error", {"message": str(e)})
            full_answer = f"Lỗi: {e}"

        try:
            from ...database import AsyncSessionLocal
            async with AsyncSessionLocal() as new_db:
                async with new_db.begin():
                    ans, think = _parse_thinking_content(full_answer)
                    new_db.add(ChatMessage(
                        session_id=session.id, role="assistant", content=ans, reasoning=think
                    ))

                    # Record estimated token usage
                    from ...models.token_usage import TokenUsage
                    # Prompt text + estimated image overhead (e.g. 1000 tokens)
                    p_tokens = max(1, len(question) // 4) + 1000
                    c_tokens = max(1, len(full_answer) // 4)
                    total = p_tokens + c_tokens

                    token_usage = TokenUsage(
                        user_id=user.id,
                        source="chatbot",
                        prompt_tokens=p_tokens,
                        completion_tokens=c_tokens,
                        total_tokens=total,
                        model_name=provider or "custom_trained",
                        user_prompt=question[:2000],
                        response_preview=full_answer[:500],
                    )
                    new_db.add(token_usage)
        except Exception as e:
            logger.error(f"Failed saving assistant msg: {e}")

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
