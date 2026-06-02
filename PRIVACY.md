# Privacy

Recall is designed as a local-first desktop app.

## What Recall Stores Locally

When you index folders, Recall stores data under its local app-data directory, including:

- the SQLite database (`recall.db`)
- generated thumbnails and document previews
- FAISS vector indexes for image and text search
- OCR text extracted from indexed visuals
- text chunks and transcription-derived text for supported documents or voice recordings

Recall needs these local artifacts so search can remain fast and offline-friendly after indexing.

## What Recall Does Not Intentionally Do

- Recall does not send your indexed files to a Recall cloud service.
- Recall does not require cloud inference for core search readiness in the supported workflow.
- Recall does not include an application telemetry pipeline in the current runtime.

## Local Model Assets

Core semantic search depends on local model assets prepared with:

```powershell
npm run prepare:models
```

Those assets are stored locally under `python\models` for source runs and copied into the staged runtime for packaged builds.

## Optional Convenience Binaries

If you use optional GitHub Release binaries, the packaged runtime may be large because it bundles offline-ready local search assets.

## Removing Recall Data

To remove Recall data completely:

1. remove the indexed folders from the app if desired
2. uninstall the app if you installed a packaged build
3. delete the Recall app-data directory manually if you want all derived local artifacts removed

If you are running from source, you can also remove the local development data directory created for the worker.

## Security / Reporting

If you discover a privacy or security issue, use the instructions in [SECURITY.md](SECURITY.md).
