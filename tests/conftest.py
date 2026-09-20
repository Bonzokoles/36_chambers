from __future__ import annotations

import os
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_RUNTIME = Path(tempfile.mkdtemp(prefix="shaolin-tests-"))

os.environ.setdefault(
    "CHAMBERS_REGISTRY",
    str(REPO_ROOT / "examples/demo_registry/36_CHAMBERS_REGISTRY.example.json"),
)
os.environ.setdefault("CHAMBERS_TRACE_DIR", str(TEST_RUNTIME / "traces"))
os.environ.setdefault(
    "CHAMBERS_GOLDEN_QUERIES",
    str(REPO_ROOT / "examples/demo_golden_queries/golden_queries.example.yaml"),
)
os.environ.setdefault("CHAMBERS_EVAL_RESULTS", str(TEST_RUNTIME / "eval_results.csv"))
os.environ.setdefault(
    "CHAMBERS_ORCHESTRATOR",
    str(REPO_ROOT / "src/orchestrator/shaolin_orchestrator.py"),
)
