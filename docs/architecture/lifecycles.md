# Operation lifecycles

Pictova uses existing functions and SQLite records for transitions. This is a
contract, not a second workflow engine.

| Area | States and rule |
| --- | --- |
| Studio page | empty → planning → review → applying → terminal. The UI cannot turn a partial result into success. |
| Approval plan | available → submitting → consumed. An enqueue failure restores available; a second approval is refused. Plans expire after 20 minutes. |
| Candidate consent | available → selected / rejected → approved. Paid candidates require separate permission. |
| HTTP jobs | queued → running → success / partial / failed. On restart queued or running becomes interrupted; no automatic retry of paid work. |
| Source selection | heading → exact candidate / expansion → verified match or empty. No generic replacement. |
| Local and iCloud files | indexed → resolved → processed / skipped / failed. Per-file losses are returned explicitly. |
| DepositPhotos | discovered → licensed link → partial download → completed / failed. Cached partials resume; no automatic resubmission of approved jobs. |
| Model providers | LM Studio → Gemini → OpenAI → Codex → Claude, first valid result wins. No basic fallback. |
| Gemini keys | usable → rejected (401) or cooling down (429/503) → usable after cooldown. |
| Metadata | existing verified cache → applied, otherwise vision → validated / error. |
| Quality gate | processed → approved / blocked, per image. |
| Native attach | validated → exclusive per-post lock → selection → process → quality → WordPress write → verified outcome. |
| WordPress media | upload → metadata → post association → article insertion → read-after-write confirmation. Failed metadata triggers a compensating delete; failed association is a partial result. Upload alone never means published. |
| Post content | editor snapshot → optimistic conflict check → mutation → readback → manifest. A changed post aborts. |
| Managed-media integrity | untracked / empty / healthy / drift / invalid. Healthy requires real blocks, expected URLs and approved section positions. |
| Guard maintenance | drift → explicit repair/reposition/reset → verified / failed. Mixed ownership stays blocked. |
| Visual Memory | pending → scanning (leased) → done / error. Explicit --retry-errors reclaims errors; stale scans are recoverable. |
| Legacy engine | running → local / skipped / success / partial / failed. WordPress write outcomes use the same verification contract as native. |
| Operation receipt | pending → persisted before work → terminal snapshot, or interrupted after restart. Full attach receipt remains separately stored. |

## Publication result contract

- **success:** WordPress article update and managed-media placement verified,
  or an exact idempotent replay of already-managed assets. Uploaded media alone
  is insufficient.
- **partial:** Some verified placement succeeded with warnings, or the
  attempted WordPress commit cannot be conclusively verified. The operator must
  inspect the article and media receipt before another run.
- **failed:** No verified article placement. Inspect any uploaded/orphaned media
  and recorded rollback details before attempting again.
- **interrupted:** The local HTTP server stopped during a queued/running job.
  Do not automatically repeat a paid download or WordPress write.

A plan is kept entirely in memory and must be freshly created after restart.
Job-status snapshots are separate: stored in restricted local JSON files (mode
0600) for up to seven days, most recent 256. The snapshot omits browser token,
raw candidate paths and detailed provider payloads. Full operation receipts
retain local-only diagnostics. No asynchronous job is silently resumed.

## Recovery

1. Inspect WordPress and the operation receipt; a missing local job does not
   prove no remote side effect occurred.
2. If the media manifest reports drift, use the explicit guard workflow after
   reviewing ownership. Do not use reset as a blind retry.
3. For failed Visual Memory scans, use
   `python3 scripts/fast_scan.py --workers 1 --limit 50 --retry-errors`.
   Jobs are claimed per asset; concurrent workers cannot process the same
   active lease. A scanning lease older than 90 minutes may be reclaimed.
4. Verify the actual WordPress article and a real original photo before
   declaring an end-to-end production result. The synthetic WordPress end-to-end
   tests run real HTTP publishing and readback against an isolated loopback
   REST emulator, not an installed WordPress instance.

WordPress REST optimistic concurrency is not an atomic compare-and-swap:
an external editor could still write in the narrow interval between the
pre-write check and server commit. Do not claim transaction isolation across
the local process and WordPress.
