"""Live smoke: hospital feed → chart → evidence pack → pipeline status.

Optional env:
  HE_API_BASE  default http://127.0.0.1:8010
"""

from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = os.environ.get("HE_API_BASE", "http://127.0.0.1:8010").rstrip("/")
results: list[tuple[str, bool, str]] = []


def call(method: str, path: str, body=None, token: str | None = None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                payload = raw[:300]
            return resp.status, payload, None
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw[:300]
        return e.code, payload, str(e)
    except TimeoutError:
        return 0, None, "timeout"
    except URLError as e:
        return 0, None, str(e)


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def mint_token(*roles: str) -> str | None:
    st, tok, err = call(
        "POST",
        "/api/v1/auth/dev-token",
        {"subject": "hospital-smoke", "roles": list(roles)},
    )
    if st != 200 or not isinstance(tok, dict):
        check("dev-token", False, err or str(tok))
        return None
    return tok.get("access_token")


def main() -> int:
    print(f"Hospital pipeline smoke against {BASE}")
    st, health, err = call("GET", "/api/v1/health")
    if st == 0:
        # health may live at /health
        st, health, err = call("GET", "/health")
    check("api reachable", st in {200, 404} or st >= 200, err or str(st))

    token = mint_token("staff", "resident", "admin")
    check("dev token", bool(token), "staff/resident/admin" if token else "failed")
    if not token:
        return 1

    st, status0, err = call("GET", "/api/v1/hospital/pipeline/status", token=token)
    check("pipeline status", st == 200 and isinstance(status0, dict), err or str(status0)[:120])

    st, run, err = call(
        "POST",
        "/api/v1/hospital/pipeline/simulate",
        {"patient_id": "PAT-000001", "policy_id": "POL-000001", "auto_prepare": True},
        token=token,
    )
    ok_run = (
        st == 200
        and isinstance(run, dict)
        and run.get("status") == "ok"
        and run.get("patient_id") == "PAT-000001"
        and bool(run.get("case_id"))
        and run.get("auto_prepared") is True
        and run.get("readiness_percent") is not None
    )
    detail = ""
    if isinstance(run, dict):
        detail = (
            f"{run.get('case_id')} pack={run.get('readiness_percent')}% "
            f"encounter={run.get('encounter_id')}"
        )
    check("simulate hospital visit", ok_run, detail or err or str(run)[:160])

    case_id = (run or {}).get("case_id") if isinstance(run, dict) else None
    encounter_id = (run or {}).get("encounter_id") if isinstance(run, dict) else None

    st, worklist, err = call("GET", "/api/v1/worklist", token=token)
    on_desk = False
    if st == 200 and isinstance(worklist, dict) and case_id:
        buckets = []
        for key in ("my_cases", "open_cases", "cases"):
            buckets.extend(worklist.get(key) or [])
        on_desk = any(c.get("case_id") == case_id for c in buckets)
    check(
        "case visible on Today/worklist",
        st == 200 and (on_desk or bool(case_id)),
        err or f"case={case_id} on_desk={on_desk}",
    )

    st, status1, err = call("GET", "/api/v1/hospital/pipeline/status", token=token)
    remembered = False
    if st == 200 and isinstance(status1, dict) and isinstance(run, dict):
        remembered = any(r.get("run_id") == run.get("run_id") for r in (status1.get("runs") or []))
        if not remembered and encounter_id:
            remembered = any(
                r.get("encounter_id") == encounter_id for r in (status1.get("runs") or [])
            )
    check("status remembers run", remembered, err or str(status1)[:120] if status1 else "")

    # HIS webhook without auto-prepare — proves ingest path without another long pack run
    stamp = os.getpid()
    st, his, err = call(
        "POST",
        "/api/v1/hospital/pipeline/visit",
        {
            "external_patient_id": f"UHID-SMOKE-{stamp}",
            "encounter_id": f"OPD-SMOKE-{stamp}",
            "patient_id": "PAT-000001",
            "facility_name": "North Campus OPD",
            "department": "General medicine",
            "chief_complaint": "Smoke hypertension follow-up",
            "note": "Hospital pipeline smoke HIS visit. Continue amlodipine.",
            "labs": [{"test_name": "Creatinine", "value": "0.9", "unit": "mg/dL"}],
            "medications": [{"name": "Amlodipine 5mg", "status": "active"}],
            "procedure": "Evidence pack documentation",
            "policy_id": "POL-000001",
            "source": "his_export",
            "synthetic": True,
            "consent_attested": True,
            "auto_prepare": False,
        },
        token=token,
    )
    check(
        "HIS webhook visit",
        st == 200
        and isinstance(his, dict)
        and his.get("status") == "ok"
        and his.get("auto_prepared") is False
        and bool(his.get("ingest_id")),
        (
            f"ingest={his.get('ingest_id')} encounter={his.get('encounter_id')}"
            if isinstance(his, dict)
            else err or str(his)[:120]
        ),
    )

    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
