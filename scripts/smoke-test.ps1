$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot

Push-Location $projectRoot

Write-Host "Running frontend typecheck..."
npm run typecheck

Write-Host "Running frontend lint..."
npm run lint

Write-Host "Running Python unit tests..."
python -m unittest discover -s python/tests -t python

Pop-Location
Write-Host "Smoke test complete."
