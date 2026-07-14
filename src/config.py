import os
import re
from pathlib import Path
from dotenv import load_dotenv

# Enforce Hugging Face Hub offline mode to prevent connection errors and timeout crashes
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

load_dotenv(override=True)

BASE_DIR = Path(__file__).parent.parent


def _parse_neo4j_aura_export_files() -> dict[str, str]:
    """
    Đọc file export từ Neo4j Aura (Neo4j-*-Created-*.txt) nếu có trong thư mục dự án.
    Ưu tiên thấp hơn biến môi trường / .env (đã load bởi load_dotenv).
    """
    out: dict[str, str] = {}
    for path in sorted(BASE_DIR.glob("Neo4j-*-Created-*.txt")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Z0-9_]+)\s*=\s*(.*)$", line)
            if not m:
                continue
            key, val = m.group(1), m.group(2).strip().strip('"').strip("'")
            if val:
                out[key] = val
    return out


_AURA = _parse_neo4j_aura_export_files()


def _neo4j_from_env_or_aura(key: str, default: str = "") -> str:
    v = os.getenv(key)
    if v:
        return v
    return _AURA.get(key, default)

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Gemini via Vertex AI (theo style test.ipynb)
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
GOOGLE_GENAI_USE_VERTEXAI = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "True")
GEMINI_USE_VERTEXAI = GOOGLE_GENAI_USE_VERTEXAI.lower() == "true"

if GOOGLE_APPLICATION_CREDENTIALS:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS
if GOOGLE_CLOUD_PROJECT:
    os.environ["GOOGLE_CLOUD_PROJECT"] = GOOGLE_CLOUD_PROJECT
if GOOGLE_CLOUD_LOCATION:
    os.environ["GOOGLE_CLOUD_LOCATION"] = GOOGLE_CLOUD_LOCATION
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True" if GEMINI_USE_VERTEXAI else "False"

GEMINI_AVAILABLE = (
    GEMINI_USE_VERTEXAI and bool(GOOGLE_CLOUD_PROJECT)
) or bool(GOOGLE_API_KEY)

HF_TOKEN = os.getenv("HF_TOKEN", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", str(BASE_DIR / "chroma_db"))
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "legal_documents")

NEO4J_URI = _neo4j_from_env_or_aura("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = (
    os.getenv("NEO4J_USER")
    or os.getenv("NEO4J_USERNAME")
    or _AURA.get("NEO4J_USERNAME")
    or _AURA.get("NEO4J_USER")
    or "neo4j"
)
NEO4J_PASSWORD = _neo4j_from_env_or_aura("NEO4J_PASSWORD", "legalrag2026")
NEO4J_DATABASE = _neo4j_from_env_or_aura("NEO4J_DATABASE", "neo4j")

ENABLE_GRAPH_RETRIEVAL = os.getenv("ENABLE_GRAPH_RETRIEVAL", "true").lower() == "true"
GRAPH_EXPAND_HOPS = int(os.getenv("GRAPH_EXPAND_HOPS", "2"))
GRAPH_TOP_M = int(os.getenv("GRAPH_TOP_M", "5"))

GRAPH_RETRIEVAL_LOG_ENABLED = os.getenv("GRAPH_RETRIEVAL_LOG_ENABLED", "true").lower() == "true"
GRAPH_RETRIEVAL_LOG_PATH = os.getenv(
    "GRAPH_RETRIEVAL_LOG_PATH",
    str(BASE_DIR / "logs" / "graph_retrieval.log"),
)

LLM_CACHE_DIR = os.getenv("LLM_CACHE_DIR", str(BASE_DIR / ".llm_cache"))

DOCS_DIR = os.getenv("DOCS_DIR", str(BASE_DIR / "data"))
SUPPORTED_EXTENSIONS = {".txt"}

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))
MAX_CHUNK_SIZE = int(os.getenv("MAX_CHUNK_SIZE", "10000"))

TOP_K = int(os.getenv("TOP_K", "5"))
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.3"))

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "7860"))

SYSTEM_PROMPT = """Bạn là trợ lý pháp luật Việt Nam chuyên nghiệp. Nhiệm vụ của bạn là trả lời câu hỏi về pháp luật dựa trên các tài liệu luật được cung cấp.

Quy tắc:
1. CHỈ trả lời và phân tích dựa trên nội dung tài liệu được cung cấp trong phần "Tài liệu tham khảo". Tuyệt đối KHÔNG được sử dụng, viện dẫn hoặc bổ sung bất kỳ kiến thức, điều luật hay văn bản pháp luật nào nằm ngoài các tài liệu được cung cấp này.
2. Trích dẫn cụ thể Điều, Khoản, Điểm khi trả lời
3. Nếu không tìm thấy thông tin liên quan, hãy nói rõ
4. Trả lời bằng tiếng Việt, rõ ràng và dễ hiểu
5. Nêu rõ nguồn tài liệu (tên văn bản luật, số hiệu) khi trích dẫn
6. Hãy suy nghĩ thật kỹ, phân tích sâu sắc các khía cạnh pháp lý và tự kiểm tra lại (recheck) lập luận của mình nhiều lần trong quá trình tư duy trước khi đưa ra kết quả cuối cùng để đảm bảo tính chính xác và tối ưu nhất.
7. Câu trả lời phải được phân tích và giải thích cặn kẽ, chi tiết, đảm bảo làm sáng tỏ các quy định pháp lý và lập luận rõ ràng cách áp dụng vào trường hợp cụ thể. Mọi lập luận, phân tích và giải thích phải hoàn toàn nằm trong phạm vi các điều luật được cung cấp ở phần "Tài liệu tham khảo", không tự ý liên hệ với các điều luật khác ngoài ngữ cảnh."""
