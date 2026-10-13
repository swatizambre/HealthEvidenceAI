"""Last-line checks so unsupported conclusions cannot ship without evidence."""

from __future__ import annotations

from app.services.evaluator import (
    STATUS_MISSING,
    STATUS_NOT_SUPPORTED,
    STATUS_SUPPORTED,
    Evaluation,
)


def apply_safety_net(items: list[Evaluation]) -> list[Evaluation]:
    """Downgrade a supported or unsupported call that has no real citation."""
    cleaned: list[Evaluation] = []
    for item in items:
        evidence = [
            entry
            for entry in item.evidence
            if entry.document_id and entry.chunk_id and entry.text_reference
        ]
        status = item.status
        reason = item.reason
        missing_label = item.missing_label
        contradiction = item.contradiction
        if status in {STATUS_SUPPORTED, STATUS_NOT_SUPPORTED} and not evidence:
            status = STATUS_MISSING
            reason = (
                "No source evidence was available, so this criterion was not marked "
                "supported or unsupported."
            )
            missing_label = missing_label or item.criterion
            contradiction = None
            evidence = []
        if status == STATUS_MISSING:
            evidence = []
        cleaned.append(
            Evaluation(
                criterion_id=item.criterion_id,
                criterion=item.criterion,
                status=status,
                evidence=evidence,
                reason=reason,
                missing_label=missing_label,
                contradiction=contradiction,
            )
        )
    return cleaned


def human_review_required(items: list[Evaluation]) -> bool:
    if not items:
        return True
    if any(item.contradiction for item in items):
        return True
    return any(item.status != STATUS_SUPPORTED for item in items)


def evidence_coverage(items: list[Evaluation]) -> str:
    if not items or not any(item.evidence for item in items):
        return "NONE"
    if all(item.status == STATUS_SUPPORTED and item.evidence for item in items):
        return "COMPLETE"
    return "AVAILABLE"
