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

# Host-specific paths resolve from environment via config.py (see .env.example).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import path as env_path, require as require_path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


try:
    import chromadb
except ImportError:
    chromadb = None

DEFAULT_REGISTRY = require_path("CHAMBERS_REGISTRY")
DEFAULT_TRACE_DIR = require_path("CHAMBERS_TRACE_DIR")

# Question words that match almost every indexed path and therefore destroy Chamber 01 precision.
SIST2_STOPWORDS = {
    "znajdź", "znajdz", "pokaz", "pokaż", "jakie", "jaki", "jaka", "które", "ktore", "gdzie",
    "dokument", "dokumenty", "dokumentów", "plik", "pliki", "plików", "folder", "foldery",
    "dysk", "dysku", "dyski", "zawierające", "zawierajace", "posiada", "dotyczące", "dotyczace",
    "oraz", "przez", "tego", "tych", "jest", "są", "sie", "się", "dla", "the", "and", "for",
}

# Graph terms become LIKE filters over triple subjects/objects; question words only add noise.
# Deliberately excludes bare "encj*" stems: "preferencje" contains "encje" and would hijack the
# memory intent into the graph chamber.
GRAPH_STOPWORDS = SIST2_STOPWORDS | {
    "graf", "grafie", "grafu", "relacja", "relacje", "relacji", "fakty", "wspierają", "wspieraja",
}

# The sist2 index spans whole volumes, so a plain substring match returns dependency internals
# (venv/site-packages, node_modules) instead of project knowledge. Filtered at query time.
SIST2_EXCLUDE_SQL = (
    "AND path NOT LIKE '%/venv/%' AND path NOT LIKE '%\\\\venv\\\\%' "
    "AND path NOT LIKE '%node_modules%' AND path NOT LIKE '%/__pycache__/%' "
    "AND path NOT LIKE '%/site-packages/%' AND path NOT LIKE '%/.git/%' "
    "AND path NOT LIKE '%.pyc'"
)

# A .sist2 file touched more recently than this is probably still being written; reading it with
# immutable=1 can yield a torn snapshot. Prefer the last index that has settled.
SIST2_QUIESCENCE_SECONDS = 60


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


# Mutation lexicon. Deliberately fail-closed: a false positive only routes the request to the
# Chamber 06 policy gate (no side effect), while a false negative would let a write through.
MUTATION_TERMS = (
    "usuń", "usun", "skasuj", "delete", "drop", "truncate",
    "zapisz", "zapamięt", "dopis", "dodaj", "wstaw", "nadpisz", "zmień", "zmien", "edytuj", "update", "insert",
    "uruchom", "wykonaj", "odpal", "terminal", "skrypt", "powershell", "cmd ",
    "przenieś", "skopiuj", "wgraj", "instaluj", "archiwizuj", "wyczys", "reset",
)


def decompose_query(state: State) -> State:
    q = state.query.lower()
    if any(term in q for term in MUTATION_TERMS):
        state.intent = "execution"
        state.subqueries = [state.query]
        state.write_intent = True
    elif any(term in q for term in (
        "cena", "ceny", "cene", "cenie", "cenow", "marż", "marz", "faktur", "produkt",
        "dostawc", "sklep", "zamów", "zamow", "konwersacj", "sprzeda", "magazyn", "zapas", "inwentarz",
    )):
        state.intent, state.subqueries = "commerce", [state.query]
    elif any(term in q for term in (
        "relacj", "graf", "węzeł", "węzł", "wezl", "entity", "entities", "kto z kim",
        "trójk", "trojc", "triple", "połączon", "polaczon", "powiązan", "powiazan", "wspiera",
    )):
        state.intent, state.subqueries = "graph", [state.query]
    elif any(term in q for term in (
        "pamię", "pamie", "preferencj", "histori", "mempalace", "drawer", "closet", "pomiar",
    )):
        state.intent, state.subqueries = "memory", [state.query]
    elif any(term in q for term in (
        "plik", "folder", "katalog", "dysk", "znajdź dokument", "muninn", "sist2",
    )):
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

