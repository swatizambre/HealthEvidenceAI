"""Discover OIDC JWKS URL from an issuer (pilot IdP wiring).

Usage:
  uv run python -m app.cli.oidc_discover https://idp.example/realms/healthevidence
"""

from __future__ import annotations

import argparse
import json
import sys

from app.auth.oidc import discover_oidc_endpoints
from app.core.exceptions import AppError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="oidc-discover",
        description="Resolve OIDC_ISSUER → OIDC_JWKS_URL via OpenID discovery",
    )
    parser.add_argument("issuer", help="Issuer URL (e.g. http://localhost:8080/realms/healthevidence)")
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    args = parser.parse_args(argv)
    try:
        endpoints = discover_oidc_endpoints(args.issuer)
    except (AppError, OSError, ValueError) as exc:
        print(f"OIDC discovery failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(endpoints, indent=2))
        return 0
    print("# Paste into .env.pilot / shared pilot secrets:")
    print("AUTH_MODE=oidc")
    print(f"OIDC_ISSUER={endpoints['issuer']}")
    print(f"OIDC_JWKS_URL={endpoints['jwks_url']}")
    print("OIDC_AUDIENCE=healthevidence-api")
    if endpoints.get("token_endpoint"):
        print(f"# token_endpoint={endpoints['token_endpoint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
