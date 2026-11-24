# Diagnostics

Use `pictova health`, plan warnings, and authenticated `GET /jobs`
to inspect the local workflow.

Job execution is process-local; compact status receipts persist for up to
seven days (latest 256 jobs). On restart, unfinished jobs become
`interrupted`, not replayed. Review the full attach receipt and actual
WordPress state before retrying.

[Operations](runbook.md) · [Operation lifecycles](../architecture/lifecycles.md)
