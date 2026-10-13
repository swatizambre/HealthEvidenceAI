"""MONAI-isolated medical image analysis.

Without a connected PACS/DICOM source this module only echoes study metadata.
It never fabricates pixel statistics or a clinical diagnosis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings, get_settings

_DISCLAIMER = (
    "No image pixels were analyzed. Metadata echo only — not a diagnostic reading. "
    "Clinical interpretation required. Not for clinical use."
)


@dataclass(frozen=True)
class ImagingAnalysis:
    study_id: str
    observations: tuple[str, ...]
    confidence: float
    human_review_required: bool
    disclaimer: str
    backend: str = "monai"


@dataclass(frozen=True)
class ImagingComparison:
    study_a: str
    study_b: str
    changed: tuple[str, ...]
    unchanged: tuple[str, ...]
    uncertain: tuple[str, ...]
    human_review_required: bool
    disclaimer: str
    backend: str = "monai"


class MedicalImageAnalyzer(Protocol):
    def analyze(self, study_id: str, metadata: dict[str, str]) -> ImagingAnalysis: ...

    def compare(
        self,
        study_a: str,
        study_b: str,
        metadata_a: dict[str, str],
        metadata_b: dict[str, str],
    ) -> ImagingComparison: ...


class MonaiIsolatedAnalyzer:
    """Imaging adapter: metadata-only until a real volume source is wired."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._monai_available = False
        try:
            import monai  # noqa: F401

            self._monai_available = True
        except Exception:
            self._monai_available = False

    def analyze(self, study_id: str, metadata: dict[str, str]) -> ImagingAnalysis:
        modality = metadata.get("modality", "unknown")
        body = metadata.get("body_part", "unspecified")
        observations = [
            f"No image file or DICOM volume was loaded for study {study_id}.",
            f"Caller metadata: modality={modality}; body_part={body}.",
            "Imaging analysis is unavailable without a connected PACS/DICOM source.",
            "No clinical diagnosis was generated.",
        ]
        if self._monai_available:
            observations.append(
                "MONAI is installed but unused until a real image volume is supplied."
            )
            backend = "monai-metadata-only"
        else:
            observations.append(
                "MONAI package not installed; metadata-only path (no synthetic tensors)."
            )
            backend = "metadata-only"
        return ImagingAnalysis(
            study_id=study_id,
            observations=tuple(observations),
            confidence=0.0,
            human_review_required=True,
            disclaimer=_DISCLAIMER,
            backend=backend,
        )

    def compare(
        self,
        study_a: str,
        study_b: str,
        metadata_a: dict[str, str],
        metadata_b: dict[str, str],
    ) -> ImagingComparison:
        left = self.analyze(study_a, metadata_a)
        right = self.analyze(study_b, metadata_b)
        changed: list[str] = []
        unchanged: list[str] = []
        for key in sorted(set(metadata_a) | set(metadata_b)):
            if metadata_a.get(key, "") == metadata_b.get(key, ""):
                unchanged.append(f"{key} unchanged")
            else:
                changed.append(f"{key} differs between studies")
        return ImagingComparison(
            study_a=study_a,
            study_b=study_b,
            changed=tuple(changed),
            unchanged=tuple(unchanged),
            uncertain=(
                "Metadata compared only; no pixels were read.",
                f"backend_a={left.backend}; backend_b={right.backend}",
            ),
            human_review_required=True,
            disclaimer=_DISCLAIMER,
            backend=left.backend,
        )


def build_image_analyzer(settings: Settings | None = None) -> MedicalImageAnalyzer:
    return MonaiIsolatedAnalyzer(settings or get_settings())
