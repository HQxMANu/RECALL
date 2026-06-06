# Changelog

## 0.1.0-beta.2

- restored the folder management view and image/document/voice-rec scope selector in packaged builds
- isolated portable app data beside the portable executable instead of reusing developer app data
- fixed packaged frontend bundling so the desktop app does not try to load localhost

## 0.1.0-beta.1

- shifted Recall to a GitHub-first open-source distribution posture
- added a tag-based Windows prerelease workflow for downloadable GitHub Release artifacts
- documented clone-and-run, local model preparation, and optional binary usage
- made core search runtime depend on explicit local model assets
- removed editable-install leakage from the staged packaged runtime
- added packaged runtime integrity checks and offline smoke validation
- stabilized safe rebuilds so unchanged ready assets avoid unnecessary OCR, embeddings, thumbnail regeneration, and vector flushes
- capped preview cache memory and added incremental result loading while scrolling
- simplified the beta UI to an image-first search and preview flow
- clarified that Windows code signing is a future trust/usability enhancement, not a current launch blocker
