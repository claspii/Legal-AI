"""
Neo4j wrapper cho knowledge graph của hệ thống RAG pháp luật.
Gồm schema init, upsert nodes/edges, query Cypher và stats.
"""

from contextlib import contextmanager
from neo4j import GraphDatabase, Driver
from loguru import logger

from . import config


SCHEMA_STATEMENTS = [
    "CREATE CONSTRAINT law_number IF NOT EXISTS FOR (l:Law) REQUIRE l.doc_number IS UNIQUE",
    "CREATE CONSTRAINT article_key IF NOT EXISTS FOR (a:Article) REQUIRE a.key IS UNIQUE",
    "CREATE CONSTRAINT chapter_key IF NOT EXISTS FOR (c:Chapter) REQUIRE c.key IS UNIQUE",
    "CREATE CONSTRAINT clause_key IF NOT EXISTS FOR (c:Clause) REQUIRE c.key IS UNIQUE",
    "CREATE CONSTRAINT concept_name IF NOT EXISTS FOR (c:Concept) REQUIRE c.name IS UNIQUE",
    "CREATE CONSTRAINT actor_name IF NOT EXISTS FOR (a:Actor) REQUIRE a.name IS UNIQUE",
    "CREATE CONSTRAINT action_name IF NOT EXISTS FOR (ac:Action) REQUIRE ac.name IS UNIQUE",
    "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE",
    "CREATE INDEX article_num_idx IF NOT EXISTS FOR (a:Article) ON (a.num)",
    "CREATE INDEX article_law_idx IF NOT EXISTS FOR (a:Article) ON (a.law_number)",
]


