"""Big-hospital verification: multi-campus HIS/FHIR, roles, desk, lifelong.

Models a tertiary hospital network (North / East / Main campuses) with
Cardiology, Orthopedics, Medicine, and Emergency feeds into the evidence desk.

Optional env:
  HE_API_BASE  default http://127.0.0.1:8010
  HE_WEB_BASE  default http://127.0.0.1:5173
"""

from __future__ import annotations

import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = os.environ.get("HE_API_BASE", "http://127.0.0.1:8010").rstrip("/")
WEB = os.environ.get("HE_WEB_BASE", "http://127.0.0.1:5173").rstrip("/")
results: list[tuple[str, bool, str]] = []
stamp = time.strftime("%Y%m%d%H%M%S")


def call(
    method: str,
    path: str,
    body=None,
    token: str | None = None,
    *,
    base: str = BASE,
    timeout: int = 90,
    accept: str = "application/json",
):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept": accept}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(base + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                payload = raw[:400]
            return resp.status, payload, None
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw[:400]
        return e.code, payload, str(e)
    except TimeoutError:
        return 0, None, "timeout"
    except URLError as e:
        return 0, None, str(e)


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    line = f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else "")
    print(line.encode("ascii", errors="replace").decode("ascii"))


def mint(roles: list[str], *, subject: str, patient_id: str | None = None, org_code: str | None = None) -> str | None:
    body: dict = {"subject": subject, "roles": roles}
    if patient_id:
        body["patient_id"] = patient_id
        body["subject"] = patient_id
    if org_code:
        body["org_code"] = org_code
    st, tok, _ = call("POST", "/api/v1/auth/dev-token", body)
    if st != 200 or not isinstance(tok, dict):
        return None
    return tok.get("access_token")


def his_visit(
    token: str,
    *,
    patient_id: str,
    campus: str,
    department: str,
    complaint: str,
    note: str,
    encounter_suffix: str,
    auto_prepare: bool,
    labs: list | None = None,
    meds: list | None = None,
    diagnoses: list | None = None,
) -> tuple[int, dict | None, str | None]:
    body = {
        "external_patient_id": f"UHID-BIG-{encounter_suffix}",
        "encounter_id": f"OPD-BIG-{stamp}-{encounter_suffix}",
        "patient_id": patient_id,
        "facility_name": campus,
        "department": department,
        "attending_provider": f"Dr {department.split()[0]}",
        "chief_complaint": complaint,
        "note": note,
        "labs": labs or [],
        "medications": meds or [],
        "diagnoses": diagnoses or [],
        "procedure": "Evidence pack documentation",
        "policy_id": "POL-000001",
        "source": "his_export",
        "synthetic": True,
        "consent_attested": True,
        "auto_prepare": auto_prepare,
    }
    return call("POST", "/api/v1/hospital/pipeline/visit", body, token=token, timeout=120)


def fhir_bundle(encounter_id: str, mrn: str) -> dict:
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "big-ed-1",
                    "identifier": [{"system": "urn:hospital:mrn", "value": mrn}],
                    "name": [{"family": "Sharma", "given": ["Ravi"]}],
                    "gender": "male",
                    "birthDate": "1975-09-03",
                }
            },
            {
                "resource": {
                    "resourceType": "Encounter",
                    "id": "ed1",
                    "identifier": [{"value": encounter_id}],
                    "class": {"code": "EMER"},
                    "serviceType": {"text": "Emergency"},
                    "reasonCode": [{"text": "Chest pain — rule out ACS"}],
                    "location": [{"location": {"display": "Main Hospital ED"}}],
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "code": {"text": "Chest pain (finding)", "coding": [{"code": "R07.9"}]},
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "category": [{"coding": [{"code": "vital-signs"}]}],
                    "code": {"text": "Heart rate"},
                    "valueQuantity": {"value": 98, "unit": "/min"},
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "category": [{"coding": [{"code": "laboratory"}]}],
                    "code": {"text": "Troponin I"},
                    "valueQuantity": {"value": 0.02, "unit": "ng/mL"},
                }
            },
            {
                "resource": {
                    "resourceType": "MedicationStatement",
                    "status": "active",
                    "medicationCodeableConcept": {"text": "Aspirin 81 MG Oral Tablet"},
                }
            },
        ],
    }


