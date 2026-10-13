"""Lexical citation verification for SUPPORTED checklist items.

Interim stand-in for an entailment (NLI) verifier. A SUPPORTED criterion keeps its
status only when at least one cited evidence item:

1. resolves to stored chunk text for the same document (retrieved hit or DB chunk), and
2. contains an affirmed mention of what the criterion asks for:
   - a required phrase / clear phrase / lab test name from the criterion rule, using the
     rules path's own negation, hedge, and family-history logic; or
   - when the criterion has no rule phrases (model-only criteria), at least two
     informative description tokens, one of them affirmed.

Anything else is downgraded to UNKNOWN for a reviewer. This never upgrades a status.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.services.evaluator import STATUS_SUPPORTED, STATUS_UNKNOWN, find_affirmed_phrase

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

DOWNGRADE_REASON = "Citation did not support the claim; needs reviewer check"
MIN_SHARED_TOKENS = 2

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    """
    a an and are as at be been being by for from has have in into is it its of on or
    that the their this to was were with within without
    any all both each either more most other some such than then there these those
    patient patients record records chart clinical documented documents documentation
    document note notes evidence present presence shown shows recorded clearly clear
    criterion criteria result results status least must should
    """.split()
)


@dataclass(frozen=True)
class ChunkText:
    document_id: str
    text: str


@dataclass
class CitationCheckResult:
    criterion_results: list[dict[str, Any]]
    checked: int = 0
    passed: int = 0
    downgraded: list[str] = field(default_factory=list)
    unresolved_citations: int = 0
    unresolved_keys: set[tuple[str, str]] = field(default_factory=set)

    @property
    def notes(self) -> list[str]:
        return [f"{cid}: cited text did not support the claim" for cid in self.downgraded]

    def summary(self) -> str:
        return (
            f"citations checked={self.checked} passed={self.passed} "
            f"downgraded={len(self.downgraded)} unresolved={self.unresolved_citations}"
        )


def criterion_phrases(rule: Mapping[str, Any] | None) -> list[str]:
    """Phrases a cited span must affirm for this rule (empty → fall back to tokens)."""
    if not rule:
        return []
    rule_type = str(rule.get("type") or "")
    if rule_type == "keyword":
        raw: Iterable[Any] = rule.get("required_any") or []
    elif rule_type == "statement_clarity":
        raw = rule.get("clear_any") or []
    elif rule_type == "lab_test":
        raw = [rule.get("test_name") or ""]
    else:
        raw = []
    return [str(item).strip() for item in raw if str(item or "").strip()]


def informative_tokens(text: str) -> set[str]:
    return {
        token
        for token in _TOKEN.findall((text or "").lower())
        if len(token) >= 3 and token not in _STOPWORDS
    }


def span_supports(
    text: str, *, phrases: list[str], description: str, lab_test: bool = False
) -> bool:
    """True when ``text`` affirms the criterion (phrases first, tokens as fallback).

    For lab criteria the phrase is the test name; a value such as "negative" is a result,
    not a negation of the test, so plain containment is enough there.
    """
    if not text.strip():
        return False
    if lab_test and phrases:
        lowered = text.lower()
        return any(phrase.lower() in lowered for phrase in phrases)
    if phrases:
        return find_affirmed_phrase(text, phrases) is not None
    wanted = informative_tokens(description)
    if not wanted:
        return False
    shared = sorted(wanted & informative_tokens(text))
    if len(shared) < min(MIN_SHARED_TOKENS, len(wanted)):
        return False
    return find_affirmed_phrase(text, shared) is not None


def chunk_texts_from_hits(hits: Iterable[Mapping[str, Any]]) -> dict[str, ChunkText]:
    """Index retrieved hits (already patient-scoped) by chunk id."""
    out: dict[str, ChunkText] = {}
    for hit in hits:
        chunk_id = str(hit.get("chunk_id") or "")
        content = str(hit.get("content") or "")
        if chunk_id and content and chunk_id not in out:
            out[chunk_id] = ChunkText(str(hit.get("document_id") or ""), content)
    return out


def load_chunk_texts(
    session: Session, chunk_ids: Iterable[str], *, patient_pk: str
) -> dict[str, ChunkText]:
    """Load stored chunk text by chunk code, restricted to this patient's documents."""
    from sqlalchemy import select

    from app.models import Document, DocumentChunk

    wanted = sorted({cid for cid in chunk_ids if cid})
    if not wanted:
        return {}
    rows = session.execute(
        select(DocumentChunk.chunk_code, Document.document_code, DocumentChunk.content)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(DocumentChunk.chunk_code.in_(wanted))
        .where(Document.patient_id == patient_pk)
    ).all()
    return {str(code): ChunkText(str(doc), str(content)) for code, doc, content in rows}


def cited_chunk_ids(criterion_results: Iterable[Mapping[str, Any]]) -> set[str]:
    return {
        str(ev.get("chunk_id") or "")
        for item in criterion_results
        if str(item.get("status") or "").upper() == STATUS_SUPPORTED
        for ev in item.get("evidence") or []
        if ev.get("chunk_id")
    }


def verify_citations(
    criterion_results: list[dict[str, Any]],
    criteria: Iterable[Mapping[str, Any]],
    chunks: Mapping[str, ChunkText],
) -> CitationCheckResult:
    """Check every SUPPORTED item; downgrade those with no supporting citation."""
    by_id = {str(item.get("criterion_id") or ""): item for item in criteria}
    result = CitationCheckResult(criterion_results=[])
    for raw in criterion_results:
        item = dict(raw)
        if str(item.get("status") or "").upper() != STATUS_SUPPORTED or not item.get("evidence"):
            result.criterion_results.append(item)
            continue
        result.checked += 1
        cid = str(item.get("criterion_id") or "")
        spec = by_id.get(cid) or {}
        rule = spec.get("rule") or {}
        phrases = criterion_phrases(rule)
        lab_test = str(rule.get("type") or "") == "lab_test"
        description = str(spec.get("description") or item.get("criterion") or "")
        resolved: list[dict[str, Any]] = []
        supported = False
        for ev in item.get("evidence") or []:
            stored = chunks.get(str(ev.get("chunk_id") or ""))
            doc_id = str(ev.get("document_id") or "")
            if stored is None or (stored.document_id and doc_id and stored.document_id != doc_id):
                result.unresolved_citations += 1
                result.unresolved_keys.add((doc_id, str(ev.get("chunk_id") or "")))
                continue
            resolved.append(ev)
            if span_supports(
                stored.text, phrases=phrases, description=description, lab_test=lab_test
            ):
                supported = True
        if supported:
            result.passed += 1
            result.criterion_results.append(item)
            continue
        item["status"] = STATUS_UNKNOWN
        item["reason"] = DOWNGRADE_REASON
        # Keep only citations that point at real stored text so the reviewer sees them.
        item["evidence"] = resolved
        result.downgraded.append(cid)
        result.criterion_results.append(item)
    return result
