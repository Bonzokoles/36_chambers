"""
Jev (TypeSafe) bridge for 36 Chambers orchestrator.
System One model for fast, calibrated query routing and re-ranking.
Fail-soft: falls back to heuristic routing when API key is not set or Jev unavailable.

Usage:
    router = JevRouter(api_key=os.getenv("TYPESAFE_API_KEY"))
    decision = router.route(query)
    # decision.chamber → "03_chroma"
    # decision.confidence → 0.92

Re-ranking:
    from jev_router import rerank
    scores = rerank(query, ["doc A", "doc B"])  # [0.87, 0.41]
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass


JEV_API = "https://api.typesafe.ai/v1/systemone"
CHAMBER_CRITERIA = {
    "01_sist2": "Full-text file search (FTS5). Use for: find files by name, search file contents, discover documents on disk.",
    "03_chroma": "Semantic knowledge base (ChromaDB). Use for: technical knowledge, project docs, AI/ML topics, product catalogs, ecommerce content.",
    "05_graph": "Knowledge graph (SQLite triples). Use for: entity relationships, facts about people/projects, provenance queries.",
    "08_bizops": "Business operations (SQLite). Use for: product prices, orders, inventory, chat history, transactional records.",
    "unknown": "Query does not match any chamber. Use for: general chat, meta-questions, unclear intent.",
}


@dataclass
class RouteDecision:
    chamber: str
    confidence: float
    probabilities: dict[str, float]
    mode: str  # "jev" or "heuristic"


@dataclass
class JevRouter:
    api_key: str | None = None
    model: str = "jev-latest"
    timeout: int = 10
    confidence_floor: float = 0.6

    def __post_init__(self):
        self.api_key = self.api_key or os.getenv("TYPESAFE_API_KEY")
        self._available = bool(self.api_key)

    @property
    def available(self) -> bool:
        return self._available

    def route(self, query: str) -> RouteDecision:
        if not self._available:
            return self._heuristic_route(query)

        try:
            return self._jev_route(query)
        except Exception:
            # Fail-soft: any Jev error falls back to heuristic
            return self._heuristic_route(query)

    # ── Heuristic fallback (original keyword logic) ────────────────

    def _heuristic_route(self, query: str) -> RouteDecision:
        """Original keyword-based routing as fallback."""
        q = query.lower()

        # File discovery keywords
        file_keywords = ["plik", "pliki", "file", "files", "znajdź", "znajdz", "szukaj", "gdzie jest",
                         "folder", "katalog", "dokument", "dokumenty", "directory", "disk", "dysk"]
        if any(k in q for k in file_keywords):
            return RouteDecision(
                chamber="01_sist2", confidence=0.7,
                probabilities={"01_sist2": 0.7, "03_chroma": 0.2, "05_graph": 0.1},
                mode="heuristic"
            )

        # Graph/relation keywords
        graph_keywords = ["relacja", "związek", "powiązanie", "kto", "czyj", "graf",
                          "entity", "entities", "triple", "relation", "connected"]
        if any(k in q for k in graph_keywords):
            return RouteDecision(
                chamber="05_graph", confidence=0.65,
                probabilities={"05_graph": 0.65, "03_chroma": 0.25, "01_sist2": 0.1},
                mode="heuristic"
            )

        # Business keywords
        biz_keywords = ["cena", "price", "produkt", "product", "zamówienie", "order", "faktura",
                        "invoice", "klient", "customer", "sklep", "store", "inventory", "stock"]
        if any(k in q for k in biz_keywords):
            return RouteDecision(
                chamber="08_bizops", confidence=0.7,
                probabilities={"08_bizops": 0.7, "03_chroma": 0.2, "01_sist2": 0.1},
                mode="heuristic"
            )

        # Default: ChromaDB semantic search
        return RouteDecision(
            chamber="03_chroma", confidence=0.5,
            probabilities={"03_chroma": 0.5, "01_sist2": 0.3, "05_graph": 0.2},
            mode="heuristic"
        )

    # ── Jev API call ──────────────────────────────────────

    def _jev_route(self, query: str) -> RouteDecision:
        payload = {
            "state": query,
            "model": self.model,
            "questions": {
                "chamber": {
                    "type": "choice",
                    "instructions": "Which knowledge chamber should handle this query? Choose the most appropriate one based on what the user is asking for.",
                    "criteria": CHAMBER_CRITERIA,
                }
            }
        }

        req = urllib.request.Request(
            JEV_API,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        answer = data["answers"]["chamber"]
        chamber = answer["choice"]
        confidence = answer["confidence"]
        probabilities = answer.get("probabilities", {})

        return RouteDecision(
            chamber=chamber,
            confidence=confidence,
            probabilities=probabilities,
            mode="jev",
        )


# ── Convenience functions ────────────────────────────────

_router: JevRouter | None = None


def get_router() -> JevRouter:
    global _router
    if _router is None:
        _router = JevRouter()
    return _router


def route_query(query: str) -> RouteDecision:
    return get_router().route(query)


# ── Re-rank using Jev Noul ────────────────────────────

def rerank(query: str, documents: list[str]) -> list[float]:
    """Score each document against the query using Jev Noul.
    Returns list of noul scores (0-1) in same order as documents.
    Fail-soft: returns zeros on any error."""
    router = get_router()
    if not router.available:
        return [0.0] * len(documents)

    question = {
        "type": "noul",
        "instructions": (
            "Could this document serve as a helpful, accurate answer to the query? "
            "Answer yes if the document contains information that directly addresses or "
            "substantially supports answering the query. Answer no if the document is "
            "about an unrelated topic, too vague to be useful, or only tangentially related."
        ),
    }

    scores: list[float] = []
    for doc in documents:
        try:
            payload = {
                "state": f"Query: {query}\n\nDocument: {doc[:3000]}",
                "model": router.model,
                "questions": {"relevant": question},
            }
            req = urllib.request.Request(
                JEV_API,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {router.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=router.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            scores.append(float(data["answers"]["relevant"]["noul"]))
        except Exception:
            scores.append(0.0)
    return scores