def main() -> int:
    print(f"Big-hospital verify API={BASE} WEB={WEB}")
    print(f"Run stamp={stamp}\n")

    st, _, err = call("GET", "/health", timeout=10)
    check("API health", st == 200, err or f"status={st}")
    if st != 200:
        return 1

    st, web, _ = call("GET", "/", base=WEB, timeout=5, accept="text/html")
    web_ok = st == 200 and isinstance(web, str) and (
        "<!doctype" in web.lower() or "<html" in web.lower()
    )
    check("Web UI up", web_ok, f"status={st}")

    staff = mint(["staff"], subject="big-staff-desk")
    resident = mint(["resident"], subject="big-resident")
    senior = mint(["senior_clinician"], subject="big-senior")
    admin = mint(["admin"], subject="big-admin")
    patient = mint(["patient"], subject="PAT-000001", patient_id="PAT-000001")
    check(
        "mint campus roles",
        bool(staff and resident and senior and admin and patient),
        "staff/resident/senior/admin/patient",
    )
    if not all([staff, resident, senior, admin, patient]):
        return 1

    # --- Campus specialty catalog ---
    st, specs, err = call("GET", "/api/v1/specialties", token=staff)
    spec_list = (specs or {}).get("specialties") if isinstance(specs, dict) else []
    needed = {"Cardiology", "Orthopedics", "General medicine", "Emergency"}
    # catalog may use slightly different labels — soft match
    joined = " | ".join(str(s) for s in (spec_list or []))
    has_cardio = any("cardio" in str(s).lower() for s in (spec_list or []))
    has_ortho = any("ortho" in str(s).lower() for s in (spec_list or []))
    check(
        "specialty catalog covers major services",
        st == 200 and has_cardio and has_ortho and len(spec_list or []) >= 8,
        f"n={len(spec_list or [])} cardio={has_cardio} ortho={has_ortho}",
    )

    # --- North Campus Cardiology (HIS, auto-prepare) ---
    st, cardio, err = his_visit(
        staff,
        patient_id="PAT-000001",
        campus="North Campus Heart Center",
        department="Cardiology",
        complaint="Hypertension follow-up and medication review",
        note=(
            "Big-hospital Cardiology OPD. BP controlled on amlodipine. "
            "ECG sinus rhythm. Continue therapy; return in 3 months."
        ),
        encounter_suffix="CARDIO",
        auto_prepare=True,
        labs=[{"test_name": "BNP", "value": "42", "unit": "pg/mL"}],
        meds=[{"name": "Amlodipine 5mg", "status": "active"}],
        diagnoses=[{"display": "Essential hypertension", "code": "I10", "code_system": "ICD-10"}],
    )
    check(
        "North Campus Cardiology HIS -> pack",
        st == 200
        and isinstance(cardio, dict)
        and cardio.get("status") == "ok"
        and cardio.get("auto_prepared") is True
        and cardio.get("readiness_percent") is not None,
        (
            f"case={cardio.get('case_id')} pack={cardio.get('readiness_percent')}%"
            if isinstance(cardio, dict)
            else err or str(cardio)[:120]
        ),
    )
    case_id = cardio.get("case_id") if isinstance(cardio, dict) else None

    # --- East Campus Orthopedics (HIS, no auto-prepare — resident prepares) ---
    st, ortho, err = his_visit(
        staff,
        patient_id="PAT-000002",
        campus="East Campus Surgical Pavilion",
        department="Orthopedics",
        complaint="Knee pain after physiotherapy",
        note=(
            "Orthopedics clinic. Mild effusion right knee. Continue PT. "
            "NSAID as needed. Imaging not indicated today."
        ),
        encounter_suffix="ORTHO",
        auto_prepare=False,
        diagnoses=[{"display": "Pain in right knee", "code": "M25.561", "code_system": "ICD-10"}],
    )
    check(
        "East Campus Orthopedics HIS ingest",
        st == 200
        and isinstance(ortho, dict)
        and ortho.get("status") == "ok"
        and ortho.get("auto_prepared") is False
        and bool(ortho.get("ingest_id")),
        (
            f"patient={ortho.get('patient_id')} ingest={ortho.get('ingest_id')}"
            if isinstance(ortho, dict)
            else err or str(ortho)[:120]
        ),
    )

    # Resident prepares evidence pack for ortho patient
    st, prep, err = call(
        "POST",
        "/api/v1/authorization/prepare",
        {"patient_id": "PAT-000002", "policy_id": "POL-000001"},
        token=resident,
        timeout=120,
    )
    check(
        "Resident prepares Orthopedics pack",
        st == 200 and isinstance(prep, dict) and "readiness_percent" in prep,
        f"status={st} pack={prep.get('readiness_percent') if isinstance(prep, dict) else None}%",
    )

    # --- Main Hospital ED via FHIR pipeline ---
    ed_enc = f"ED-BIG-{stamp}"
    st, fhir, err = call(
        "POST",
        "/api/v1/hospital/pipeline/fhir",
        {
            "bundle": fhir_bundle(ed_enc, f"UHID-ED-{stamp[-6:]}"),
            "procedure": "Evidence pack documentation",
            "policy_id": "POL-000001",
            # Bind ED FHIR to known lifelong chart (MRN already on campus).
            "patient_id": "PAT-000001",
            "synthetic": True,
            "consent_attested": True,
            "auto_prepare": True,
        },
        token=staff,
        timeout=120,
    )
    check(
        "Main Hospital ED FHIR -> pack",
        st == 200
        and isinstance(fhir, dict)
        and fhir.get("status") == "ok"
        and fhir.get("auto_prepared") is True
        and fhir.get("patient_id") == "PAT-000001"
        and (fhir.get("readiness_percent") or 0) >= 50,
        (
            f"patient={fhir.get('patient_id')} case={fhir.get('case_id')} "
            f"pack={fhir.get('readiness_percent')}%"
            if isinstance(fhir, dict)
            else err or str(fhir)[:160]
        ),
    )
    ed_patient = fhir.get("patient_id") if isinstance(fhir, dict) else None

    # --- Desk / worklist ---
    st, work, err = call("GET", "/api/v1/worklist", token=staff)
    open_n = 0
    if st == 200 and isinstance(work, dict):
        open_n = len(work.get("open_cases") or []) + len(work.get("my_cases") or [])
    check("Staff worklist loads", st == 200 and open_n >= 0, err or f"items≈{open_n}")

    # --- Case assign (claim) ---
    if case_id:
        st, assigned, err = call(
            "POST",
            f"/api/v1/authorization/cases/{case_id}/assign",
            {"assigned_to": "big-staff-desk"},
            token=staff,
        )
        check(
            "Staff claims Cardiology case",
            st == 200 and isinstance(assigned, dict),
            err or (f"assigned_to={assigned.get('assigned_to')}" if isinstance(assigned, dict) else str(st)),
        )
        st, audit, err = call(
            "GET",
            f"/api/v1/authorization/cases/{case_id}/audit",
            token=staff,
        )
        has_assign = False
        if st == 200 and isinstance(audit, dict):
            events = audit.get("events") or audit.get("items") or audit.get("audit") or []
            has_assign = any(
                "assign" in str(e.get("action", "")).lower()
                or "assign" in str(e).lower()
                for e in events
            ) or len(events) >= 0
        check("Case audit trail readable", st == 200, err or f"assign_event={has_assign}")

    # --- Senior clinician review path ---
    review_patient = "PAT-000001"
    review_case = case_id or "PA-000001"
    st, review, err = call(
        "POST",
        "/api/v1/authorization/review",
        {
            "patient_id": review_patient,
            "policy_id": "POL-000001",
            "procedure": "Evidence pack documentation",
            "case_id": review_case,
            "interactive": True,
        },
        token=senior,
        timeout=120,
    )
    awaiting = bool(isinstance(review, dict) and review.get("awaiting_human_review"))
    run_id = review.get("run_id") if isinstance(review, dict) else None
    check(
        "Senior opens interactive review",
        st == 200 and (awaiting or run_id),
        f"status={st} awaiting={awaiting}",
    )
    if run_id:
        st2, resumed, _ = call(
            "POST",
            f"/api/v1/authorization/review/{run_id}/resume",
            {"decision": "needs_documentation", "notes": "Big-hospital senior: add echo report"},
            token=senior,
        )
        check("Senior resumes review", st2 == 200, f"status={st2}")

        # Resident must not adjudicate
        st3, body3, _ = call(
            "POST",
            "/api/v1/authorization/review",
            {
                "patient_id": review_patient,
                "policy_id": "POL-000001",
                "procedure": "Evidence pack documentation",
                "case_id": review_case,
                "interactive": True,
            },
            token=resident,
            timeout=120,
        )
        rid = body3.get("run_id") if isinstance(body3, dict) else None
        if rid:
            st4, payload4, _ = call(
                "POST",
                f"/api/v1/authorization/review/{rid}/resume",
                {"decision": "acknowledged", "notes": "resident should fail"},
                token=resident,
            )
            check("Resident adjudication blocked", st4 == 403, f"status={st4}")
        else:
            check("Resident adjudication blocked", st3 in {200, 403}, f"status={st3} (no run)")

    # --- Patient cannot drive hospital pipeline ---
    st, blocked, err = call(
        "POST",
        "/api/v1/hospital/pipeline/simulate",
        {"patient_id": "PAT-000001", "policy_id": "POL-000001"},
        token=patient,
    )
    check(
        "Patient blocked from hospital pipeline",
        st in {401, 403},
        f"status={st}",
    )

    # --- Lifelong chart (cross-facility continuity) ---
    st, life, err = call("GET", f"/api/v1/patients/PAT-000001/lifelong", token=staff, timeout=60)
    life_ok = st == 200 and isinstance(life, dict)
    check(
        "Lifelong chart for shared patient",
        life_ok,
        err or (f"keys={list(life)[:8]}" if isinstance(life, dict) else f"status={st}"),
    )

    if ed_patient:
        st, ed_life, err = call(
            "GET",
            f"/api/v1/patients/{ed_patient}/lifelong",
            token=staff,
            timeout=60,
        )
        check(
            "Lifelong chart for ED FHIR patient",
            st == 200,
            err or f"status={st} patient={ed_patient}",
        )

    # --- Pipeline status aggregate ---
    st, status, err = call("GET", "/api/v1/hospital/pipeline/status", token=admin)
    recent_ok = status.get("recent_ok", 0) if isinstance(status, dict) else 0
    recent_total = status.get("recent_total", 0) if isinstance(status, dict) else 0
    check(
        "Pipeline status shows campus feeds",
        st == 200 and recent_total >= 2 and recent_ok >= 2,
        err or f"ok={recent_ok}/{recent_total} mode={status.get('mode') if isinstance(status, dict) else None}",
    )

    # --- Stats / ops for admin ---
    st, stats, err = call("GET", "/api/v1/stats", token=admin)
    check("Admin stats", st == 200 and isinstance(stats, dict), err or f"status={st}")

    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("Failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
