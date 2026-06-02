$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$releaseRoot = Join-Path $projectRoot "src-tauri\target\release"
$portableRoot = Join-Path $releaseRoot "portable"
$appRoot = Join-Path $portableRoot "Recall"
$pythonSource = Join-Path $projectRoot "src-tauri\resources\python"
$exeSource = Join-Path $releaseRoot "recall.exe"
$zipPath = Join-Path $portableRoot "Recall_0.1.0-beta.1_portable-win64.zip"
$readmePath = Join-Path $appRoot "README-portable.txt"

if (-not (Test-Path $exeSource)) {
  throw "Expected release executable not found: $exeSource"
}

if (-not (Test-Path $pythonSource)) {
  throw "Expected staged runtime not found: $pythonSource"
}

if (Test-Path $portableRoot) {
  Remove-Item -LiteralPath $portableRoot -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $appRoot | Out-Null
Copy-Item -LiteralPath $exeSource -Destination (Join-Path $appRoot "recall.exe") -Force

$null = robocopy $pythonSource (Join-Path $appRoot "python") /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS /NP
$exitCode = $LASTEXITCODE
if ($exitCode -ge 8) {
  throw "Failed to copy the staged Python runtime into the portable package (robocopy exit code $exitCode)."
}

@"
Recall Portable Build
=====================

This is a GitHub-first portable build of Recall.

- The executable is unsigned in the current release posture.
- Windows may show an unknown publisher warning.
- Core search expects the bundled python runtime and local models that ship in the adjacent python folder.

To run:
1. Keep recall.exe and the python folder together.
2. Launch recall.exe from this folder.
"@ | Set-Content -LiteralPath $readmePath -Encoding UTF8

Compress-Archive -Path (Join-Path $appRoot '*') -DestinationPath $zipPath -Force
Write-Output "Created portable package at $zipPath"
