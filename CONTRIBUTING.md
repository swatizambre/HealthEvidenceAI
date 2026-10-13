# Contributing

```bash
uv sync
uv run pytest -q
uv run ruff check .
uv run mypy .
cd frontend && npm ci
```

- Keep criterion status deterministic and cited.
- Do not add an autonomous approve, deny, diagnose, or prescribe path.
- Do not commit `.env`, credentials, or generated database files.
- Prefer `uv` for the Python environment and `npm ci` for the UI.
