"""
Visualize knowledge graph bằng pyvis (HTML interactive) cho tab Gradio.
"""

import tempfile
from pathlib import Path
from loguru import logger

from .graph_store import GraphStore


# Màu sắc theo label — đồng bộ với style của Neo4j Browser
NODE_COLORS = {
    "Law": "#FF6B6B",
    "Chapter": "#FFB347",
    "Section": "#FFD866",
    "Article": "#4ECDC4",
    "Clause": "#95E1D3",
    "Point": "#AEE1E1",
    "Concept": "#A78BFA",
    "Actor": "#60A5FA",
    "Action": "#34D399",
    "Chunk": "#D1D5DB",
    "Node": "#999999",
}


def _make_network(height: str = "600px"):
    from pyvis.network import Network
    net = Network(
        height=height,
        width="100%",
        bgcolor="#ffffff",
        font_color="#222",
        directed=True,
        notebook=False,
        cdn_resources="in_line",
    )
    net.barnes_hut(
        gravity=-8000,
        central_gravity=0.3,
        spring_length=120,
        spring_strength=0.04,
        damping=0.09,
    )
    return net


def _render_to_html(net) -> str:
    """Lưu tạm rồi đọc lại, trả HTML string để Gradio embed."""
    tmpdir = Path(tempfile.mkdtemp(prefix="kg_viz_"))
    html_file = tmpdir / "graph.html"
    try:
        net.save_graph(str(html_file))
        html = html_file.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"pyvis render lỗi: {e}")
        return f"<p>Lỗi render graph: {e}</p>"
    # Nhúng vào iframe để không xung đột CSS/JS với Gradio
    return (
        f'<iframe srcdoc="{html.replace(chr(34), "&quot;")}" '
        'style="width:100%;height:620px;border:1px solid #ddd;border-radius:8px"></iframe>'
    )


def _add_node_from_neo4j(net, node, seen: set):
    if node is None:
        return None
    nid = node.element_id if hasattr(node, "element_id") else id(node)
    if nid in seen:
        return nid
    seen.add(nid)

    label = list(node.labels)[0] if hasattr(node, "labels") and node.labels else "Node"
    props = dict(node)
    display = (
        props.get("name")
        or props.get("title")
        or props.get("doc_number")
        or props.get("num")
        or props.get("chunk_id")
        or label
    )
    title_lines = [f"<b>{label}</b>"]
    for k in ("num", "title", "doc_number", "name", "law_number"):
        if k in props and props[k]:
            title_lines.append(f"{k}: {str(props[k])[:120]}")

    net.add_node(
        nid,
        label=str(display)[:40],
        title="<br>".join(title_lines),
        color=NODE_COLORS.get(label, NODE_COLORS["Node"]),
        shape="dot" if label not in ("Law", "Chapter") else "box",
        size=25 if label == "Law" else (20 if label == "Article" else 15),
    )
    return nid


def render_neighbors(node_type: str, node_id: str, depth: int = 2) -> str:
    """HTML pyvis cho subgraph quanh 1 node."""
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
    store = GraphStore()
    try:
        with store.session() as s:
            result = s.run(
                f"""
                MATCH (n:{node_type} {{{id_field}: $id}})
                OPTIONAL MATCH path = (n)-[*1..{depth}]-(m)
                WITH n, collect(path) AS paths
                RETURN n, paths
                """,
                id=node_id,
            )
            rec = result.single()
            if rec is None:
                return f'<p style="padding:20px">Không tìm thấy node {node_type} với id <code>{node_id}</code>.</p>'

            net = _make_network()
            seen: set = set()
            _add_node_from_neo4j(net, rec["n"], seen)

            for path in rec["paths"] or []:
                if path is None:
                    continue
                for r in path.relationships:
                    sid = _add_node_from_neo4j(net, r.start_node, seen)
                    tid = _add_node_from_neo4j(net, r.end_node, seen)
                    if sid and tid:
                        net.add_edge(sid, tid, label=r.type, arrows="to")
    finally:
        store.close()

    return _render_to_html(net)


