$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "HealthEvidence AI — portfolio launch (not for clinical use)"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  throw "Install uv first: https://docs.astral.sh/uv/"
}

if (-not (Test-Path .env)) {
  Copy-Item .env.example .env
  Write-Host "Created .env from .env.example"
}

uv sync --all-extras
if (-not (Test-Path "frontend\node_modules")) {
  Push-Location frontend
  npm ci
  Pop-Location
}

Write-Host "Starting API on :8000 and UI on :5173"
$api = Start-Process -PassThru -NoNewWindow -FilePath "uv" -ArgumentList @(
  "run", "python", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"
)
Push-Location frontend
try {
  Write-Host "UI  http://127.0.0.1:5173"
  Write-Host "API http://127.0.0.1:8000/docs"
  npm run dev -- --host 127.0.0.1 --port 5173
} finally {
  Pop-Location
  if ($api -and -not $api.HasExited) {
    Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue
  }
}
