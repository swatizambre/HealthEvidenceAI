# Pilot quality gate: unit/integration + PostgreSQL bootstrap + ten personas on Postgres.
# Requires Postgres listening (e.g. docker compose up -d postgres).

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$DbUrl = if ($env:DATABASE_URL) { $env:DATABASE_URL } else {
    "postgresql+psycopg://healthevidence:healthevidence@127.0.0.1:5432/healthevidence"
}

$PythonCmd = $null
$UseUv = $false
if (Test-Path ".\.venv\Scripts\python.exe") {
    $PythonCmd = ".\.venv\Scripts\python.exe"
} else {
    $UseUv = $true
}

Write-Host "=== Pilot gate: pytest (SQLite in-memory) ==="
if ($UseUv) {
    & uv run pytest -q
} else {
    & $PythonCmd -m pytest -q
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "=== Pilot gate: PostgreSQL bootstrap + ten personas ==="
Write-Host "Ensure Postgres is up: docker compose up -d postgres"
Write-Host "OIDC IdP (optional): docs/OIDC_PILOT.md"
$env:PILOT_POSTGRES_TEST = "1"
$env:DATABASE_URL = $DbUrl
if ($UseUv) {
    & uv run pytest tests/pilot -v --tb=short
} else {
    & $PythonCmd -m pytest tests/pilot -v --tb=short
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "=== Optional live smoke (API must be running) ==="
if ($env:HE_API_BASE) {
    if ($UseUv) {
        & uv run python scripts\_smoke_web_api.py
    } else {
        & $PythonCmd scripts\_smoke_web_api.py
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Write-Host "Skip smoke — set HE_API_BASE=http://127.0.0.1:8000 to include"
}

Write-Host "Pilot gate OK — see docs/PILOT_ROADMAP.md and docs/OIDC_PILOT.md"
exit 0
