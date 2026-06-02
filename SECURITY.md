# Security Policy

## Supported Release Posture

Recall is currently maintained as a GitHub-first open-source project with Windows-first support.

The primary supported workflows are:

- clone the repository and run from source
- optionally build packaged Windows binaries locally

## Reporting A Security Issue

Please do not open a public issue first for a sensitive security problem.

Instead, contact the maintainer privately through the repository owner contact path, then open a public issue only after a fix or mitigation is ready to disclose safely.

When reporting, include:

- affected version or commit
- reproduction steps
- whether the issue affects source runs, packaged builds, or both
- whether it impacts local file exposure, offline/runtime integrity, or bundled models

## Current Security Posture Notes

- Core search is intended to run from local assets only in the supported release path.
- Optional Windows binaries may be unsigned during the current GitHub-first release phase.
- If optional binaries are published, verify checksums and review release notes before running them.
