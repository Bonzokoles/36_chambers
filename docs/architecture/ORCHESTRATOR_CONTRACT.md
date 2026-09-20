# Chamber 36 Master Orchestrator Contract

## 1. Specification Overview
Chamber 36 (`The Buch / Shaolin Master Engine`) acts as the top-level federated router and deterministic evidence aggregator. Generative synthesis is not implemented; the response identifies this explicitly with `answer_mode: evidence_aggregation` and `synthesis.status: not_implemented`.

## 2. Ingress & Routing Contract
- **Input**: Query string or task intent payload.
- **Classification Engine**:
  - `technical_knowledge` -> Routes to FTS/Vector knowledge stores (Chamber 01 Eye of Shaolin, Chamber 03 Grand Knowledge).
  - `memory` -> Routes to Memory Palace & Episodic storage (Chamber 04 Memory Palace).
  - `graph_fact` -> Routes to Triples / Knowledge Graph (Chamber 05 Graph of Truth).
  - `commerce` / `operations` -> Routes to local chat & transactional logs (Chamber 08 Store & Operations).
  - `mutation` / `destructive` -> Trapped by Chamber 06 (The Iron Fist) Security Gate.
- **Parallel Dispatch**: Allowed targets are queried simultaneously with one worker per selected chamber. The orchestrator stops waiting on an individual future after the configured timeout and reports a warning, but thread-executor shutdown still waits for blocked adapter work; the timeout is not a hard wall-clock cancellation guarantee.
- **Read-Only Enforcement**: SQLite connections enforce `mode=ro` and `immutable=1`.

## 3. Egress & Telemetry Contract
- **Evidence Formatting**: Results are normalized, deduplicated, and emitted as a deterministic evidence pack.
- **Attribution**: Aggregated answers identify each source chamber and retrieval method; normalized source records preserve record IDs.
- **Trace Output**: Every query produces a JSON trace; observatory integration emits append-only JSONL events containing:
  - `agent_event`: `event_type`, `event_time`, `request_id`, `agent_name`, `action`, `app_name`, `chamber_id`, `resource_id`, `status`, `error`, `latency_ms`, `model`, and `task_type`.
  - `retrieval_event`: `event_type`, `event_time`, `request_id`, `agent_name`, `chamber_id`, `resource_id`, `document_id`, `chunk_id`, `retrieval_method`, `rank`, `score`, prompt/citation flags, source/index timestamps, embedding model, and token count. Adapter failures emit a failed `agent_event` and no `retrieval_event`.
- **Observatory Sync**: Logged events are ingested into `knowledge_observatory.sqlite` for real-time visualization and dead-asset monitoring.

## 4. Registry Capability Contract

- `status: implemented` requires a registered adapter and at least one compatible route mode.
- `status: not_implemented` must not declare an executable adapter or route mode and is never routed.
- `status: orchestration_only` is reserved for Chamber 36 until synthesis exists.
- Registry loading fails fast when a capability claim does not match the adapter table.
