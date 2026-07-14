"""Graph retriever clause-first cho hybrid RAG."""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from . import config
from .graph_store import GraphStore
from .graph_extractor import extract_entities_from_query, _law_info_from_source


_graph_retrieval_log_lock = threading.Lock()
_GENERIC_TERMS = {
    "pháp luật", "luật", "quy định", "yêu cầu", "thực hiện", "quyền", "nghĩa vụ",
}


def _truncate(s: str, n: int = 400) -> str:
    if not s:
        return ""
    s = str(s).replace("\r", " ").replace("\n", " ")
    return s if len(s) <= n else s[: n - 3] + "..."


def _infer_law_from_meta(meta: dict) -> str:
    law = (meta.get("law_number") or meta.get("doc_number") or "").strip()
    if law:
        return law
    source = (meta.get("source") or "").strip()
    if not source:
        return ""
    info = _law_info_from_source(source)
    return str(info.get("doc_number") or "").strip()


def _normalize_entities(ents: dict) -> dict:
    def clean(items: list[str] | None) -> list[str]:
        out = []
        for x in items or []:
            s = str(x or "").strip().lower()
            if not s or len(s) < 3 or s in _GENERIC_TERMS:
                continue
            out.append(s)
        return out[:8]

    return {
        "concepts": clean(ents.get("concepts")),
        "actors": clean(ents.get("actors")),
        "actions": clean(ents.get("actions")),
        "article_refs": ents.get("article_refs", []),
        "clause_article_refs": ents.get("clause_article_refs", []),
    }


def _summarize_vector_seeds(vector_hits: list[dict] | None) -> list[dict]:
    out = []
    for h in (vector_hits or [])[:20]:
        meta = h.get("metadata", h) if isinstance(h, dict) else {}
        out.append({
            "chunk_id": h.get("id"),
            "source": meta.get("source"),
            "law": meta.get("law_number") or meta.get("doc_number"),
            "article_num": meta.get("article_num"),
            "clause_num": meta.get("clause_num"),
            "similarity": h.get("similarity"),
        })
    return out


def _references_from_seed_targets(store: GraphStore, seeds: list[dict]) -> list[dict]:
    if not seeds:
        return []
    seeds_param = seeds[:25]
    cypher = """
    UNWIND $seeds AS s
    MATCH (a {key: s.key})-[r:REFERENCES]->(b)
    RETURN DISTINCT labels(a)[0] AS src_type, a.law_number AS src_law, a.article_num AS src_art,
           a.num AS src_num, labels(b)[0] AS dst_type,
           b.law_number AS dst_law, b.article_num AS dst_art, b.num AS dst_num,
           coalesce(r.type, '') AS ref_type
    LIMIT 120
    """
    try:
        return store.query_cypher(cypher, {"seeds": seeds_param})
    except Exception as e:
        logger.warning(f"log REFERENCES query lỗi: {e}")
        return []


def _cross_law_refs_from_seed_targets(store: GraphStore, seeds: list[dict]) -> list[dict]:
    if not seeds:
        return []
    seeds_param = seeds[:25]
    cypher = """
    UNWIND $seeds AS s
    MATCH (a {key: s.key})-[r:CROSS_LAW_REF]->(l:Law)
    RETURN DISTINCT labels(a)[0] AS src_type, a.law_number AS src_law, a.article_num AS src_art, a.num AS src_num,
           l.doc_number AS dst_law_doc, l.title AS dst_law_title
    LIMIT 60
    """
    try:
        return store.query_cypher(cypher, {"seeds": seeds_param})
    except Exception as e:
        logger.warning(f"log CROSS_LAW_REF query lỗi: {e}")
        return []


def _serialize_hit_rows(rows: list[dict], text_max: int = 350) -> list[dict]:
    out = []
    for row in rows or []:
        item = {
            "target_type": row.get("target_type"),
            "key": row.get("key"),
            "law_number": row.get("law_number"),
            "article_num": row.get("num") or row.get("article_num"),
            "clause_num": row.get("clause_num"),
            "title": row.get("title"),
            "hop_distance": row.get("hop_distance"),
            "relation": row.get("relation"),
            "source": row.get("source"),
            "rank": row.get("rank"),
            "relations": row.get("relations"),
            "matched_entities": row.get("matched_entities"),
        }
        ft = row.get("full_text") or row.get("text")
        if ft:
            item["full_text_preview"] = _truncate(ft, text_max)
        out.append({k: v for k, v in item.items() if v is not None})
    return out


