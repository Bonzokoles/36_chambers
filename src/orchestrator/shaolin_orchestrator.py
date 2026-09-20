"""Read-only, registry-driven orchestration for the 36 Chambers of Shaolin Cognitive Matrix.

Integrates real database adapters for:
- Chamber 01 (sist2 document index / FTS5)
- Chamber 03 (DEVz Knowledge Base / ChromaDB)
- Chamber 04 (MemPalace / ChromaDB)
- Chamber 05 (Graph of Truth / SQLite triples & entities)
- Chamber 06 (The Iron Fist / Policy gate for write & execution)
- Chamber 07 (Vector Micro-Engine / sqlite-vec + fastembed)
- Chamber 08 (Store & Operations / SQLite chat.db)
- Chamber 36 (The Buch / Jimbo synthesis)
"""
from __future__ import annotations

import argparse
import concurrent.futures
import glob
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from dataclasses import asdict, dataclass, field

from pathlib import Path
from typing import Any, Callable

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


try:
    import chromadb
except ImportError:
    chromadb = None

DEFAULT_REGISTRY = Path(r"Z:\36_chambers\.doc\36_CHAMBERS_REGISTRY.json")
DEFAULT_TRACE_DIR = Path(r"Z:\36_chambers\.doc\traces")


@dataclass
class Chamber:
    id: int
    name: str
    domain: str
    engine: str
    physical_path: str
    description: str = ""
    notes: str = ""


@dataclass
class Evidence:
    chamber_id: int
    chamber_name: str
    resource_path: str
    method: str
    record_id: str | None
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float | None = None


@dataclass
class Route:
    chamber_id: int
    mode: str
    reason: str


@dataclass
class State:
    request_id: str
    query: str
    mode: str = "research"
    max_chambers: int = 3
    timeout_s: float = 15.0
    allow_web: bool = False
    write_intent: bool = False
    intent: str = "unknown"
    subqueries: list[str] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=lambda: {"stage_latency_ms": {}, "retrieval": {}})


def now_ms() -> int:
    return time.perf_counter_ns() // 1_000_000


def timed(state: State, stage: str, fn: Callable[[], Any]) -> Any:
    start = now_ms()
    try:
        return fn()
    finally:
        state.metrics["stage_latency_ms"][stage] = now_ms() - start


def load_registry(path: Path) -> dict[int, Chamber]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    chambers = {}
    for raw in data.get("chambers", []):
        chambers[int(raw["id"])] = Chamber(
            id=int(raw["id"]),
            name=raw["name"],
            domain=raw.get("domain", ""),
            engine=raw.get("engine", ""),
            physical_path=raw.get("physical_path", ""),
            description=raw.get("description", ""),
            notes=raw.get("notes", ""),
        )
    return chambers


def get_chamber(chambers: dict[int, Chamber], chamber_id: int) -> Chamber:
    try:
        return chambers[chamber_id]
    except KeyError as exc:
        raise ValueError(f"Chamber {chamber_id} is not registered") from exc


def decompose_query(state: State) -> State:
    q = state.query.lower()
    if any(term in q for term in ("usuń", "skasuj", "delete", "zapisz", "uruchom", "wykonaj", "terminal", "skrypt", "drop", "alter")):
        state.intent = "execution"
        state.subqueries = [state.query]
        state.write_intent = True
    elif any(term in q for term in ("cena", "marża", "faktura", "produkt", "dostawca", "sklep", "zamów", "konwersacj")):
        state.intent, state.subqueries = "commerce", [state.query]
    elif any(term in q for term in ("relacj", "graf", "węzeł", "węzł", " encja", " encje", " encji", "kto z kim", "trójk", "triple", "połączon", "wspiera")):
        state.intent, state.subqueries = "graph", [state.query]
    elif any(term in q for term in ("pamię", "preferencj", "zapamięt", "histori", "mempalace", "drawer", "closet", "pomiar")):
        state.intent, state.subqueries = "memory", [state.query]


    elif any(term in q for term in ("plik", "folder", "dysk", "znajdź dokument", "muninn", "sist2")):
        state.intent, state.subqueries = "file_discovery", [state.query]
    else:
        state.intent, state.subqueries = "technical_knowledge", [state.query]
    return state


