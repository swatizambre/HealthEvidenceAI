"""Disorder labels and clinical condition filtering for lifelong history."""

from app.services.disorders import (
    disorders_for_condition,
    is_clinical_condition,
    is_clinical_criterion_text,
    is_clinical_procedure,
)


def test_drops_social_findings_and_situations() -> None:
    assert not is_clinical_condition("Housing unsatisfactory (finding)")
    assert not is_clinical_condition("Homeless (finding)")
    assert not is_clinical_condition("Full-time employment (finding)")
    assert not is_clinical_condition("Only received primary school education (finding)")
    assert not is_clinical_condition("Social isolation (finding)")
    assert not is_clinical_condition("Stress (finding)")
    assert not is_clinical_condition("Medication review due (situation)")


def test_criterion_text_filters_social_noise() -> None:
    assert not is_clinical_criterion_text(
        "The record clearly documents Full-time employment (finding)."
    )
    assert not is_clinical_criterion_text("Medication review due (situation) is documented.")
    assert is_clinical_criterion_text("Acute viral pharyngitis (disorder) is documented.")
    assert is_clinical_criterion_text("A Cholesterol [Mass/volume] in Serum or Plasma result is present.")


def test_keeps_clinical_disorders() -> None:
    assert is_clinical_condition("Viral sinusitis (disorder)")
    assert is_clinical_condition("Chronic intractable migraine without aura (disorder)")
    assert is_clinical_condition("Dependent drug abuse (disorder)")
    assert is_clinical_condition("Overdose (disorder)")
    assert is_clinical_condition("Impacted molars (disorder)")
    assert disorders_for_condition("Viral sinusitis (disorder)") == ["Infection"]
    assert disorders_for_condition("Overdose (disorder)") == ["Substance use"]
    assert disorders_for_condition("Chronic intractable migraine without aura (disorder)") == [
        "Neurological disorder"
    ]


def test_skips_admin_procedures() -> None:
    assert not is_clinical_procedure("Medication reconciliation (procedure)")
    assert not is_clinical_procedure("Medication review due")
    assert is_clinical_procedure("Appendectomy")


SOCIAL_FINDINGS = (
    "Received higher education (finding)",
    "Received higher education",
    "Full-time employment (finding)",
    "Full-time employment",
    "Stress (finding)",
    "Stress",
    "Social isolation (finding)",
    "Has a criminal record (finding)",
    "Has a criminal record",
    "Not in labor force (finding)",
    "Reports of violence in the environment (finding)",
)


def test_synthea_social_findings_are_never_clinical_conditions() -> None:
    from app.services.disorders import clinical_conditions, is_social_finding

    for item in SOCIAL_FINDINGS:
        assert not is_clinical_condition(item), item
    assert is_social_finding("Received higher education (finding)")
    assert not is_social_finding("Essential hypertension (disorder)")
    kept = clinical_conditions([*SOCIAL_FINDINGS, "Essential hypertension (disorder)", "diabetes"])
    assert kept == ["Essential hypertension (disorder)", "diabetes"]


def test_social_findings_hidden_from_patients_list_chart_and_problem_list(monkeypatch) -> None:
    from app.models import Patient
    from sqlalchemy import select
    from tests.conftest import make_client

    with make_client(monkeypatch) as client:
        session = client.app.state.session_factory()
        try:
            patient = session.scalar(select(Patient).where(Patient.patient_code == "PAT-000003"))
            assert patient is not None
            patient.conditions = [*SOCIAL_FINDINGS, "Essential hypertension (disorder)"]
            session.commit()
        finally:
            session.close()

        listing = client.get("/api/v1/patients", params={"limit": 5})
        assert listing.status_code == 200, listing.text
        row = next(p for p in listing.json()["patients"] if p["patient_id"] == "PAT-000003")
        assert row["conditions"] == ["Essential hypertension (disorder)"]

        detail = client.get("/api/v1/patients/PAT-000003")
        assert detail.status_code == 200, detail.text
        assert detail.json()["conditions"] == ["Essential hypertension (disorder)"]

        lifelong = client.get("/api/v1/patients/PAT-000003/lifelong")
        assert lifelong.status_code == 200, lifelong.text
        problem_titles = " ".join(
            event["title"].lower()
            for event in lifelong.json()["events"]
            if event["event_id"].startswith("cond-")
        )
        assert "hypertension" in problem_titles
        for item in ("higher education", "full-time employment", "social isolation", "criminal record",
                     "stress"):
            assert item not in problem_titles
