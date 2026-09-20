from __future__ import annotations

import pytest

from src.evaluation.eval_runner import evaluate_case, score_answer, score_retrieval


def real_source(content: str, method: str = "fts") -> dict[str, object]:
    return {
        "chamber_id": 1,
        "chamber_name": "Eye of Shaolin",
        "resource_path": "demo",
        "method": method,
        "record_id": "doc-1",
        "content": content,
    }


def test_answer_metrics_separate_completeness_from_groundedness() -> None:
    result = {
        "answer": "[Eye of Shaolin | fts | record_id=doc-1] provider and api",
        "sources": [real_source("provider configuration")],
    }

    grounded, completeness, citation = score_answer(
        result,
        {"must_include": ["provider", "api"], "citations_required": True},
    )

    assert grounded == 1.0
    assert completeness == 2.0
    assert citation == 2.0


def test_retrieval_uses_rank_sensitive_ndcg() -> None:
    evidence = [real_source("unrelated"), real_source("required term", method="graph_sql")]

    recall, precision, ndcg, basis = score_retrieval(
        evidence,
        {"required_terms": ["required"], "top_k": 2},
    )

    assert recall == 1.0
    assert precision == 0.5
    assert ndcg == pytest.approx(1 / 1.5849625007)
    assert basis == "required_terms"


def test_term_based_ndcg_allows_one_source_to_cover_multiple_terms() -> None:
    recall, precision, ndcg, basis = score_retrieval(
        [real_source("required first and required second"), real_source("unrelated")],
        {"required_terms": ["first", "second"], "top_k": 2},
    )

    assert (recall, precision, ndcg, basis) == (1.0, 0.5, 1.0, "required_terms")


def test_retrieval_scores_gold_ids_and_ignores_placeholder_evidence() -> None:
    placeholder = {
        "record_id": None,
        "method": "sist2_no_match",
        "content": "No documents matched required",
    }
    evidence = [placeholder, real_source("verified", method="fts")]

    recall, precision, ndcg, basis = score_retrieval(
        evidence,
        {"required_evidence_ids": ["doc-1"], "top_k": 2},
    )

    assert (recall, precision, ndcg, basis) == (1.0, 1.0, 1.0, "evidence_ids")


def test_retrieval_accepts_metadata_only_record_ids() -> None:
    evidence = [{**real_source("verified"), "record_id": None, "metadata": {"record_id": "doc-1"}}]

    recall, precision, ndcg, basis = score_retrieval(
        evidence,
        {"required_evidence_ids": ["doc-1"], "top_k": 1},
    )

    assert (recall, precision, ndcg, basis) == (1.0, 1.0, 1.0, "evidence_ids")


def test_id_based_ndcg_deduplicates_repeated_evidence_ids() -> None:
    duplicate = {**real_source("verified"), "record_id": "doc-1"}

    recall, precision, ndcg, basis = score_retrieval(
        [duplicate, duplicate],
        {"required_evidence_ids": ["doc-1"], "top_k": 2},
    )

    assert (recall, precision, ndcg, basis) == (1.0, 0.5, 1.0, "evidence_ids")


def test_id_based_ndcg_penalizes_missing_required_evidence() -> None:
    recall, precision, ndcg, basis = score_retrieval(
        [real_source("verified")],
        {"required_evidence_ids": ["doc-1", "doc-2"], "top_k": 2},
    )

    assert recall == 0.5
    assert precision == 1.0
    assert ndcg == pytest.approx(1 / (1 + 1 / 1.5849625007))
    assert basis == "evidence_ids"


def test_record_id_zero_is_preserved() -> None:
    evidence = [
        {
            **real_source("verified"),
            "record_id": 0,
            "metadata": {"record_id": "fallback"},
        }
    ]

    recall, precision, ndcg, basis = score_retrieval(
        evidence,
        {"required_evidence_ids": [0], "top_k": 1},
    )

    assert (recall, precision, ndcg, basis) == (1.0, 1.0, 1.0, "evidence_ids")


def test_undefined_metrics_are_explicitly_marked_not_evaluated() -> None:
    scores = evaluate_case(
        {"routes_expected": {}, "retrieval": {}, "answer": {}, "safety": {}},
        {"route": [], "sources": [], "warnings": [], "metrics": {}},
    )

    assert scores["groundedness_0_2"] is None
    assert scores["completeness_0_2"] is None
    assert "groundedness=not_evaluated" in scores["notes"]
    assert "completeness=not_evaluated" in scores["notes"]


def test_negative_only_answer_criterion_does_not_claim_completeness() -> None:
    grounded, completeness, _citation = score_answer(
        {"answer": "The request was safely blocked.", "sources": []},
        {"must_not_claim": ["unsupported fact"]},
    )

    assert grounded == 2.0
    assert completeness is None


def test_citation_scoring_requires_nonempty_source_identifiers() -> None:
    _grounded, _completeness, citation = score_answer(
        {
            "answer": "A normalized answer.",
            "sources": [{**real_source("verified"), "chamber_name": "", "method": ""}],
        },
        {"citations_required": True},
    )

    assert citation == 0.0


def test_citation_scoring_requires_each_source_record_identifier() -> None:
    first = {**real_source("first"), "record_id": "doc-1"}
    second = {**real_source("second"), "record_id": "doc-2"}
    _grounded, _completeness, citation = score_answer(
        {
            "answer": "[Eye of Shaolin | fts | record_id=doc-1] first",
            "sources": [first, second],
        },
        {"citations_required": True},
    )

    assert citation == 1.0


def test_citation_scoring_uses_only_sources_rendered_in_the_answer() -> None:
    sources = [{**real_source(f"source {index}"), "record_id": f"doc-{index}"} for index in range(9)]
    answer = "\n".join(
        f"[Eye of Shaolin | fts | record_id=doc-{index}] source {index}" for index in range(8)
    )

    _grounded, _completeness, citation = score_answer(
        {"answer": answer, "sources": sources, "answer_evidence_limit": 8},
        {"citations_required": True},
    )

    assert citation == 2.0