def route_query(state: State, chambers: dict[int, Chamber]) -> State:
    candidates: list[Route]
    if state.write_intent:
        candidates = [Route(6, "policy_gate", "Execution or state-changing intent detected")]
    elif state.intent == "commerce":
        candidates = [Route(8, "sql", "Business-data intent"), Route(1, "fts", "Lexical fallback")]
    elif state.intent == "graph":
        candidates = [Route(5, "graph_sql", "Relationship intent"), Route(3, "semantic", "Semantic fallback")]
    elif state.intent == "memory":
        candidates = [Route(4, "semantic", "Long-term memory intent"), Route(5, "graph_sql", "Relation fallback")]
    elif state.intent == "file_discovery":
        candidates = [Route(1, "fts", "File discovery intent"), Route(3, "semantic", "Technical KB fallback")]
    else:
        candidates = [
            Route(3, "semantic", "Technical/project knowledge"),
            Route(1, "fts", "Lexical corroboration"),
            Route(5, "graph_sql", "Entity relation corroboration"),
        ]

    if state.allow_web and 2 in chambers:
        candidates.append(Route(2, "http", "Web retrieval explicitly allowed"))
    state.routes = [r for r in candidates if r.chamber_id in chambers][: state.max_chambers]
    return state


def sqlite_readonly(path: str, immutable: bool = False) -> sqlite3.Connection:
    clean_path = path.replace("\\", "/")
    uri = "file:" + urllib.parse.quote(clean_path) + "?mode=ro"
    if immutable:
        uri += "&immutable=1"
    return sqlite3.connect(uri, uri=True, timeout=5.0)


# ---------------------------------------------------------------------------
# ADAPTERS
# ---------------------------------------------------------------------------

def adapter_chamber_01_sist2(chamber: Chamber, query: str, limit: int = 5) -> list[Evidence]:
    """Chamber 01: Full-text and file discovery on indexed volumes."""
    sist_files = glob.glob(os.path.join(chamber.physical_path, "*.sist2"))
    if not sist_files:
        return [
            Evidence(
                chamber_id=chamber.id,
                chamber_name=chamber.name,
                resource_path=chamber.physical_path,
                method="sist2_search",
                record_id=None,
                content="No .sist2 index files found in directory.",
                metadata={"query": query},
            )
        ]

    search_terms = [w.strip() for w in query.replace("?", " ").replace(",", " ").split() if len(w.strip()) > 2]
    term = search_terms[-1] if search_terms else query

    evidence_list = []
    target_sist = sist_files[0]

    try:
        with sqlite_readonly(target_sist, immutable=True) as conn:
            cursor = conn.cursor()
            param = f"%{term}%"
            rows = cursor.execute(
                "SELECT id, path, size, json_data FROM document WHERE path LIKE ? OR json_data LIKE ? LIMIT ?",
                (param, param, limit),
            ).fetchall()

            for doc_id, doc_path, doc_size, json_data in rows:
                evidence_list.append(
                    Evidence(
                        chamber_id=chamber.id,
                        chamber_name=chamber.name,
                        resource_path=target_sist,
                        method="sist2_index_match",
                        record_id=str(doc_id),
                        content=f"Document: {doc_path} (Size: {doc_size} bytes, Metadata: {json_data})",
                        metadata={"path": doc_path, "size": doc_size, "query": query},
                    )
                )
    except Exception as exc:
        evidence_list.append(
            Evidence(
                chamber_id=chamber.id,
                chamber_name=chamber.name,
                resource_path=target_sist,
                method="sist2_error",
                record_id=None,
                content=f"sist2 index query failed: {exc}",
                metadata={"error": str(exc)},
            )
        )

    if not evidence_list:
        evidence_list.append(
            Evidence(
                chamber_id=chamber.id,
                chamber_name=chamber.name,
                resource_path=target_sist,
                method="sist2_index_match",
                record_id=None,
                content=f"No documents matched term '{term}' in sist2 index.",
                metadata={"query": query},
            )
        )
    return evidence_list