def append_graph_retrieval_file_log(
    *,
    question: str,
    vector_hits: list[dict] | None,
    target_keys: list[dict],
    ents: dict,
    expanded: list[dict],
    entity_hits: list[dict],
    art_ref_hits: list[dict],
    merged: list[dict],
    references_edges: list[dict],
    cross_law_edges: list[dict],
    hops: int,
    top_m: int,
) -> None:
    if not getattr(config, "GRAPH_RETRIEVAL_LOG_ENABLED", True):
        return
    path = Path(getattr(config, "GRAPH_RETRIEVAL_LOG_PATH", "") or "")
    if not path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning(f"Không tạo được thư mục log graph: {e}")
        return

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "params": {"GRAPH_EXPAND_HOPS": hops, "GRAPH_TOP_M": top_m},
        "vector_seeds_summary": _summarize_vector_seeds(vector_hits),
        "target_keys_from_vector": target_keys,
        "entities_from_query_llm": {
            "concepts": ents.get("concepts", []),
            "actors": ents.get("actors", []),
            "actions": ents.get("actions", []),
            "article_refs_regex": ents.get("article_refs", []),
            "clause_refs_regex": ents.get("clause_article_refs", []),
        },
        "graph_expand_hits": _serialize_hit_rows(expanded),
        "graph_entity_hits": _serialize_hit_rows(entity_hits),
        "graph_article_ref_hits": _serialize_hit_rows(art_ref_hits),
        "references_from_vector_seeds": references_edges,
        "cross_law_refs_from_vector_seeds": cross_law_edges,
        "merged_unique_articles": _serialize_hit_rows(merged, text_max=280),
        "counts": {
            "target_keys": len(target_keys),
            "expanded": len(expanded or []),
            "entity_hits": len(entity_hits or []),
            "art_ref_hits": len(art_ref_hits or []),
            "merged": len(merged or []),
            "ref_edges_logged": len(references_edges or []),
        },
    }
    line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
    try:
        with _graph_retrieval_log_lock:
            path.open("a", encoding="utf-8").write(line)
    except OSError as e:
        logger.warning(f"Không ghi được graph retrieval log: {e}")


