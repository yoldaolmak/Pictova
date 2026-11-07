# Changelog

## Unreleased

### Added
- Pictova Studio: local URL-based preview, heading placement, candidate rejection and single-use approval.
- Separate consent for licensed stock downloads and revalidation of approved post/image identities.
- Offline OpenAI-compatible model contract tests and Studio HTTP/security regressions.

### Changed
- Native selection now requires evidence for the target heading, including bounded Turkish/English concept matching; broadened queries cannot override the original subject.
- Managed-media reset/reposition rejects mixed-ownership galleries.
- DepositPhotos transfers, cached files and asset identifiers have explicit bounds.
- Local vision responses reject truncated, malformed or oversized completions; operator errors omit raw model output.
- CI runs tests on Python 3.10–3.12, lint and Studio JS syntax. Coverage stays in GitHub Actions logs.
- Public docs and build commands are aligned with the standalone product and current code.

## 0.1.0 — 2026-06

Initial native CLI and HTTP application; WordPress selection, processing, metadata, publishing, Visual Memory integration and compatibility paths.