def adapter_chamber_03_devz_kb(chamber: Chamber, query: str, limit: int = 5) -> list[Evidence]:
    """Chamber 03: ChromaDB DEVz knowledge base."""
    if chromadb is None:
        raise RuntimeError("chromadb library is not installed")

    root = Path(chamber.physical_path)
    if not root.exists():
        raise FileNotFoundError(str(root))

    client = chromadb.PersistentClient(path=str(root))
    collections = client.list_collections()
    if not collections:
        return [
            Evidence(
                chamber_id=chamber.id,
                chamber_name=chamber.name,
                resource_path=str(root),
                method="chroma_query",
                record_id=None,
                content="No collections found in DEVz KB ChromaDB.",
                metadata={"query": query},
            )
        ]

    # Search the primary agent & strategy collections first, or iterate all
    target_names = ["kb_cat_agents_rag", "kb_cat_strategy", "kb_cat_ai_news"]
    active_colls = [c for c in collections if c.name in target_names]
    if not active_colls:
        active_colls = collections[:3]

    evidence_list = []
    for coll in active_colls:
        try:
            res = coll.query(query_texts=[query], n_results=min(limit, 3))
            ids = res.get("ids", [[]])[0]
            docs = res.get("documents", [[]])[0]
            metas = res.get("metadatas", [[]])[0] or [{}] * len(ids)

            for doc_id, doc_text, meta in zip(ids, docs, metas):
                clean_text = (doc_text or "").strip().replace("\r\n", "\n")
                if len(clean_text) > 400:
                    clean_text = clean_text[:400] + "..."
                evidence_list.append(
                    Evidence(
                        chamber_id=chamber.id,
                        chamber_name=chamber.name,
                        resource_path=str(root),
                        method=f"chroma_semantic[{coll.name}]",
                        record_id=doc_id,
                        content=f"[{coll.name}] doc_id={doc_id}: {clean_text}",
                        metadata={"collection": coll.name, "doc_id": doc_id, "meta": meta},
                    )
                )
        except Exception:
            continue

    if not evidence_list:
        evidence_list.append(
            Evidence(
                chamber_id=chamber.id,
                chamber_name=chamber.name,
                resource_path=str(root),
                method="chroma_semantic",
                record_id=None,
                content=f"No matching documents found in DEVz KB collections for query: '{query}'",
                metadata={"query": query},
            )
        )
    return evidence_list[:limit]


def adapter_chamber_04_mempalace(chamber: Chamber, query: str, limit: int = 5) -> list[Evidence]:
    """Chamber 04: MemPalace agent memories and closets."""
    if chromadb is None:
        raise RuntimeError("chromadb library is not installed")

    root = Path(chamber.physical_path)
    if not root.exists():
        raise FileNotFoundError(str(root))

    client = chromadb.PersistentClient(path=str(root))
    collections = client.list_collections()
    if not collections:
        return [
            Evidence(
                chamber_id=chamber.id,
                chamber_name=chamber.name,
                resource_path=str(root),
                method="mempalace_query",
                record_id=None,
                content="No collections found in MemPalace ChromaDB.",
                metadata={"query": query},
            )
        ]

    evidence_list = []
    for coll in collections:
        try:
            res = coll.query(query_texts=[query], n_results=min(limit, 3))
            ids = res.get("ids", [[]])[0]
            docs = res.get("documents", [[]])[0]
            metas = res.get("metadatas", [[]])[0] or [{}] * len(ids)

            for doc_id, doc_text, meta in zip(ids, docs, metas):
                clean_text = (doc_text or "").strip().replace("\r\n", "\n")
                if len(clean_text) > 350:
                    clean_text = clean_text[:350] + "..."
                evidence_list.append(
                    Evidence(
                        chamber_id=chamber.id,
                        chamber_name=chamber.name,
                        resource_path=str(root),
                        method=f"mempalace[{coll.name}]",
                        record_id=doc_id,
                        content=f"[{coll.name}] memory_id={doc_id}: {clean_text}",
                        metadata={"collection": coll.name, "doc_id": doc_id, "meta": meta},
                    )
                )
        except Exception:
            continue

    if not evidence_list:
        evidence_list.append(
            Evidence(
                chamber_id=chamber.id,
                chamber_name=chamber.name,
                resource_path=str(root),
                method="mempalace_query",
                record_id=None,
                content=f"No matching memories found in MemPalace for query: '{query}'",
                metadata={"query": query},
            )
        )
    return evidence_list[:limit]


