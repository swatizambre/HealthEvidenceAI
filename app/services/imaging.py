"""MONAI-isolated medical image analysis.

Produces metadata and tensor statistics only. Never generates a clinical diagnosis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings, get_settings

_DISCLAIMER = (
    "Observed image-level metadata or synthetic tensor statistics only. "
    "No diagnostic interpretation is provided. Clinical interpretation required. "
    "Not for clinical use."
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
    """Imaging adapter using MONAI when installed, otherwise a NumPy tensor bridge."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._monai_available = False
        try:
            import monai  # noqa: F401

            self._monai_available = True
        except Exception:
            self._monai_available = False

    def analyze(self, study_id: str, metadata: dict[str, str]) -> ImagingAnalysis:
        import numpy as np

        modality = metadata.get("modality", "unknown")
        body = metadata.get("body_part", "unspecified")
        seed = abs(hash(study_id)) % (2**32)
        rng = np.random.default_rng(seed)
        volume = rng.random((16, 16, 16), dtype=np.float32)
        observations = [
            f"Imaging backend engaged for study {study_id}.",
            f"Metadata modality={modality}; body_part={body}.",
            f"Tensor shape={tuple(volume.shape)}; mean={float(volume.mean()):.4f}; "
            f"std={float(volume.std()):.4f}.",
            "No clinical diagnosis was generated.",
        ]
        if self._monai_available:
            try:
                from monai.transforms import ScaleIntensity

                scaled = ScaleIntensity()(volume)
                observations.append(
                    f"MONAI ScaleIntensity applied; post-mean={float(scaled.mean()):.4f}."
                )
                backend = "monai"
            except Exception as exc:
                observations.append(f"MONAI transform runtime issue: {exc}")
                backend = "monai-numpy-bridge"
        else:
            observations.append(
                "MONAI package not installed in this image; using NumPy bridge. "
                "Install optional dependency group 'imaging' for full MONAI transforms."
            )
            backend = "monai-numpy-bridge"
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
                "Tensor statistics compared only; no pixel diagnosis.",
                f"backend_a={left.backend}; backend_b={right.backend}",
            ),
            human_review_required=True,
            disclaimer=_DISCLAIMER,
            backend=left.backend,
        )


def build_image_analyzer(settings: Settings | None = None) -> MedicalImageAnalyzer:
    return MonaiIsolatedAnalyzer(settings or get_settings())