def render_law_structure(law_doc_number: str, max_articles: int = 60) -> str:
    """Cây Law → Chapter → Article (giới hạn để khỏi lag browser)."""
    store = GraphStore()
    try:
        with store.session() as s:
            result = s.run(
                """
                MATCH (l:Law {doc_number: $doc})
                OPTIONAL MATCH (l)-[:HAS_CHAPTER]->(c:Chapter)
                OPTIONAL MATCH (c)-[:HAS_ARTICLE]->(a:Article)
                RETURN l, c, a
                LIMIT $lim
                """,
                doc=law_doc_number, lim=max_articles * 3,
            )
            records = list(result)
            if not records:
                return f'<p style="padding:20px">Không tìm thấy Luật <code>{law_doc_number}</code>.</p>'

            net = _make_network()
            seen = set()
            for rec in records:
                if rec["l"]:
                    lid = _add_node_from_neo4j(net, rec["l"], seen)
                if rec["c"]:
                    cid = _add_node_from_neo4j(net, rec["c"], seen)
                    if lid and cid:
                        net.add_edge(lid, cid, label="HAS_CHAPTER", arrows="to")
                if rec["a"]:
                    aid = _add_node_from_neo4j(net, rec["a"], seen)
                    if rec["c"] and cid and aid:
                        net.add_edge(cid, aid, label="HAS_ARTICLE", arrows="to")
                    elif lid and aid:
                        net.add_edge(lid, aid, label="HAS_ARTICLE", arrows="to")
    finally:
        store.close()

    return _render_to_html(net)


def render_concept_neighborhood(concept_name: str, depth: int = 2) -> str:
    """Shortcut: render neighbors của 1 Concept."""
    return render_neighbors("Concept", concept_name.strip().lower(), depth=depth)


def render_stats_bar(stats: dict) -> str:
    """HTML table đơn giản — đỡ phải dùng chart lib."""
    nodes = stats.get("nodes", {})
    rels = stats.get("relationships", {})
    total_n = stats.get("total_nodes", sum(nodes.values()))
    total_r = stats.get("total_relationships", sum(rels.values()))

    def _rows(d: dict) -> str:
        if not d:
            return '<tr><td colspan="2" style="color:#888">(rỗng)</td></tr>'
        return "".join(
            f"<tr><td>{k}</td><td style='text-align:right'>{v:,}</td></tr>"
            for k, v in sorted(d.items(), key=lambda x: -x[1])
        )

    return f"""
    <div style="display:flex;gap:16px;flex-wrap:wrap;font-family:system-ui">
      <div style="flex:1;min-width:280px;border:1px solid #e5e7eb;border-radius:8px;padding:12px">
        <h3 style="margin:0 0 8px">Nodes <span style="color:#6b7280;font-weight:400">({total_n:,})</span></h3>
        <table style="width:100%;border-collapse:collapse">{_rows(nodes)}</table>
      </div>
      <div style="flex:1;min-width:280px;border:1px solid #e5e7eb;border-radius:8px;padding:12px">
        <h3 style="margin:0 0 8px">Relationships <span style="color:#6b7280;font-weight:400">({total_r:,})</span></h3>
        <table style="width:100%;border-collapse:collapse">{_rows(rels)}</table>
      </div>
    </div>
    """


def list_laws() -> list[tuple[str, str]]:
    """Trả [(doc_number, title), ...] để làm dropdown choices."""
    store = GraphStore()
    try:
        rows = store.query_cypher(
            "MATCH (l:Law) RETURN l.doc_number AS doc, l.title AS title ORDER BY l.doc_number"
        )
        return [(r["doc"], r.get("title") or r["doc"]) for r in rows]
    except Exception as e:
        logger.warning(f"list_laws lỗi: {e}")
        return []
    finally:
        store.close()
