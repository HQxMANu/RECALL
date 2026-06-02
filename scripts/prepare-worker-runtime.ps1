$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonDir = Join-Path $projectRoot "python"
$sourcePython = Join-Path $pythonDir ".venv\Scripts\python.exe"
$runtimeRoot = Join-Path $projectRoot "src-tauri\resources\python"
$runtimeReportPath = Join-Path $projectRoot "src-tauri\resources\python-runtime-report.json"
$runtimeSmokeScript = Join-Path $projectRoot "scripts\smoke_worker_runtime.py"
$prepareModelsScript = Join-Path $projectRoot "scripts\prepare_local_models.py"
$runtimeBudgetMb = if ($env:RECALL_RUNTIME_MAX_MB) { [double]$env:RECALL_RUNTIME_MAX_MB } else { 2500.0 }
$runtimeBudgetFiles = if ($env:RECALL_RUNTIME_MAX_FILES) { [int]$env:RECALL_RUNTIME_MAX_FILES } else { 25000 }

if (-not (Test-Path $sourcePython)) {
  throw "Python runtime not found at $pythonDir\.venv. Create python\.venv and install the worker dependencies first."
}

function Sync-Tree {
  param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Destination
  )

  New-Item -ItemType Directory -Force -Path $Destination | Out-Null
  $null = robocopy $Source $Destination /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS /NP /XF "*.pyc"
  $exitCode = $LASTEXITCODE
  if ($exitCode -ge 8) {
    throw "Failed to sync $Source to $Destination (robocopy exit code $exitCode)."
  }
}

$sourceModelsRoot = Join-Path $pythonDir "models"
& $sourcePython $prepareModelsScript --model-root $sourceModelsRoot
if ($LASTEXITCODE -ne 0) {
  throw "Failed to prepare Recall core models for runtime staging."
}

if (Test-Path $runtimeRoot) {
  Remove-Item -LiteralPath $runtimeRoot -Recurse -Force
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $runtimeRoot) | Out-Null
$runtimeVenv = Join-Path $runtimeRoot ".venv"
New-Item -ItemType Directory -Force -Path $runtimeVenv | Out-Null
Sync-Tree (Join-Path $pythonDir ".venv\Lib") (Join-Path $runtimeVenv "Lib")
Sync-Tree (Join-Path $pythonDir ".venv\Scripts") (Join-Path $runtimeVenv "Scripts")
Copy-Item -LiteralPath (Join-Path $pythonDir ".venv\pyvenv.cfg") -Destination (Join-Path $runtimeVenv "pyvenv.cfg") -Force
Sync-Tree $sourceModelsRoot (Join-Path $runtimeRoot "models")
Copy-Item -LiteralPath (Join-Path $pythonDir "run_worker.py") -Destination (Join-Path $runtimeRoot "run_worker.py") -Force

$stagedPython = Join-Path $runtimeVenv "Scripts\python.exe"
if (-not (Test-Path $stagedPython)) {
  throw "Staged python executable missing after runtime preparation: $stagedPython"
}

$wheelhouse = Join-Path $env:TEMP ("recall-wheel-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $wheelhouse | Out-Null
try {
  & $sourcePython -m pip wheel --no-deps --wheel-dir $wheelhouse $pythonDir
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to build a non-editable Recall worker wheel."
  }

  $workerWheel = Get-ChildItem -Path $wheelhouse -Filter "recall_worker-*.whl" | Select-Object -First 1
  if (-not $workerWheel) {
    throw "Recall worker wheel was not produced in $wheelhouse."
  }

  & $stagedPython -m pip install --no-deps --force-reinstall $workerWheel.FullName
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to install the Recall worker wheel into the staged runtime."
  }
}
finally {
  if (Test-Path $wheelhouse) {
    Remove-Item -LiteralPath $wheelhouse -Recurse -Force
  }
}

$env:RECALL_RUNTIME_ROOT = $runtimeRoot
$env:RECALL_RUNTIME_REPORT = $runtimeReportPath
$env:RECALL_RUNTIME_MAX_MB = [string]$runtimeBudgetMb
$env:RECALL_RUNTIME_MAX_FILES = [string]$runtimeBudgetFiles
$env:RECALL_PROJECT_ROOT = $projectRoot

@'
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

runtime_root = Path(os.environ["RECALL_RUNTIME_ROOT"])
runtime_report = Path(os.environ["RECALL_RUNTIME_REPORT"])
project_root = Path(os.environ["RECALL_PROJECT_ROOT"]).resolve()
max_mb = float(os.environ["RECALL_RUNTIME_MAX_MB"])
max_files = int(os.environ["RECALL_RUNTIME_MAX_FILES"])
venv_root = runtime_root / ".venv"
site_packages = venv_root / "Lib" / "site-packages"
protected_roots = [
    site_packages / "torch",
    site_packages / "paddle",
    site_packages / "paddlex",
    site_packages / "paddleocr",
    site_packages / "open_clip",
    site_packages / "torchvision",
    site_packages / "timm",
    site_packages / "faiss",
    site_packages / "numpy",
    site_packages / "PIL",
    site_packages / "cv2",
    site_packages / "huggingface_hub",
    site_packages / "recall_worker",
]
absolute_path_markers = {
    str(project_root).replace("\\", "/").lower(),
    str(project_root).lower(),
}


def remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def stat_tree(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    files = [child for child in path.rglob("*") if child.is_file()]
    return len(files), sum(child.stat().st_size for child in files)


def is_protected(path: Path) -> bool:
    return any(root == path or root in path.parents for root in protected_roots if root.exists())


def top_largest_roots() -> list[dict[str, object]]:
    candidates: list[Path] = []
    if site_packages.exists():
        candidates.extend(site_packages.iterdir())
    candidates.extend(
        candidate
        for candidate in runtime_root.iterdir()
        if candidate.name not in {".venv"} and candidate.is_dir()
    )
    unique_candidates: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique_candidates.append(candidate)
    roots: list[dict[str, object]] = []
    for candidate in unique_candidates:
        file_count, total_size = stat_tree(candidate)
        roots.append(
            {
                "path": str(candidate),
                "name": candidate.name,
                "fileCount": file_count,
                "sizeMb": round(total_size / 1024 / 1024, 2),
            }
        )
    roots.sort(key=lambda item: item["sizeMb"], reverse=True)
    return roots[:10]


def scan_for_runtime_leaks() -> list[str]:
    leak_messages: list[str] = []
    suspicious_patterns = ("__editable__", ".egg-link", "direct_url.json", ".pth")
    for path in runtime_root.rglob("*"):
        if not path.is_file():
            continue

        if any(pattern in path.name for pattern in suspicious_patterns):
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                text = ""
            if "__editable__" in path.name or any(marker in text.lower() for marker in absolute_path_markers):
                leak_messages.append(f"Editable/runtime leak artifact present: {path}")
                continue

        if path.suffix.lower() not in {".pth", ".py", ".json", ".txt", ".cfg", ".dist-info"} and path.stat().st_size > 1024 * 1024:
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        lowered = text.lower()
        if any(marker in lowered for marker in absolute_path_markers):
            leak_messages.append(f"Absolute project path leaked into runtime file: {path}")
    return leak_messages


pyvenv_cfg = venv_root / "pyvenv.cfg"
if pyvenv_cfg.exists():
    sanitized_lines = []
    for raw_line in pyvenv_cfg.read_text(encoding="utf-8").splitlines():
        if raw_line.lower().startswith("command ="):
            sanitized_lines.append("command = python -m venv .venv")
            continue
        sanitized_lines.append(raw_line)
    pyvenv_cfg.write_text("\n".join(sanitized_lines) + "\n", encoding="utf-8")


for relative in [
    Path(".venv") / "Include",
    Path(".venv") / "share",
    Path(".venv") / "Lib" / "site-packages" / "torch" / "include",
    Path(".venv") / "Lib" / "site-packages" / "paddle" / "include",
    Path(".venv") / "Lib" / "site-packages" / "numpy" / "core" / "include",
    Path(".venv") / "Lib" / "site-packages" / "numpy" / "_core" / "include",
]:
    remove_path(runtime_root / relative)

for pattern in ("pip*", "setuptools*", "wheel*", "__editable__*"):
    for path in site_packages.glob(pattern):
        remove_path(path)

for pattern in ("*.egg-link", "direct_url.json"):
    for path in site_packages.rglob(pattern):
        remove_path(path)

for path in site_packages.glob("~*"):
    remove_path(path)

for path in sorted(site_packages.rglob("*"), key=lambda candidate: len(candidate.parts), reverse=True):
    if is_protected(path):
        continue
    if path.is_dir() and path.name.lower() in {
        "__pycache__",
        "tests",
        "test",
        "docs",
        "doc",
        "examples",
        "example",
    }:
        remove_path(path)

for pattern in ("*.pyc", "*.pyo", "*.lib", "*.h", "*.hpp", "*.cuh"):
    for path in runtime_root.rglob(pattern):
        remove_path(path)

for script_name in [
    "pip.exe",
    "pip3.exe",
    "pip3.11.exe",
    "Activate.ps1",
    "activate",
    "activate.bat",
    "deactivate.bat",
]:
    remove_path(venv_root / "Scripts" / script_name)

leaks = scan_for_runtime_leaks()
if leaks:
    raise SystemExit("Runtime integrity check failed:\n- " + "\n- ".join(leaks))

file_count, total_size = stat_tree(runtime_root)
total_size_mb = round(total_size / 1024 / 1024, 2)
report = {
    "runtimeRoot": str(runtime_root),
    "fileCount": file_count,
    "sizeMb": total_size_mb,
    "maxFilesBudget": max_files,
    "maxSizeMbBudget": max_mb,
    "largestRoots": top_largest_roots(),
}
runtime_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(
    f"Prepared Recall worker runtime at {runtime_root} "
    f"({file_count} files, {total_size_mb:.2f} MB)"
)
print("Top largest runtime roots:")
for root in report["largestRoots"]:
    print(f"  - {root['name']}: {root['sizeMb']} MB ({root['fileCount']} files)")

if total_size_mb > max_mb:
    raise SystemExit(
        f"Prepared runtime is {total_size_mb:.2f} MB, which exceeds the {max_mb:.2f} MB budget."
    )
if file_count > max_files:
    raise SystemExit(
        f"Prepared runtime has {file_count} files, which exceeds the {max_files} file budget."
    )
'@ | python -

if (-not $env:RECALL_SKIP_RUNTIME_SMOKE) {
  & $stagedPython $runtimeSmokeScript --runtime-root $runtimeRoot
  if ($LASTEXITCODE -ne 0) {
    throw "Staged Recall worker smoke test failed."
  }
}
