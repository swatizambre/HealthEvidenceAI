$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (Get-Command uv -ErrorAction SilentlyContinue) {
  uv run python -m app.cli.demo
} else {
  python -m app.cli.demo
}
