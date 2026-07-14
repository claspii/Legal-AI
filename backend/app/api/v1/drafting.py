"""
Drafting API router: templates, layout analyzer, AI drafting generator (SSE), docx/pdf exporter.
"""

import os
import sys
import json
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger
from pydantic import BaseModel

from ...database import get_db
from ...models.user import User
from ...models.draft_templates import DraftTemplate
from ...models.chat import ChatSession, ChatMessage
from ...dependencies import get_current_user
from ...config import settings
from ...utils.document_generator import markdown_to_docx

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import config

router = APIRouter(prefix="/drafting", tags=["Drafting"])


# ---------------------------------------------------------------------------
# Intent detection helpers
# ---------------------------------------------------------------------------

# Regex keywords that indicate drafting intent (Vietnamese legal context)
_DRAFTING_KEYWORDS = [
    r"soạn\s*(thảo|ra|cho|giúp|hộ)?",
    r"viết\s*(cho|giúp|hộ|ra)?",
    r"tạo\s*(ra|cho|giúp)?\s*(văn\s*bản|hợp\s*đồng|đơn|biên\s*bản|thông\s*báo|nghị\s*quyết|quyết\s*định|tờ\s*trình|giấy\s*ủy\s*quyền|cam\s*kết|thỏa\s*thuận)",
    r"lập\s*(ra|cho|giúp)?\s*(văn\s*bản|hợp\s*đồng|đơn|biên\s*bản)",
    r"(hợp\s*đồng|biên\s*bản|đơn\s*(từ|xin|khiếu\s*nại|ly\s*hôn|nghỉ\s*việc)|giấy\s*ủy\s*quyền|cam\s*kết|thỏa\s*thuận|tờ\s*trình|thông\s*báo|nghị\s*quyết|quyết\s*định)\s*(mẫu|thuê|vay|bán|cho\s*vay|lao\s*động|dịch\s*vụ|mua\s*bán|hợp\s*tác)?",
]

# Template name/category keywords for smart selection
# Maps: category_hint -> list of Vietnamese keywords indicating that template
_TEMPLATE_CATEGORY_MAP = {
    "hop_dong_thue_nha": ["hợp đồng thuê nhà", "hợp đồng thuê phòng", "hợp đồng thuê trọ", "hợp đồng thuê mặt bằng", "thuê nhà", "thuê phòng"],
    "hop_dong_mua_ban": ["hợp đồng mua bán hàng hóa", "hợp đồng mua bán nhà", "hợp đồng mua bán đất", "mua bán tài sản", "mua bán hàng hóa"],
    "hop_dong_lao_dong": ["hợp đồng lao động", "hợp đồng thuê nhân viên", "hợp đồng làm việc", "hợp đồng thử việc"],
    "hop_dong_dich_vu": ["hợp đồng dịch vụ", "hợp đồng tư vấn", "hợp đồng gia công", "hợp đồng thuê khoán"],
    "hop_dong_vay": ["hợp đồng vay", "hợp đồng cho vay", "hợp đồng vay tiền"],
    "don_xin": ["đơn xin", "đơn từ", "đơn khiếu nại", "đơn xin nghỉ", "đơn xin việc", "đơn khởi kiện"],
    "bien_ban": ["biên bản", "biên bản họp", "biên bản giao nhận", "biên bản bàn giao"],
    "giay_uy_quyen": ["giấy ủy quyền", "ủy quyền"],
    "cam_ket": ["cam kết", "thỏa thuận", "cam kết không tái phạm"],
    "nda": ["thỏa thuận bảo mật", "bảo mật thông tin", "nda", "non-disclosure"],
}

# Map hint → template name (partial, for secondary matching)
_HINT_TO_TEMPLATE_NAME = {
    "hop_dong_thue_nha": "Hợp đồng thuê nhà",
    "hop_dong_mua_ban": "Hợp đồng mua bán hàng hóa",
    "hop_dong_lao_dong": "Hợp đồng lao động",
    "hop_dong_dich_vu": "Hợp đồng dịch vụ",
    "hop_dong_vay": "Hợp đồng vay",
    "don_xin": "Đơn khởi kiện dân sự",
    "bien_ban": "Biên bản",
    "giay_uy_quyen": "Giấy ủy quyền",
    "cam_ket": "Thỏa thuận",
    "nda": "Thỏa thuận bảo mật thông tin (NDA)",
}


class DetectIntentRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class DetectIntentResponse(BaseModel):
    is_drafting_intent: bool
    confidence: float
    document_type: Optional[str] = None
    template_hint: Optional[str] = None
    template_name: Optional[str] = None  # Exact template name for precise frontend matching
    extracted_inputs: dict = {}
    short_response: Optional[str] = None
    session_id: Optional[str] = None


@router.post("/detect-intent", response_model=DetectIntentResponse)
async def detect_drafting_intent(
    req: DetectIntentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Detect if a user message contains a legal document drafting intent.
    Stage 1: Regex fast-path (no LLM, ~5ms).
    Stage 2: LLM classification for ambiguous/no-diacritics cases (~1-2s).
    Returns classification + extracted metadata to pre-fill DraftingPanel.
    """
    import re
    import asyncio

    msg = req.message.strip()
    msg_lower = msg.lower()

    # ────────────────────────────────────────────────────────────────
    # STAGE 1 — REGEX FAST PATH
    # ────────────────────────────────────────────────────────────────
    regex_is_drafting = False
    for pattern in _DRAFTING_KEYWORDS:
        if re.search(pattern, msg_lower, re.IGNORECASE | re.UNICODE):
            regex_is_drafting = True
            break

    # Try to identify specific document type via keyword dict
    regex_doc_type = None
    regex_template_hint = None
    regex_confidence = 0.0

    if regex_is_drafting:
        regex_confidence = 0.7  # generic drafting keyword matched
        for category, keywords in _TEMPLATE_CATEGORY_MAP.items():
            for kw in keywords:
                if kw in msg_lower:
                    regex_doc_type = kw
                    regex_template_hint = category
                    regex_confidence = 0.95  # specific template matched
                    break
            if regex_template_hint:
                break

    # Fast exit: specific template keyword found → skip LLM, we're confident
    use_llm = not (regex_is_drafting and regex_confidence >= 0.95)

    # ────────────────────────────────────────────────────────────────
    # STAGE 2 — LLM CLASSIFICATION (only when regex is uncertain)
    # ────────────────────────────────────────────────────────────────
    llm_result = {}
    if use_llm:
        llm_prompt = (
            "Bạn là bộ phân loại ý định soạn thảo văn bản pháp lý.\n"
            "Nhiệm vụ: Phân tích câu sau và trả về JSON (KHÔNG giải thích thêm).\n\n"
            f"Câu người dùng: \"{msg}\"\n\n"
            "Trả về JSON với các trường sau:\n"
            "{\n"
            "  \"is_drafting\": true/false,\n"
            "  \"confidence\": 0.0-1.0,\n"
            "  \"document_type\": \"tên loại văn bản tiếng Việt hoặc null\",\n"
            "  \"template_hint\": \"hop_dong_thue_nha|hop_dong_mua_ban|hop_dong_lao_dong|hop_dong_dich_vu|hop_dong_vay|don_xin|bien_ban|giay_uy_quyen|cam_ket|nda|null\",\n"
            "  \"extracted\": {\n"
            "    \"ben_a\": \"tên bên A nếu có\",\n"
            "    \"ben_b\": \"tên bên B nếu có\",\n"
            "    \"so_tien\": \"số tiền nếu có (VD: 5.000.000 VNĐ)\",\n"
            "    \"gia_tri_hop_dong\": \"giá trị hợp đồng nếu có\",\n"
            "    \"thoi_han\": \"thời hạn nếu có (VD: 12 tháng)\",\n"
            "    \"ngay_ky\": \"ngày ký nếu có\",\n"
            "    \"dia_chi\": \"địa chỉ nếu có\"\n"
            "  }\n"
            "}\n\n"
            "Lưu ý: is_drafting=true khi người dùng muốn soạn/tạo/lập văn bản, hợp đồng, đơn, biên bản, giấy tờ pháp lý. "
            "Câu không có dấu tiếng Việt vẫn có thể là ý định soạn thảo."
        )

        try:
            from src.rag_engine import _call_llm_raw
            raw = await asyncio.to_thread(_call_llm_raw, llm_prompt, config.LLM_PROVIDER, {
                "gemini_model": config.GEMINI_MODEL,
                "api_url": os.environ.get("CUSTOM_MODEL_URL", ""),
                "model_name": "claspi2509/legal-AI-qwen3.5-q8-gguf",
                "temperature": 0.1,
                "max_tokens": 512,
            })
            # Parse JSON from LLM output (tolerate markdown fences)
            json_str = raw.strip()
            if "```" in json_str:
                json_str = json_str.split("```")[1]
                if json_str.startswith("json"):
                    json_str = json_str[4:]
            llm_result = json.loads(json_str.strip())
            logger.info(f"LLM intent detection result: {llm_result}")
        except Exception as e:
            logger.warning(f"LLM intent detection failed, using regex only: {e}")
            llm_result = {}

    # ────────────────────────────────────────────────────────────────
    # MERGE: regex + LLM results
    # ────────────────────────────────────────────────────────────────
    if use_llm and llm_result:
        is_drafting = llm_result.get("is_drafting", regex_is_drafting)
        confidence = float(llm_result.get("confidence", regex_confidence))
        doc_type = llm_result.get("document_type") or regex_doc_type
        template_hint = llm_result.get("template_hint") or regex_template_hint
        if template_hint == "null":
            template_hint = regex_template_hint
        if doc_type == "null":
            doc_type = regex_doc_type
        # LLM extracted entities
        extracted_raw = llm_result.get("extracted", {}) or {}
        extracted = {k: v for k, v in extracted_raw.items() if v and v != "null"}
    else:
        # Fast path — regex only
        is_drafting = regex_is_drafting
        confidence = regex_confidence
        doc_type = regex_doc_type
        template_hint = regex_template_hint
        extracted = {}

    if not is_drafting or confidence < 0.5:
        return DetectIntentResponse(is_drafting_intent=False, confidence=confidence)

    # ────────────────────────────────────────────────────────────────
    # REGEX ENTITY EXTRACTION (supplement LLM for fast-path cases)
    # ────────────────────────────────────────────────────────────────
    if not extracted:
        # Amount of money (VND)
        money_match = re.search(
            r'(\d[\d.,]*)\s*(triệu|tỷ|nghìn|ngàn|đồng|vnđ|vnd)',
            msg_lower, re.IGNORECASE
        )
        if money_match:
            raw_num = money_match.group(1).replace(',', '').replace('.', '')
            unit = money_match.group(2).lower()
            multiplier = {'triệu': 1_000_000, 'tỷ': 1_000_000_000, 'nghìn': 1_000, 'ngàn': 1_000}.get(unit, 1)
            try:
                amount = int(float(raw_num) * multiplier)
                extracted['so_tien'] = f"{amount:,} VNĐ".replace(',', '.')
                extracted['gia_tri_hop_dong'] = extracted['so_tien']
            except Exception:
                pass

        # Duration
        duration_match = re.search(r'(\d+)\s*(tháng|năm)', msg_lower, re.IGNORECASE)
        if duration_match:
            extracted['thoi_han'] = f"{duration_match.group(1)} {duration_match.group(2)}"

        # Date
        date_match = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})', msg_lower)
        if date_match:
            extracted['ngay_ky'] = date_match.group(0)

        # Parties
        party_a = re.search(r'(?:bên\s*a|bên\s*cho\s*thuê|giữa)\s*[:\s]*([^\s,\.]{2,30})', msg_lower, re.IGNORECASE)
        if party_a:
            extracted['ben_a'] = party_a.group(1).strip().title()
        party_b = re.search(r'(?:bên\s*b|bên\s*thuê|và)\s*[:\s]*([^\s,\.]{2,30})', msg_lower, re.IGNORECASE)
        if party_b:
            extracted['ben_b'] = party_b.group(1).strip().title()

        # Address
        address_match = re.search(r'(?:tại|địa\s*chỉ|ở)\s+(.{5,60})(?:[,\.]|$)', msg_lower, re.IGNORECASE)
        if address_match:
            extracted['dia_chi'] = address_match.group(1).strip()

    # Get precise template name
    template_name = _HINT_TO_TEMPLATE_NAME.get(template_hint) if template_hint else None

    # Short acknowledgement
    if doc_type:
        short_response = f"Được rồi! Tôi sẽ giúp bạn soạn thảo **{doc_type}**. Vui lòng kiểm tra và bổ sung thông tin trong bảng soạn thảo bên phải."
    else:
        short_response = "Tôi hiểu bạn cần soạn thảo một văn bản pháp lý. Vui lòng chọn loại văn bản và điền thông tin trong bảng soạn thảo."

    # ────────────────────────────────────────────────────────────────
    # PERSIST: save to chat session
    # ────────────────────────────────────────────────────────────────
    session_id = req.session_id
    if session_id:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user.id,
            )
        )
        session = result.scalar_one_or_none()
        if not session:
            session_id = None

    if not session_id:
        title = req.message[:50] + ("..." if len(req.message) > 50 else "")
        session = ChatSession(user_id=user.id, title=title)
        db.add(session)
        await db.commit()
        await db.refresh(session)
        session_id = session.id

    user_msg = ChatMessage(session_id=session_id, role="user", content=req.message)
    db.add(user_msg)
    bot_msg = ChatMessage(session_id=session_id, role="assistant", content=short_response)
    bot_msg.metadata_extra = {"is_drafting_ack": True}
    db.add(bot_msg)
    await db.commit()

    return DetectIntentResponse(
        is_drafting_intent=True,
        confidence=confidence,
        document_type=doc_type,
        template_hint=template_hint,
        template_name=template_name,
        extracted_inputs=extracted,
        short_response=short_response,
        session_id=session_id
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_rag_engine():
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


class StyleGuideModel(BaseModel):
    font_name: Optional[str] = "Times New Roman"
    font_size_body: Optional[str] = "12pt"
    alignment: Optional[str] = "justify"
    line_spacing: Optional[str] = "1.15"


def resolve_model_settings(
    provider: Optional[str],
    model_name: Optional[str],
    api_url: Optional[str] = None,
    selected_model_id: Optional[str] = None
) -> tuple[str, str, str]:
    """
    Resolves correct provider, model name/ID, and API URL by looking up in the model pool.
    Acts as a self-healing layer to prevent provider/model mismatches.
    """
    import json
    from pathlib import Path
    
    resolved_provider = provider or "gemini"
    resolved_model_name = model_name or ""
    resolved_api_url = api_url or ""
    
    pool_path = Path(__file__).parent.parent.parent.parent.parent.resolve() / "data" / "model_pool.json"
    
    pool = []
    if pool_path.exists():
        try:
            with open(pool_path, "r", encoding="utf-8") as f:
                pool = json.load(f)
        except Exception:
            pass
            
    # 1. Match by selected_model_id
    matched_model = None
    if selected_model_id:
        for m in pool:
            if m.get("id") == selected_model_id and m.get("is_active", True):
                matched_model = m
                break
                
    # 2. Match by model_name/model_id
    if not matched_model and model_name:
        for m in pool:
            if not m.get("is_active", True):
                continue
            m_name = m.get("model_name") or ""
            m_id = m.get("model_id") or ""
            if (m_name and m_name == model_name) or (m_id and m_id == model_name):
                matched_model = m
                break
                
    # 3. Match by fuzzy name (case-insensitive substring)
    if not matched_model and model_name:
        model_name_lower = model_name.lower()
        for m in pool:
            if not m.get("is_active", True):
                continue
            m_name = (m.get("model_name") or "").lower()
            m_id = (m.get("model_id") or "").lower()
            if (m_name and m_name in model_name_lower) or (m_id and m_id in model_name_lower) or (model_name_lower in m_name) or (model_name_lower in m_id):
                matched_model = m
                break

    if matched_model:
        resolved_provider = matched_model.get("provider") or resolved_provider
        resolved_api_url = matched_model.get("api_url") or resolved_api_url
        if resolved_provider == "gemini":
            resolved_model_name = matched_model.get("model_id") or resolved_model_name
        else:
            resolved_model_name = matched_model.get("model_name") or resolved_model_name
            
    # 4. Fallback heuristics for unmatched names to prevent calling wrong providers
    if resolved_model_name:
        model_name_lower = resolved_model_name.lower()
        if "qwen" in model_name_lower or "claspi" in model_name_lower or "unsloth" in model_name_lower:
            resolved_provider = "custom_trained"
        elif "gemini" in model_name_lower:
            resolved_provider = "gemini"
        elif "gpt-" in model_name_lower:
            resolved_provider = "openai"
            
    # Heuristics: if provider is custom_trained but api_url is empty, get first active custom model url
    if resolved_provider == "custom_trained" and not resolved_api_url:
        for m in pool:
            if m.get("provider") == "custom_trained" and m.get("is_active", True) and m.get("api_url"):
                resolved_api_url = m.get("api_url")
                break

    # Ensure sensible defaults if name is empty
    if not resolved_model_name:
        if resolved_provider == "gemini":
            from src import config as rag_config
            resolved_model_name = getattr(rag_config, "GEMINI_MODEL", "gemini-2.5-flash")
        elif resolved_provider == "openai":
            resolved_model_name = "gpt-4o"
        else:
            resolved_model_name = "claspi2509/legal-AI-qwen3.5-q8-gguf"
            
    return resolved_provider, resolved_model_name, resolved_api_url


class GenerateDraftRequest(BaseModel):
    template_id: Optional[str] = None
    reference_style_guide: Optional[dict] = None
    user_inputs: dict = {}
    custom_instructions: Optional[str] = ""
    session_id: Optional[str] = None
    provider: Optional[str] = "custom_trained"
    api_url: Optional[str] = ""
    model_name: Optional[str] = ""
    selected_model_id: Optional[str] = None
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 3000
    use_rag: Optional[bool] = True


class ExportDraftRequest(BaseModel):
    markdown: str
    format: str  # "docx" | "pdf"
    style_guide: Optional[StyleGuideModel] = None


@router.get("/templates")
async def list_templates(
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve all seeded legal templates."""
    stmt = select(DraftTemplate)
    if category:
        stmt = stmt.where(DraftTemplate.category == category)
    stmt = stmt.order_by(DraftTemplate.name.asc())
    
    result = await db.execute(stmt)
    templates = result.scalars().all()
    
    response = []
    for t in templates:
        placeholders_list = []
        if t.placeholders:
            try:
                placeholders_list = json.loads(t.placeholders)
            except Exception:
                placeholders_list = []
                
        response.append({
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "category": t.category,
            "placeholders": placeholders_list,
            "content": t.content
        })
    return response


@router.post("/analyze-reference")
async def analyze_reference(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user)
):
    """
    Upload a layout reference file (.docx or .pdf) to extract structure and style properties.
    """
    ext = Path(file.filename).suffix.lower()
    if ext not in {'.docx', '.pdf'}:
        raise HTTPException(415, "Định dạng file không được hỗ trợ. Vui lòng tải lên file .docx hoặc .pdf")

    contents = await file.read()
    if len(contents) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(413, "Kích thước tệp quá lớn (tối đa 10MB).")

    # Temp save path
    tmp_path = Path(settings.UPLOAD_DIR) / f"ref_style_{user.id}_{file.filename}"
    tmp_path.write_bytes(contents)

    style_guide = {
        "font_name": "Times New Roman",
        "font_size_body": "12pt",
        "alignment": "justify",
        "line_spacing": "1.15",
        "reference_name": file.filename
    }
    
    text_preview = ""

    try:
        if ext == ".docx":
            # Extract basic styling properties via python-docx
            try:
                import docx
                doc = docx.Document(str(tmp_path))
                
                # Analyze paragraphs for style guide properties
                font_names = {}
                font_sizes = {}
                alignments = {}
                
                heading_titles = []
                
                for p in doc.paragraphs[:50]:  # Scan first 50 paragraphs
                    text = p.text.strip()
                    if not text:
                        continue
                    
                    # Store text preview
                    if len(text_preview) < 800:
                        text_preview += text + "\n"
                        
                    # Extract alignment
                    align = p.alignment
                    if align is not None:
                        align_str = str(align).lower()
                        if "center" in align_str:
                            alignments["center"] = alignments.get("center", 0) + 1
                        elif "right" in align_str:
                            alignments["right"] = alignments.get("right", 0) + 1
                        elif "justify" in align_str:
                            alignments["justify"] = alignments.get("justify", 0) + 1
                        else:
                            alignments["left"] = alignments.get("left", 0) + 1
                            
                    for run in p.runs:
                        if run.font.name:
                            font_names[run.font.name] = font_names.get(run.font.name, 0) + 1
                        if run.font.size:
                            size_pt = f"{int(run.font.size.pt)}pt"
                            font_sizes[size_pt] = font_sizes.get(size_pt, 0) + 1
                
                # Pick dominant styling values
                if font_names:
                    style_guide["font_name"] = max(font_names, key=font_names.get)
                if font_sizes:
                    style_guide["font_size_body"] = max(font_sizes, key=font_sizes.get)
                if alignments:
                    style_guide["alignment"] = max(alignments, key=alignments.get)
                    
            except Exception as e:
                logger.warning(f"Error parsing styles from docx: {e}")
                style_guide["info"] = "Không thể trích xuất chi tiết; sử dụng cấu trúc mặc định."
                
        elif ext == ".pdf":
            # PDF file style guide layout defaults (since raw layout is static)
            try:
                from .chat_extended import _extract_text_from_file
                pdf_text = _extract_text_from_file(tmp_path, ".pdf")
                text_preview = pdf_text[:800]
                style_guide["info"] = "Trích xuất từ tệp PDF: định dạng văn bản chuẩn."
            except Exception as e:
                logger.warning(f"Error reading PDF: {e}")
                style_guide["info"] = "Lỗi khi trích xuất PDF."
                
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    return {
        "success": True,
        "style_guide": style_guide,
        "text_preview": text_preview
    }


