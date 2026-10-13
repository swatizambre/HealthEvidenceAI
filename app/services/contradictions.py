"""General contradiction detection across structured patient facts.

This is an engineering signal for human review. It is not a clinical judgment.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.evaluator import EvidenceItem, LabRecord, TextRecord


@dataclass(frozen=True)
class ContradictionFinding:
    code: str
    description: str
    evidence: tuple[EvidenceItem, ...]


def detect_record_contradictions(
    notes: list[TextRecord],
    labs: list[LabRecord],
    *,
    medication_names: list[str] | None = None,
) -> list[ContradictionFinding]:
    """Detect contradictory phrases that appear together in the same record set."""
    findings: list[ContradictionFinding] = []
    findings.extend(_active_vs_stopped_medication(notes, medication_names or []))
    findings.extend(_duplicate_conflicting_lab_names(labs))
    return findings


def _active_vs_stopped_medication(
    notes: list[TextRecord],
    medication_names: list[str],
) -> list[ContradictionFinding]:
    findings: list[ContradictionFinding] = []
    blob = "\n".join(note.content for note in notes).lower()
    for name in medication_names:
        lowered = name.lower()
        if not lowered:
            continue
        active = f"{lowered} active" in blob or f"taking {lowered}" in blob
        stopped = (
            f"{lowered} discontinued" in blob
            or f"stopped {lowered}" in blob
            or f"{lowered} was not attempted" in blob
        )
        if active and stopped:
            evidence = tuple(
                EvidenceItem(
                    document_id=note.document_id,
                    chunk_id=note.chunks[0][0] if note.chunks else "",
                    source=note.source,
                    text_reference=note.content[:240],
                )
                for note in notes
                if lowered in note.content.lower() and note.chunks
            )
            findings.append(
                ContradictionFinding(
                    code="MEDICATION_STATUS_CONFLICT",
                    description=f"Medication status phrases conflict for {name}.",
                    evidence=evidence[:3],
                )
            )
    return findings


def _duplicate_conflicting_lab_names(labs: list[LabRecord]) -> list[ContradictionFinding]:
    """Same lab name with clearly opposing textual values is escalated."""
    by_name: dict[str, list[LabRecord]] = {}
    for lab in labs:
        by_name.setdefault(lab.test_name.lower(), []).append(lab)
    findings: list[ContradictionFinding] = []
    for name, group in by_name.items():
        values = {_lab_value(item) for item in group}
        values.discard("")
        if len(values) < 2:
            continue
        if {"positive", "negative"} <= values or {"detected", "not detected"} <= values:
            evidence = tuple(
                EvidenceItem(
                    document_id=item.document_id,
                    chunk_id=item.chunks[0][0] if item.chunks else "",
                    source="lab_result",
                    text_reference=item.content[:240],
                )
                for item in group
                if item.chunks
            )
            findings.append(
                ContradictionFinding(
                    code="LAB_VALUE_CONFLICT",
                    description=f"Laboratory values conflict for {name}.",
                    evidence=evidence[:3],
                )
            )
    return findings


def _lab_value(lab: LabRecord) -> str:
    text = lab.content
    if ":" in text:
        text = text.split(":", 1)[1]
    return text.strip().lower()
