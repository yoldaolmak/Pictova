# Changelog

## Unreleased

### Fixed
- Verified WordPress Gutenberg insertion and manifest evidence now determine native and legacy publish outcomes; upload-only successes are rejected.
- Partial, failed and interrupted jobs are distinct across the server and Studio UI. Short-lived Studio plans survive failed enqueue attempts without double submission.
- Authenticated job-state receipts survive process restarts without automatically replaying paid writes; stale jobs are marked interrupted.
- Managed-media integrity now checks actual Gutenberg blocks, approved heading and original URL, not just matching ID tokens.
- Failed media metadata writes now trigger compensating deletion of the new WordPress attachment; failed cleanup and association errors are reported for manual reconciliation.
- Per-photo processing errors and recoverable Visual Memory scan errors are explicit. SQLite scan leases prevent duplicate concurrent paid analysis; daily scan quotas count attempted work.


### Added
- Isolated synthetic WordPress REST end-to-end suite exercising Studio HTTP approval, real JPEG-to-WebP processing, one- and two-section Gutenberg placement/readback, manifest, rollback, editor conflicts and paid consent without real credentials or license charges.
- Gutenberg heading proximity now respects section boundaries: an image belonging to a previous peer H2/H3 no longer blocks a valid image in the next section; parent-to-child proximity restrictions remain in place.
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