@router.post("/generate")
async def generate_draft(
    req: GenerateDraftRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Stream legal draft generation using standard SSE, integrating model settings and RAG context.
    """
    # 1. Fetch template context if ID is provided
    template_content = ""
    template_name = "Văn bản pháp lý"
    
    if req.template_id:
        result = await db.execute(select(DraftTemplate).where(DraftTemplate.id == req.template_id))
        template = result.scalar_one_or_none()
        if not template:
            raise HTTPException(404, "Không tìm thấy mẫu văn bản pháp luật yêu cầu.")
        template_name = template.name
        template_content = template.content
        
        # Populate template parameters
        for k, v in req.user_inputs.items():
            template_content = template_content.replace(f"{{{{{k}}}}}", str(v))

    # 2. Retrieve RAG Context to verify compliance
    context = ""
    if req.use_rag:
        try:
            engine = _get_rag_engine()
            query_str = f"{template_name} {req.custom_instructions or ''}".strip()
            vector_hits = engine.store.query(query_str, top_k=5)
            
            if engine.graph_retriever is not None:
                try:
                    graph_hits = engine.graph_retriever.retrieve(
                        question=query_str,
                        vector_hits=vector_hits,
                    )
                    from src.hybrid_fusion import fuse, build_context
                    fused = fuse(vector_hits, graph_hits, top_n=8)
                    context = build_context(fused, max_chars=8000)
                except Exception as e:
                    logger.warning(f"Drafting graph retrieval failed: {e}")
                    context = "\n".join([h.get("content", "") for h in vector_hits if h.get("content")])
            else:
                context = "\n".join([h.get("content", "") for h in vector_hits if h.get("content")])
        except Exception as e:
            logger.error(f"Error retrieving RAG context for drafting: {e}")
            context = "Không tải được tài liệu RAG."

    # 3. Formulate custom legal prompt
    system_prompt = (
        "Bạn là chuyên gia soạn thảo văn bản pháp luật hàng đầu tại Việt Nam.\n"
        "Nhiệm vụ của bạn là soạn thảo một văn bản pháp lý chính xác, chặt chẽ, và TUÂN THỦ TUYỆT ĐỐI pháp luật Việt Nam.\n\n"
    )
    
    if context.strip():
        system_prompt += (
            "Dưới đây là các tài liệu luật tham khảo (RAG Context) để bạn đối chiếu tính hợp pháp của các điều khoản:\n"
            f"\"\"\"\n{context}\n\"\"\"\n\n"
        )
        
    system_prompt += (
        "HƯỚNG DẪN SOẠN THẢO VÀ ĐỊNH DẠNG (STYLE GUIDE):\n"
        "- Soạn thảo toàn bộ nội dung hoàn chỉnh bằng tiếng Việt.\n"
        "- Trình bày văn bản dạng Markdown sạch sẽ (sử dụng '# ' cho tiêu đề chính, '## ' cho tiêu đề phụ/Điều khoản, các khoản ký hiệu bằng số hoặc gạch đầu dòng).\n"
        "- Các tiêu đề quốc hiệu tiêu ngữ, tên hợp đồng/văn bản phải được đặt ở dòng riêng biệt.\n"
        "- Đảm bảo văn bản đầy đủ tất cả các cấu trúc chuẩn pháp lý từ đầu đến cuối bao gồm cả phần ký tên ở cuối văn bản.\n"
    )
    
    if req.reference_style_guide:
        style = req.reference_style_guide
        system_prompt += (
            f"- Áp dụng phong cách bố cục từ file tham khảo: Font chữ '{style.get('font_name', 'Times New Roman')}', "
            f"Cỡ chữ body '{style.get('font_size_body', '12pt')}', Căn lề '{style.get('alignment', 'justify')}' cho đoạn văn.\n"
        )
        
    system_prompt += (
        "\nLƯU Ý CỰC KỲ QUAN TRỌNG: CHỈ TRẢ VỀ NỘI DUNG VĂN BẢN PHÁP LÝ DƯỚI DẠNG MARKDOWN. KHÔNG ĐƯỢC CHỨA BẤT KỲ LỜI NÓI ĐẦU, LỜI KẾT, LỜI CHÀO HỎI HOẶC BÌNH LUẬN NÀO KHÁC."
    )

    user_prompt = "Hãy soạn thảo văn bản pháp lý hoàn chỉnh dựa trên các thông số sau:\n\n"
    if template_content:
        user_prompt += f"BẢN NHÁP MẪU BAN ĐẦU:\n\"\"\"\n{template_content}\n\"\"\"\n\n"
    if req.custom_instructions:
        user_prompt += f"YÊU CẦU BỔ SUNG/SỬA ĐỔI ĐẶC BIỆT:\n- {req.custom_instructions}\n\n"
        
    user_prompt += "Vui lòng điền và hoàn thiện toàn bộ các trường thông tin trống hoặc placeholder. Xuất ra tài liệu hoàn chỉnh sẵn sàng in ấn."

    # 4. Save to chat session if provided
    chat_session = None
    if req.session_id:
        result_sess = await db.execute(
            select(ChatSession).where(ChatSession.id == req.session_id, ChatSession.user_id == user.id)
        )
        chat_session = result_sess.scalar_one_or_none()
        if chat_session:
            user_msg = ChatMessage(
                session_id=chat_session.id,
                role="user",
                content=f"Yêu cầu soạn thảo văn bản '{template_name}'" + (f" với lưu ý: {req.custom_instructions}" if req.custom_instructions else "")
            )
            db.add(user_msg)
            await db.commit()

    # 5. Define SSE stream generator
    async def sse_stream():
        yield _sse("status", {"message": "Đang soạn thảo..."})
        
        # Resolve correct model provider, name and API URL using helper
        provider, model_name, api_url = resolve_model_settings(
            provider=req.provider,
            model_name=req.model_name,
            api_url=req.api_url,
            selected_model_id=req.selected_model_id
        )
        
        logger.info(f"Drafting generation started with model: {model_name} (provider: {provider}) (api_url: {api_url})")
        
        full_text = ""
        try:
            if provider == "custom_trained":
                import requests
                # Normalise API endpoint URL
                url = api_url.rstrip("/")
                if not url.startswith("http://") and not url.startswith("https://"):
                    raise RuntimeError(f"API URL không hợp lệ: '{url}'")
                if "/v1/chat/completions" not in url:
                    if url.endswith("/v1"):
                        url = url + "/chat/completions"
                    else:
                        url = url + "/v1/chat/completions"
                
                headers = {"Content-Type": "application/json"}
                data = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": req.temperature,
                    "max_tokens": req.max_tokens,
                    "stream": True
                }
                
                response = requests.post(url, headers=headers, json=data, stream=True, timeout=60)
                response.raise_for_status()
                
                for line in response.iter_lines():
                    if not line:
                        continue
                    line_str = line.decode('utf-8').strip()
                    if line_str.startswith("data: "):
                        data_content = line_str[6:]
                        if data_content == "[DONE]":
                            break
                        try:
                            chunk_json = json.loads(data_content)
                            delta = chunk_json["choices"][0]["delta"].get("content", "")
                            if delta:
                                full_text += delta
                                yield _sse("answer", {"content": full_text, "done": False})
                        except Exception:
                            pass
                            
            elif provider == "gemini":
                from google.genai import types
                from src.rag_engine import _create_gemini_client, _get_effective_gemini_model
                client = _create_gemini_client()
                effective_model = _get_effective_gemini_model(model_name)
                
                response = client.models.generate_content_stream(
                    model=effective_model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=req.temperature,
                        max_output_tokens=req.max_tokens
                    )
                )
                for chunk in response:
                    text_delta = chunk.text
                    if text_delta:
                        full_text += text_delta
                        yield _sse("answer", {"content": full_text, "done": False})
                        
            elif provider == "openai":
                from openai import OpenAI
                client = OpenAI(api_key=config.OPENAI_API_KEY)
                response = client.chat.completions.create(
                    model=model_name or "gpt-4o",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=req.temperature,
                    max_tokens=req.max_tokens,
                    stream=True
                )
                for chunk in response:
                    text_delta = chunk.choices[0].delta.content or ""
                    if text_delta:
                        full_text += text_delta
                        yield _sse("answer", {"content": full_text, "done": False})
            else:
                yield _sse("error", {"message": f"Provider '{provider}' không được hỗ trợ."})
                return
                
            yield _sse("done", {"content": full_text, "done": True})
            
            # Save Assistant message in session history if active
            if chat_session:
                from ...database import AsyncSessionLocal
                async with AsyncSessionLocal() as new_db:
                    async with new_db.begin():
                        ans, think = _parse_thinking_content(full_text)
                        new_db.add(ChatMessage(
                            session_id=chat_session.id,
                            role="assistant",
                            content=ans,
                            reasoning=think
                        ))
        except Exception as e:
            logger.error(f"SSE drafting error: {e}")
            yield _sse("error", {"message": f"Lỗi sinh văn bản: {str(e)}"})

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    )


@router.post("/export")
async def export_draft(
    req: ExportDraftRequest,
    user: User = Depends(get_current_user)
):
    """
    Export markdown document into binary styled DOCX files.
    """
    format_type = req.format.lower()
    style_guide = req.style_guide.dict() if req.style_guide else {}
    
    if format_type == "docx":
        try:
            docx_bytes = markdown_to_docx(req.markdown, style_guide)
            return Response(
                content=docx_bytes,
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={
                    "Content-Disposition": "attachment; filename=van_ban_phap_ly.docx"
                }
            )
        except Exception as e:
            logger.error(f"Export docx failed: {e}")
            raise HTTPException(500, f"Lỗi xuất file Word: {str(e)}")
    else:
        raise HTTPException(400, "Định dạng xuất file phải là 'docx'")