class GraphStore:
    def __init__(
        self,
        uri: str = None,
        user: str = None,
        password: str = None,
        database: str = None,
    ):
        self.uri = uri or config.NEO4J_URI
        self.user = user or config.NEO4J_USER
        self.password = password or config.NEO4J_PASSWORD
        self.database = database or config.NEO4J_DATABASE
        self._driver: Driver | None = None
        self._connect()

    def _connect(self):
        logger.info(f"Kết nối Neo4j tại {self.uri}")
        self._driver = GraphDatabase.driver(
            self.uri, auth=(self.user, self.password)
        )
        self._driver.verify_connectivity()
        logger.info("Neo4j đã sẵn sàng")

    @contextmanager
    def session(self):
        with self._driver.session(database=self.database) as s:
            yield s

    def close(self):
        if self._driver:
            self._driver.close()

    def init_schema(self):
        with self.session() as s:
            for stmt in SCHEMA_STATEMENTS:
                s.run(stmt)
        logger.info("Schema constraints + indexes đã tạo")

    def clear(self):
        """Xóa toàn bộ graph. Dùng khi muốn rebuild từ đầu."""
        with self.session() as s:
            s.run("MATCH (n) DETACH DELETE n")
        logger.warning("Đã xóa toàn bộ knowledge graph")

    def delete_document(self, filename: str):
        """Xóa toàn bộ các node và quan hệ liên quan đến một tài liệu."""
        with self.session() as s:
            from pathlib import Path
            stem = Path(filename).stem
            
            # 1. Tìm doc_number từ Law node bằng source_file hoặc doc_number stem (không phân biệt hoa thường)
            records = list(s.run(
                """
                MATCH (l:Law)
                WHERE toLower(l.source_file) = toLower($filename)
                   OR toLower(l.doc_number) = toLower($stem)
                RETURN l.doc_number AS doc_num
                """,
                filename=filename,
                stem=stem
            ))
            
            doc_num = records[0]["doc_num"] if records else None
            
            # Nếu không tìm thấy Law node trong Neo4j, sử dụng fallback từ LAW_METADATA hoặc stem
            if not doc_num:
                try:
                    from src.graph_extractor import _law_info_from_source
                    info = _law_info_from_source(filename)
                    doc_num = info["doc_number"]
                except Exception as e:
                    logger.warning(f"Neo4j: Không lấy được thông tin fallback cho {filename}: {e}")
                    doc_num = stem
            
            logger.info(f"Neo4j: Xóa các node cấu trúc của luật {doc_num} (source={filename})")
            s.run(
                """
                MATCH (n)
                WHERE n:Law AND (toLower(n.doc_number) = toLower($doc_num) OR toLower(n.source_file) = toLower($filename))
                   OR n:Chapter AND toLower(n.law_number) = toLower($doc_num)
                   OR n:Article AND toLower(n.law_number) = toLower($doc_num)
                   OR n:Clause AND toLower(n.law_number) = toLower($doc_num)
                DETACH DELETE n
                """,
                doc_num=doc_num,
                filename=filename
            )
            
            # 2. Xóa các Chunk node thuộc tài liệu này (không phân biệt hoa thường)
            logger.info(f"Neo4j: Xóa các node Chunk có tiền tố {filename}__")
            s.run(
                """
                MATCH (c:Chunk)
                WHERE toLower(c.chunk_id) STARTS WITH toLower($prefix)
                   OR toLower(c.chunk_id) STARTS WITH toLower($stem_prefix)
                DETACH DELETE c
                """,
                prefix=f"{filename}__",
                stem_prefix=f"{stem}__"
            )
            
            # 3. Dọn dẹp các Concept, Actor, Action bị cô lập (không còn quan hệ nào)
            logger.info("Neo4j: Dọn dẹp các node Concept, Actor, Action bị cô lập")
            s.run(
                """
                MATCH (n)
                WHERE (n:Concept OR n:Actor OR n:Action) AND NOT (n)--()
                DELETE n
                """
            )
            logger.info(f"Neo4j: Đã xóa xong dữ liệu của {filename}")

    def upsert_law(self, doc_number: str, title: str, source_file: str):
        with self.session() as s:
            s.run(
                """
                MERGE (l:Law {doc_number: $doc})
                SET l.title = $title, l.source_file = $src
                """,
                doc=doc_number, title=title, src=source_file,
            )

    def upsert_chapter(self, law_number: str, num: str, title: str):
        key = f"{law_number}::ch::{num}"
        with self.session() as s:
            s.run(
                """
                MATCH (l:Law {doc_number: $law})
                MERGE (c:Chapter {key: $key})
                SET c.num = $num, c.title = $title, c.law_number = $law
                MERGE (l)-[:HAS_CHAPTER]->(c)
                """,
                law=law_number, num=num, title=title, key=key,
            )

    def upsert_article(
        self,
        law_number: str,
        num: str,
        title: str,
        full_text: str,
        chapter_num: str = None,
    ):
        key = f"{law_number}::art::{num}"
        with self.session() as s:
            s.run(
                """
                MERGE (a:Article {key: $key})
                SET a.num = $num,
                    a.title = $title,
                    a.law_number = $law,
                    a.full_text = $text
                """,
                key=key, num=num, title=title, law=law_number, text=full_text,
            )
            if chapter_num:
                chap_key = f"{law_number}::ch::{chapter_num}"
                s.run(
                    """
                    MATCH (c:Chapter {key: $ckey})
                    MATCH (a:Article {key: $akey})
                    MERGE (c)-[:HAS_ARTICLE]->(a)
                    """,
                    ckey=chap_key, akey=key,
                )
            else:
                # Fallback: tài liệu không có metadata chapter
                s.run(
                    """
                    MATCH (l:Law {doc_number: $law})
                    MATCH (a:Article {key: $akey})
                    MERGE (l)-[:HAS_ARTICLE]->(a)
                    """,
                    law=law_number, akey=key,
                )

    def upsert_clause(
        self, law_number: str, article_num: str, clause_num: str, text: str
    ):
        key = f"{law_number}::art::{article_num}::cl::{clause_num}"
        art_key = f"{law_number}::art::{article_num}"
        with self.session() as s:
            s.run(
                """
                MERGE (c:Clause {key: $key})
                SET c.num = $num, c.text = $text,
                    c.article_num = $art, c.law_number = $law
                WITH c
                MATCH (a:Article {key: $akey})
                MERGE (a)-[:HAS_CLAUSE]->(c)
                """,
                key=key, num=clause_num, text=text[:5000],
                art=article_num, law=law_number, akey=art_key,
            )

    def link_chunk(self, chunk_id: str, law_number: str, article_num: str,
                   clause_num: str = None):
        art_key = f"{law_number}::art::{article_num}"
        with self.session() as s:
            s.run(
                """
                MERGE (ch:Chunk {chunk_id: $cid})
                WITH ch
                MATCH (a:Article {key: $akey})
                MERGE (a)-[:IN_CHUNK]->(ch)
                """,
                cid=chunk_id, akey=art_key,
            )
            if clause_num:
                cl_key = f"{law_number}::art::{article_num}::cl::{clause_num}"
                s.run(
                    """
                    MATCH (cl:Clause {key: $ckey})
                    MATCH (ch:Chunk {chunk_id: $cid})
                    MERGE (cl)-[:IN_CHUNK]->(ch)
                    """,
                    ckey=cl_key, cid=chunk_id,
                )

    def add_reference(
        self,
        src_law: str,
        src_article: str,
        dst_law: str,
        dst_article: str,
        ref_type: str = "internal",
        src_clause: str = None,
        dst_clause: str = None,
    ):
        """Thêm cạnh dẫn chiếu giữa Article/Clause tùy mức granular."""
        src_art_key = f"{src_law}::art::{src_article}"
        dst_art_key = f"{dst_law}::art::{dst_article}"
        src_clause_key = (
            f"{src_law}::art::{src_article}::cl::{src_clause}"
            if src_clause else None
        )
        dst_clause_key = (
            f"{dst_law}::art::{dst_article}::cl::{dst_clause}"
            if dst_clause else None
        )
        with self.session() as s:
            s.run(
                """
                MATCH (src_art:Article {key: $src_art})
                OPTIONAL MATCH (src_clause:Clause {key: $src_clause_key})
                WITH coalesce(src_clause, src_art) AS src, $dst_clause_key AS dck,
                     $dst_art AS dst_art, $dst_num AS dst_num, $dst_law AS dst_law
                CALL {
                    WITH dck, dst_art, dst_num, dst_law
                    WITH dck, dst_art, dst_num, dst_law WHERE dck IS NOT NULL
                    MERGE (dst:Clause {key: dck})
                    ON CREATE SET dst.num = $dst_clause_num,
                                  dst.article_num = dst_num,
                                  dst.law_number = dst_law,
                                  dst.text = ''
                    RETURN dst
                    UNION
                    WITH dck, dst_art, dst_num, dst_law
                    WITH dck, dst_art, dst_num, dst_law WHERE dck IS NULL
                    MERGE (dst:Article {key: dst_art})
                    ON CREATE SET dst.num = dst_num, dst.law_number = dst_law,
                                  dst.full_text = '', dst.title = ''
                    RETURN dst
                }
                MERGE (src)-[r:REFERENCES]->(dst)
                SET r.type = $type
                """,
                src_art=src_art_key,
                src_clause_key=src_clause_key,
                dst_art=dst_art_key,
                dst_clause_key=dst_clause_key,
                dst_clause_num=dst_clause,
                dst_num=dst_article,
                dst_law=dst_law,
                type=ref_type,
            )

    def add_cross_law_ref(
        self,
        src_law: str,
        src_article: str,
        dst_law_name: str,
        src_clause: str = None,
    ):
        """Dẫn chiếu sang luật khác mà không cụ thể Điều nào."""
        src_art_key = f"{src_law}::art::{src_article}"
        src_clause_key = (
            f"{src_law}::art::{src_article}::cl::{src_clause}"
            if src_clause else None
        )
        with self.session() as s:
            s.run(
                """
                MATCH (src_art:Article {key: $src_art})
                OPTIONAL MATCH (src_clause:Clause {key: $src_clause_key})
                WITH coalesce(src_clause, src_art) AS src
                MERGE (l:Law {doc_number: $dst})
                ON CREATE SET l.title = $dst, l.source_file = ''
                MERGE (src)-[:CROSS_LAW_REF]->(l)
                """,
                src_art=src_art_key, src_clause_key=src_clause_key, dst=dst_law_name,
            )

    def add_semantic(
        self,
        law_number: str,
        article_num: str,
        clause_num: str = None,
        concepts_defined: list[str] = None,
        actors: list[str] = None,
        actions: list[str] = None,
        actor_actions: list[tuple[str, str]] = None,
        related_concepts: list[tuple[str, str]] = None,
    ):
        """Thêm semantic edges từ LLM extraction."""
        art_key = f"{law_number}::art::{article_num}"
        clause_key = (
            f"{law_number}::art::{article_num}::cl::{clause_num}"
            if clause_num else None
        )
        with self.session() as s:
            for concept in concepts_defined or []:
                s.run(
                    """
                    MATCH (a:Article {key: $akey})
                    OPTIONAL MATCH (cl:Clause {key: $ckey})
                    WITH coalesce(cl, a) AS src
                    MERGE (c:Concept {name: $name})
                    MERGE (src)-[:DEFINES]->(c)
                    """,
                    akey=art_key, ckey=clause_key, name=concept.strip().lower(),
                )
            for actor in actors or []:
                s.run(
                    """
                    MATCH (a:Article {key: $akey})
                    OPTIONAL MATCH (cl:Clause {key: $ckey})
                    WITH coalesce(cl, a) AS src
                    MERGE (ac:Actor {name: $name})
                    MERGE (src)-[:MENTIONS]->(ac)
                    """,
                    akey=art_key, ckey=clause_key, name=actor.strip().lower(),
                )
            for action in actions or []:
                s.run(
                    """
                    MATCH (a:Article {key: $akey})
                    OPTIONAL MATCH (cl:Clause {key: $ckey})
                    WITH coalesce(cl, a) AS src
                    MERGE (ac:Action {name: $name})
                    MERGE (src)-[:REGULATES]->(ac)
                    """,
                    akey=art_key, ckey=clause_key, name=action.strip().lower(),
                )
            for actor, action in actor_actions or []:
                s.run(
                    """
                    MERGE (ac:Actor {name: $actor})
                    MERGE (act:Action {name: $action})
                    MERGE (ac)-[:PERFORMS]->(act)
                    """,
                    actor=actor.strip().lower(), action=action.strip().lower(),
                )
            for a, b in related_concepts or []:
                s.run(
                    """
                    MERGE (c1:Concept {name: $a})
                    MERGE (c2:Concept {name: $b})
                    MERGE (c1)-[r:RELATED_TO]->(c2)
                    ON CREATE SET r.weight = 1
                    ON MATCH SET r.weight = coalesce(r.weight, 0) + 1
                    """,
                    a=a.strip().lower(), b=b.strip().lower(),
                )

    def query_cypher(self, cypher: str, params: dict = None) -> list[dict]:
        """Execute Cypher query, trả về list record dạng dict."""
        with self.session() as s:
            result = s.run(cypher, params or {})
            return [r.data() for r in result]

    def safe_read_cypher(self, cypher: str, params: dict = None) -> list[dict]:
        """Chạy Cypher read-only, chặn các keyword ghi."""
        forbidden = [
            "CREATE", "DELETE", "DETACH", "MERGE", "SET ", "REMOVE",
            "DROP", "CALL DB.CLEAR", "FOREACH",
        ]
        upper = cypher.upper()
        for kw in forbidden:
            if kw in upper:
                raise ValueError(f"Cypher chứa keyword bị cấm: {kw.strip()}")
        return self.query_cypher(cypher, params)

    def stats(self) -> dict:
        with self.session() as s:
            nodes = s.run(
                """
                CALL db.labels() YIELD label
                CALL apoc.cypher.run('MATCH (n:`' + label + '`) RETURN count(n) AS c', {})
                YIELD value RETURN label, value.c AS count
                """
            ).data()
            rels = s.run(
                """
                CALL db.relationshipTypes() YIELD relationshipType AS rt
                CALL apoc.cypher.run('MATCH ()-[r:`' + rt + '`]->() RETURN count(r) AS c', {})
                YIELD value RETURN rt, value.c AS count
                """
            ).data()
        return {
            "nodes": {r["label"]: r["count"] for r in nodes},
            "relationships": {r["rt"]: r["count"] for r in rels},
            "total_nodes": sum(r["count"] for r in nodes),
            "total_relationships": sum(r["count"] for r in rels),
        }

    def stats_simple(self) -> dict:
        """Stats không cần apoc, chậm hơn nhưng luôn chạy được."""
        with self.session() as s:
            labels = [r["label"] for r in s.run("CALL db.labels() YIELD label").data()]
            rtypes = [
                r["rt"] for r in s.run(
                    "CALL db.relationshipTypes() YIELD relationshipType AS rt"
                ).data()
            ]
            node_counts = {}
            for lb in labels:
                c = s.run(f"MATCH (n:`{lb}`) RETURN count(n) AS c").single()["c"]
                node_counts[lb] = c
            rel_counts = {}
            for rt in rtypes:
                c = s.run(f"MATCH ()-[r:`{rt}`]->() RETURN count(r) AS c").single()["c"]
                rel_counts[rt] = c
        return {
            "nodes": node_counts,
            "relationships": rel_counts,
            "total_nodes": sum(node_counts.values()),
            "total_relationships": sum(rel_counts.values()),
        }
