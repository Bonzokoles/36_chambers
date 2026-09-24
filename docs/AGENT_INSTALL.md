# 36 Chambers — Installation Guide for Coding Agents

You are installing **36 Chambers of Shaolin Cognitive Matrix**, a federated search
engine that routes queries through TypeSafe Jev (AI) or keyword heuristics to
specialized storage backends (FTS5, ChromaDB, knowledge graph, SQLite).

## Step 1 — Clone

```
git clone https://github.com/Bonzokoles/36_chambers.git
cd 36_chambers
```

## Step 2 — Create virtual environment

```
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# or: .venv\Scripts\Activate.ps1   # Windows
```

## Step 3 — Install dependencies

```
pip install -r requirements.txt
```

## Step 4 — Configure environment

```
cp .env.example .env
```

Open `.env` in your editor. The **only required variable** is
`CHAMBERS_REGISTRY` — point it to an existing registry JSON file, or use
`examples/demo_registry/36_CHAMBERS_REGISTRY.example.json` for testing.

### Optional: TypeSafe Jev (AI-powered routing)

Get a free API key at https://console.typesafe.ai/keys and set:

```
TYPESAFE_API_KEY=tsk_...
```

Without this key, routing uses deterministic keyword matching (works fine,
just less flexible).

### Optional: Re-ranking for better results

```
CHAMBERS_RERANK_ENABLED=1
# Install local reranker deps:
pip install -r requirements-rerank.txt
```

### Optional: LLM answer synthesis

```
CHAMBERS_SYNTHESIS_ENABLED=1
CHAMBERS_SYNTHESIS_BASE_URL=https://api.openrouter.ai/v1
CHAMBERS_SYNTHESIS_API_KEY=sk-or-...
CHAMBERS_SYNTHESIS_MODEL=openrouter/auto
```

## Step 5 — Run tests

```
python -m pytest tests/ -q
```

Should see **30 passed** in under 1 second.

## Step 6 — Try it

```
python src/orchestrator/shaolin_orchestrator.py "what documents discuss the observatory?"
```

If Jev is configured you'll see `route_source: jev`; otherwise `route_source: heuristic`.

## What to check if something fails

- Is `CHAMBERS_REGISTRY` pointing to a valid JSON file?
- Are the paths in the registry entries reachable on this machine?
- Does `python -m pytest tests/ -q` pass? (30/30)
- If Jev routing is enabled: is the API key valid? Check `curl -s https://api.typesafe.ai/v1/systemone` with your key.
- If synthesis is enabled: is the LLM endpoint reachable and key valid?

## Security

- `.env` is in `.gitignore` — secrets are never committed.
- All adapters use read-only access by default.
- No LLM output is executed as shell, SQL, or ACL instruction without validation.