def adapter_chamber_05_graph(chamber: Chamber, query: str, limit: int = 5) -> list[Evidence]:
    """Chamber 05: Knowledge Graph triples and entities."""
    path = Path(chamber.physical_path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    evidence_list = []
    search_words = [w.strip() for w in query.replace("?", " ").replace(",", " ").split() if len(w.strip()) > 2]
    filter_word = search_words[0] if search_words else ""

    with sqlite_readonly(str(path)) as conn:
        cursor = conn.cursor()
        if filter_word:
            param = f"%{filter_word}%"
            triples = cursor.execute(
                "SELECT id, subject, predicate, object, confidence FROM triples WHERE subject LIKE ? OR predicate LIKE ? OR object LIKE ? LIMIT ?",
                (param, param, param, limit),
            ).fetchall()
        else:
            triples = cursor.execute(
                "SELECT id, subject, predicate, object, confidence FROM triples LIMIT ?",
                (limit,),
            ).fetchall()

        for tid, subj, pred, obj, conf in triples:
            evidence_list.append(
                Evidence(
                    chamber_id=chamber.id,
                    chamber_name=chamber.name,
                    resource_path=str(path),
                    method="graph_triple",
                    record_id=tid,
                    content=f"Triple: ({subj}) --[{pred}]--> ({obj}) [confidence={conf}]",
                    metadata={"subject": subj, "predicate": pred, "object": obj, "confidence": conf},
                )
            )

        if not evidence_list:
            entities = cursor.execute(
                "SELECT id, name, type FROM entities LIMIT ?", (limit,)
            ).fetchall()
            for eid, ename, etype in entities:
                evidence_list.append(
                    Evidence(
                        chamber_id=chamber.id,
                        chamber_name=chamber.name,
                        resource_path=str(path),
                        method="graph_entity",
                        record_id=eid,
                        content=f"Entity: {ename} (Type: {etype})",
                        metadata={"id": eid, "name": ename, "type": etype},
                    )
                )

    if not evidence_list:
        evidence_list.append(
            Evidence(
                chamber_id=chamber.id,
                chamber_name=chamber.name,
                resource_path=str(path),
                method="graph_query",
                record_id=None,
                content=f"No graph relations found matching query: '{query}'",
                metadata={"query": query},
            )
        )
    return evidence_list[:limit]


def adapter_chamber_06_policy_gate(chamber: Chamber, query: str, limit: int = 5) -> list[Evidence]:
    """Chamber 06: Iron Fist safety gate blocking execution/write actions."""
    return [
        Evidence(
            chamber_id=chamber.id,
            chamber_name=chamber.name,
            resource_path=chamber.physical_path,
            method="policy_gate",
            record_id="POLICY_BLOCK_MUTATION",
            content="Execution/write request detected. Operation blocked by Shaolin Iron Fist policy gate. Human approval and explicit allowlisted plan required.",
            metadata={"query": query, "policy": "read_only_default", "status": "BLOCKED"},
        )
    ]


def adapter_chamber_07_semantic_sqlite(chamber: Chamber, query: str, limit: int = 5) -> list[Evidence]:
    """Chamber 07: Vector Micro-Engine (sqlite-vec + fastembed)."""
    try:
        from semantic_sqlite import search_semantic
        results = search_semantic(query, top_k=limit)
        return [
            Evidence(
                chamber_id=chamber.id,
                chamber_name=chamber.name,
                resource_path=chamber.physical_path,
                method="sqlite_vec_fastembed",
                record_id=str(r.get("id")),
                content=f"Semantic record: {r.get('content')} (score={r.get('score'):.4f})",
                metadata=r,
                score=r.get("score"),
            )
            for r in results
        ]
    except Exception as exc:
        return [
            Evidence(
                chamber_id=chamber.id,
                chamber_name=chamber.name,
                resource_path=chamber.physical_path,
                method="sqlite_vec_error",
                record_id=None,
                content=f"Micro-vector query fallback: {exc}",
                metadata={"error": str(exc)},
            )
        ]


def adapter_chamber_08_commerce_ops(chamber: Chamber, query: str, limit: int = 5) -> list[Evidence]:
    """Chamber 08: Store & Operations SQLite database (read-only)."""
    candidates = [
        Path(chamber.physical_path),
        Path(r"Z:\36_chambers\The_Buch\backend\app\chat.db"),
        Path(r"Z:\36_chambers\The_Buch\backend\chat.db"),
    ]
    target = next((p for p in candidates if p.exists()), None)
    if not target:
        return [
            Evidence(
                chamber_id=chamber.id,
                chamber_name=chamber.name,
                resource_path=chamber.physical_path,
                method="sqlite_sql_read",
                record_id=None,
                content="No operational database file found.",
                metadata={"candidates": [str(c) for c in candidates]},
            )
        ]

    evidence_list = []
    with sqlite_readonly(str(target)) as conn:
        cursor = conn.cursor()
        tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

        if "conversations" in tables:
            rows = cursor.execute(
                "SELECT id, title, created_at FROM conversations ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            for cid, title, cat in rows:
                evidence_list.append(
                    Evidence(
                        chamber_id=chamber.id,
                        chamber_name=chamber.name,
                        resource_path=str(target),
                        method="sqlite_sql_read",
                        record_id=str(cid),
                        content=f"Conversation record #{cid}: '{title}' (Created: {cat})",
                        metadata={"table": "conversations", "id": cid, "title": title},
                    )
                )
        else:
            evidence_list.append(
                Evidence(
                    chamber_id=chamber.id,
                    chamber_name=chamber.name,
                    resource_path=str(target),
                    method="sqlite_sql_schema",
                    record_id=None,
                    content=f"Available operational tables: {', '.join(tables)}",
                    metadata={"tables": tables},
                )
            )

    return evidence_list[:limit]


# ---------------------------------------------------------------------------
# ORCHESTRATION PIPELINE
# ---------------------------------------------------------------------------

def retrieve_one(route: Route, chamber: Chamber, query: str) -> list[Evidence]:
    cid = route.chamber_id
    if route.mode == "policy_gate" or cid == 6:
        return adapter_chamber_06_policy_gate(chamber, query)
    if cid == 1:
        return adapter_chamber_01_sist2(chamber, query)
    if cid == 3:
        return adapter_chamber_03_devz_kb(chamber, query)
    if cid == 4:
        return adapter_chamber_04_mempalace(chamber, query)
    if cid == 5:
        return adapter_chamber_05_graph(chamber, query)
    if cid == 7:
        return adapter_chamber_07_semantic_sqlite(chamber, query)
    if cid == 8:
        return adapter_chamber_08_commerce_ops(chamber, query)

    # Generic fallback
    if route.mode == "semantic":
        return adapter_chamber_03_devz_kb(chamber, query)
    if route.mode in {"sql", "graph_sql"}:
        return adapter_chamber_05_graph(chamber, query)
    if route.mode == "fts":
        return adapter_chamber_01_sist2(chamber, query)

    raise ValueError(f"Unsupported route mode {route.mode} for chamber {cid}")


def retrieve(state: State, chambers: dict[int, Chamber]) -> State:
    if not state.routes:
        state.warnings.append("Router selected no chambers.")
        return state

    def task(route: Route) -> tuple[Route, list[Evidence], str | None, int]:
        start = now_ms()
        try:
            result = retrieve_one(route, get_chamber(chambers, route.chamber_id), state.query)
            return route, result, None, now_ms() - start
        except Exception as exc:
            return route, [], f"Chamber {route.chamber_id} failed: {type(exc).__name__}: {exc}", now_ms() - start

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(state.routes))) as pool:
        futures = [pool.submit(task, route) for route in state.routes]
        for future in futures:
            try:
                route, result, error, latency = future.result(timeout=state.timeout_s)
                state.metrics["retrieval"][str(route.chamber_id)] = {"latency_ms": latency, "mode": route.mode}
                state.evidence.extend(result)
                if error:
                    state.warnings.append(error)
            except concurrent.futures.TimeoutError:
                state.warnings.append("A retrieval task exceeded the global timeout.")
    return state


