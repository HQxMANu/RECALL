$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonDir = Join-Path $projectRoot "python"

Write-Host "Preparing Recall Python environment..."
Push-Location $pythonDir

if (-not (Test-Path ".venv")) {
  python -m venv .venv
}

. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install ".[ml]"

Pop-Location
Write-Host "Recall worker dependencies installed."
