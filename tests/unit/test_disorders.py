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
