"""Read-only, registry-driven orchestration for the 36 Chambers of Shaolin Cognitive Matrix.

Integrates read-only database adapters for:
- Chamber 01 (sist2 document index / FTS5)
- Chamber 03 (DEVz Knowledge Base / ChromaDB)
- Chamber 04 (MemPalace / ChromaDB)
- Chamber 05 (Graph of Truth / SQLite triples & entities)
- Chamber 06 (The Iron Fist / Policy gate for write & execution)
- Chamber 08 (Store & Operations / SQLite chat.db)

Chamber 07 is intentionally not implemented until a database schema, embedding model, and
query contract are supplied. Chamber 36 currently orchestrates and aggregates evidence; it does
not perform generative synthesis. Both limitations are declared in the registry.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import glob
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Host-specific paths resolve from environment via config.py (see .env.example).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import path as env_path
from config import require as require_path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


try:
    import chromadb
except ImportError:
    chromadb = None

DEFAULT_REGISTRY = env_path("CHAMBERS_REGISTRY")
DEFAULT_TRACE_DIR = env_path("CHAMBERS_TRACE_DIR")

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
    adapter: str | None = None
    status: str = "implemented"
    route_modes: tuple[str, ...] = ()
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
    policy_blocked: bool = False
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
    chambers: dict[int, Chamber] = {}
    for raw in data.get("chambers", []):
        chamber_id = int(raw["id"])
        if chamber_id in chambers:
            raise ValueError(f"Duplicate chamber id {chamber_id} in registry")
        chambers[chamber_id] = Chamber(
            id=chamber_id,
            name=raw["name"],
            domain=raw.get("domain", raw.get("specialization", "")),
            engine=raw.get("engine", ""),
            physical_path=raw.get("physical_path", raw.get("path", raw.get("endpoint", ""))),
            adapter=raw.get("adapter"),
            status=str(raw.get("status", "implemented")).lower(),
            route_modes=tuple(raw.get("route_modes", ())),
            description=raw.get("description", raw.get("specialization", "")),
            notes=raw.get("notes", ""),
        )
    validate_registry(chambers)
    return chambers


def validate_registry(chambers: dict[int, Chamber]) -> None:
    """Fail fast when registry capability claims do not match executable adapters."""
    valid_statuses = {"implemented", "not_implemented", "orchestration_only"}
    for chamber in chambers.values():
        if chamber.status not in valid_statuses:
            raise ValueError(f"Chamber {chamber.id} has unsupported status {chamber.status!r}")
        if chamber.status == "implemented":
            if not chamber.adapter or chamber.adapter not in ADAPTERS:
                raise ValueError(
                    f"Implemented chamber {chamber.id} must name a registered adapter; "
                    f"got {chamber.adapter!r}"
                )
            supported_modes = ADAPTER_ROUTE_MODES[chamber.adapter]
            if not chamber.route_modes or not set(chamber.route_modes).issubset(supported_modes):
                raise ValueError(
                    f"Chamber {chamber.id} route_modes {chamber.route_modes!r} do not match "
                    f"adapter {chamber.adapter!r} modes {sorted(supported_modes)!r}"
                )
        elif chamber.adapter is not None or chamber.route_modes:
            raise ValueError(
                f"Non-retrieval chamber {chamber.id} must not declare an adapter or route_modes"
            )
    if 36 in chambers and chambers[36].status != "orchestration_only":
        raise ValueError("Chamber 36 must be orchestration_only until synthesis is implemented")
    invalid_orchestrators = sorted(
        chamber.id
        for chamber in chambers.values()
        if chamber.id != 36 and chamber.status == "orchestration_only"
    )
    if invalid_orchestrators:
        raise ValueError(
            "Only Chamber 36 may be orchestration_only; invalid chamber ids: "
            f"{invalid_orchestrators}"
        )


def get_chamber(chambers: dict[int, Chamber], chamber_id: int) -> Chamber:
    try:
        return chambers[chamber_id]
    except KeyError as exc:
        raise ValueError(f"Chamber {chamber_id} is not registered") from exc


# Mutation command verbs. They are only treated as action requests in imperative or polite-command
# position so explanatory questions (for example, "how delete commands work") stay retrievable.
MUTATION_TERMS = (
    "usuń", "usun", "skasuj", "delete", "drop", "truncate",
    "zapisz", "zapamięt", "dopis", "dodaj", "wstaw", "nadpisz", "zmień", "zmien", "zmieni", "edytuj", "update", "insert", "zaktualizuj", "aktualizuj",
    "uruchom", "wykonaj", "odpal",
    "przenieś", "skopiuj", "wgraj", "instaluj", "archiwizuj", "wyczys", "reset",
)
MUTATION_STEMS = ("usun", "zapamięt", "dopis", "zmień", "zmieni", "wyczys")
COMMAND_REQUEST_PREFIXES = (
    "can you please ", "could you please ", "would you please ", "i want you to ",
    "i need you to ", "can you ", "could you ", "would you ", "i need to ", "i want to ",
    "please ", "proszę ", "prosze ", "czy możesz ", "czy mozesz ", "ok, ", "then, ",
)
ANSWER_EVIDENCE_LIMIT = 8

# Deterministic prompt-injection patterns. These are policy requests rather than knowledge
# questions, so they must reach Chamber 06 even when they contain no mutation verb.
SECURITY_BLOCK_TERMS = (
    "ignore all previous instructions", "ignore previous instructions", "ignore prior instructions",
    "bypass security", "bypass policy", "jailbreak",
)
PROTECTED_PROMPT_TARGETS = (
    "system prompt", "developer message", "developer instructions", "hidden instructions", "internal instructions",
)
PROTECTED_PROMPT_VALUE_REFERENCES = (
    "the system prompt", "your system prompt", "my system prompt", "the developer message",
    "your developer message", "my developer message", "system prompt content", "system prompt text",
    "system prompt verbatim", "developer message content", "developer message text",
)
CREDENTIAL_TARGETS = (
    "database password", "master password", "password", "api key", "access token", "auth token",
    "private key", "credentials", "the secret", "secret value",
)
CREDENTIAL_VALUE_REFERENCES = tuple(
    f"{owner} {target}"
    for owner in ("the", "my", "your", "our")
    for target in CREDENTIAL_TARGETS
) + (
    "api key value", "password value", "token value", "stored api key", "stored password",
    "stored token", "actual api key", "actual password", "actual token",
)
DIRECT_DISCLOSURE_TERMS = ("reveal", "print", "output", "disclose", "display", "give me")
GENERIC_DISCLOSURE_TERMS = ("show", "tell me", "what is")


def has_mutation_intent(query: str) -> bool:
    """Fail closed for imperative writes while allowing informational mentions of command verbs."""
    command_terms = MUTATION_TERMS + (
        "execute", "run", "move", "copy", "remove", "restore", "overwrite", "install",
    )
    for clause in re.split(r"[.!?;\n]+", query):
        request = clause.strip()
        while True:
            prefix = next((p for p in COMMAND_REQUEST_PREFIXES if request.startswith(p)), None)
            if prefix is None:
                break
            request = request[len(prefix):].lstrip()
        for term in command_terms:
            if not request.startswith(term):
                continue
            if term in MUTATION_STEMS or (
                len(request) == len(term) or not request[len(term)].isalpha()
            ):
                return True
    return False


def has_security_block_intent(query: str) -> bool:
    """Detect explicit policy bypass or requests to exfiltrate sensitive prompt material."""
    if any(term in query for term in SECURITY_BLOCK_TERMS):
        return True

    # Direct disclosure verbs plus a protected target are unambiguously exfiltration. Generic
    # "show"/"tell me" wording must also identify the live prompt value, so design questions
    # such as "show system prompt examples" remain technical-knowledge queries.
    if any(term in query for term in DIRECT_DISCLOSURE_TERMS) and any(
        target in query for target in PROTECTED_PROMPT_TARGETS
    ):
        return True
    if any(term in query for term in GENERIC_DISCLOSURE_TERMS) and any(
        target in query for target in PROTECTED_PROMPT_VALUE_REFERENCES
    ):
        return True

    if any(term in query for term in DIRECT_DISCLOSURE_TERMS) and any(
        target in query for target in CREDENTIAL_TARGETS
    ):
        return True
    return any(term in query for term in GENERIC_DISCLOSURE_TERMS) and any(
        target in query for target in CREDENTIAL_VALUE_REFERENCES
    )


def decompose_query(state: State) -> State:
    q = state.query.lower()
    if has_security_block_intent(q):
        state.intent = "prompt_injection_attack"
        state.subqueries = [state.query]
        state.policy_blocked = True
    elif has_mutation_intent(q):
        state.intent = "execution"
        state.subqueries = [state.query]
        state.write_intent = True
        state.policy_blocked = True
    elif any(term in q for term in (
        "cena", "ceny", "cene", "cenie", "cenow", "marż", "marz", "faktur", "produkt",
        "dostawc", "sklep", "zamów", "zamow", "konwersacj", "sprzeda", "magazyn", "zapas", "inwentarz",
        "price", "product", "supplier", "store", "inventory", "stock", "conversation",
    )):
        state.intent, state.subqueries = "commerce", [state.query]
    elif any(term in q for term in (
        "relacj", "graf", "węzeł", "węzł", "wezl", "entity", "entities", "kto z kim",
        "trójk", "trojc", "triple", "połączon", "polaczon", "powiązan", "powiazan", "wspiera",
        "relation", "connected",
    )):
        state.intent, state.subqueries = "graph", [state.query]
    elif any(term in q for term in (
        "pamię", "pamie", "preferencj", "histori", "mempalace", "drawer", "closet", "pomiar",
        "memory", "preference", "history", "recall",
    )):
        state.intent, state.subqueries = "memory", [state.query]
    elif any(term in q for term in (
        "plik", "folder", "katalog", "dysk", "znajdź dokument", "muninn", "sist2",
        " file", "directory", " disk",
    )):
        state.intent, state.subqueries = "file_discovery", [state.query]
    else:
        state.intent, state.subqueries = "technical_knowledge", [state.query]
    return state


def route_query(state: State, chambers: dict[int, Chamber]) -> State:
    candidates: list[Route]
    if state.policy_blocked:
        candidates = [Route(6, "policy_gate", "Security policy-sensitive intent detected")]
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

    if state.allow_web:
        if state.policy_blocked:
            state.warnings.append("Web retrieval was suppressed by the security policy gate.")
        elif 2 in chambers and chambers[2].status == "implemented":
            candidates.append(Route(2, "http", "Web retrieval explicitly allowed"))
        else:
            state.warnings.append("Web retrieval requested, but Chamber 02 is not implemented.")

    state.routes = [
        route
        for route in candidates
        if route.chamber_id in chambers
        and chambers[route.chamber_id].status == "implemented"
        and route.mode in chambers[route.chamber_id].route_modes
    ][: state.max_chambers]
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
                    # The appended clause is a module constant; all user values stay bound.
                    lookup_sql = (
                        "SELECT id, path, size, json_data FROM document "  # nosec B608
                        "WHERE (path LIKE ? OR json_data LIKE ?) "
                        + SIST2_EXCLUDE_SQL
                        + " LIMIT ?"
                    )
                    rows = cursor.execute(
                        lookup_sql,
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
            content=(
                "SECURITY BLOCKED: policy-sensitive prompt, execution, or write intent detected. "
                "No operation was performed; human approval and an explicit allowlisted plan are required."
            ),
            metadata={"query": query, "policy": "read_only_default", "status": "BLOCKED"},
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
            # Identifiers come only from the fixed allowlist above, never from the query.
            conversation_sql = (
                f"SELECT {sel} FROM conversations{order_by} LIMIT ?"  # nosec B608
            )
            rows = cursor.execute(conversation_sql, (limit,)).fetchall()

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

ADAPTERS: dict[str, Callable[[Chamber, str, int], list[Evidence]]] = {
    "sist2": adapter_chamber_01_sist2,
    "chroma_devz": adapter_chamber_03_devz_kb,
    "chroma_mempalace": adapter_chamber_04_mempalace,
    "graph_sqlite": adapter_chamber_05_graph,
    "policy_gate": adapter_chamber_06_policy_gate,
    "commerce_sqlite": adapter_chamber_08_commerce_ops,
}

ADAPTER_ROUTE_MODES: dict[str, set[str]] = {
    "sist2": {"fts"},
    "chroma_devz": {"semantic"},
    "chroma_mempalace": {"semantic"},
    "graph_sqlite": {"graph_sql"},
    "policy_gate": {"policy_gate"},
    "commerce_sqlite": {"sql"},
}

def retrieve_one(route: Route, chamber: Chamber, query: str) -> list[Evidence]:
    if chamber.status != "implemented" or not chamber.adapter:
        raise ValueError(f"Chamber {chamber.id} is not an implemented retrieval chamber")
    if route.mode not in chamber.route_modes:
        raise ValueError(f"Route mode {route.mode!r} is not declared for chamber {chamber.id}")
    return ADAPTERS[chamber.adapter](chamber, query, 5)


def retrieve(state: State, chambers: dict[int, Chamber]) -> State:
    if not state.routes:
        state.warnings.append("Router selected no chambers.")
        return state

    def task(route: Route) -> tuple[Route, list[Evidence], str | None, int]:
        start = now_ms()
        try:
            chamber = get_chamber(chambers, route.chamber_id)
            result = retrieve_one(route, chamber, state.query)
            return route, result, None, now_ms() - start
        except Exception as exc:
            message = f"Chamber {route.chamber_id} failed: {type(exc).__name__}: {exc}"
            return route, [], message, now_ms() - start

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(state.routes))) as pool:
        futures = [pool.submit(task, route) for route in state.routes]
        for future in futures:
            try:
                route, result, error, latency = future.result(timeout=state.timeout_s)
                route_metric = {
                    "latency_ms": latency,
                    "mode": route.mode,
                    "status": "failed" if error else "success",
                }
                if error:
                    route_metric["error"] = error
                state.metrics["retrieval"][str(route.chamber_id)] = route_metric
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
    if state.policy_blocked:
        lines.append("[POLICY GATE ACTIVE] Security-sensitive intent detected. No automated action was taken.")
    if state.evidence:
        chambers_str = ", ".join(sorted({f"Chamber {e.chamber_id:02d}" for e in state.evidence}))
        lines.append(f"Retrieved {len(state.evidence)} evidence item(s) across: {chambers_str}.")
        lines.extend(
            f"- [{e.chamber_name} | {e.method} | record_id={e.record_id if e.record_id is not None else 'unverified'}] {e.content}"
            for e in state.evidence[:ANSWER_EVIDENCE_LIMIT]
        )
    else:
        lines.append("No verified evidence is available for a grounded answer.")
    if state.warnings:
        lines.append("Warnings: " + " | ".join(state.warnings))
    return {
        "request_id": state.request_id,
        "answer": "\n".join(lines),
        "answer_mode": "evidence_aggregation",
        "answer_evidence_limit": ANSWER_EVIDENCE_LIMIT,
        "synthesis": {
            "chamber_id": 36,
            "status": "not_implemented",
            "detail": "The deterministic answer is an evidence pack; no LLM synthesis was performed.",
        },
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
                route_metric = state.metrics.get("retrieval", {}).get(str(route.chamber_id), {})
                lat = route_metric.get("latency_ms", 0)
                f.write(json.dumps({
                    "event_type": "agent_event",
                    "event_time": now_str,
                    "request_id": state.request_id,
                    "agent_name": "shaolin_orchestrator",
                    "app_name": "The_Buch",
                    "chamber_id": route.chamber_id,
                    "resource_id": f"chamber_{route.chamber_id:02d}",
                    "action": f"{route.mode}_retrieval",
                    "status": route_metric.get("status", "failed"),
                    "error": route_metric.get("error"),
                    "latency_ms": lat,
                    "model": "local-deterministic",
                    "task_type": state.intent
                }) + "\n")
            for rank, ev in enumerate(state.evidence, 1):
                method = ev.method.lower()
                if "error" in method or "no_match" in method or ev.record_id is None:
                    continue
                f.write(json.dumps({
                    "event_type": "retrieval_event",
                    "event_time": now_str,
                    "request_id": state.request_id,
                    "agent_name": "shaolin_orchestrator",
                    "chamber_id": ev.chamber_id,
                    "resource_id": f"chamber_{ev.chamber_id:02d}",
                    "document_id": (
                        ev.record_id
                        if ev.record_id is not None
                        else ev.metadata.get("path") or "doc_unknown"
                    ),
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


def run(
    query: str,
    registry_path: Path | None = DEFAULT_REGISTRY,
    allow_web: bool = False,
    trace_dir: Path | None = DEFAULT_TRACE_DIR,
) -> dict[str, Any]:
    registry_path = registry_path or require_path("CHAMBERS_REGISTRY")
    trace_dir = trace_dir or require_path("CHAMBERS_TRACE_DIR")
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
    try:
        registry_path = args.registry or require_path("CHAMBERS_REGISTRY")
        trace_dir = args.trace_dir or require_path("CHAMBERS_TRACE_DIR")
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not registry_path.exists():
        print(f"Registry not found: {registry_path}", file=sys.stderr)
        return 2
    res = run(args.query, registry_path, args.allow_web, trace_dir)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
