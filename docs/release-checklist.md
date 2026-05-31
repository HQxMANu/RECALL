# Recall Windows Beta Release Checklist

Use this checklist before publishing a new Windows beta installer.

## Automated gates

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

## Manual Windows 11 publish checks

1. Build a fresh installer:

```powershell
npm run build:tauri
```

2. Install the fresh NSIS package from:

- `src-tauri/target/release/bundle/nsis/Recall_0.1.0-beta.1_x64-setup.exe`

3. Confirm startup and shell behavior:

- Shell appears cleanly
- Core search reaches ready state
- Indexing/OCR remains deferred until indexing work starts

4. Confirm startup reconcile and live indexing:

- Images appear after startup reconcile
- Documents appear after startup reconcile
- `Voice rec` appears after startup reconcile
- Adding `.m4a`, `.docx`, `.pdf`, and image files while Recall is open works
- Adding the same file types while Recall is closed works after relaunch
- Moving files between indexed folders keeps them searchable

5. Confirm preview and file actions:

- Image previews render inside Recall
- Preview rendering works without arbitrary local-file URLs
- `Open file`
- `Open file location`
- `Copy file path`

6. Confirm installer hygiene:

- Install succeeds on a clean Windows 11 machine
- Uninstall removes the app cleanly
- Signed installer passes the intended SmartScreen expectations

## Release policy for `0.1.0-beta.1`

- Windows-only beta
- NSIS installer only
- Bundled Python worker runtime
- No cloud fallback in the runtime path
