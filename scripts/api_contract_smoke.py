"""OpenAPI-driven API contract smoke (industry practice: schema → live probe).

Walks GET operations from /openapi.json with role-appropriate tokens.
Also hits critical POST happy paths. Exit non-zero on any failure.

Env:
  HE_API_BASE  default http://127.0.0.1:8010
"""

from __future__ import annotations

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = os.environ.get("HE_API_BASE", "http://127.0.0.1:8010").rstrip("/")
SAMPLE_PATH = {
    "patient_id": "PAT-000001",
    "policy_id": "POL-000001",
    "document_id": "DOC-000001",
    "run_id": "00000000-0000-0000-0000-000000000000",
}

results: list[tuple[str, bool, str]] = []


def call(method: str, path: str, body=None, token=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                payload = raw[:200]
            return resp.status, payload, None
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw[:200]
        return e.code, payload, str(e)
    except URLError as e:
        return 0, None, str(e)


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def mint(*roles: str, **extra) -> str | None:
    body = {"subject": "contract-" + "-".join(roles), "roles": list(roles), **extra}
    st, tok, _ = call("POST", "/api/v1/auth/dev-token", body)
    if st != 200 or not isinstance(tok, dict):
        return None
    return tok.get("access_token")


def concrete_path(template: str) -> str | None:
    """Fill {param} placeholders with known sample ids; skip unknown templates."""
    params = re.findall(r"\{([^}]+)\}", template)
    path = template
    for name in params:
        key = name
        if name not in SAMPLE_PATH:
            # common aliases
            if "patient" in name:
                key = "patient_id"
            elif "policy" in name:
                key = "policy_id"
            elif "document" in name:
                key = "document_id"
            elif "run" in name:
                key = "run_id"
            else:
                return None
        path = path.replace("{" + name + "}", SAMPLE_PATH[key])
    return path


def main() -> int:
    print(f"API contract smoke -> {BASE}")
    st, health, err = call("GET", "/health")
    if st != 200:
        print(f"API not reachable: status={st} err={err}")
        return 2

    st, openapi, err = call("GET", "/openapi.json")
    check("GET /openapi.json", st == 200 and isinstance(openapi, dict), f"status={st}")
    if not isinstance(openapi, dict):
        return 1

    paths = openapi.get("paths") or {}
    check("openapi paths present", len(paths) >= 10, f"count={len(paths)}")

    staff = mint("staff", org_code="ORG-000001")
    senior = mint("senior_clinician", org_code="ORG-000001")
    admin = mint("admin")
    patient = mint("patient", patient_id="PAT-000001")
    check("mint staff/senior/admin/patient", bool(staff and senior and admin and patient))

    # Prefer staff for GETs; admin for audit; patient for self chart.
    get_token = staff
    admin_paths = ("/api/v1/audit", "/api/v1/security/break-glass")

    for template, ops in sorted(paths.items()):
        if "get" not in ops:
            continue
        concrete = concrete_path(template)
        if concrete is None:
            check(f"GET {template}", True, "skipped — unresolved path params")
            continue
        token = admin if any(concrete.startswith(p) for p in admin_paths) else get_token
        # patient-only self chart already covered separately
        st, payload, _ = call("GET", concrete, token=token)
        # 404 on unknown sample document is acceptable; 401/403/5xx are not for staff GETs
        ok = st in {200, 404} or (
            st == 403 and "audit" in concrete
        )
        # /ready and /health may be without /api
        if concrete in {"/health", "/ready"}:
            ok = st == 200
        detail = f"status={st}"
        if isinstance(payload, dict) and "error_code" in payload:
            detail += f" code={payload.get('error_code')}"
        check(f"GET {concrete}", ok, detail)

    # Critical POST happy paths
    if staff:
        st, body, _ = call(
            "POST",
            "/api/v1/authorization/prepare",
            {"patient_id": "PAT-000001", "policy_id": "POL-000001"},
            token=staff,
        )
        check(
            "POST /authorization/prepare",
            st == 200 and isinstance(body, dict) and "readiness_percent" in body,
            f"status={st}",
        )
        st, body, _ = call(
            "POST",
            "/api/v1/evidence/search",
            {"query": "medication reconciliation documentation"},
            token=staff,
        )
        check("POST /evidence/search", st == 200, f"status={st}")

    if patient:
        st, _, _ = call("GET", "/api/v1/patients/PAT-000001/lifelong", token=patient)
        check("GET lifelong as patient", st == 200, f"status={st}")
        st, body, _ = call("GET", "/api/v1/patients/PAT-000002", token=patient)
        code = body.get("error_code") if isinstance(body, dict) else None
        check("patient cross-chart denied", st == 403, f"status={st} code={code}")

    if senior:
        st, body, _ = call(
            "POST",
            "/api/v1/authorization/review",
            {
                "patient_id": "PAT-000002",
                "policy_id": "POL-000001",
                "procedure": "Evidence packet",
                "case_id": "PA-000002",
                "interactive": True,
            },
            token=senior,
        )
        check(
            "POST /authorization/review interactive",
            st == 200 and isinstance(body, dict),
            f"status={st}",
        )

    st, _, _ = call("GET", "/ready")
    check("GET /ready", st == 200, f"status={st}")

    failed = [r for r in results if not r[1]]
    print(f"\n=== SUMMARY: {len(results) - len(failed)}/{len(results)} passed ===")
    for name, _ok, detail in failed:
        print(f"  FAIL: {name} — {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
