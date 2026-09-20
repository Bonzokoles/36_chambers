# Chamber 36 Master Orchestrator Contract

## 1. Specification Overview
Chamber 36 (`The Buch / Shaolin Master Engine`) acts as the top-level federated router and cognitive synthesizer across all 35 specialized training chambers.

## 2. Ingress & Routing Contract
- **Input**: Query string or task intent payload.
- **Classification Engine**:
  - `technical_knowledge` -> Routes to FTS/Vector knowledge stores (Chamber 01 Eye of Shaolin, Chamber 03 Grand Knowledge).
  - `memory` -> Routes to Memory Palace & Episodic storage (Chamber 04 Memory Palace).
  - `graph_fact` -> Routes to Triples / Knowledge Graph (Chamber 05 Graph of Truth).
  - `commerce` / `operations` -> Routes to local chat & transactional logs (Chamber 08 Store & Operations).
  - `mutation` / `destructive` -> Trapped by Chamber 06 (The Iron Fist) Security Gate.
- **Parallel Dispatch**: All allowed target chambers are queried simultaneously via `ThreadPoolExecutor(max_workers=8)` with a bounded timeout (`timeout=5.0s`).
- **Read-Only Enforcement**: SQLite connections enforce `mode=ro` and `immutable=1`.

## 3. Egress & Telemetry Contract
- **Evidence Formatting**: Results are aggregated, deduplicated, and ranked by relevance score.
- **Citations**: Synthetic answers must explicitly cite evidence IDs and source chambers.
- **Trace Streaming**: Every query produces an append-only JSONL log containing:
  - `agent_event`: timestamp, session_id, duration_ms, chamber_path, success, error.
  - `retrieval_event`: query_hash, asset_uri, score, source_chamber, latency_ms.
- **Observatory Sync**: Logged events are ingested into `knowledge_observatory.sqlite` for real-time visualization and dead-asset monitoring.