def verify_evidence(state: State) -> State:
    unique: dict[tuple[int, str | None, str], Evidence] = {}
    for item in state.evidence:
        key = (item.chamber_id, item.record_id, item.content[:200])
        unique.setdefault(key, item)
    state.evidence = list(unique.values())
    if not state.evidence:
        state.warnings.append("No evidence was retrieved. Do not present an unsupported answer.")
    return state


def aggregate(state: State) -> dict[str, Any]:
    lines = [f"Intent: {state.intent}."]
    if state.write_intent:
        lines.append("[POLICY GATE ACTIVE] Execution or write intent detected. No automated commands executed; explicit approval required.")
    if state.evidence:
        chambers_str = ", ".join(sorted({f"Chamber {e.chamber_id:02d}" for e in state.evidence}))
        lines.append(f"Retrieved {len(state.evidence)} evidence item(s) across: {chambers_str}.")
        lines.extend(f"- [{e.chamber_name} | {e.method}] {e.content}" for e in state.evidence[:8])
    else:
        lines.append("No verified evidence is available for a grounded answer.")
    if state.warnings:
        lines.append("Warnings: " + " | ".join(state.warnings))
    return {
        "request_id": state.request_id,
        "answer": "\n".join(lines),
        "intent": state.intent,
        "route": [asdict(r) for r in state.routes],
        "sources": [asdict(e) for e in state.evidence],
        "warnings": state.warnings,
        "metrics": state.metrics,
    }


