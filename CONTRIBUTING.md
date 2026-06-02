# Contributing

Thanks for contributing to Recall.

## Recommended Setup

1. Clone the repository and enter the checkout directory.
2. Install frontend dependencies with `npm install`.
3. Create the Python worker environment under `python\.venv`.
4. Install worker dependencies with `pip install -e ".[ml]"`.
5. Prepare the local model assets with `npm run prepare:models`.
6. Start the app with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-tauri.ps1
```

## Before Opening A PR

Run:

```powershell
npm run lint
npm run build
python -m unittest discover -s python/tests -t python
```

If you touched packaging or release behavior, also run:

```powershell
npm run build:runtime
```

## Scope Guidelines

- Preserve Recall's local-first product direction.
- Avoid changing the core readiness contract unless there is a strong product reason.
- Prefer production-safe, minimal changes over broad rewrites.

## Issues And Discussion

Use GitHub Issues for bug reports, broken workflows, and release problems.
