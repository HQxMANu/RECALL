# Recall

Recall is a Windows-first, local-first desktop search app for screenshots and images. It lets you search your visual history in plain English using on-device OCR, embeddings, thumbnails, and hybrid ranking.

## Why Recall

- Search screenshots like a private desktop copilot
- Keep indexing, OCR, and semantic search on your machine
- Blend text matches, OCR snippets, semantic similarity, and recency into one result list
- Open results fast without uploading your image library anywhere

## Product snapshot

- `Tauri` desktop shell
- `React + TypeScript` UI
- `Rust` host for native desktop integration
- `Python` worker for indexing and search
- `SQLite + FTS5` for metadata and text search
- `FAISS` for vector search with local fallback paths

## What it does today

- Index local folders of screenshots and images
- Extract OCR text for searchable content
- Generate embeddings for description-based image search
- Store metadata, OCR text, embeddings, and thumbnails locally
- Run hybrid ranking across text search and semantic search
- Track indexing jobs and filesystem changes
- Show search readiness, indexing progress, and local engine state in the UI
- Support preview, open location, and copy path actions

## Architecture

Recall uses a local three-part architecture:

1. `React + Tauri UI`
2. `Rust desktop host`
3. `Python indexing and search worker`

More detail:

- [Architecture notes](docs/architecture.md)
- [SQLite schema](docs/schema.md)
- [Ranking notes](docs/ranking.md)

## Local-first design

- No cloud inference in the runtime path
- No telemetry pipeline in the current app runtime
- Data stays in local app storage
- OCR and indexing services are deferred until they are actually needed
- Core search readiness is treated separately from shell readiness

## Current status

Recall is an active prototype with real local indexing and search, not just a UI mockup. The repository is Windows-first and currently optimized around desktop development on Windows.

## Run locally

### Requirements

- Node.js
- Python 3.11+
- Rust toolchain
- Visual Studio Build Tools with the C++ workload on Windows

### Install

```powershell
npm install
cd python
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
pip install ".[ml]"
cd ..
```

### Development

```powershell
npm run dev:tauri
```

### Packaged build

```powershell
npm run build:tauri
```

## Validation

- Frontend typecheck: `npm run typecheck`
- Frontend lint: `npm run lint`
- Python tests: `python -m unittest discover -s python/tests -t python`

## Notes

- This repository currently includes a Python ML stack, so local build artifacts can get large during development.
- The packaged runtime is pruned for distribution, but the development workspace is still heavier than a typical CRUD desktop app.

## License

MIT
