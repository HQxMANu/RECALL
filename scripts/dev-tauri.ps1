$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
$env:PATH = "$cargoBin;$env:PATH"

$vsWhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vsWhere)) {
  throw "vswhere.exe not found. Visual Studio Build Tools may not be installed correctly."
}

$installationPath = & $vsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $installationPath) {
  throw "No Visual Studio installation with VC++ tools was found."
}

$vsDevCmd = Join-Path $installationPath "Common7\Tools\VsDevCmd.bat"
if (-not (Test-Path $vsDevCmd)) {
  throw "VsDevCmd.bat not found at $vsDevCmd"
}

$devShellExport = & cmd /c "`"$vsDevCmd`" -arch=x64 -host_arch=x64 >nul && set"
foreach ($line in $devShellExport) {
  if ($line -match "^(.*?)=(.*)$") {
    [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
  }
}

$venvPython = Join-Path $projectRoot "python\.venv\Scripts\python.exe"
if (Test-Path $venvPython) {
  $env:RECALL_PYTHON_EXE = $venvPython
}

Push-Location $projectRoot
try {
  npm run dev:tauri
}
finally {
  Pop-Location
}
