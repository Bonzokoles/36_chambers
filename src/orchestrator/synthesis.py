#!/usr/bin/env python3
"""synthesis.py — Chamber 36: odpowiedz zbudowana WYLACZNIE z dowodow, z cytowaniami.

Zasady (krok 26 planu):
  1. Synteza korzysta tylko z evidence packa. Nie dokłada wiedzy z modelu.
  2. Kazde zdanie-roszczenie ma znacznik cytatu; bez znacznika zdanie nie wchodzi.
  3. Gdy Jev oceni zbior jako niewystarczajacy (sufficiency < prog), odpowiedz NIE udaje
     odpowiedzi: mowi wprost, ze dowodow nie ma, i pokazuje je jako slabe, nie jako wynik.
  4. Gdy polityka zablokowala zapytanie (Chamber 06), synteza nie powstaje wcale.
  5. Metoda domyslna jest ekstrakcyjna i deterministyczna (zero LLM): bierzemy zdania
     z dowodow, porzadkujemy po trafnosci i sklejamy z cytatami. Reszta to opcja, nie warunek.

Modul nie zna orkiestratora: dostaje liste dowodow (obiekty z atrybutami Evidence) i zwraca dict
gotowy do wpiecia w evidence pack.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

PROG_SUFFICIENCY = 0.5
LIMIT_ZDAN = 5
MAX_NA_ZRODLO = 2
MIN_SLOW = 6

# Linie, ktore sa naglowkami/stopkami dokumentu, a nie trescia odpowiedzi.
POMIJANE_PREFIKSY = ("#", ">", "|", "**kategoria", "**zebrane", "**filtr", "**source", "kategoria:",
                     "zebrane:", "filtr:", "source:", "---", "```", "document:", "plik:", "file:")
# Zdania bez tresci: metadane indeksu, JSON, listy kluczy, sciezki.
WZORCE_SMIECI = (
    re.compile(r"\(size:\s*\d+ bytes", re.I),
    re.compile(r"metadata:\s*[\{\[]"),          # surowy JSON w tresci
    re.compile(r"^[\w .-]{2,24}:\s*(\{|\[|-\s)"),  # "use_when: - ..."
    re.compile(r"^[^\s]{40,}$"),                  # jedna dluga "sciezka" bez spacji
    re.compile(r"^[\w./\\-]+\.(json|jsonl|ya?ml|csv|db|sist2|zip)\b", re.I),
)
# Roszczenie musi byc zdaniem: konczy sie kropka/pytajnikiem/wykrzyknikiem i nie jest
# zbita lista kluczy (dump JSON/YAML ma duzo dwukropkow i separatorow).
KONCOWKI_ZDANIA = (".", "?", "!", "…", "”", '"')
# Fakt strukturalny: graf zwraca gotowe, cytowalne trojki, nie zdania prozy.
# Format: "Triple: (a) --[rel]--> (b) [confidence=1.0]" albo "Found 3 relations ...".
WZORZEC_FAKTU = re.compile(r"^(triple|edge|relation|entity|record|found)\b\s*[:\-]", re.I)
# Pytanie o istnienie/nieistnienie: poprawna odpowiedzia przy braku dowodow jest "nie znalazlem",
# a nie "dowody niewystarczajace" (to jest test na niezmyslanie, nie na wyszukiwanie).
WZORZEC_PYTANIA_O_ISTNIENIE = re.compile(
    r"(czy\b[^.?]{0,60}\b(istnieje|jest|znajduje)|does\b[^.?]{0,60}\bexist|is\s+there\b|znajd[zź]\s+pliki)", re.I)
# Werdykty, ktore nie moga byc roszczeniem w odpowiedzi (Jev uznal je za brak dowodu).
WERDYKTY_ODRZUCONE = ("irrelevant", "null_result", "contradicted")
WZORZEC_ZDANIA = re.compile(r"(?<=[.!?])\s+|\n+")
STOP = {"the", "and", "for", "with", "that", "this", "are", "was", "jest", "oraz", "ktore", "które",
        "nie", "sie", "się", "jak", "ale", "albo", "lub", "the", "of", "to", "in", "on", "is"}


def _zdania(tekst: str, ostro: bool = True) -> list[str]:
    """Dzieli dowod na zdania-roszczenia. `ostro=False` (gdy Jev ocenil dowody jako wystarczajace)
    dopuszcza krotkie wpisy bez koncowej kropki - graf i bazy operacyjne zwracaja wlasnie takie."""
    out = []
    for zdanie in WZORZEC_ZDANIA.split(tekst or ""):
        z = " ".join(zdanie.split())
        if WZORZEC_FAKTU.match(z) and len(z.split()) >= 4:
            # Fakt strukturalny przechodzi jak jest: jest kompletny i sam opisuje relacje.
            if not any(w.match(z) for w in WZORCE_SMIECI):
                out.append(z)
            continue
        if len(z.split()) < MIN_SLOW:
            continue
        if z.lower().startswith(POMIJANE_PREFIKSY):
            continue
        if any(w.match(z) for w in WZORCE_SMIECI):
            continue
        # zdanie musi byc tekstem, nie tabela liczb/kluczy
        litery = sum(1 for c in z if c.isalpha())
        if litery < 0.55 * len(z):
            continue
        if z.count(":") >= 3 or z.count(" , ") >= 2:
            continue
        if ostro and not z.endswith(KONCOWKI_ZDANIA):
            continue
        out.append(z)
    return out


def _terminy(zapytanie: str) -> set[str]:
    return {t for t in re.findall(r"[\wąćęłńóśźżäöüß-]{3,}", (zapytanie or "").lower()) if t not in STOP}


def _trafnosc(zdanie: str, terminy: set[str]) -> float:
    if not terminy:
        return 0.0
    slowa = set(re.findall(r"[\wąćęłńóśźżäöüß-]{3,}", zdanie.lower()))
    return len(terminy & slowa) / len(terminy)


def _znacznik(dowod: Any) -> str:
    """Krotki, ale jednoznaczny znacznik cytatu: [c03#record] albo [c03#norec:plik]."""
    cid = f"c{int(getattr(dowod, 'chamber_id', 0)):02d}"
    rid = getattr(dowod, "record_id", None)
    if rid:
        krotki = str(rid)[:12]
        return f"[{cid}#{krotki}]"
    nazwa = str(getattr(dowod, "resource_path", "") or "").replace("\\", "/").split("/")[-1][:24]
    return f"[{cid}#norec:{nazwa}]"


def _sufficiency(metrics: dict[str, Any] | None) -> float | None:
    """Ocena zbioru dowodow. Preferujemy ocene zbioru UZYTECZNEGO (po odsianiu odrzucen przez Jeva):
    smieci w pakiecie nie moga rozcienczac odpowiedzi na pytanie "czy to wystarcza"."""
    weryfikacja = (metrics or {}).get("verification") or {}
    wartosc = weryfikacja.get("sufficient_effective")
    if wartosc is None:
        wartosc = weryfikacja.get("sufficient_on_kept")
    if wartosc is None:
        wartosc = weryfikacja.get("sufficient")
    try:
        return float(wartosc) if wartosc is not None else None
    except (TypeError, ValueError):
        return None


def _wybierz(dowody: list[Any], zapytanie: str, limit: int, max_na_zrodlo: int,
             ostro: bool = True) -> list[tuple[Any, str, float]]:
    """Zdania-roszczenia z dowodow: (dowod, zdanie, ocena). Bez duplikatow, z limitem na zrodlo.

    Dowody, ktore Jev ocenil jako `irrelevant`/`null_result`/`contradicted`, nie wchodza jako
    roszczenia - ida tylko do sekcji "najblizsze fragmenty" i to pod warunkiem, ze nic lepszego nie ma.
    """
    terminy = _terminy(zapytanie)
    zaufane = [d for d in dowody if (getattr(d, "metadata", {}) or {}).get("jev_verdict") not in WERDYKTY_ODRZUCONE]
    pula = zaufane or dowody
    kandydaci: list[tuple[Any, str, float]] = []
    for pozycja, dowod in enumerate(pula):
        tresc = getattr(dowod, "content", "") or ""
        ocena_dowodu = float(getattr(dowod, "score", None) or 0.0)
        # Na realnych danych ocena Jev po reranku lezy w pasmie 0.02-0.05 (pomiar
        # 2026-09-29, docs/operations/EVALUATION.md), wiec wklad 0.30*score to niemal
        # stala ~0.006-0.015 i NIE przestawia roszczen. Kolejnosc robi `trafnosc` (0.55),
        # a jakosc odsiewa `jev_verdict` wyzej. Nie zwiekszaj tej wagi - ocena reranku
        # nie ma zdolnosci rozdzielczej (odstep -0.71).
        for numer, zdanie in enumerate(_zdania(tresc, ostro=ostro)):
            trafnosc = _trafnosc(zdanie, terminy)
            ocena = 0.55 * trafnosc + 0.30 * min(1.0, ocena_dowodu) + 0.15 * (1.0 / (1 + pozycja + numer))
            kandydaci.append((dowod, zdanie, ocena))
    kandydaci.sort(key=lambda x: -x[2])
    wybrane: list[tuple[Any, str, float]] = []
    widziane: set[str] = set()
    na_zrodlo: dict[int, int] = {}
    for dowod, zdanie, ocena in kandydaci:
        klucz = hashlib.sha256(" ".join(zdanie.lower().split())[:180].encode()).hexdigest()[:16]
        if klucz in widziane:
            continue
        ident = id(dowod)
        if na_zrodlo.get(ident, 0) >= max_na_zrodlo:
            continue
        widziane.add(klucz)
        na_zrodlo[ident] = na_zrodlo.get(ident, 0) + 1
        wybrane.append((dowod, zdanie, ocena))
        if len(wybrane) >= limit:
            break
    return wybrane


def synthesize(dowody: Iterable[Any], zapytanie: str, *, metrics: dict[str, Any] | None = None,
               policy_blocked: bool = False, limit: int = LIMIT_ZDAN,
               max_na_zrodlo: int = MAX_NA_ZRODLO) -> dict[str, Any]:
    """Buduje odpowiedz z dowodow. Zwraca dict do wpiecia w evidence pack."""
    lista = list(dowody or [])
    sufficiency = _sufficiency(metrics)
    # Ostrosc filtra zalezy od oceny Jevem: przy wystarczajacych dowodach nie odrzucamy
    # krotkich wpisow bez kropki (graf, bazy operacyjne). Przy watpliwych - tylko zdania.
    ostro = not (sufficiency is not None and sufficiency >= PROG_SUFFICIENCY)
    bazowy = {
        "chamber_id": 36,
        "method": "extractive",
        "sufficiency": sufficiency,
        "sufficiency_threshold": PROG_SUFFICIENCY,
        "claims": 0,
        "citations": 0,
        "citation_coverage": 0.0,
        "sources_used": 0,
    }

    if policy_blocked:
        return {
            "answer": "No verified evidence is presented: the policy gate (Chamber 06) blocked this "
                      "intent, so no automated read or action was performed.",
            "answer_mode": "evidence_synthesis",
            "synthesis": {**bazowy, "status": "policy_blocked",
                          "detail": "Policy gate active; synthesis suppressed."},
            "citations": [],
        }

    if not lista:
        if WZORZEC_PYTANIA_O_ISTNIENIE.search(zapytanie or ""):
            return {
                "answer": "Not found in the knowledge base: no document matching this query was retrieved, "
                          "so the component asked about cannot be confirmed to exist. The system does not "
                          "confirm the existence of something it has no evidence for.",
                "answer_mode": "evidence_synthesis",
                "synthesis": {**bazowy, "status": "no_evidence",
                              "detail": "Existence question with an empty evidence pack: answered as not found."},
                "citations": [],
            }
        return {
            "answer": "No verified evidence was retrieved for this query. The system does not answer "
                      "without evidence; treat the question as unanswered.",
            "answer_mode": "evidence_synthesis",
            "synthesis": {**bazowy, "status": "no_evidence",
                          "detail": "Empty evidence pack."},
            "citations": [],
        }

    wybrane = _wybierz(lista, zapytanie, limit, max_na_zrodlo, ostro=ostro)
    zaufanych = [d for d in lista if (getattr(d, "metadata", {}) or {}).get("jev_verdict") not in WERDYKTY_ODRZUCONE]
    if not wybrane:
        # Dowody sa, ale po filtrze jakosci nie ma z czego zrobic roszczenia.
        if WZORZEC_PYTANIA_O_ISTNIENIE.search(zapytanie or ""):
            tresc = ("Not found in the knowledge base: retrieved items contain no statement that names the "
                     "component asked about. Treat it as absent rather than assumed.")
        else:
            tresc = ("No verified evidence is sufficient to answer this query: the retrieved items contain "
                     "no statement that can be cited as a claim. Treat the question as unanswered.")
        return {
            "answer": tresc,
            "answer_mode": "evidence_synthesis",
            "synthesis": {**bazowy, "status": "no_evidence", "sources_used": 0,
                          "detail": f"{len(lista)} item(s) retrieved, 0 usable claims after quality filter."},
            "citations": [],
        }
    cytaty: list[dict[str, Any]] = []
    widziane_znaczniki: dict[str, int] = {}
    linie: list[str] = []
    for dowod, zdanie, ocena in wybrane:
        znacznik = _znacznik(dowod)
        if znacznik not in widziane_znaczniki:
            widziane_znaczniki[znacznik] = len(cytaty)
            cytaty.append({
                "marker": znacznik,
                "chamber_id": int(getattr(dowod, "chamber_id", 0)),
                "chamber_name": getattr(dowod, "chamber_name", ""),
                "resource_path": getattr(dowod, "resource_path", ""),
                "record_id": getattr(dowod, "record_id", None),
                "method": getattr(dowod, "method", ""),
                "jev_verdict": (getattr(dowod, "metadata", {}) or {}).get("jev_verdict"),
                "score": getattr(dowod, "score", None),
                "relevance": round(ocena, 3),
            })
        linie.append(f"- {zdanie} {znacznik}")

    niedostateczne = sufficiency is not None and sufficiency < PROG_SUFFICIENCY
    if not zaufanych:
        # Sa tylko dowody odrzucone przez Jeva - nie udajemy, ze odpowiadamy.
        niedostateczne = True
    if niedostateczne and WZORZEC_PYTANIA_O_ISTNIENIE.search(zapytanie or ""):
        # Pytanie o istnienie przy slabej sufficiency: mowimy wprost, ze istnienia nie potwierdzamy.
        naglowek = (
            f"Not confirmed in the knowledge base (sufficiency={sufficiency:.2f} < {PROG_SUFFICIENCY}): "
            "no retrieved fragment names the thing asked about, so its existence is not supported by "
            "evidence. Fragments below are context only, not an answer.")
    elif niedostateczne:
        naglowek = (
            f"No verified evidence is sufficient to answer this query (sufficiency="
            f"{sufficiency:.2f} < {PROG_SUFFICIENCY}). Below are the closest retrieved fragments, "
            f"presented as evidence only, not as an answer.")
    else:
        naglowek = "Grounded answer built only from retrieved evidence (one citation per claim):"
    tresc = "\n".join([naglowek, *linie])
    # Metryka liczona z GOTOWEGO TEKSTU, nie z zalozenia: ile zdan-roszczen ma znacznik cytatu.
    wzorzec = re.compile(r"\[c\d{2}#[^\]]+\]")
    zdania_roszczen = [linia for linia in tresc.splitlines() if linia.startswith("- ")]
    z_cytatami = [linia for linia in zdania_roszczen if wzorzec.search(linia)]
    pokrycie = round(len(z_cytatami) / max(1, len(zdania_roszczen)), 3)
    claims = len(zdania_roszczen)
    return {
        "answer": tresc,
        "answer_mode": "evidence_synthesis",
        "synthesis": {
            **bazowy,
            "status": "insufficient_evidence" if niedostateczne else "synthesized",
            "claims": claims,
            "citations": len(cytaty),
            "citation_coverage": pokrycie,
            "sources_used": len({id(d) for d, _, _ in wybrane}),
            "detail": "Deterministic extractive synthesis: every claim is a verbatim sentence from "
                      "the evidence pack with its citation marker; no model-generated prose.",
        },
        "citations": cytaty,
    }
