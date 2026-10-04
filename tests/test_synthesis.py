"""tests/test_synthesis.py — Contract tests for Chamber 36 deterministic extractive synthesis."""

from __future__ import annotations

from typing import Any
import pytest
from src.orchestrator.synthesis import synthesize


class MockEvidence:
    def __init__(
        self,
        chamber_id: int,
        content: str,
        record_id: str | None = None,
        chamber_name: str = "TestChamber",
        resource_path: str = "/test/path",
        score: float | None = 0.95,
        metadata: dict[str, Any] | None = None,
    ):
        self.chamber_id = chamber_id
        self.chamber_name = chamber_name
        self.resource_path = resource_path
        self.record_id = record_id
        self.content = content
        self.score = score
        self.method = "mock_retrieval"
        self.metadata = metadata or {}


def test_synthesis_empty_evidence():
    result = synthesize([], "how does authentication work?")
    assert result["answer_mode"] == "evidence_synthesis"
    assert result["synthesis"]["status"] == "no_evidence"
    assert result["citations"] == []
    assert "No verified evidence was retrieved" in result["answer"]


def test_synthesis_policy_blocked():
    evidence = [MockEvidence(1, "Some secure document content here that should not leak.")]
    result = synthesize(evidence, "drop table users", policy_blocked=True)
    assert result["synthesis"]["status"] == "policy_blocked"
    assert result["answer_mode"] == "evidence_synthesis"
    assert result["citations"] == []
    assert "policy gate (Chamber 06) blocked this intent" in result["answer"]


def test_synthesis_grounded_claims_with_citations():
    evidence = [
        MockEvidence(
            chamber_id=3,
            record_id="rec_42",
            content="Authentication tokens are signed with HMAC SHA-256 for integrity verification. Tokens expire after thirty minutes.",
        ),
        MockEvidence(
            chamber_id=1,
            record_id="doc_101",
            content="All secrets are stored in environment variables rather than inside the source code repository.",
        ),
    ]
    result = synthesize(evidence, "how are authentication tokens signed?", metrics={"verification": {"sufficient": 0.85}})
    assert result["answer_mode"] == "evidence_synthesis"
    assert result["synthesis"]["status"] == "synthesized"
    assert result["synthesis"]["citation_coverage"] == 1.0
    assert result["synthesis"]["claims"] > 0
    assert len(result["citations"]) > 0
    assert "[c03#rec_42]" in result["answer"]


def test_synthesis_insufficient_evidence_gating():
    evidence = [
        MockEvidence(
            chamber_id=3,
            record_id="rec_1",
            content="Unrelated fragment talking about database migrations and indexing strategies.",
        )
    ]
    # Sufficiency below threshold 0.5 in verification metrics
    result = synthesize(evidence, "quantum computing algorithms", metrics={"verification": {"sufficient": 0.2}})
    assert result["synthesis"]["status"] == "insufficient_evidence"
    assert "No verified evidence is sufficient" in result["answer"]


def test_synthesis_existence_query_not_found():
    result = synthesize([], "does the secret backdoor exist in the codebase?")
    assert result["synthesis"]["status"] == "no_evidence"
    assert "Not found in the knowledge base" in result["answer"]
