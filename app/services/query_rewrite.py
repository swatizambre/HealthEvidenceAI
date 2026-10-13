"""Multi-query expansion for hybrid RAG (competitor-grade retrieval breadth).

Expands a clinical/PA query into complementary retrieval angles without inventing
clinical facts. Used by the hybrid pipeline before dense+lexical fusion.
"""

from __future__ import annotations

import re

# Synonym / angle banks — documentation readiness language, not coverage decisions.
_ANGLE_MAP: list[tuple[re.Pattern[str], list[str]]] = [
    (
        re.compile(r"\b(mri|magnetic resonance)\b", re.I),
        ["imaging report", "radiology findings"],
    ),
    (
        re.compile(r"\b(ct|computed tomography)\b", re.I),
        ["imaging report", "cross-sectional imaging"],
    ),
    (
        re.compile(r"\b(lab|laboratory|a1c|hemoglobin)\b", re.I),
        ["lab result", "laboratory value"],
    ),
    (
        re.compile(r"\b(medicat|drug|therapy|prescription)\b", re.I),
        ["medication list", "active medications"],
    ),
    (
        re.compile(r"\b(diagnos|disorder|condition)\b", re.I),
        ["problem list", "clinical diagnosis note"],
    ),
    (
        re.compile(r"\b(conservativ|physio|physical therapy|rehab)\b", re.I),
        ["therapy note", "conservative care"],
    ),
    (
        re.compile(r"\b(surgery|operative|procedure)\b", re.I),
        ["operative note", "procedure documentation"],
    ),
    (
        re.compile(r"\b(consent|attestation)\b", re.I),
        ["consent documented", "patient attestation"],
    ),
]


def expand_retrieval_queries(query: str, *, max_queries: int = 6) -> list[str]:
    """Return original query plus complementary retrieval angles (deduped)."""
    cleaned = " ".join((query or "").split())
    if not cleaned:
        return []
    out: list[str] = [cleaned]
    lower = cleaned.lower()
    for pattern, angles in _ANGLE_MAP:
        if pattern.search(cleaned):
            for angle in angles:
                candidate = f"{cleaned} {angle}".strip()
                if candidate.lower() not in {item.lower() for item in out}:
                    out.append(candidate)
                short = angle
                if short.lower() not in {item.lower() for item in out}:
                    out.append(short)
        if len(out) >= max_queries:
            break
    # Clause split for compound criteria text.
    for sep in (";", " and ", " / ", " — ", " - "):
        if sep in lower or sep in cleaned:
            for piece in re.split(r";| and | / | — | - ", cleaned, flags=re.I):
                piece = piece.strip()
                if len(piece) >= 4 and piece.lower() not in {item.lower() for item in out}:
                    out.append(piece)
    return out[:max_queries]