def _sist2_pick_index(paths: list[str], required_table: str) -> str | None:
    """Newest settled .sist2 that carries ``required_table``.

    Two index kinds now live side by side in the data folder: the document index (table
    ``document``) and the SQLite full-text search index (table ``search``). Selecting by mtime
    alone can land on the wrong one, so the required table is checked and in-progress files are
    skipped unless nothing has settled yet.
    """
    now = time.time()
    settled: list[str] = []
    fresh: list[str] = []
    for candidate in paths:
        try:
            with sqlite_readonly(candidate, immutable=True) as conn:
                has_table = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (required_table,)
                ).fetchone()
            if not has_table:
                continue
        except Exception:
            continue
        bucket = fresh if now - os.path.getmtime(candidate) < SIST2_QUIESCENCE_SECONDS else settled
        bucket.append(candidate)
    pool = settled or fresh
    return max(pool, key=os.path.getmtime) if pool else None


def _sist2_fts_terms(query: str, max_terms: int = 6) -> list[str]:
    """Distinctive terms for a MATCH query, longest first (positional guessing picks stopwords)."""
    terms = [w.strip('.,?!:;"\'()').lower() for w in query.split()]
    terms = [t for t in terms if len(t) > 2 and t not in SIST2_STOPWORDS]
    return sorted(dict.fromkeys(terms), key=len, reverse=True)[:max_terms]


