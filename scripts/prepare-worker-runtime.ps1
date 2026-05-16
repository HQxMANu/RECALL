$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonDir = Join-Path $projectRoot "python"
$runtimeRoot = Join-Path $projectRoot "src-tauri\resources\python"
$legacyRuntimeZip = Join-Path $projectRoot "src-tauri\resources\worker-runtime.zip"

if (-not (Test-Path (Join-Path $pythonDir ".venv\Scripts\python.exe"))) {
  throw "Python runtime not found at $pythonDir\.venv. Run scripts\\package-models.ps1 first."
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $runtimeRoot) | Out-Null

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

$runtimeVenv = Join-Path $runtimeRoot ".venv"
New-Item -ItemType Directory -Force -Path $runtimeVenv | Out-Null
Sync-Tree (Join-Path $pythonDir ".venv\\Lib") (Join-Path $runtimeVenv "Lib")
Sync-Tree (Join-Path $pythonDir ".venv\\Scripts") (Join-Path $runtimeVenv "Scripts")
Copy-Item -LiteralPath (Join-Path $pythonDir ".venv\\pyvenv.cfg") -Destination (Join-Path $runtimeVenv "pyvenv.cfg") -Force
Sync-Tree (Join-Path $pythonDir "recall_worker") (Join-Path $runtimeRoot "recall_worker")
Copy-Item -LiteralPath (Join-Path $pythonDir "run_worker.py") -Destination (Join-Path $runtimeRoot "run_worker.py") -Force

if (Test-Path $legacyRuntimeZip) {
  Remove-Item -LiteralPath $legacyRuntimeZip -Force
}

$env:RECALL_RUNTIME_ROOT = $runtimeRoot

@'
from __future__ import annotations

import os
import shutil
from pathlib import Path

runtime_root = Path(os.environ["RECALL_RUNTIME_ROOT"])
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
]


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


for relative in [
    Path(".venv") / "Include",
    Path(".venv") / "share",
    Path(".venv") / "Lib" / "site-packages" / "torch" / "include",
    Path(".venv") / "Lib" / "site-packages" / "paddle" / "include",
    Path(".venv") / "Lib" / "site-packages" / "numpy" / "core" / "include",
    Path(".venv") / "Lib" / "site-packages" / "numpy" / "_core" / "include",
]:
    remove_path(runtime_root / relative)

for pattern in ("pip*", "setuptools*", "wheel*"):
    for path in site_packages.glob(pattern):
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

file_count, total_size = stat_tree(runtime_root)
print(
    f"Prepared Recall worker runtime at {runtime_root} "
    f"({file_count} files, {total_size / 1024 / 1024:.2f} MB)"
)
'@ | python -