class GraphRetriever:
    def __init__(self, store: GraphStore = None):
        self.store = store or GraphStore()

    def close(self):
        self.store.close()

    # ------------------------------------------------------------------
    # Expand từ vector hits (article/clause)
    # ------------------------------------------------------------------

    def expand_from_targets(
        self,
        target_keys: list[dict],
        hops: int = None,
        limit: int = 20,
    ) -> list[dict]:
        if not target_keys:
            return []

        hops = hops or config.GRAPH_EXPAND_HOPS
        keys = [x["key"] for x in target_keys if x.get("key")]

        cypher = f"""
        UNWIND $keys AS k
        MATCH (src {{key: k}})
        OPTIONAL MATCH path = (src)-[r:REFERENCES*1..{hops}]-(dst)
        WHERE dst:Article OR dst:Clause
        WITH src, dst, relationships(path) AS rels
        WITH collect({{node: src, hop: 0, rel: 'seed'}}) +
             collect({{node: dst, hop: coalesce(size(rels),0), rel: coalesce(type(rels[0]),'')}}) AS all
        UNWIND all AS item
        WITH item.node AS n, item.hop AS hop, item.rel AS rel
        WHERE n IS NOT NULL
        OPTIONAL MATCH (a:Article)-[:HAS_CLAUSE]->(n)
        RETURN CASE WHEN n:Clause THEN 'clause' ELSE 'article' END AS target_type,
               n.key AS key,
               coalesce(n.law_number, a.law_number) AS law_number,
               CASE WHEN n:Clause THEN n.article_num ELSE n.num END AS num,
               CASE WHEN n:Clause THEN n.num ELSE null END AS clause_num,
               coalesce(a.title, n.title, '') AS title,
               coalesce(n.text, n.full_text, '') AS full_text,
               min(hop) AS hop_distance,
               collect(DISTINCT rel)[0] AS relation
        ORDER BY hop_distance ASC
        LIMIT $limit
        """
        try:
            records = self.store.query_cypher(cypher, {"keys": keys, "limit": limit})
        except Exception as e:
            logger.warning(f"expand_from_targets lỗi: {e}")
            return []
        return records

    # ------------------------------------------------------------------
    # Direct entity lookup
    # ------------------------------------------------------------------

    def targets_by_entities(
        self,
        concepts: list[str] = None,
        actors: list[str] = None,
        actions: list[str] = None,
        preferred_laws: list[str] = None,
        limit: int = 15,
    ) -> list[dict]:
        if not any([concepts, actors, actions]):
            return []

        cypher = """
        WITH $concepts AS concepts, $actors AS actors, $actions AS actions
        CALL {
            WITH concepts
            UNWIND concepts AS c
            MATCH (n:Concept) WHERE toLower(n.name) CONTAINS toLower(c)
            MATCH (t)-[:DEFINES|MENTIONS]->(n)
            WHERE t:Clause OR t:Article
            RETURN t, 'concept' AS via, c AS matched
            UNION
            WITH actors
            UNWIND actors AS x
            MATCH (n:Actor) WHERE toLower(n.name) CONTAINS toLower(x)
            MATCH (t)-[:MENTIONS]->(n)
            WHERE t:Clause OR t:Article
            RETURN t, 'actor' AS via, x AS matched
            UNION
            WITH actions
            UNWIND actions AS x
            MATCH (n:Action) WHERE toLower(n.name) CONTAINS toLower(x)
            MATCH (t)-[:REGULATES]->(n)
            WHERE t:Clause OR t:Article
            RETURN t, 'action' AS via, x AS matched
        }
        WITH t, collect(DISTINCT via) AS vias, collect(DISTINCT matched) AS matches
        OPTIONAL MATCH (a:Article)-[:HAS_CLAUSE]->(t)
        WITH t, a, vias, matches, $preferred_laws AS preferred_laws,
             coalesce(t.law_number, a.law_number) AS law
        WITH t, a, vias, matches, law,
             CASE
                 WHEN size(preferred_laws)=0 THEN 0
                 WHEN law IN preferred_laws THEN 2
                 ELSE 0
             END AS law_bonus
        RETURN CASE WHEN t:Clause THEN 'clause' ELSE 'article' END AS target_type,
               t.key AS key,
               law AS law_number,
               CASE WHEN t:Clause THEN t.article_num ELSE t.num END AS num,
               CASE WHEN t:Clause THEN t.num ELSE null END AS clause_num,
               coalesce(a.title, t.title, '') AS title,
               coalesce(t.text, t.full_text, '') AS full_text,
               vias AS relations,
               matches AS matched_entities,
               size(vias) + law_bonus AS score
        ORDER BY score DESC, target_type DESC
        LIMIT $limit
        """
        try:
            return self.store.query_cypher(cypher, {
                "concepts": concepts or [],
                "actors": actors or [],
                "actions": actions or [],
                "preferred_laws": preferred_laws or [],
                "limit": limit,
            })
        except Exception as e:
            logger.warning(f"targets_by_entities lỗi: {e}")
            return []

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------

    def retrieve(
        self,
        question: str,
        vector_hits: list[dict] = None,
        top_m: int = None,
        hops: int = None,
    ) -> list[dict]:
        """
        Trả về list candidate cấp clause/article từ graph.
        """
        top_m = top_m or config.GRAPH_TOP_M
        hops = hops or config.GRAPH_EXPAND_HOPS

        # 1. Collect target keys từ vector hits
        target_keys = []
        for h in vector_hits or []:
            meta = h.get("metadata", h)
            law = _infer_law_from_meta(meta)
            art = str(meta.get("article_num") or "").strip()
            clause = str(meta.get("clause_num") or "").strip()
            if law and art:
                if clause:
                    target_keys.append({
                        "type": "clause",
                        "law": law,
                        "article": art,
                        "clause": clause,
                        "key": f"{law}::art::{art}::cl::{clause}",
                    })
                target_keys.append({
                    "type": "article",
                    "law": law,
                    "article": art,
                    "clause": "",
                    "key": f"{law}::art::{art}",
                })

        expanded = self.expand_from_targets(target_keys, hops=hops, limit=top_m * 4)

        # 2. Entity lookup từ query
        try:
            ents = _normalize_entities(extract_entities_from_query(question))
        except Exception as e:
            logger.warning(f"Entity extract lỗi: {e}")
            ents = {
                "concepts": [],
                "actors": [],
                "actions": [],
                "article_refs": [],
                "clause_article_refs": [],
            }

        preferred_laws = sorted({x["law"] for x in target_keys if x.get("law")})
        entity_hits = self.targets_by_entities(
            concepts=ents.get("concepts"),
            actors=ents.get("actors"),
            actions=ents.get("actions"),
            preferred_laws=preferred_laws,
            limit=top_m * 2,
        )

        # 3. Nếu query chứa "Điều X" cụ thể, thêm trực tiếp
        art_ref_hits = []
        if ents.get("article_refs"):
            cypher = """
            UNWIND $nums AS num
            MATCH (a:Article {num: num})
            OPTIONAL MATCH (a)-[:HAS_CLAUSE]->(c:Clause)
            WITH a, c
            ORDER BY c.num
            RETURN CASE WHEN c IS NULL THEN 'article' ELSE 'clause' END AS target_type,
                   coalesce(c.key, a.key) AS key,
                   a.law_number AS law_number,
                   a.num AS num,
                   c.num AS clause_num,
                   a.title AS title,
                   coalesce(c.text, a.full_text, '') AS full_text
            LIMIT 10
            """
            try:
                art_ref_hits = self.store.query_cypher(
                    cypher, {"nums": ents["article_refs"]}
                )
            except Exception:
                pass
        if ents.get("clause_article_refs"):
            cypher = """
            UNWIND $refs AS ref
            MATCH (c:Clause {article_num: ref.article_num, num: ref.clause_num})
            RETURN 'clause' AS target_type,
                   c.key AS key,
                   c.law_number AS law_number,
                   c.article_num AS num,
                   c.num AS clause_num,
                   '' AS title,
                   c.text AS full_text
            LIMIT 20
            """
            try:
                art_ref_hits.extend(self.store.query_cypher(cypher, {"refs": ents["clause_article_refs"]}))
            except Exception:
                pass

        # Gộp tất cả, dedupe theo key clause/article
        merged: dict[tuple, dict] = {}
        for i, row in enumerate(expanded):
            key = (row.get("target_type"), row.get("law_number"), row.get("num"), row.get("clause_num") or "")
            row.setdefault("source", "expand")
            row.setdefault("rank", i + 1)
            merged[key] = row
        for i, row in enumerate(entity_hits):
            key = (row.get("target_type"), row.get("law_number"), row.get("num"), row.get("clause_num") or "")
            row.setdefault("source", "entity")
            row.setdefault("rank", i + 1)
            if key not in merged:
                merged[key] = row
            else:
                merged[key]["source"] = merged[key].get("source", "") + "+entity"
        for i, row in enumerate(art_ref_hits):
            key = (row.get("target_type"), row.get("law_number"), row.get("num"), row.get("clause_num") or "")
            row.setdefault("source", "article_ref")
            row.setdefault("rank", i + 1)
            if key not in merged:
                merged[key] = row

        merged_list = list(merged.values())
        ref_edges = _references_from_seed_targets(self.store, target_keys)
        cross_edges = _cross_law_refs_from_seed_targets(self.store, target_keys)
        append_graph_retrieval_file_log(
            question=question,
            vector_hits=vector_hits,
            target_keys=target_keys,
            ents=ents,
            expanded=expanded,
            entity_hits=entity_hits,
            art_ref_hits=art_ref_hits,
            merged=merged_list,
            references_edges=ref_edges,
            cross_law_edges=cross_edges,
            hops=hops,
            top_m=top_m,
        )

        return merged_list

    # ------------------------------------------------------------------
    # Neighbors (for viz/API)
    # ------------------------------------------------------------------

    def neighbors(self, node_type: str, node_id: str, depth: int = 1) -> dict:
        """
        Lấy subgraph quanh 1 node cho API /api/graph/neighbors.
        node_type: 'Law' | 'Article' | 'Concept' | 'Actor' | 'Action' | 'Chapter' | 'Clause'
        node_id: giá trị unique (doc_number / key / name)
        """
        id_field = {
            "Law": "doc_number",
            "Article": "key",
            "Chapter": "key",
            "Clause": "key",
            "Concept": "name",
            "Actor": "name",
            "Action": "name",
            "Chunk": "chunk_id",
        }.get(node_type, "name")

        depth = max(1, min(int(depth or 1), 3))

        cypher = f"""
        MATCH (n:{node_type} {{{id_field}: $id}})
        CALL {{
            WITH n
            MATCH path = (n)-[*1..{depth}]-(m)
            RETURN path
            LIMIT 100
        }}
        UNWIND relationships(path) AS r
        WITH collect(DISTINCT r) AS rels, collect(DISTINCT startNode(r)) + collect(DISTINCT endNode(r)) AS nodes
        RETURN nodes, rels
        """
        try:
            result = self.store.query_cypher(cypher, {"id": node_id})
        except Exception as e:
            logger.warning(f"neighbors query lỗi: {e}")
            return {"nodes": [], "edges": []}
        if not result:
            return {"nodes": [], "edges": []}

        record = result[0]
        raw_nodes = record.get("nodes", []) or []
        raw_rels = record.get("rels", []) or []

        nodes_out: dict[int, dict] = {}
        for n in raw_nodes:
            if n is None:
                continue
            nid = n.element_id if hasattr(n, "element_id") else id(n)
            label = list(n.labels)[0] if hasattr(n, "labels") and n.labels else "Node"
            props = dict(n)
            display = (
                props.get("name")
                or props.get("title")
                or props.get("doc_number")
                or props.get("num")
                or props.get("chunk_id")
                or label
            )
            nodes_out[nid] = {
                "id": str(nid),
                "label": label,
                "display": str(display)[:80],
                "properties": {k: str(v)[:200] for k, v in props.items()},
            }

        edges_out = []
        for r in raw_rels:
            if r is None:
                continue
            s = r.start_node.element_id if hasattr(r.start_node, "element_id") else id(r.start_node)
            t = r.end_node.element_id if hasattr(r.end_node, "element_id") else id(r.end_node)
            edges_out.append({
                "source": str(s),
                "target": str(t),
                "type": r.type,
            })

        return {"nodes": list(nodes_out.values()), "edges": edges_out}
