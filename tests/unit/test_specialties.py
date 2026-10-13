"""Hospital specialty catalog coverage."""

from app.services.specialties import (
    SPECIALTY_CATALOG,
    clinical_specialty_catalog,
    normalize_specialty,
    seed_specialty_for_patient,
)


def test_catalog_covers_high_volume_pa_specialties() -> None:
    required = {
        "Cardiology",
        "Orthopedics",
        "Oncology",
        "Obstetrics & gynecology",
        "Neurology",
        "Urology",
        "Surgery",
        "Radiology",
    }
    assert required.issubset(set(SPECIALTY_CATALOG))
    assert len(SPECIALTY_CATALOG) >= 35


def test_aliases_map_common_hospital_labels() -> None:
    assert normalize_specialty("gynaecology") == "Obstetrics & gynecology"
    assert normalize_specialty("cardio") == "Cardiology"
    assert normalize_specialty("ortho") == "Orthopedics"
    assert normalize_specialty("cardiac surgery") == "Cardiac surgery"
    assert normalize_specialty("urology") == "Urology"
    assert normalize_specialty("rheumatology") == "Rheumatology"
    assert normalize_specialty("hematology") == "Hematology"
    assert normalize_specialty("ENT") == "ENT"


def test_seed_rotates_clinical_specialties() -> None:
    clinical = clinical_specialty_catalog()
    assert "Laboratory" not in clinical
    assert seed_specialty_for_patient(1) in clinical
    assert seed_specialty_for_patient(2) in clinical
    assert seed_specialty_for_patient(1) != seed_specialty_for_patient(2)
