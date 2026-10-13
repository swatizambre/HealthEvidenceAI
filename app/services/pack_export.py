"""Evidence pack export (minimal PDF, no external PDF library)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.safety import DISCLAIMER, PROTOTYPE_BANNER
from app.models import AuthorizationCase, Patient


def export_case_pdf_bytes(session: Session, case_code: str) -> tuple[bytes, str]:
    case = session.scalar(
        select(AuthorizationCase).where(AuthorizationCase.case_code == case_code)
    )
    if case is None:
        raise NotFoundError("CASE_NOT_FOUND", f"Case {case_code} was not found.")
    patient = session.get(Patient, case.patient_id)
    patient_code = patient.patient_code if patient else "unknown"
    lines = [
        "HealthEvidence AI — Evidence pack export",
        PROTOTYPE_BANNER,
        DISCLAIMER,
        "",
        f"Case: {case.case_code}",
        f"Patient: {patient_code}",
        f"Procedure: {case.procedure or 'Evidence pack documentation'}",
        f"Status: {case.status or 'queued'}",
        f"Assigned to: {getattr(case, 'assigned_to', None) or 'unassigned'}",
        f"Lifecycle: {(case.lifecycle_note or '')[:400]}",
        f"Exported at: {datetime.now(UTC).isoformat()}",
        "",
        "This export organizes documentation readiness only.",
        "It does not approve, deny, diagnose, or submit prior authorization.",
    ]
    filename = f"{case.case_code}-evidence-pack.pdf"
    return _simple_pdf("\n".join(lines)), filename


def _simple_pdf(text: str) -> bytes:
    """Minimal single-page PDF with Helvetica text lines."""
    # Escape PDF string specials.
    safe_lines: list[str] = []
    for raw in text.splitlines()[:48]:
        line = raw.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        safe_lines.append(line[:95] or " ")

    content_ops = ["BT", "/F1 10 Tf", "50 780 Td", "14 TL"]
    for i, line in enumerate(safe_lines):
        if i == 0:
            content_ops.append(f"({line}) Tj")
        else:
            content_ops.append("T*")
            content_ops.append(f"({line}) Tj")
    content_ops.append("ET")
    stream = "\n".join(content_ops).encode("latin-1", errors="replace")

    objects: list[bytes] = []
    objects.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objects.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    objects.append(
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
    )
    objects.append(
        f"4 0 obj<< /Length {len(stream)} >>stream\n".encode("ascii")
        + stream
        + b"\nendstream\nendobj\n"
    )
    objects.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(out)