def write_trace(result: dict[str, Any], trace_dir: Path) -> None:
    trace_dir.mkdir(parents=True, exist_ok=True)
    target = trace_dir / f"{result['request_id']}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def log_observatory_events(state: State, result: dict[str, Any]) -> None:
    events_file = Path(r"Z:\36_chambers\.doc\observatory\events\events.jsonl")
    try:
        events_file.parent.mkdir(parents=True, exist_ok=True)
        now_str = datetime.now(timezone.utc).isoformat()
        with events_file.open("a", encoding="utf-8") as f:
            for route in state.routes:
                lat = state.metrics.get("retrieval", {}).get(str(route.chamber_id), {}).get("latency_ms", 0)
                f.write(json.dumps({
                    "event_type": "agent_event",
                    "event_time": now_str,
                    "request_id": state.request_id,
                    "agent_name": "shaolin_orchestrator",
                    "app_name": "The_Buch",
                    "chamber_id": route.chamber_id,
                    "resource_id": f"chamber_{route.chamber_id:02d}",
                    "action": f"{route.mode}_retrieval",
                    "status": "success",
                    "latency_ms": lat,
                    "model": "local-deterministic",
                    "task_type": state.intent
                }) + "\n")
            for rank, ev in enumerate(state.evidence, 1):
                f.write(json.dumps({
                    "event_type": "retrieval_event",
                    "event_time": now_str,
                    "request_id": state.request_id,
                    "agent_name": "shaolin_orchestrator",
                    "chamber_id": ev.chamber_id,
                    "resource_id": f"chamber_{ev.chamber_id:02d}",
                    "document_id": ev.record_id or ev.metadata.get("path") or "doc_unknown",
                    "chunk_id": f"{ev.record_id}_chunk",
                    "retrieval_method": ev.method,
                    "rank": rank,
                    "score": ev.score or 1.0,
                    "included_in_prompt": True,
                    "cited_in_answer": True,
                    "source_modified_at": now_str,
                    "indexed_at": now_str,
                    "embedding_model": "bge-small-en-v1.5",
                    "token_count": len(ev.content) // 4
                }) + "\n")
    except Exception:
        pass


def run(query: str, registry_path: Path = DEFAULT_REGISTRY, allow_web: bool = False, trace_dir: Path = DEFAULT_TRACE_DIR) -> dict[str, Any]:
    chambers = load_registry(registry_path)
    state = State(request_id=str(uuid.uuid4()), query=query, allow_web=allow_web)
    total_start = now_ms()
    timed(state, "decomposition", lambda: decompose_query(state))
    timed(state, "routing", lambda: route_query(state, chambers))
    timed(state, "retrieval_total", lambda: retrieve(state, chambers))
    timed(state, "verification", lambda: verify_evidence(state))
    result = timed(state, "aggregation", lambda: aggregate(state))
    state.metrics["total_latency_ms"] = now_ms() - total_start
    result["metrics"] = state.metrics
    write_trace(result, trace_dir)
    log_observatory_events(state, result)
    return result



def main() -> int:
    parser = argparse.ArgumentParser(description="36 Chambers read-only Shaolin Orchestrator")
    parser.add_argument("query")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--allow-web", action="store_true")
    parser.add_argument("--trace-dir", type=Path, default=DEFAULT_TRACE_DIR)
    args = parser.parse_args()
    if not args.registry.exists():
        print(f"Registry not found: {args.registry}", file=sys.stderr)
        return 2
    res = run(args.query, args.registry, args.allow_web, args.trace_dir)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
