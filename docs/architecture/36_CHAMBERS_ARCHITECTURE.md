# 36 Chambers Cognitive Matrix — Architecture

> **Status:** evolving architecture  
> **Primary orchestrator:** `$CHAMBERS_ORCHESTRATOR`  
> **Registry:** `$CHAMBERS_REGISTRY`

## Purpose

The system is a federated AI knowledge and execution platform. Data remains on its native disk and in its native engine; the orchestration layer discovers, queries, evaluates, and combines it without destructive relocation.

The architecture optimizes four measurable outcomes:

- Retrieval quality and source attribution
- End-to-end latency and per-stage latency
- Cost per useful answer, including embedding and LLM costs
- Operational safety: read-only defaults, auditability, deterministic routing

## Design Principles

1. **Federated, not centralized:** do not move working databases merely to make the topology look tidy.
2. **Registry before access:** every agent resolves a resource through `36_CHAMBERS_REGISTRY.json`; no hard-coded database paths in agent logic.
3. **Read-only by default:** retrieval agents may inspect and search; writes require an explicit, separate workflow and backup strategy.
4. **Source-aware synthesis:** every result carries chamber ID, database path, retrieval method, document ID, score, and timestamp.
5. **Bounded fan-out:** query only the chambers that the router selects; set timeouts and a maximum number of sources.
6. **Fail soft:** a missing disk, locked SQLite database, unavailable extension, or failed collection must not break the whole answer.
7. **Evaluate continuously:** change to routing, chunking, embedding, model, or prompt requires regression evaluation.
8. **Physical truth matters:** Chroma's SQLite metadata and its HNSW sidecar directories form one logical store; inspect safely and avoid manual edits while the service is live.

## Topology

```text
User / API / CLI
      |
      v
Chamber 36: Shaolin Orchestrator
      |
      +-- Decompose -> classify intent, constraints, query plan
      +-- Route ----> select chambers and retrieval modes
      +-- Retrieve -> parallel, bounded adapters
      +-- Verify ---> source checks, dedupe, conflict handling
      +-- Aggregate -> evidence pack and answer synthesis
      +-- Observe --> JSONL / SQLite trace / evaluation metrics
      |
      v
Answer with provenance
```

## Chamber Map

| Chamber | Function | Primary location | Engine / access mode | Default safety |
|---|---|---|---|---|
| 01 — Eye of Shaolin | Lexical discovery across indexed files | `$SIST2_DATA_ROOT` | sist2 / SQLite / FTS5 | Read-only |
| 02 — Web Crawler & Edge Search | External or local web retrieval | `localhost:8888` | HTTP service | Read-only |
| 03 — Grand Knowledge | DEVz technical knowledge | `$DEVZ_KB_ROOT\chroma_db_v2` | ChromaDB + SQLite + HNSW | Read-only |
| 04 — Memory Palace | Long-term semantic memory | `$MEMPALACE_ROOT\palace` | ChromaDB + SQLite + HNSW | Read-only; privacy-sensitive |
| 05 — Graph of Truth | Entities, facts, and relations | `$MEMPALACE_ROOT\knowledge_graph.sqlite3` | SQLite graph schema | Read-only |
| 06 — Iron Fist | Controlled code and terminal execution | `<CLI tools directory>` | CLI tools | Explicit approval for writes/execution |
| 07 — Vector Micro-Engine | Local embedding and vector operations | `$SIST2_DATA_ROOT\vec0.dll` | sqlite-vec + fastembed | Read-only for search; isolated writes |
| 08 — Store & Commerce Ops | Commercial data | `$THE_BUCH_ROOT\backend\meblepumo.db` | SQLite | Read-only; sensitive business data |
| 36 — The Buch / Jimbo | Planning, orchestration, audit | `$THE_BUCH_ROOT` | Python agents + tool server | Coordinates policy |

## Orchestrator Contract

### Input

```json
{
  "query": "Znajdź dokumentację dotyczącą sqlite-vec i powiązane projekty DEVz.",
  "mode": "research",
  "max_chambers": 3,
  "timeout_s": 20,
  "allow_web": false,
  "write_intent": false
}
```

### Internal State

```json
{
  "request_id": "uuid",
  "query": "...",
  "intent": "technical_knowledge",
  "subqueries": ["sqlite-vec", "projekty DEVz"],
  "route": [{"chamber_id": 3, "mode": "semantic"}, {"chamber_id": 1, "mode": "fts"}],
  "evidence": [],
  "warnings": [],
  "metrics": {"total_latency_ms": 0, "stage_latency_ms": {}, "tokens": {}, "cost": {}}
}
```

### Output

```json
{
  "answer": "...",
  "sources": [{"chamber_id": 3, "path": "...", "record_id": "...", "score": 0.82}],
  "warnings": [],
  "metrics": {"total_latency_ms": 0}
}
```

## Data Access Rules

- Open SQLite files with URI read-only mode when possible: `file:path?mode=ro`.
- Do not use DB Browser, Python, or background agents to write into active Chroma SQLite internals directly.
- Query Chroma through its client/API for semantic search; use SQLite inspection only for auditing, counting, and schema discovery.
- Do not assume table names from a registry are current; run schema discovery and record versioned findings.
- Each adapter must return normalized evidence, never raw engine-specific rows alone.

## Retrieval Policy

| Intent | Primary chambers | Fallback | Retrieval mode |
|---|---|---|---|
| File discovery | 01 | 03 | FTS5 / lexical |
| DEVz/project knowledge | 03 | 01, 05 | semantic then lexical / graph |
| Personal context or durable memory | 04 | 05 | semantic then graph |
| Entity relation / provenance | 05 | 03 | graph traversal then semantic |
| Commerce / operations | 08 | 01 | parameterized SQL then lexical |
| Code execution request | 06 | 36 | policy gate before execution |
| Vector diagnostics | 07 | 01 | sqlite-vec diagnostics / FTS |
| Broad research | 03, 01, 02 | 05 | bounded multi-source |

## Observability

Persist one trace per request to a JSONL file or dedicated audit SQLite database. Capture:

- Request ID, timestamp, query hash, mode, selected chambers
- Stage latency: decomposition, routing, each retrieval adapter, synthesis
- Retrieval: top-k, scores, duplicates removed, timeouts, errors
- Model: provider/model/version, input tokens, output tokens, cost estimate
- Evaluation: groundedness, relevance, answer completeness, citation coverage

Recommended initial service levels:

- Interactive local search: p95 under 4 seconds
- Multi-source research: p95 under 15 seconds
- No-source answer rate: under 5% for indexed-domain questions
- Source-attributed answer rate: above 95%

## Change Management

1. Snapshot or back up a database before any schema or ingestion change.
2. Add or update its registry entry first.
3. Implement and test a chamber adapter in read-only mode.
4. Add a small golden-query evaluation set.
5. Measure baseline quality, latency, and cost.
6. Deploy behind a feature flag or explicit route rule.
7. Promote only if the measured outcome improves or meets its defined trade-off.

## Non-Goals

- The registry is not a replacement for database access control.
- The orchestrator is not permitted to silently modify business, memory, or Chroma data.
- A multi-agent graph is not inherently better than a single retrieval path; use fan-out only where evaluation shows benefit.
