# 🏛️ Legal RAG — Trợ lý Pháp luật Việt Nam v2.0

Hệ thống hỏi đáp pháp luật thông minh sử dụng Hybrid RAG (Vector + Knowledge Graph) kết hợp model ngôn ngữ đã fine-tuned chuyên về luật Việt Nam.

![Tech Stack](https://img.shields.io/badge/Backend-FastAPI-009688?style=flat-square&logo=fastapi)
![Tech Stack](https://img.shields.io/badge/Frontend-React_18-61DAFB?style=flat-square&logo=react)
![Tech Stack](https://img.shields.io/badge/Database-SQLite-003B57?style=flat-square&logo=sqlite)
![Tech Stack](https://img.shields.io/badge/RAG-Hybrid_Vector_+_Graph-4A90D9?style=flat-square)

---

## ✨ Tính năng

### Giao diện Chat
- 💬 **Streaming chat** — SSE streaming real-time từ model
- 🧠 **Thinking/CoT** — Hiển thị quá trình suy luận của model (collapsible)
- 📚 **Sources panel** — Danh sách tài liệu tham khảo
- 🎙️ **Speech-to-Text** — Ghi âm tiếng Việt (vi-VN) qua Web Speech API
- 📎 **File upload** — Upload .doc/.pdf/.txt để phân tích pháp luật
- 🖼️ **Image support** — Dán/upload ảnh để query multimodal model (Ctrl+V)
- 💾 **Session history** — Lưu lịch sử chat vào SQLite

### RAG Engine
- **Hybrid retrieval**: Vector similarity (BAAI/bge-m3) + Knowledge Graph (Neo4j)
- **Hybrid fusion**: RRF scoring để kết hợp kết quả
- **Custom fine-tuned model**: Qwen3.5 SFT trên dataset pháp luật VN
- **Multi-provider**: Custom model, Gemini 2.5 Flash/Pro, OpenRouter

### Auth & Admin
- 🔐 **JWT authentication** — Access + Refresh token
- 👥 **Role-based access** — User / Admin roles
- 📊 **Admin Dashboard** — Stats, documents, users management
- 📁 **Document management** — Upload, auto-index, delete

---

## 🚀 Chạy local (Development)

### Prerequisites
- Python 3.10+ (conda env: `chatbot`)
- Node.js 18+
- Neo4j (optional — cho knowledge graph)

### Backend
```powershell
# Activate conda env
conda activate chatbot

# Install backend deps
pip install -r backend/requirements.txt

# Start FastAPI server
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend

> ⚠️ **Windows/Conda note:** `conda activate` có thể xoá Node.js khỏi PATH.  
> Mở **terminal mới** (không cần activate conda) rồi chạy:

```powershell
# Terminal mới (KHÔNG activate conda)
cd frontend
npm install        # lần đầu hoặc sau khi thêm package
npm run dev
```

**Nếu gặp lỗi `node.exe is not recognized`** trong terminal đang dùng conda:
```powershell
# Thêm Node.js vào PATH trong session hiện tại
$env:PATH = "C:\Program Files\nodejs;" + $env:PATH
cd frontend
npm run dev
```

### Truy cập
| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| Swagger Docs | http://localhost:8000/docs |

**Default admin:** `admin@legalrag.vn` / `admin123`

---

## 🐳 Deploy với Docker

```bash
# Copy env file
cp .env.example .env
# Chỉnh sửa .env với giá trị thực

# Build và chạy
docker compose up -d --build

# Xem logs
docker compose logs -f backend

# Dừng
docker compose down
```

Sau khi chạy, truy cập http://localhost (port 80).

### Deploy lên Cloud

#### Google Cloud Run
```bash
gcloud builds submit --tag gcr.io/PROJECT_ID/legal-rag-backend --dockerfile Dockerfile.backend
gcloud run deploy legal-rag-backend --image gcr.io/PROJECT_ID/legal-rag-backend --port 8000
```

#### Railway / Render
- Connect GitHub repo
- Set environment variables từ `.env.example`
- Deploy `Dockerfile.backend` cho backend
- Deploy `Dockerfile.frontend` cho frontend

---

## 📁 Cấu trúc Project

```
doan/
├── src/                    # RAG Core (legacy)
│   ├── rag_engine.py       # Main RAG engine (singleton)
│   ├── hybrid_fusion.py    # Vector + Graph fusion
│   ├── graph_rag.py        # Neo4j integration
│   └── api.py              # Engine API wrapper
├── backend/                # FastAPI Backend
│   ├── app/
│   │   ├── main.py         # FastAPI entry point + lifespan
│   │   ├── config.py       # Settings (Pydantic)
│   │   ├── database.py     # SQLAlchemy async
│   │   ├── models/         # ORM models (User, Chat, Document)
│   │   ├── schemas/        # Pydantic schemas
│   │   ├── api/v1/
│   │   │   ├── auth.py     # /auth/* endpoints
│   │   │   ├── chat.py     # /chat/* (SSE streaming)
│   │   │   ├── chat_extended.py  # /chat/upload-check, /query-with-image
│   │   │   ├── documents.py      # /documents/* (admin)
│   │   │   └── admin.py          # /admin/* (stats, users)
│   │   ├── dependencies.py # get_current_user, get_current_admin
│   │   └── utils/
│   │       └── security.py # PBKDF2 hash + JWT
│   └── requirements.txt
├── frontend/               # React + Vite Frontend
│   ├── src/
│   │   ├── pages/          # LoginPage, RegisterPage, ChatPage, AdminPage
│   │   ├── components/
│   │   │   ├── chat/       # ChatInput, SettingsPanel, SourcesPanel, ThinkingBlock
│   │   │   └── common/     # ProtectedRoute
│   │   ├── stores/         # authStore, chatStore, settingsStore (Zustand)
│   │   ├── services/       # api.js (Axios), authService, chatService
│   │   └── styles/         # globals.css, components/
│   └── vite.config.js      # Dev proxy → :8000
├── data/                   # Corpus .txt files (pháp luật)
├── training/               # Fine-tuning scripts
├── Dockerfile.backend      # Production backend image
├── Dockerfile.frontend     # Production frontend (multi-stage)
├── nginx.conf              # Nginx với API proxy + SPA routing
├── docker-compose.yml      # Full stack deployment
└── .env.example            # Environment variables template
```

---

## 🔌 API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/auth/login` | Public | Đăng nhập |
| POST | `/api/v1/auth/register` | Public | Đăng ký |
| GET | `/api/v1/auth/me` | User | Profile |
| GET | `/api/v1/chat/sessions` | User | Danh sách phiên |
| POST | `/api/v1/chat/stream` | User | Stream chat (SSE) |
| POST | `/api/v1/chat/upload-check` | User | Upload file + check |
| POST | `/api/v1/chat/query-with-image` | User | Query với ảnh |
| GET | `/api/v1/documents/` | User | Danh sách tài liệu |
| POST | `/api/v1/documents/upload` | Admin | Upload tài liệu |
| GET | `/api/v1/admin/stats` | Admin | Thống kê hệ thống |
| GET | `/api/v1/admin/users` | Admin | Danh sách users |

Full Swagger docs: http://localhost:8000/docs

---

## 🏗️ Kiến trúc

```
Browser (React)
    │  JWT Bearer
    ▼
FastAPI Backend (port 8000)
    │  SQLite (async SQLAlchemy)
    │  Auth, Sessions, History
    ▼
RAG Engine (src/rag_engine.py)
    ├── VectorDB (ChromaDB + BAAI/bge-m3)
    ├── Knowledge Graph (Neo4j)
    └── LLM Provider
        ├── Custom Fine-tuned (ngrok → Colab/vLLM)
        ├── Google Gemini 2.5 Flash/Pro
        └── OpenRouter
```
