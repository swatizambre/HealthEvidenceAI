"""Load the synthetic dataset: ``python -m app.cli.seed``."""

from __future__ import annotations

from app.services.seed import seed_command


def main() -> None:
    raise SystemExit(seed_command())


if __name__ == "__main__":
    main()
