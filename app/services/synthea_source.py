"""Load the public Synthea sample CSV.

The files are the MITRE Synthea 100-patient sample:
https://synthetichealth.github.io/synthea-sample-data/downloads/latest/synthea_sample_data_csv_latest.zip

Synthea records are synthetic. This loader does not read names, addresses,
phone numbers, SSNs, or other contact identifiers from the CSV.
"""

from __future__ import annotations

import csv
import ssl
import subprocess
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path

SOURCE_URL = (
    "https://synthetichealth.github.io/synthea-sample-data/"
    "downloads/latest/synthea_sample_data_csv_latest.zip"
)
SOURCE_NAME = "Synthea sample CSV"
PATIENT_LIMIT = 100

_CACHE = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "cache"


class SyntheaSourceError(RuntimeError):
    """The public Synthea sample could not be loaded."""


@dataclass(frozen=True)
class MedicationFact:
    description: str
    started_at: datetime
    stopped: bool


@dataclass(frozen=True)
class LabFact:
    description: str
    value: str
    unit: str
    collected_at: datetime


@dataclass(frozen=True)
class ProcedureFact:
    description: str
    performed_at: datetime


@dataclass(frozen=True)
class ImagingFact:
    modality: str
    body_part: str
    description: str
    studied_at: datetime


@dataclass(frozen=True)
class ClaimFact:
    status: str
    amount_cents: int
    service_date: datetime


@dataclass(frozen=True)
class SyntheaPatient:
    source_id: str
    birth_date: date
    sex: str
    conditions: tuple[str, ...]
    medications: tuple[MedicationFact, ...]
    labs: tuple[LabFact, ...]
    procedures: tuple[ProcedureFact, ...]
    imaging: tuple[ImagingFact, ...]
    claims: tuple[ClaimFact, ...]


@dataclass(frozen=True)
class SyntheaCatalog:
    patients: tuple[SyntheaPatient, ...]
    payer_names: tuple[str, ...]


def load_catalog() -> SyntheaCatalog:
    """Return the cached 100-patient catalog. The CSV parse runs once per process."""
    return _cached_catalog()


@lru_cache(maxsize=1)
def _cached_catalog() -> SyntheaCatalog:
    folder = _ensure_csv_dir()
    return _read_catalog(folder)


def _ensure_csv_dir() -> Path:
    folder = _CACHE / "csv"
    if (folder / "patients.csv").exists():
        return folder
    _CACHE.mkdir(parents=True, exist_ok=True)
    archive = _CACHE / "synthea_sample_data_csv_latest.zip"
    if not archive.exists():
        _download(SOURCE_URL, archive)
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as handle:
        handle.extractall(folder)
    located = _find_patients_csv(folder)
    if located is None:
        raise SyntheaSourceError("The Synthea archive did not contain patients.csv.")
    return located.parent


def _find_patients_csv(folder: Path) -> Path | None:
    direct = folder / "patients.csv"
    if direct.exists():
        return direct
    matches = sorted(folder.rglob("patients.csv"))
    return matches[0] if matches else None


