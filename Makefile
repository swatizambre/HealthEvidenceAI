.PHONY: setup sync seed demo test coverage lint typecheck frontend launch launch-check eval-rag eval-agent mcp-server pilot-up pilot-oidc-up pilot-gate demo-up demo-gate quality-gate e2e-smoke

setup: sync
	uv run python -m app.cli.seed

sync:
	uv sync
	cd frontend && npm ci

seed:
	uv run python -m app.cli.seed

demo:
	uv run python -m app.cli.demo

test:
	uv run pytest -q

coverage:
	uv run coverage run -m pytest
	uv run coverage report

lint:
	uv run ruff check .

typecheck:
	uv run mypy .

frontend:
	cd frontend && npm ci

eval-rag:
	uv run python -m evaluation.run_rag

eval-agent:
	uv run python -m evaluation.run_agent

mcp-server:
	uv run python -m app.mcp.server

launch:
	@echo "API:  uv run python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8010"
	@echo "UI:   cd frontend && npm run dev -- --host 127.0.0.1 --port 5173"
	@echo "Docs: docs/LAUNCH.md"
	uv run python -m app.cli.demo

launch-check:
	uv run pytest -q
	cd frontend && npm run build
	@echo "Launch gate OK — see docs/LAUNCH.md"

PILOT_DATABASE_URL ?= postgresql+psycopg://healthevidence:healthevidence@127.0.0.1:5432/healthevidence
HE_API_BASE ?= http://127.0.0.1:8000
HE_WEB_BASE ?= http://127.0.0.1:3000

pilot-up:
	docker compose -f docker-compose.yml -f docker-compose.pilot.yml up --build -d

pilot-oidc-up:
	docker compose -f docker-compose.yml -f docker-compose.pilot.yml -f docker-compose.oidc.yml up --build -d

pilot-gate:
	uv run pytest -q
	PILOT_POSTGRES_TEST=1 DATABASE_URL=$(PILOT_DATABASE_URL) uv run pytest tests/pilot -v
	@echo "Pilot gate OK — see docs/PILOT_ROADMAP.md and docs/OIDC_PILOT.md"

demo-up:
	docker compose -f docker-compose.yml -f docker-compose.pilot.yml -f docker-compose.demo.yml up --build -d

demo-gate:
	uv run pytest -q
	uv run pytest tests/integration/test_ten_personas.py -q --tb=line
	HE_API_BASE=$(HE_API_BASE) HE_WEB_BASE=$(HE_WEB_BASE) uv run python scripts/_smoke_web_api.py
	HE_API_BASE=$(HE_API_BASE) uv run python scripts/api_contract_smoke.py
	@echo "Demo gate OK — see docs/LAUNCH.md"

e2e-smoke:
	cd frontend && npm ci && npx playwright install chromium && npm run e2e:smoke
	@echo "E2E smoke OK"

quality-gate:
	uv run ruff check .
	uv run mypy .
	uv run coverage run -m pytest -q
	uv run coverage report --fail-under=80
	cd frontend && npm run build
	@echo "Quality gate OK (start API then make demo-gate for live API)"
