"""Deterministic policy-criterion evaluation.

Status is decided by recorded source text. This module does not call a language model
and does not invent evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

STATUS_SUPPORTED = "SUPPORTED"
STATUS_NOT_SUPPORTED = "NOT_SUPPORTED"
STATUS_MISSING = "MISSING"
STATUS_UNKNOWN = "UNKNOWN"

_REASONS = {
    STATUS_SUPPORTED: "A source record contains the evidence this criterion asks for.",
    STATUS_NOT_SUPPORTED: "A source record states that this criterion is not met.",
    STATUS_MISSING: "No source record contains the evidence this criterion asks for.",
    STATUS_UNKNOWN: (
        "The available records are uncertain or contradictory, so this criterion "
        "cannot be safely evaluated."
    ),
}

# Prefixed cues that reverse or weaken a nearby phrase (scoped to the clause).
# Includes family history, uncertainty (rule-out / possible), and hard negation.
_NEGATION_PREFIX = re.compile(
    r"(?:"
    r"\bfamily\s+history\s+of\b|\bfamily\s+hx\s+of\b|\bfh(?:x)?\s+of\b|"
    r"\brule\s+out\b|\br/o\b|\br\.o\.\b|"
    r"\bpossible\b|\bprobable\b|\bsuspected\b|\bquestionable\b|\bquery\b|"
    r"\bno\s+history\s+of\b|\bno\s+known\b|\bnegative\s+for\b|\bruled\s+out\b|"
    r"\babsence\s+of\b|\bfree\s+of\b|\bdenies\b|\bdenied\b|\bwithout\b|\bnever\b|"
    r"\bno\b|\bnot\b"
    r")\s+",
    re.I,
)
# "diabetes: none" / "Diabetes was excluded" / "diabetes?" trailing cues.
_TRAILING_NONE = re.compile(
    r"^\s*(?:[:\-–—]\s*)?(?:"
    r"\?|"
    r"(?:none|nil|negative|absent|denies|denied|"
    r"ruled\s+out|was\s+ruled\s+out|excluded|was\s+excluded)\b"
    r")",
    re.I,
)
_CLAUSE_BREAK = re.compile(r"[.;\n]|,\s*but\b|\bbut\b|\bhowever\b|\balthough\b", re.I)
_NUMERIC = re.compile(r"[-+]?\d+(?:\.\d+)?")
_UNIT_TOKEN = re.compile(
    r"\b(?:%|percent|mmol\s*/\s*mol|mmol/mol|mg\s*/\s*d[lL]|mg/dl|g\s*/\s*d[lL]|g/dl|"
    r"mmol\s*/\s*[lL]|mmol/l|u\s*/\s*[lL]|iu\s*/\s*[lL])\b",
    re.I,
)


@dataclass(frozen=True)
class EvidenceItem:
    document_id: str
    chunk_id: str
    source: str
    text_reference: str


@dataclass(frozen=True)
class TextRecord:
    content: str
    document_id: str
    chunks: tuple[tuple[str, str], ...]
    source: str


@dataclass(frozen=True)
class LabRecord:
    test_name: str
    content: str
    document_id: str
    chunks: tuple[tuple[str, str], ...]
    value: str = ""
    unit: str = ""
    collected_at: datetime | None = None


@dataclass(frozen=True)
class CriterionInput:
    code: str
    description: str
    rule: dict[str, Any]


@dataclass
class Evaluation:
    criterion_id: str
    criterion: str
    status: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    reason: str = ""
    missing_label: str | None = None
    contradiction: str | None = None


def evaluate_criteria(
    criteria: list[CriterionInput],
    notes: list[TextRecord],
    labs: list[LabRecord],
) -> list[Evaluation]:
    return [evaluate_criterion(criterion, notes, labs) for criterion in criteria]


def evaluate_criterion(
    criterion: CriterionInput,
    notes: list[TextRecord],
    labs: list[LabRecord],
) -> Evaluation:
    rule = criterion.rule
    rule_type = str(rule.get("type", ""))
    missing_label = str(rule.get("missing_label") or criterion.description)
    if rule_type == "keyword":
        return _evaluate_phrases(
            criterion,
            notes,
            required=list(rule.get("required_any") or []),
            opposing=list(rule.get("negation_any") or []),
            missing_label=missing_label,
            opposing_status=STATUS_NOT_SUPPORTED,
        )
    if rule_type == "statement_clarity":
        return _evaluate_phrases(
            criterion,
            notes,
            required=list(rule.get("clear_any") or []),
            opposing=list(rule.get("uncertain_any") or []),
            missing_label=missing_label,
            opposing_status=STATUS_UNKNOWN,
        )
    if rule_type == "lab_test":
        return _evaluate_lab(
            criterion,
            labs,
            str(rule.get("test_name") or ""),
            missing_label,
            comparator=str(rule.get("comparator") or rule.get("operator") or "").strip(),
            threshold=_optional_float(rule.get("threshold", rule.get("value"))),
            expected_unit=str(rule.get("unit") or "").strip(),
            max_age_days=_optional_float(rule.get("max_age_days")),
            presence_only=bool(rule.get("presence")),
        )
    return Evaluation(
        criterion_id=criterion.code,
        criterion=criterion.description,
        status=STATUS_UNKNOWN,
        reason=_REASONS[STATUS_UNKNOWN],
        missing_label=None,
    )


def _evaluate_phrases(
    criterion: CriterionInput,
    notes: list[TextRecord],
    *,
    required: list[str],
    opposing: list[str],
    missing_label: str,
    opposing_status: str,
) -> Evaluation:
    support = _matching(notes, required)
    conflict = _matching(notes, opposing)
    if support and conflict:
        return Evaluation(
            criterion_id=criterion.code,
            criterion=criterion.description,
            status=STATUS_UNKNOWN,
            evidence=_cite_matches(support + conflict),
            reason=_REASONS[STATUS_UNKNOWN],
            contradiction="The record contains statements that both meet and conflict with this criterion.",
        )
    if conflict:
        return Evaluation(
            criterion_id=criterion.code,
            criterion=criterion.description,
            status=opposing_status,
            evidence=_cite_matches(conflict),
            reason=_REASONS[opposing_status],
        )
    if support:
        return Evaluation(
            criterion_id=criterion.code,
            criterion=criterion.description,
            status=STATUS_SUPPORTED,
            evidence=_cite_matches(support),
            reason=_REASONS[STATUS_SUPPORTED],
        )
    return Evaluation(
        criterion_id=criterion.code,
        criterion=criterion.description,
        status=STATUS_MISSING,
        reason=_REASONS[STATUS_MISSING],
        missing_label=missing_label,
    )


def _evaluate_lab(
    criterion: CriterionInput,
    labs: list[LabRecord],
    test_name: str,
    missing_label: str,
    *,
    comparator: str = "",
    threshold: float | None = None,
    expected_unit: str = "",
    max_age_days: float | None = None,
    presence_only: bool = False,
) -> Evaluation:
    matches = [lab for lab in labs if lab.test_name.lower() == test_name.lower() and lab.chunks]
    matches.sort(
        key=lambda lab: (
            lab.collected_at or datetime.min.replace(tzinfo=UTC),
            lab.document_id,
        ),
        reverse=True,
    )
    if not matches:
        return Evaluation(
            criterion_id=criterion.code,
            criterion=criterion.description,
            status=STATUS_MISSING,
            reason=_REASONS[STATUS_MISSING],
            missing_label=missing_label,
        )
    lab = matches[0]
    evidence = _cite_text(
        content=lab.content,
        document_id=lab.document_id,
        chunks=lab.chunks,
        phrase=test_name,
        source="lab_result",
    )
    if evidence is None:
        return Evaluation(
            criterion_id=criterion.code,
            criterion=criterion.description,
            status=STATUS_MISSING,
            reason=_REASONS[STATUS_MISSING],
            missing_label=missing_label,
        )
    # Explicit presence checks (not numeric). Bare lab_test without comparator → UNKNOWN.
    if presence_only and not comparator:
        return Evaluation(
            criterion_id=criterion.code,
            criterion=criterion.description,
            status=STATUS_SUPPORTED,
            evidence=[evidence],
            reason=_REASONS[STATUS_SUPPORTED],
        )
    if not comparator or threshold is None:
        return Evaluation(
            criterion_id=criterion.code,
            criterion=criterion.description,
            status=STATUS_UNKNOWN,
            evidence=[evidence],
            reason=_REASONS[STATUS_UNKNOWN],
        )
    if max_age_days is not None and lab.collected_at is not None:
        collected = lab.collected_at
        if collected.tzinfo is None:
            collected = collected.replace(tzinfo=UTC)
        age = datetime.now(UTC) - collected.astimezone(UTC)
        if age > timedelta(days=float(max_age_days)):
            return Evaluation(
                criterion_id=criterion.code,
                criterion=criterion.description,
                status=STATUS_UNKNOWN,
                evidence=[evidence],
                reason=_REASONS[STATUS_UNKNOWN],
            )
    measured, lab_unit = _parse_lab_measurement(lab)
    if measured is None:
        return Evaluation(
            criterion_id=criterion.code,
            criterion=criterion.description,
            status=STATUS_UNKNOWN,
            evidence=[evidence],
            reason=_REASONS[STATUS_UNKNOWN],
        )
    expected_norm = _normalize_unit(expected_unit)
    # Policy named a unit but the lab result has none — do not assume they match.
    if expected_norm and not lab_unit:
        return Evaluation(
            criterion_id=criterion.code,
            criterion=criterion.description,
            status=STATUS_UNKNOWN,
            evidence=[evidence],
            reason=_REASONS[STATUS_UNKNOWN],
        )
    target_unit = expected_norm or lab_unit
    converted = _convert_lab_value(measured, lab_unit, target_unit or lab_unit)
    if converted is None:
        return Evaluation(
            criterion_id=criterion.code,
            criterion=criterion.description,
            status=STATUS_UNKNOWN,
            evidence=[evidence],
            reason=_REASONS[STATUS_UNKNOWN],
        )
    if expected_norm and converted[1] != expected_norm:
        return Evaluation(
            criterion_id=criterion.code,
            criterion=criterion.description,
            status=STATUS_UNKNOWN,
            evidence=[evidence],
            reason=_REASONS[STATUS_UNKNOWN],
        )
    if _compare_lab(converted[0], comparator, threshold):
        return Evaluation(
            criterion_id=criterion.code,
            criterion=criterion.description,
            status=STATUS_SUPPORTED,
            evidence=[evidence],
            reason=_REASONS[STATUS_SUPPORTED],
        )
    return Evaluation(
        criterion_id=criterion.code,
        criterion=criterion.description,
        status=STATUS_NOT_SUPPORTED,
        evidence=[evidence],
        reason=_REASONS[STATUS_NOT_SUPPORTED],
    )


def _matching(notes: list[TextRecord], phrases: list[str]) -> list[tuple[TextRecord, str]]:
    if not phrases:
        return []
    found: list[tuple[TextRecord, str]] = []
    for note in sorted(notes, key=lambda item: item.document_id):
        phrase = _find_phrase(note.content, phrases)
        if phrase is not None:
            found.append((note, phrase))
    return found


def _cite_matches(matches: list[tuple[TextRecord, str]]) -> list[EvidenceItem]:
    evidence: list[EvidenceItem] = []
    seen: set[tuple[str, str]] = set()
    for note, phrase in matches:
        item = _cite_text(
            content=note.content,
            document_id=note.document_id,
            chunks=note.chunks,
            phrase=phrase,
            source=note.source,
        )
        if item is None:
            continue
        key = (item.document_id, item.text_reference)
        if key in seen:
            continue
        seen.add(key)
        evidence.append(item)
        if len(evidence) == 3:
            break
    return evidence


def _cite_text(
    *,
    content: str,
    document_id: str,
    chunks: tuple[tuple[str, str], ...],
    phrase: str,
    source: str,
) -> EvidenceItem | None:
    if not chunks or not document_id:
        return None
    snippet = _snippet(content, phrase)
    if not snippet:
        return None
    chunk_id = ""
    for code, chunk_content in chunks:
        if snippet in chunk_content or phrase.lower() in chunk_content.lower():
            chunk_id = code
            break
    if not chunk_id:
        return None
    return EvidenceItem(
        document_id=document_id,
        chunk_id=chunk_id,
        source=source,
        text_reference=snippet,
    )


def _find_phrase(text: str, phrases: list[str]) -> str | None:
    lowered = text.lower()
    for phrase in phrases:
        needle = phrase.lower()
        start = 0
        while True:
            index = lowered.find(needle, start)
            if index < 0:
                break
            if not _is_negated(lowered, index, len(needle)):
                return phrase
            start = index + len(needle)
    return None


def _clause_span(text: str, match_index: int) -> tuple[int, int]:
    """Return [start, end) of the clause containing match_index (nearby scope only)."""
    starts = [0]
    ends: list[int] = []
    for match in _CLAUSE_BREAK.finditer(text):
        ends.append(match.start())
        starts.append(match.end())
    ends.append(len(text))
    for start, end in zip(starts, ends, strict=False):
        if start <= match_index < end:
            return start, end
    return 0, len(text)


def _is_negated(lowered: str, match_index: int, match_len: int) -> bool:
    """Negation applies only within the same clause / nearby window."""
    clause_start, clause_end = _clause_span(lowered, match_index)
    before = lowered[clause_start:match_index]
    after = lowered[match_index + match_len : clause_end]
    # Keep only the last ~40 chars before the phrase inside the clause.
    before = before[-40:]
    if _NEGATION_PREFIX.search(before):
        # Ensure no clause-breaking word sits between the cue and the phrase.
        last = None
        for match in _NEGATION_PREFIX.finditer(before):
            last = match
        if last is not None and not _CLAUSE_BREAK.search(before[last.end() :]):
            return True
    if _TRAILING_NONE.match(after):
        return True
    return False


def _optional_float(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _normalize_unit(unit: str) -> str:
    raw = (unit or "").strip().lower().replace(" ", "")
    aliases = {
        "percent": "%",
        "pct": "%",
        "mmol/mol": "mmol/mol",
        "mg/dl": "mg/dl",
        "g/dl": "g/dl",
        "mmol/l": "mmol/l",
        "u/l": "u/l",
        "iu/l": "iu/l",
    }
    if raw in {"%", "percent", "pct"}:
        return "%"
    return aliases.get(raw, raw)


def _parse_lab_measurement(lab: LabRecord) -> tuple[float | None, str]:
    if lab.value.strip():
        match = _NUMERIC.search(lab.value)
        if match is None:
            return None, _normalize_unit(lab.unit)
        try:
            return float(match.group(0)), _normalize_unit(lab.unit)
        except ValueError:
            return None, _normalize_unit(lab.unit)
    text = lab.content
    if ":" in text:
        text = text.split(":", 1)[1]
    match = _NUMERIC.search(text)
    if match is None:
        return None, _normalize_unit(lab.unit)
    unit = _normalize_unit(lab.unit)
    if not unit:
        unit_match = _UNIT_TOKEN.search(text[match.end() : match.end() + 24])
        if unit_match:
            unit = _normalize_unit(unit_match.group(0))
    try:
        return float(match.group(0)), unit
    except ValueError:
        return None, unit


def _convert_lab_value(
    value: float, from_unit: str, to_unit: str
) -> tuple[float, str] | None:
    src = _normalize_unit(from_unit)
    dst = _normalize_unit(to_unit)
    if not src and not dst:
        return value, ""
    # Policy unit without a lab unit must not be assumed identical (e.g. 53 vs 53%).
    if dst and not src:
        return None
    if not dst:
        dst = src
    if src == dst:
        return value, src
    # HbA1c IFCC (mmol/mol) ↔ NGSP (%)
    if src == "mmol/mol" and dst == "%":
        return (0.09148 * value) + 2.152, "%"
    if src == "%" and dst == "mmol/mol":
        return (value - 2.152) / 0.09148, "mmol/mol"
    return None


def _compare_lab(measured: float, comparator: str, threshold: float) -> bool:
    op = comparator.strip().lower()
    aliases = {
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
        "eq": "==",
        "ne": "!=",
        "greater_than": ">",
        "greater_than_or_equal": ">=",
        "less_than": "<",
        "less_than_or_equal": "<=",
        "equal": "==",
        "equals": "==",
    }
    op = aliases.get(op, op)
    if op in {">", "gt"}:
        return measured > threshold
    if op in {">=", "gte"}:
        return measured >= threshold
    if op in {"<", "lt"}:
        return measured < threshold
    if op in {"<=", "lte"}:
        return measured <= threshold
    if op in {"==", "=", "eq"}:
        return measured == threshold
    if op in {"!=", "ne"}:
        return measured != threshold
    return False


def _snippet(text: str, phrase: str) -> str:
    lowered = text.lower()
    index = lowered.find(phrase.lower())
    if index < 0:
        return text.strip()[:240]
    line_start = text.rfind("\n", 0, index) + 1
    line_end = text.find("\n", index + len(phrase))
    if line_end < 0:
        line_end = len(text)
    line = text[line_start:line_end].strip()
    if 0 < len(line) <= 320:
        return line
    start = max(0, index - 60)
    end = min(len(text), index + len(phrase) + 80)
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    while end < len(text) and not text[end:end + 1].isspace():
        end += 1
    return text[start:end].strip()
