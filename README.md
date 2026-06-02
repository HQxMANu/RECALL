# Recall

Recall is a Windows-first, local-first desktop search app for screenshots, images, documents, and voice recordings. It uses on-device OCR, embeddings, thumbnails, and hybrid ranking so you can search your local history in plain English without sending files to the cloud.

## Release Posture

Recall is currently distributed **GitHub-first**:

- the repository is the primary public release surface
- you can clone it, install the dependencies, and run it locally
- optional prebuilt Windows binaries may be published on GitHub Releases for convenience
- no Microsoft Store dependency
- no code-signing requirement for the initial open-source launch

If optional Windows binaries are provided, Windows may show an **unsigned / unknown publisher** warning. That is expected for the current release posture.

## Product Snapshot

- `Tauri` desktop shell
- `React + TypeScript` UI
- `Rust` host for desktop integration and worker orchestration
- `Python` worker for indexing and search
- `SQLite + FTS5` for metadata and text retrieval
- `FAISS` for local vector search

## What Recall Does Today

- indexes local folders recursively
- extracts OCR text from indexed visuals
- builds embeddings for description-based search
- stores metadata, OCR text, thumbnails, and search state locally
- supports image, document, and voice-rec search scopes
- keeps OCR and transcription deferred until indexing actually needs them

## Quickstart

### Requirements

- Windows 11 recommended
- Node.js 22+
- Python 3.11
- Rust toolchain
- Visual Studio Build Tools with the C++ workload on Windows

### Clone And Run From Source

```powershell
git clone https://github.com/HQxMANu/RECALL.git
cd RECALL
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

That path is best for contributors and technical users who want the live dev workflow.

### Local Packaged Build

```powershell
npm run build:tauri
```

This builds a portable Windows package:

- the release executable at `src-tauri\target\release\recall.exe`
- the portable folder at `src-tauri\target\release\portable\Recall`
- the portable zip at `src-tauri\target\release\portable\Recall_0.1.0-beta.1_portable-win64.zip`

### Optional Binary Download

If a GitHub Release includes Windows binaries:

1. download the latest portable zip or unpacked portable folder
2. keep the bundled `python` folder next to `recall.exe` if you use the portable build
3. expect Windows to warn that the publisher is unknown if the artifact is unsigned
4. review the release notes and checksums before running the file

The repo is still the source of truth even when convenience binaries are published.

## Documentation And Support

- [Privacy and local data handling](PRIVACY.md)
- [Security reporting](SECURITY.md)
- [Contribution guide](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

Bug reports and support requests should go through GitHub Issues on the main repository.

## Local Model Preparation

Core semantic search is intentionally **offline/local-only** at runtime. Recall no longer downloads its core search models on startup.

Prepare the local model assets once with:

```powershell
npm run prepare:models
```

This downloads the required local assets into `python\models`.

More detail:

- [Local model setup and offline behavior](docs/local-models.md)

## Recommended Developer Workflow

- use `powershell -ExecutionPolicy Bypass -File .\scripts\dev-tauri.ps1` for daily development
- use `npm run build:tauri` when you want to test the packaged build
- avoid opening `src-tauri\target\debug\recall.exe` directly unless the dev server is already running

## Validation

- frontend lint: `npm run lint`
- frontend build: `npm run build`
- Python tests: `python -m unittest discover -s python/tests -t python`
- staged runtime smoke test: `npm run smoke:runtime`
- release validation gate: `npm run validate:release`

## Architecture Notes

- [Architecture notes](docs/architecture.md)
- [SQLite schema](docs/schema.md)
- [Ranking notes](docs/ranking.md)
- [GitHub-first release checklist](docs/release-checklist.md)

## Troubleshooting

### `localhost refused to connect`

You probably opened the debug executable directly. Start Recall in development mode with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-tauri.ps1
```

### Core search never becomes ready

- make sure `npm run prepare:models` completed successfully
- verify `python\models` exists
- if you are testing a packaged runtime, rebuild it after changing the worker or model setup

### Windows build tools errors

Install Visual Studio Build Tools with the C++ workload, then rerun the provided PowerShell launcher.

### Large workspace / build size

Recall ships a local ML stack, so the Python worker runtime is heavier than a typical desktop CRUD app. The packaged runtime is pruned, but local development artifacts are still large.

### Optional binary size expectations

Convenience binaries are currently heavier than typical desktop apps because Recall bundles a local ML runtime and offline-ready core search models. Expect large downloads and meaningful disk usage if you choose the packaged route instead of the source workflow.

## Current Scope

- Windows-first
- GitHub-first open-source distribution
- optional unsigned convenience binaries
- local-first runtime for core search

## License

MIT
