"""
FastAPI endpoints cho hệ thống RAG pháp luật.
"""

import threading
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from loguru import logger

from . import config

_engine = None
_engine_lock = threading.Lock()
_engine_loading = False


def get_engine():
    """Lấy RAG engine instance (singleton, thread-safe)."""
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is None:
            from .rag_engine import RAGEngine
            logger.info("Khởi tạo RAG engine...")
            _engine = RAGEngine()
            logger.info("RAG engine sẵn sàng")
    return _engine


def _preload_engine():
    global _engine_loading
    _engine_loading = True
    try:
        get_engine()
    finally:
        _engine_loading = False


def start_background_loading():
    """Load model ở background thread để server khởi động nhanh."""
    t = threading.Thread(target=_preload_engine, daemon=True)
    t.start()


def is_engine_ready() -> bool:
    return _engine is not None


api = FastAPI(
    title="Legal RAG API",
    description="API hỏi đáp tài liệu pháp luật Việt Nam",
    version="1.0.0",
)


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=2, description="Câu hỏi về pháp luật")
    top_k: int = Field(default=5, ge=1, le=20)
    provider: Optional[str] = Field(default=None, description="gemini hoặc openai")


class QueryResponse(BaseModel):
    answer: str
    sources: list[dict]
    query: str
    llm_provider: str


class IndexRequest(BaseModel):
    docs_dir: Optional[str] = Field(default=None)
    strategy: str = Field(default="hybrid", description="chapter/article/clause/hybrid")


class IndexResponse(BaseModel):
    chunks_processed: int
    total_in_store: int
    strategy: str


class StatsResponse(BaseModel):
    total_chunks: int
    documents: list[str]
    document_count: int
    collection: str
    embedding_model: str
    graph_enabled: Optional[bool] = False


class QueryRequestGraph(BaseModel):
    question: str = Field(..., min_length=2)
    top_k: int = Field(default=5, ge=1, le=20)
    provider: Optional[str] = None
    use_graph: Optional[bool] = None


class CypherRequest(BaseModel):
    cypher: str = Field(..., min_length=3, description="Cypher read-only")
    params: Optional[dict] = None


class BuildGraphRequest(BaseModel):
    strategy: str = Field(default="hybrid")
    extract_semantic: bool = Field(default=False)
    clear: bool = Field(default=False)
    max_semantic: Optional[int] = None


@api.get("/api/health")
def health():
    return {"status": "ok", "llm_provider": config.LLM_PROVIDER}


@api.post("/api/query", response_model=QueryResponse)
def query(req: QueryRequest):
    engine = get_engine()
    if engine.store.collection.count() == 0:
        raise HTTPException(
            status_code=400,
            detail="Chưa có tài liệu nào. Gọi POST /api/index trước.",
        )

    result = engine.query(
        question=req.question,
        top_k=req.top_k,
        provider=req.provider,
    )
    return QueryResponse(
        answer=result.answer,
        sources=result.sources,
        query=result.query,
        llm_provider=result.llm_provider,
    )


@api.post("/api/query_hybrid")
def query_hybrid(req: QueryRequestGraph):
    engine = get_engine()
    if engine.store.collection.count() == 0:
        raise HTTPException(status_code=400, detail="Chưa có dữ liệu vector")
    result = engine.query(
        question=req.question,
        top_k=req.top_k,
        provider=req.provider,
        use_graph=req.use_graph,
    )
    return {
        "answer": result.answer,
        "sources": result.sources,
        "query": result.query,
        "llm_provider": result.llm_provider,
        "retrieval_mode": result.retrieval_mode,
        "fusion_info": result.fusion_info,
    }


@api.post("/api/index", response_model=IndexResponse)
def index_documents(req: IndexRequest = IndexRequest()):
    engine = get_engine()
    result = engine.index_documents(
        docs_dir=req.docs_dir,
        strategy=req.strategy,
    )
    return IndexResponse(**result)


@api.get("/api/stats", response_model=StatsResponse)
def stats():
    engine = get_engine()
    return StatsResponse(**engine.get_stats())


@api.get("/api/documents")
def list_documents():
    engine = get_engine()
    return {"documents": engine.store.get_all_documents()}


@api.delete("/api/collection")
def clear_collection():
    engine = get_engine()
    engine.store.delete_collection()
    return {"status": "cleared"}


@api.delete("/api/documents/{source_name}")
def delete_document(source_name: str):
    engine = get_engine()
    engine.store.delete_document(source_name)
    return {"status": "deleted", "source": source_name}


# ---------------------------------------------------------------------------
# Knowledge Graph endpoints
# ---------------------------------------------------------------------------

def _get_graph_store():
    from .graph_store import GraphStore
    try:
        return GraphStore()
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Không kết nối được Neo4j: {e}. Chạy 'docker-compose up -d neo4j' trước.",
        )


@api.post("/api/graph/build")
def graph_build(req: BuildGraphRequest = BuildGraphRequest()):
    """Build/rebuild knowledge graph từ data/."""
    from scripts.build_graph import build
    try:
        result = build(
            strategy=req.strategy,
            extract_semantic=req.extract_semantic,
            clear=req.clear,
            max_semantic=req.max_semantic,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api.get("/api/graph/stats")
def graph_stats():
    store = _get_graph_store()
    try:
        return store.stats_simple()
    finally:
        store.close()


@api.post("/api/graph/cypher")
def graph_cypher(req: CypherRequest):
    """Chạy Cypher read-only. Các từ khóa ghi sẽ bị chặn."""
    store = _get_graph_store()
    try:
        rows = store.safe_read_cypher(req.cypher, req.params or {})
        # Serialize: chuyển Node/Rel về dict
        out = []
        for r in rows:
            item = {}
            for k, v in r.items():
                if hasattr(v, "items"):
                    item[k] = dict(v)
                else:
                    item[k] = v
            out.append(item)
        return {"rows": out, "count": len(out)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store.close()


@api.get("/api/graph/neighbors/{node_type}/{node_id:path}")
def graph_neighbors(node_type: str, node_id: str, depth: int = 1):
    """Lấy subgraph quanh 1 node. depth 1-3."""
    from .graph_retriever import GraphRetriever
    store = _get_graph_store()
    try:
        retriever = GraphRetriever(store=store)
        return retriever.neighbors(node_type, node_id, depth=depth)
    finally:
        store.close()
