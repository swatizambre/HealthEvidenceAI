# Pre-demo quality gate: unit/integration + live smoke against demo/pilot API.
# Start the stack first, e.g.:
#   docker compose -f docker-compose.yml -f docker-compose.pilot.yml -f docker-compose.demo.yml up --build
# Then:
#   .\scripts\demo_gate.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$ApiBase = if ($env:HE_API_BASE) { $env:HE_API_BASE } else { "http://127.0.0.1:8000" }
$WebBase = if ($env:HE_WEB_BASE) { $env:HE_WEB_BASE } else { "http://127.0.0.1:3000" }

$Python = if (Test-Path ".\.venv\Scripts\python.exe") {
    ".\.venv\Scripts\python.exe"
} else {
    "uv"
}

Write-Host "=== Demo gate: pytest ==="
if ($Python -eq "uv") {
    & uv run pytest -q
} else {
    & $Python -m pytest -q
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "=== Demo gate: ten-persona matrix (SQLite) ==="
if ($Python -eq "uv") {
    & uv run pytest tests/integration/test_ten_personas.py -q --tb=line
} else {
    & $Python -m pytest tests/integration/test_ten_personas.py -q --tb=line
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "=== Demo gate: live smoke ($ApiBase) ==="
$env:HE_API_BASE = $ApiBase
$env:HE_WEB_BASE = $WebBase
if ($Python -eq "uv") {
    & uv run python scripts\_smoke_web_api.py
} else {
    & $Python scripts\_smoke_web_api.py
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Demo gate OK — see docs/LAUNCH.md"
exit 0
