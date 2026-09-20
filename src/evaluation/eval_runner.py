"""Evaluator for 36 Chambers golden queries.

Reads golden_queries.yaml, invokes shaolin_orchestrator.py, and writes eval_results.csv.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Host-specific paths resolve from environment via config.py (see .env.example).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import path as env_path, require as require_path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_GOLDEN = require_path("CHAMBERS_GOLDEN_QUERIES")
DEFAULT_OUTPUT = require_path("CHAMBERS_EVAL_RESULTS")
DEFAULT_ORCHESTRATOR = require_path("CHAMBERS_ORCHESTRATOR")
DEFAULT_REGISTRY = require_path("CHAMBERS_REGISTRY")


@dataclass
class EvalRun:
    run_id: str
    case_id: str
    scenario: str
    system_version: str
    registry_version: str
    model: str
    embedding_model: str
    route_actual: str
    route_expected_pass: int
    retrieval_recall_at_k: float
    retrieval_precision_at_k: float
    ndcg_at_k: float
    groundedness_0_2: float
    completeness_0_2: float
    citation_coverage_0_2: float
    safety_pass: int
    latency_ms: int
    ttft_ms: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    reviewer: str
    notes: str


def run_orchestrator(query: str, registry: Path, orchestrator: Path, allow_web: bool = False) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(orchestrator),
        query,
        "--registry", str(registry),
    ]
    if allow_web:
        cmd.append("--allow-web")
    start = time.perf_counter()
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    latency_ms = int((time.perf_counter() - start) * 1000)
    if proc.returncode != 0:
        return {"error": proc.stderr, "latency_ms": latency_ms}
    try:
        result = json.loads(proc.stdout)
        result.setdefault("metrics", {})
        result["metrics"]["total_latency_ms"] = result["metrics"].get("total_latency_ms", latency_ms)
        return result
    except json.JSONDecodeError:
        return {"error": "Invalid JSON from orchestrator", "raw_stdout": proc.stdout, "latency_ms": latency_ms}


def score_route(route_actual: list[dict[str, Any]], routes_expected: dict[str, Any]) -> int:
    required = set(routes_expected.get("required", []))
    allowed = set(routes_expected.get("allowed", []))
    forbidden = set(routes_expected.get("forbidden", []))
    actual_ids = {int(r.get("chamber_id")) for r in route_actual if isinstance(r, dict) and "chamber_id" in r}
    if not required and not allowed and not forbidden:
        return 1
    if required and not required.issubset(actual_ids):
        return 0
    if forbidden and forbidden.intersection(actual_ids):
        return 0
    if allowed and not actual_ids.issubset(set(required) | set(allowed)):
        return 0
    return 1


def is_real_source(item: dict[str, Any]) -> bool:
    """A source only counts when it carries a real record, not a placeholder or adapter error."""
    method = str(item.get("method") or "").lower()
    if item.get("record_id") in (None, "", "None"):
        return False
    if "error" in method or "no_match" in method:
        return False
    content = str(item.get("content") or "")
    for marker in ("No documents matched", "No matching memories", "No graph relations found", "No evidence"):
        if content.startswith(marker):
            return False
    return True


def score_retrieval(evidence: list[dict[str, Any]], retrieval: dict[str, Any]) -> tuple[float | None, float | None, float | None, str]:
    """Return (recall, precision, ndcg, basis).

    Recall is only meaningful against a gold reference. With gold evidence ids it is computed on
    ids; without them it falls back to the required terms; with neither it is reported as
    undefined (None) instead of a fabricated 1.0.
    """
    required_ids = {str(i) for i in (retrieval.get("required_evidence_ids") or [])}
    required_terms = [t.lower() for t in (retrieval.get("required_terms") or [])]
    top_k = int(retrieval.get("top_k", 5))
    top_items = evidence[:top_k]

    if required_ids:
        matched_ids = {str(e.get("record_id") or e.get("metadata", {}).get("record_id")) for e in top_items}
        recall: float | None = len(required_ids & matched_ids) / len(required_ids)
        basis = "evidence_ids"
    elif required_terms:
        blob = " ".join(str(e.get("content") or "").lower() for e in top_items)
        recall = sum(1 for t in required_terms if t in blob) / len(required_terms)
        basis = "required_terms"
    else:
        recall = None
        basis = "none"

    if not required_terms:
        precision: float | None = None
        ndcg: float | None = None
    else:
        relevant = sum(
            1 for e in top_items if any(t in str(e.get("content") or "").lower() for t in required_terms)
        )
        precision = relevant / len(top_items) if top_items else 0.0
        ndcg = precision  # documented shortcut, see GOLDEN_QUERIES_AND_EVALUATION.md
    return recall, precision, ndcg, basis


def score_answer(result: dict[str, Any], answer_spec: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    """Score answer quality. Returns None for metrics the case defines no criterion for."""
    answer = (result.get("answer") or "").lower()
    sources = [s for s in (result.get("sources") or []) if isinstance(s, dict)]
    # The aggregate template embeds every source's content verbatim, including "no match"
    # placeholders that quote the question. Score generated content, not the echoed query.
    for s in sources:
        if not is_real_source(s):
            placeholder = str(s.get("content") or "").lower()
            if placeholder:
                answer = answer.replace(placeholder, "")
    must_include = [t.lower() for t in (answer_spec.get("must_include") or [])]
    must_not_claim = [t.lower() for t in (answer_spec.get("must_not_claim") or [])]
    citations_required = bool(answer_spec.get("citations_required", False))
    real_sources = [s for s in sources if is_real_source(s)]

    forbidden_hit = any(t in answer for t in must_not_claim)

    grounded: float | None
    if not must_include:
        # No positive criterion: only scoreable when the case defines a forbidden claim.
        grounded = None if not must_not_claim else (0.0 if forbidden_hit else 2.0)
    else:
        matched = sum(1 for t in must_include if t in answer)
        if matched == len(must_include):
            grounded = 2.0
        elif matched > 0:
            grounded = 1.0
        else:
            grounded = 0.0
    completeness = grounded
    if forbidden_hit:
        grounded = 0.0 if grounded is None else min(grounded, 0.0)
        completeness = 0.0 if completeness is None else min(completeness, 0.0)

    citation: float | None
    if not citations_required:
        citation = None
    elif real_sources:
        citation = 2.0
    elif "no verified evidence" in answer or "brak znalezionych" in answer:
        citation = 1.0
    else:
        citation = 0.0
    return grounded, completeness, citation


def score_safety(result: dict[str, Any], safety: dict[str, Any]) -> int:
    read_only = bool(safety.get("read_only", True))
    expected_action = safety.get("expected_action", "answer")
    warnings = result.get("warnings", [])
    if read_only and expected_action == "block":
        # Must have blocked execution
        return 1 if any("policy" in str(r.get("mode", "")).lower() or r.get("chamber_id") == 6 for r in result.get("route", [])) else 0
    if read_only:
        if any("write" in w.lower() or "execution" in w.lower() for w in warnings):
            return 0
    return 1


def evaluate_case(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    routes_expected = case.get("routes_expected", {})
    retrieval_spec = case.get("retrieval", {})
    answer_spec = case.get("answer", {})
    safety_spec = case.get("safety", {})
    route_actual = result.get("route", [])
    route_pass = score_route(route_actual, routes_expected)
    recall, precision, ndcg, basis = score_retrieval(result.get("sources", []), retrieval_spec)
    grounded, completeness, citation = score_answer(result, answer_spec)
    safety_pass = score_safety(result, safety_spec)
    metrics = result.get("metrics", {})
    latency = metrics.get("total_latency_ms", 0)
    tokens = metrics.get("tokens", {})
    cost = metrics.get("cost", {})
    warnings = result.get("warnings", []) or []
    notes = (case.get("reviewer_notes") or "").strip()
    notes = f"{notes} | recall_basis={basis} | warnings={len(warnings)}".strip(" |")
    return {
        "route_expected_pass": route_pass,
        "retrieval_recall_at_k": recall,
        "retrieval_precision_at_k": precision,
        "ndcg_at_k": ndcg,
        "groundedness_0_2": grounded,
        "completeness_0_2": completeness,
        "citation_coverage_0_2": citation,
        "safety_pass": safety_pass,
        "latency_ms": latency,
        "ttft_ms": metrics.get("ttft_ms", 0),
        "input_tokens": tokens.get("input", 0),
        "output_tokens": tokens.get("output", 0),
        "cost_usd": float(cost.get("total", 0.0)),
    }


def run_eval(
    golden_path: Path = DEFAULT_GOLDEN,
    output_path: Path = DEFAULT_OUTPUT,
    orchestrator: Path = DEFAULT_ORCHESTRATOR,
    registry: Path = DEFAULT_REGISTRY,
    run_id: str | None = None,
    system_version: str = "shaolin-1.0",
    registry_version: str = "1.0.0",
    model: str = "local-deterministic",
    embedding_model: str = "bge-small-en-v1.5",
    reviewer: str = "auto",
) -> list[EvalRun]:
    if not golden_path.exists():
        raise FileNotFoundError(f"Golden queries not found: {golden_path}")
    if not orchestrator.exists():
        raise FileNotFoundError(f"Orchestrator not found: {orchestrator}")
    if not registry.exists():
        raise FileNotFoundError(f"Registry not found: {registry}")
    with golden_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    cases = data.get("cases", [])
    if run_id is None:
        from uuid import uuid4
        run_id = str(uuid4())[:8]
    results: list[EvalRun] = []
    for case in cases:
        case_id = case["id"]
        scenario = case.get("scenario", "unknown")
        query = case["query"]
        orchestrator_result = run_orchestrator(query, registry, orchestrator)
        scores = evaluate_case(case, orchestrator_result)
        row = EvalRun(
            run_id=run_id,
            case_id=case_id,
            scenario=scenario,
            system_version=system_version,
            registry_version=registry_version,
            model=model,
            embedding_model=embedding_model,
            route_actual=json.dumps(orchestrator_result.get("route", [])),
            route_expected_pass=scores["route_expected_pass"],
            retrieval_recall_at_k=scores["retrieval_recall_at_k"],
            retrieval_precision_at_k=scores["retrieval_precision_at_k"],
            ndcg_at_k=scores["ndcg_at_k"],
            groundedness_0_2=scores["groundedness_0_2"],
            completeness_0_2=scores["completeness_0_2"],
            citation_coverage_0_2=scores["citation_coverage_0_2"],
            safety_pass=scores["safety_pass"],
            latency_ms=scores["latency_ms"],
            ttft_ms=scores["ttft_ms"],
            input_tokens=scores["input_tokens"],
            output_tokens=scores["output_tokens"],
            cost_usd=scores["cost_usd"],
            reviewer=reviewer,
            notes=scores.get("notes", case.get("reviewer_notes", "")),
        )
        results.append(row)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(EvalRun.__dataclass_fields__.keys()))
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))
    return results


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Run golden queries evaluation")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--orchestrator", type=Path, default=DEFAULT_ORCHESTRATOR)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--system-version", type=str, default="shaolin-1.0")
    parser.add_argument("--model", type=str, default="local-deterministic")
    parser.add_argument("--embedding-model", type=str, default="bge-small-en-v1.5")
    parser.add_argument("--reviewer", type=str, default="auto")
    args = parser.parse_args()
    results = run_eval(
        golden_path=args.golden,
        output_path=args.output,
        orchestrator=args.orchestrator,
        registry=args.registry,
        run_id=args.run_id,
        system_version=args.system_version,
        model=args.model,
        embedding_model=args.embedding_model,
        reviewer=args.reviewer,
    )
    print(f"Evaluation complete: {len(results)} cases -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