def _download(url: str, destination: Path) -> None:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "HealthEvidenceAI/0.1"})
        context = ssl.create_default_context()
        with urllib.request.urlopen(request, context=context, timeout=120) as response:
            destination.write_bytes(response.read())
        return
    except OSError:
        curl = _curl_executable()
        completed = subprocess.run(
            [curl, "-fL", "--retry", "3", "-o", str(destination), url],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0 or not destination.exists():
            raise SyntheaSourceError(
                "Could not download the Synthea sample CSV. "
                "Place synthea_sample_data_csv_latest.zip in data/synthetic/cache."
            ) from None


def _curl_executable() -> str:
    if Path("C:/Windows/System32/curl.exe").exists():
        return "C:/Windows/System32/curl.exe"
    return "curl"


def _read_catalog(folder: Path) -> SyntheaCatalog:
    patient_rows = _csv(folder, "patients.csv")
    ordered = sorted((row for row in patient_rows if row.get("Id")), key=lambda row: row["Id"])
    if len(ordered) < PATIENT_LIMIT:
        raise SyntheaSourceError("The Synthea sample has fewer than 100 patients.")
    allowed = {row["Id"] for row in ordered}
    conditions = _grouped_text(folder, "conditions.csv", "PATIENT", "DESCRIPTION", allowed)
    medications = _medications(folder, allowed)
    labs = _labs(folder, allowed)
    procedures = _procedures(folder, allowed)
    imaging = _imaging(folder, allowed)
    claims = _claims(folder, allowed)
    patients: list[SyntheaPatient] = []
    for row in ordered:
        source_id = row["Id"]
        if not medications[source_id] or not labs[source_id] or not procedures[source_id]:
            continue
        patients.append(
            SyntheaPatient(
                source_id=source_id,
                birth_date=date.fromisoformat(row["BIRTHDATE"][:10]),
                sex=_sex(row.get("GENDER", "")),
                conditions=tuple(dict.fromkeys(conditions[source_id])),
                medications=tuple(medications[source_id]),
                labs=tuple(labs[source_id]),
                procedures=tuple(procedures[source_id]),
                imaging=tuple(imaging[source_id]),
                claims=tuple(claims[source_id]),
            )
        )
        if len(patients) == PATIENT_LIMIT:
            break
    if len(patients) < PATIENT_LIMIT:
        raise SyntheaSourceError("Fewer than 100 Synthea patients had notes, labs, and medications.")
    payers = tuple(dict.fromkeys(row["NAME"] for row in _csv(folder, "payers.csv") if row.get("NAME")))
    if not payers:
        raise SyntheaSourceError("The Synthea sample did not include payer names.")
    return SyntheaCatalog(patients=tuple(patients), payer_names=payers)


def _grouped_text(
    folder: Path,
    filename: str,
    id_column: str,
    value_column: str,
    allowed: set[str],
) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in _csv(folder, filename):
        source_id = row.get(id_column, "")
        value = row.get(value_column, "").strip()
        if source_id in allowed and value:
            grouped[source_id].append(value)
    return grouped


def _medications(folder: Path, allowed: set[str]) -> dict[str, list[MedicationFact]]:
    grouped: dict[str, list[MedicationFact]] = defaultdict(list)
    for row in _csv(folder, "medications.csv"):
        source_id = row.get("PATIENT", "")
        description = row.get("DESCRIPTION", "").strip()
        if source_id not in allowed or not description or not row.get("START"):
            continue
        grouped[source_id].append(
            MedicationFact(
                description=description,
                started_at=_timestamp(row["START"]),
                stopped=bool(row.get("STOP", "").strip()),
            )
        )
    return grouped


def _labs(folder: Path, allowed: set[str]) -> dict[str, list[LabFact]]:
    grouped: dict[str, list[LabFact]] = defaultdict(list)
    for row in _csv(folder, "observations.csv"):
        if row.get("CATEGORY") != "laboratory":
            continue
        source_id = row.get("PATIENT", "")
        description = row.get("DESCRIPTION", "").strip()
        if source_id not in allowed or not description or not row.get("DATE"):
            continue
        grouped[source_id].append(
            LabFact(
                description=description,
                value=(row.get("VALUE") or "").strip()[:64] or "recorded",
                unit=(row.get("UNITS") or "").strip()[:64] or "recorded",
                collected_at=_timestamp(row["DATE"]),
            )
        )
    return grouped


def _procedures(folder: Path, allowed: set[str]) -> dict[str, list[ProcedureFact]]:
    grouped: dict[str, list[ProcedureFact]] = defaultdict(list)
    for row in _csv(folder, "procedures.csv"):
        source_id = row.get("PATIENT", "")
        description = row.get("DESCRIPTION", "").strip()
        if source_id not in allowed or not description or not row.get("START"):
            continue
        grouped[source_id].append(
            ProcedureFact(description=description[:200], performed_at=_timestamp(row["START"]))
        )
    return grouped


def _imaging(folder: Path, allowed: set[str]) -> dict[str, list[ImagingFact]]:
    grouped: dict[str, list[ImagingFact]] = defaultdict(list)
    for row in _csv(folder, "imaging_studies.csv"):
        source_id = row.get("PATIENT", "")
        if source_id not in allowed or not row.get("DATE"):
            continue
        modality = (row.get("MODALITY_DESCRIPTION") or row.get("MODALITY_CODE") or "unknown").strip()
        body = _body_part(row.get("BODYSITE_DESCRIPTION", ""))
        grouped[source_id].append(
            ImagingFact(
                modality=modality[:32] or "unknown",
                body_part=body[:64] or "unspecified",
                description=(
                    f"{modality} of {body}. Synthea imaging metadata only. "
                    "No image pixels are stored. No diagnostic interpretation is provided."
                ),
                studied_at=_timestamp(row["DATE"]),
            )
        )
    return grouped


def _claims(folder: Path, allowed: set[str]) -> dict[str, list[ClaimFact]]:
    grouped: dict[str, list[ClaimFact]] = defaultdict(list)
    for row in _csv(folder, "claims.csv"):
        source_id = row.get("PATIENTID", "")
        if source_id not in allowed or not row.get("SERVICEDATE"):
            continue
        status = (row.get("STATUS1") or "recorded").strip().lower()[:32]
        outstanding = row.get("OUTSTANDING1") or "0"
        try:
            amount_cents = int(round(float(outstanding) * 100))
        except ValueError:
            amount_cents = 0
        grouped[source_id].append(
            ClaimFact(
                status=status or "recorded",
                amount_cents=amount_cents,
                service_date=_timestamp(row["SERVICEDATE"]),
            )
        )
    return grouped


def _csv(folder: Path, filename: str) -> list[dict[str, str]]:
    path = folder / filename
    if not path.exists():
        found = list(folder.rglob(filename))
        if not found:
            raise SyntheaSourceError(f"Missing Synthea file {filename}.")
        path = found[0]
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _sex(value: str) -> str:
    return {"M": "male", "F": "female"}.get(value.strip().upper(), "unknown")


def _body_part(value: str) -> str:
    text = value.strip()
    if text.endswith("(body structure)"):
        text = text[: -len("(body structure)")].strip()
    return text or "unspecified"


def _timestamp(value: str) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
