"""``health-evidence`` command."""

from __future__ import annotations

import argparse

from app.cli.demo import run_demo
from app.services.seed import seed_command


def main() -> None:
    parser = argparse.ArgumentParser(prog="health-evidence")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("seed", help="Reset and load the synthetic dataset")
    subparsers.add_parser("run-demo", help="Run the deterministic senior agent evidence review")
    args = parser.parse_args()
    if args.command == "seed":
        raise SystemExit(seed_command())
    raise SystemExit(run_demo())


if __name__ == "__main__":
    main()
