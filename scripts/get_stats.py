import json
from pathlib import Path
from loguru import logger
from src.graph_store import GraphStore
from src.vector_store import VectorStore
from src import config

def get_stats():
    stats = {}

    # 1. Neo4j Graph Stats
    logger.info("Connecting to Neo4j to fetch stats...")
    try:
        store = GraphStore()
        graph_stats = store.stats_simple()
        store.close()
        stats["graph"] = graph_stats
        logger.info(f"Graph stats fetched successfully: {graph_stats}")
    except Exception as e:
        logger.error(f"Failed to fetch Neo4j stats: {e}")
        stats["graph"] = {"error": str(e)}

    # 2. Vector DB Stats
    logger.info("Connecting to ChromaDB to fetch stats...")
    try:
        # Avoid loading model to CUDA if not needed, but VectorStore init does it. Let's load it.
        v_store = VectorStore()
        stats["vector"] = {
            "total_chunks": v_store.collection.count(),
            "embedding_model": config.EMBEDDING_MODEL,
        }
        logger.info(f"Vector stats fetched successfully: {stats['vector']}")
    except Exception as e:
        logger.error(f"Failed to fetch ChromaDB stats: {e}")
        stats["vector"] = {"error": str(e)}

    # 3. Data Gen Stats
    logger.info("Checking data_gen folder...")
    data_gen_dir = Path("data_gen")
    stats["distill"] = {}
    if data_gen_dir.exists():
        q_file = data_gen_dir / "questions.jsonl"
        d_file = data_gen_dir / "distill_data.jsonl"
        train_file = data_gen_dir / "train.jsonl"
        val_file = data_gen_dir / "val.jsonl"
        test_file = data_gen_dir / "test.jsonl"

        for file_path, name in [
            (q_file, "questions"),
            (d_file, "distill_data"),
            (train_file, "train"),
            (val_file, "val"),
            (test_file, "test")
        ]:
            if file_path.exists():
                count = 0
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            count += 1
                stats["distill"][name] = {
                    "count": count,
                    "size_bytes": file_path.stat().st_size
                }
            else:
                stats["distill"][name] = {"count": 0, "size_bytes": 0}
        
    print(json.dumps(stats, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    get_stats()
