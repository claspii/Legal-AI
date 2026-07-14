"""
Vector store dùng ChromaDB + SentenceTransformer.
Embedding tự động dùng GPU (CUDA) nếu có, fallback về CPU.
"""

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from loguru import logger

from . import config
from .document_processor import DocumentChunk


class VectorStore:
    def __init__(
        self,
        persist_dir: str = None,
        collection_name: str = None,
        embedding_model: str = None,
    ):
        self.persist_dir = persist_dir or config.CHROMA_PERSIST_DIR
        self.collection_name = collection_name or config.CHROMA_COLLECTION
        self.model_name = embedding_model or config.EMBEDDING_MODEL

        import os
        is_offline = os.environ.get("HF_HUB_OFFLINE") == "1" or os.environ.get("TRANSFORMERS_OFFLINE") == "1"
        if config.HF_TOKEN and not is_offline:
            from huggingface_hub import login
            login(token=config.HF_TOKEN, add_to_git_credential=False)

        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Loading embedding model {self.model_name} on {device.upper()}...")
        self.embedder = SentenceTransformer(self.model_name, device=device)
        logger.info(f"Embedding model loaded on {device.upper()}")

        self.client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            f"ChromaDB: {self.collection.count()} docs in '{self.collection_name}'"
        )

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return self.embedder.encode(texts, show_progress_bar=False).tolist()

    def add_chunks(self, chunks: list[DocumentChunk], batch_size: int = 64):
        if not chunks:
            return

        existing_ids = set(self.collection.get()["ids"])
        new_chunks = [c for c in chunks if c.id not in existing_ids]

        if not new_chunks:
            logger.info("Tất cả chunks đã tồn tại, bỏ qua")
            return

        for i in range(0, len(new_chunks), batch_size):
            batch = new_chunks[i : i + batch_size]
            texts = [c.content for c in batch]
            ids = [c.id for c in batch]
            metadatas = []
            for c in batch:
                meta = {k: str(v) for k, v in c.metadata.items()}
                meta["content_preview"] = c.content[:200]
                metadatas.append(meta)

            embeddings = self._embed(texts)
            self.collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )
            logger.info(f"Batch {i // batch_size + 1}: thêm {len(batch)} chunks")

        logger.info(
            f"Đã index {len(new_chunks)} chunks mới. Tổng: {self.collection.count()}"
        )

    def query(
        self,
        question: str,
        top_k: int = None,
        threshold: float = None,
    ) -> list[dict]:
        top_k = top_k or config.TOP_K
        threshold = threshold or config.SIMILARITY_THRESHOLD

        if self.collection.count() == 0:
            return []

        embedding = self._embed([question])[0]
        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=min(top_k, self.collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        retrieved = []
        for id_, doc, meta, dist in zip(
            results["ids"][0],
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            # ChromaDB cosine distance -> similarity
            similarity = 1 - dist
            if similarity >= threshold:
                retrieved.append(
                    {
                        "id": id_,
                        "content": doc,
                        "metadata": meta,
                        "similarity": round(similarity, 4),
                    }
                )

        retrieved.sort(key=lambda x: x["similarity"], reverse=True)
        return retrieved

    def get_all_documents(self) -> list[str]:
        if self.collection.count() == 0:
            return []
        all_meta = self.collection.get(include=["metadatas"])["metadatas"]
        return sorted({m.get("source", "unknown") for m in all_meta})

    def get_stats(self) -> dict:
        count = self.collection.count()
        sources = self.get_all_documents()
        return {
            "total_chunks": count,
            "documents": sources,
            "document_count": len(sources),
            "collection": self.collection_name,
            "embedding_model": self.model_name,
        }

    def delete_collection(self):
        self.client.delete_collection(self.collection_name)
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"Đã xóa collection '{self.collection_name}'")

    def delete_document(self, source_name: str):
        all_data = self.collection.get(include=["metadatas"])
        ids_to_delete = [
            id_
            for id_, meta in zip(all_data["ids"], all_data["metadatas"])
            if meta.get("source") == source_name
        ]
        if ids_to_delete:
            self.collection.delete(ids=ids_to_delete)
            logger.info(f"Đã xóa {len(ids_to_delete)} chunks của {source_name}")
