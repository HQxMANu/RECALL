# Recall GitHub-First Release Checklist

Use this checklist before publishing a new open-source release of Recall.

## Automated Gates

Run from the repository root:

```powershell
npm run validate:release
```

This covers:

- `npm run lint`
- `npm run build:runtime`
- `npm run build`
- `cargo check --manifest-path src-tauri/Cargo.toml`
- `python -m unittest discover -s python/tests -t python`

## Required Release Checks

1. Confirm the clone-and-run workflow still works:

```powershell
npm install
cd python
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -e ".[ml]"
cd ..
npm run prepare:models
powershell -ExecutionPolicy Bypass -File .\scripts\dev-tauri.ps1
```

2. Confirm offline core search behavior:

- `python\models` exists after `npm run prepare:models`
- staged runtime smoke still passes
- core search reaches ready without depending on remote model downloads

3. Confirm packaged runtime integrity:

- no `__editable__*` artifacts remain in the staged runtime
- no absolute local developer paths remain in staged runtime metadata
- packaged worker boot passes from `src-tauri\resources\python`

4. Confirm startup and search behavior:

- shell appears cleanly
- core search reaches ready
- image/document/voice-rec search still work
- OCR and transcription remain deferred until indexing needs them

## Optional Binary Release Checks

If you publish convenience binaries on GitHub Releases:

1. Build a fresh portable package:

```powershell
npm run build:tauri
```

2. Verify the produced artifacts exist:

- `src-tauri\target\release\recall.exe`
- `src-tauri\target\release\portable\Recall`
- `src-tauri\target\release\portable\Recall_0.1.0-beta.3_portable-win64.zip`

3. Attach checksums and release notes.

4. State clearly in the release notes that the Windows artifacts may be unsigned and may show an unknown publisher warning.

5. Prefer publishing from a version tag:

```powershell
git tag v0.1.0-beta.3
git push origin v0.1.0-beta.3
```

The `Build Windows Portable Release Artifacts` workflow creates a draft prerelease with:

- `recall.exe`
- `Recall_0.1.0-beta.3_portable-win64.zip`
- `SHA256SUMS.txt`
- `python-runtime-report.json`

Review the draft release, edit the notes if needed, then publish it manually from GitHub.

## Future Enhancement

Code signing is recommended for broader non-technical Windows distribution, but it is not a current blocker for the GitHub-first open-source release posture.