def adapter_chamber_01_sist2(chamber: Chamber, query: str, limit: int = 5) -> list[Evidence]:
    """Chamber 01: full-text/content search plus file-name discovery on indexed volumes."""
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

    evidence_list: list[Evidence] = []

    # 1) Prefer the SQLite FTS5 search index: it matches document CONTENT. The document index
    #    only carries names and metadata, so a LIKE scan over it is a file-name lookup.
    search_index = _sist2_pick_index(sist_files, "search")
    if search_index:
        fts_terms = _sist2_fts_terms(query)
        rows: list[Any] = []
        fts_query = ""
        # Progressive AND over terms sorted longest-first: drop the least distinctive term one at a
        # time. An OR fallback would answer an "does X exist?" question with arbitrary documents
        # and echo the query back, which is both junk evidence and a false positive for negatives.
        for take in range(len(fts_terms), 0, -1):
            fts_query = " AND ".join('"' + t.replace('"', '""') + '"' for t in fts_terms[:take])
            try:
                with sqlite_readonly(search_index, immutable=True) as conn:
                    rows = conn.execute(
                        "SELECT d.id, d.path, d.name, d.mime, d.size, bm25(search) AS score "
                        "FROM search s JOIN document_index d ON d.id = s.rowid "
                        "WHERE s.search MATCH ? "
                        "ORDER BY (d.mime IS NULL), score LIMIT ?",
                        (fts_query, limit),
                    ).fetchall()
            except Exception:
                rows = []
            if rows:
                break

        for row_id, doc_path, doc_name, mime, size, score in rows:
            # document_index keeps the folder in `path` and the leaf in `name`.
            full_path = f"{doc_path.rstrip('/')}/{doc_name}" if doc_name else doc_path
            evidence_list.append(
                Evidence(
                    chamber_id=chamber.id,
                    chamber_name=chamber.name,
                    resource_path=search_index,
                    method="sist2_fts_match",
                    record_id=str(row_id),
                    content=(
                        f"Content match for {fts_query}: {full_path} "
                        f"(type={mime or 'directory'}, size={size} bytes, bm25={score:.3f})"
                    ),
                    metadata={
                        "path": full_path,
                        "dir": doc_path,
                        "name": doc_name,
                        "mime": mime,
                        "size": size,
                        "bm25": score,
                        "fts_query": fts_query,
                    },
                    score=score,
                )
            )

    # 2) Fall back to the document index (file-name / metadata lookup) when FTS is absent or empty.
    doc_index = _sist2_pick_index(sist_files, "document")
    if not evidence_list and doc_index:
        search_terms = [
            w.strip() for w in query.replace("?", " ").replace(",", " ").replace(".", " ").split()
            if len(w.strip()) > 2 and w.strip().lower() not in SIST2_STOPWORDS
        ]
        search_terms.sort(key=len, reverse=True)
        if not search_terms:
            search_terms = [query.strip()]

        seen_ids: set[Any] = set()
        try:
            with sqlite_readonly(doc_index, immutable=True) as conn:
                cursor = conn.cursor()
                for term in search_terms:
                    if len(evidence_list) >= limit:
                        break
                    param = f"%{term}%"
                    rows = cursor.execute(
                        "SELECT id, path, size, json_data FROM document "
                        "WHERE (path LIKE ? OR json_data LIKE ?) " + SIST2_EXCLUDE_SQL + " LIMIT ?",
                        (param, param, limit - len(evidence_list)),
                    ).fetchall()
                    for doc_id, doc_path, doc_size, json_data in rows:
                        if doc_id in seen_ids:
                            continue
                        seen_ids.add(doc_id)
                        evidence_list.append(
                            Evidence(
                                chamber_id=chamber.id,
                                chamber_name=chamber.name,
                                resource_path=doc_index,
                                method="sist2_index_match",
                                record_id=str(doc_id),
                                content=f"Document: {doc_path} (Size: {doc_size} bytes, Metadata: {json_data})",
                                metadata={"path": doc_path, "size": doc_size, "matched_term": term, "query": query},
                            )
                        )
        except Exception as exc:
            evidence_list.append(
                Evidence(
                    chamber_id=chamber.id,
                    chamber_name=chamber.name,
                    resource_path=doc_index,
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
                resource_path=search_index or doc_index or chamber.physical_path,
                method="sist2_no_match",
                record_id=None,
                content="No documents matched the supplied query terms in the sist2 indexes.",
                metadata={"query": query, "terms": _sist2_fts_terms(query)},
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

    per_collection: dict[str, list[Evidence]] = {}
    for coll in active_colls:
        try:
            res = coll.query(
                query_texts=[query],
                n_results=max(limit, 3),
                include=["documents", "metadatas", "distances"],
            )
            ids = res.get("ids", [[]])[0]
            docs = res.get("documents", [[]])[0]
            metas = res.get("metadatas", [[]])[0] or [{}] * len(ids)
            dists = (res.get("distances") or [[]])[0]

            items: list[Evidence] = []
            for idx, (doc_id, doc_text, meta) in enumerate(zip(ids, docs, metas)):
                clean_text = (doc_text or "").strip().replace("\r\n", "\n")
                if len(clean_text) > 400:
                    clean_text = clean_text[:400] + "..."
                distance = float(dists[idx]) if idx < len(dists) and dists[idx] is not None else 999.0
                items.append(
                    Evidence(
                        chamber_id=chamber.id,
                        chamber_name=chamber.name,
                        resource_path=str(root),
                        method=f"chroma_semantic[{coll.name}]",
                        record_id=doc_id,
                        content=f"[{coll.name}] doc_id={doc_id}: {clean_text}",
                        metadata={"collection": coll.name, "doc_id": doc_id, "meta": meta, "distance": distance},
                        score=distance,
                    )
                )
            if items:
                per_collection[coll.name] = items
        except Exception:
            continue

    # Reciprocal Rank Fusion across collections. A flat global distance sort lets the largest
    # collection crowd out the others, dropping the best chunk of a smaller category.
    rrf_k = 60
    fused: dict[str, tuple[float, Evidence]] = {}
    for name, items in per_collection.items():
        for rank, ev in enumerate(items, start=1):
            key = f"{name}:{ev.record_id}"
            increment = 1.0 / (rrf_k + rank)
            prior = fused.get(key)
            fused[key] = ((prior[0] + increment) if prior else increment, ev)
    ranked = sorted(fused.values(), key=lambda pair: pair[0], reverse=True)
    evidence_list = [ev for _, ev in ranked[:limit]]

    if not evidence_list:
        evidence_list.append(
            Evidence(
                chamber_id=chamber.id,
                chamber_name=chamber.name,
                resource_path=str(root),
                method="chroma_semantic",
                record_id=None,
                content="No matching documents found in DEVz KB collections for the supplied query terms.",
                metadata={"query_terms": query.split()},
            )
        )
    return evidence_list


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

    evidence_list: list[Evidence] = []
    # Rank terms by length: an unfiltered fallback would silently answer with arbitrary rows and
    # present them as evidence, which is confabulation. No match -> explicit "no relations found".
    terms = [
        t for t in (w.strip('.,?!:;"\'()').lower() for w in query.split())
        if len(t) > 3 and t not in GRAPH_STOPWORDS
    ]
    terms = sorted(dict.fromkeys(terms), key=len, reverse=True)

    with sqlite_readonly(str(path)) as conn:
        cursor = conn.cursor()
        seen: set[str] = set()
        for term in terms:
            param = f"%{term}%"
            rows = cursor.execute(
                "SELECT id, subject, predicate, object, confidence FROM triples "
                "WHERE subject LIKE ? OR predicate LIKE ? OR object LIKE ? LIMIT ?",
                (param, param, param, limit),
            ).fetchall()
            for tid, subj, pred, obj, conf in rows:
                if tid in seen:
                    continue
                seen.add(tid)
                evidence_list.append(
                    Evidence(
                        chamber_id=chamber.id,
                        chamber_name=chamber.name,
                        resource_path=str(path),
                        method="graph_triple",
                        record_id=tid,
                        content=f"Triple: ({subj}) --[{pred}]--> ({obj}) [confidence={conf}]",
                        metadata={"subject": subj, "predicate": pred, "object": obj, "confidence": conf, "matched_term": term},
                    )
                )
            if len(evidence_list) >= limit:
                break

        if not evidence_list:
            # Entities are only returned when the name actually matches a query term.
            for term in terms:
                param = f"%{term}%"
                rows = cursor.execute(
                    "SELECT id, name, type FROM entities WHERE name LIKE ? LIMIT ?", (param, limit)
                ).fetchall()
                for eid, ename, etype in rows:
                    if eid in seen:
                        continue
                    seen.add(eid)
                    evidence_list.append(
                        Evidence(
                            chamber_id=chamber.id,
                            chamber_name=chamber.name,
                            resource_path=str(path),
                            method="graph_entity",
                            record_id=eid,
                            content=f"Entity: {ename} (Type: {etype})",
                            metadata={"id": eid, "name": ename, "type": etype, "matched_term": term},
                        )
                    )
                if len(evidence_list) >= limit:
                    break

    if not evidence_list:
        evidence_list.append(
            Evidence(
                chamber_id=chamber.id,
                chamber_name=chamber.name,
                resource_path=str(path),
                method="graph_query",
                record_id=None,
                content="No graph relations found for the supplied query terms.",
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
    candidates = [Path(chamber.physical_path)]
    for _name in ("CHAMBERS_CHAT_DB_PRIMARY", "CHAMBERS_CHAT_DB_FALLBACK"):
        _db = env_path(_name)
        if _db:
            candidates.append(_db)
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

        def columns(table: str) -> list[str]:
            return [r[1] for r in cursor.execute(f'PRAGMA table_info("{table}")').fetchall()]

        if "conversations" in tables:
            # Schema is discovered, never assumed: chat.db ships conversations(id, created_at).
            conv_cols = columns("conversations")
            selectable = [c for c in ("id", "title", "created_at") if c in conv_cols]
            if not selectable:
                selectable = conv_cols[:1]
            if not selectable:
                return [
                    Evidence(
                        chamber_id=chamber.id,
                        chamber_name=chamber.name,
                        resource_path=str(target),
                        method="sqlite_sql_schema",
                        record_id=None,
                        content="Table 'conversations' has no readable columns.",
                        metadata={"tables": tables},
                    )
                ]

            order_by = ' ORDER BY "id" DESC' if "id" in conv_cols else ""
            sel = ", ".join('"' + c + '"' for c in selectable)
            rows = cursor.execute(
                f"SELECT {sel} FROM conversations{order_by} LIMIT ?", (limit,)
            ).fetchall()

            msg_counts: dict[Any, int] = {}
            if "messages" in tables and "conversation_id" in columns("messages"):
                msg_counts = dict(
                    cursor.execute("SELECT conversation_id, COUNT(*) FROM messages GROUP BY conversation_id").fetchall()
                )

            for row in rows:
                record = dict(zip(selectable, row))
                cid = record.get("id")
                title = record.get("title") or f"conversation #{cid}"
                evidence_list.append(
                    Evidence(
                        chamber_id=chamber.id,
                        chamber_name=chamber.name,
                        resource_path=str(target),
                        method="sqlite_sql_read",
                        record_id=str(cid),
                        content=(
                            f"Conversation record #{cid}: '{title}' (Created: {record.get('created_at')}, "
                            f"messages: {msg_counts.get(cid, 0)})"
                        ),
                        metadata={"table": "conversations", **record, "message_count": msg_counts.get(cid, 0)},
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
    events_file = env_path("CHAMBERS_OBSERVATORY_EVENTS")
    if events_file is None:
        return
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
