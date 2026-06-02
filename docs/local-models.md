# Recall Local Models

Recall is distributed as a GitHub-first local app. Core semantic search does **not** fetch models at runtime anymore.

## Core Search Models

Recall expects these local assets for core search:

- `OpenCLIP` checkpoint for image semantic search
- `BAAI/bge-small-en-v1.5` assets for document and voice-rec semantic search

Prepare them with:

```powershell
npm run prepare:models
```

This populates `python/models` for source runs and seeds the packaged runtime build.

## Source Workflow

If you clone the repo and want Recall to start successfully with full core search readiness:

1. Install the Python worker dependencies with `pip install ".[ml]"` or `pip install -e ".[ml]"`.
2. Run `npm run prepare:models`.
3. Start Recall with the provided dev launcher.

The dev launcher exports `RECALL_MODEL_ROOT=python\models` automatically when that folder exists.

## Packaged Runtime

`npm run build:runtime` copies the prepared core models into the staged Tauri resources bundle. The runtime smoke test then boots the worker with offline cache directories and `HF_HUB_OFFLINE=1`.

That means the packaged runtime only passes if the staged local assets are sufficient for core search.

## Optional Indexing Engines

OCR and voice transcription remain deferred until indexing needs them. The current public release posture guarantees offline core search readiness first. If you rely on OCR or voice transcription heavily, test those paths on your machine before publishing convenience binaries to others.
