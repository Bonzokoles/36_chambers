# 36 Chambers of Shaolin Cognitive Matrix

[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/License-PolyForm%20Noncommercial%201.0.0-blue.svg)](LICENSE)
[![Security: Four-Room Pipeline](https://img.shields.io/badge/Security-Four--Room%20Pipeline-emerald.svg)](docs/security/FOUR_ROOM_PIPELINE.md)
[![Architecture: Registry-First](https://img.shields.io/badge/Architecture-Federated%20Matrix-cyan.svg)](RADM.md)
[![AI: TypeSafe/Jev](https://img.shields.io/badge/AI-TypeSafe%2FJev%20System%20One-orange.svg)](src/orchestrator/jev_router.py)

![36 Chambers of Shaolin Cognitive Matrix](assets/36_chambers_shaolin_matrix_hero.jpg)

**A federated, registry-first knowledge retrieval engine for autonomous AI agents.** Data remains in its native storage layers (SQLite FTS5, ChromaDB, knowledge graph) while agents discover and query through a unified immutable registry. Powered by **TypeSafe Jev** for fast, calibrated query routing and evidence re-ranking.

---

## What's New in v0.2.0

- **Jev (TypeSafe) integration** — AI-powered query routing and re-ranking via the System One model. Jev decomposes user queries into chamber routes with confidence scores, and re-ranks evidence using Noul probability judgments.
- **Confidence-gated routing** — routes queries through Jev when confidence ≥ 0.6; falls back to keyword matching on low confidence or API errors (fail-soft).
- **Evidence re-ranking** — re-sorts retrieved evidence by relevance using Jev Noul, HTTP (Cohere-compatible), or local BGE cross-encoder.
- **Generative synthesis** (optional) — LLM-based answer synthesis with source citations over evidence packs.
- **Safe by default** — Jev is optional. Without a `TYPESAFE_API_KEY`, the orchestrator uses deterministic keyword routing. All new features are feature-flagged off in `.env`.

---

## Architecture

```
 [ User / CLI / API ]
          │
          ▼
┌──────────────────────────────────────┐
│     CHAMBER 36: THE MASTER ENGINE    │
│  ┌──────────────────────────────┐    │
│  │ Jev Router (AI-powered)      │    │
│  │ query → intent → chamber     │    │
│  │ confidence-gated fallback    │    │
│  └──────────────────────────────┘    │
│  ┌──────────────────────────────┐    │
│  │ Federated Adapters           │    │
│  │ 01-FTS5  03-Chroma  05-Graph │    │
│  └──────────────────────────────┘    │
│  ┌──────────────────────────────┐    │
│  │ Evidence Re-rank             │    │
│  │ Jev Noul → HTTP → local BGE  │    │
│  └──────────────────────────────┘    │
│  ┌──────────────────────────────┐    │
│  │ Synthesis (optional LLM)     │    │
│  │ cited answer from evidence   │    │
│  └──────────────────────────────┘    │
└───────────────────┬──────────────────┘
                    │
     ┌──────────────┼──────────────┐
     │              │              │
     ▼              ▼              ▼
┌─────────┐  ┌───────────┐  ┌──────────┐
│ CH. 01  │  │  CH. 03   │  │  CH. 05  │
│ sist2   │  │ ChromaDB  │  │  Graph   │
│ FTS5    │  │ Semantic  │  │ Triples  │
└─────────┘  └───────────┘  └──────────┘
```

### Federated Chambers

| Chamber | Name | Engine | Role |
|---|---|---|---|
| 01 | Eye of Shaolin | SQLite FTS5 / sist2 | Full-text file discovery |
| 02 | Web Crawler | HTTP (planned) | External web retrieval |
| 03 | Grand Knowledge | ChromaDB | Semantic project knowledge |
| 04 | Memory Palace | ChromaDB | Long-term memory |
| 05 | Graph of Truth | SQLite | Entity relationships |
| 06 | Iron Fist | Policy Gate | Mutation blocking, security |
| 07 | Vector Micro-Engine | Planned | Local embeddings |
| 08 | Store & Operations | SQLite | Business data, transactions |
| 36 | **Master Engine** | **Orchestrator** | **Routing, re-ranking, synthesis** |

---

## Quick Start

### Prerequisites

- Python 3.10+ (3.13 recommended)
- Optional: [TypeSafe API key](https://console.typesafe.ai/keys) for AI-powered routing

### Installation

```bash
git clone https://github.com/Bonzokoles/36_chambers.git
cd 36_chambers
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# Edit .env with your paths and API keys
```

### Run the Orchestrator

```bash
# Keyword routing (no API key needed):
python src/orchestrator/shaolin_orchestrator.py "where is the agent provider configured?"

# With Jev routing (set TYPESAFE_API_KEY in .env):
python src/orchestrator/shaolin_orchestrator.py "what documents discuss the security pipeline?"
```

### Enable Features in `.env`

```bash
# AI-powered query routing
TYPESAFE_API_KEY=tsk_...

# Evidence re-ranking (by relevance)
CHAMBERS_RERANK_ENABLED=1

# LLM answer synthesis from evidence
CHAMBERS_SYNTHESIS_ENABLED=1
CHAMBERS_SYNTHESIS_BASE_URL=https://api.openrouter.ai/v1
CHAMBERS_SYNTHESIS_API_KEY=sk-or-...
```

---

## TypeSafe / Jev Integration

### How Jev Routing Works

1. User query arrives at the orchestrator
2. Jev classifies it into a chamber using a `Choice` question with 5 criteria
3. If confidence ≥ 0.6, the chamber route is accepted
4. If confidence < 0.6 or Jev is unavailable, the orchestrator falls back to keyword matching
5. The selected chamber adapters retrieve evidence

**Jev Chamber Criteria:**

| Chamber | Jev sees this as |
|---|---|
| `01_sist2` | "Full-text file search (FTS5)" |
| `03_chroma` | "Semantic knowledge base (ChromaDB)" |
| `05_graph` | "Knowledge graph (SQLite triples)" |
| `08_bizops` | "Business operations (SQLite)" |

### How Jev Re-Ranking Works

After retrieval, each evidence item is scored against the query using a `Noul` question: "Could this document answer the query?" Documents are sorted by noul score (0-1). The re-rank backend cascade is:

```
Jev Noul → HTTP (Cohere) → local BGE cross-encoder
```

### Cost

- **Routing**: ~1 Jev call per query (~$0.0001 at current pricing)
- **Re-ranking**: N calls (one per evidence item) — ~$0.0015 per query with 6 evidence items
- **Fallback is free**: keyword routing and local BGE re-ranker cost $0

---

## Key Subsystems

### Four-Room Security Pipeline

Untrusted intake follows a 72-hour security cycle:
1. **Invitation Room** — SHA-256 fingerprinting, injection heuristic analysis
2. **Rookie Validation** — Isolated LLM evaluation with strict JSON schemas
3. **Retirement Quarantine** — Pre-retirement dependency analysis
4. **Deletion Hold** — Restore testing and final approval

### Knowledge Observatory

Tracks asset lifecycle across chambers:
- Identifies "cold assets" never retrieved by agents
- Generates Plotly dashboards and telemetry reports
- `knowledge_observatory.sqlite` with agent/retrieval events

### Golden Queries Evaluation

Validates routing precision, retrieval recall@k, and safety compliance against curated scenarios.

---

## Directory Structure

```
36_chambers/
├── src/orchestrator/
│   ├── shaolin_orchestrator.py    # Master orchestrator
│   └── jev_router.py             # TypeSafe/Jev bridge
├── src/security/                  # Four-Room quarantine
├── src/observatory/               # Knowledge growth tracking
├── src/evaluation/                # Golden queries runner
├── src/analytics/                 # OpenRouter benchmark
├── docs/                          # Architecture & operations
├── examples/                      # Demo registry, queries, canary
├── tests/                         # Contract & evaluator tests
└── .env.example                   # Configuration template
```

---

## Governance

For architectural specifications, ADRs, and operational risk matrices, see [`RADM.md`](RADM.md).

- **Code**: Licensed under PolyForm Noncommercial 1.0.0 — free for individual, academic, and noncommercial research. See [`LICENSE`](LICENSE).
- **Commercial Use**: Requires a separate written agreement. See [`COMMERCIAL_LICENSE.md`](COMMERCIAL_LICENSE.md).
- **Data**: No production databases, private keys, or proprietary memories are included. See [`DATA_LICENSE.md`](DATA_LICENSE.md).