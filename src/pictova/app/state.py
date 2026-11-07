"""Durable, bounded operator job statuses for the local Pictova HTTP surface.

A restarted process never silently resumes a possibly paid or partially
published job. Queued/running receipts become 'interrupted' and require
WordPress inspection before another approved run.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import uuid
from typing import Any, Callable, Dict, List

from src.pictova.engine.publish_outcome import classify_job_result
from src.utils.config import PROJECT_ROOT, env_str


JobRunner = Callable[[Dict[str, Any]], Dict[str, Any]]
_MAX_JOBS = 256
_RETENTION = timedelta(days=7)
_MAX_RECEIPT_BYTES = 512 * 1024
_RESULT_FIELDS = (
    "status", "inserted_blocks", "uploaded_media_ids", "warnings",
    "publish_reason", "needs_reconciliation", "receipt_path",
    "content_update", "rollback",
)
_PAYLOAD_FIELDS = ("site", "post_id", "selected_count", "source", "count", "engine")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact_job(job: Dict[str, Any]) -> Dict[str, Any]:
    result = job.get("result")
    small_result = (
        {field: result[field] for field in _RESULT_FIELDS if field in result}
        if isinstance(result, dict) else None
    )
    return {
        "job_id": job["job_id"],
        "kind": job["kind"],
        "status": job["status"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "payload": {k: v for k, v in job.get("payload", {}).items() if k in _PAYLOAD_FIELDS},
        "result": small_result,
        "error": job.get("error"),
    }


class JobRegistry:
    def __init__(self, *, directory: Path | None = None) -> None:
        self._lock = threading.RLock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._directory = Path(directory) if directory is not None else Path(
            env_str("PICTOVA_JOB_DIR") or PROJECT_ROOT / "data" / "jobs"
        ).expanduser()
        self._restore()

    def _persist(self, job: Dict[str, Any]) -> None:
        payload = json.dumps(_compact_job(job), ensure_ascii=False, default=str).encode("utf-8")
        if len(payload) > _MAX_RECEIPT_BYTES:
            raise ValueError("Pictova job receipt exceeds safe storage bound")
        directory = self._directory
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        path = directory / f"{job['job_id']}.json"
        fd, temp_name = tempfile.mkstemp(prefix=".job-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, path)
        finally:
            Path(temp_name).unlink(missing_ok=True)

    def _restore(self) -> None:
        if not self._directory.is_dir():
            return
        cutoff = datetime.now(timezone.utc) - _RETENTION
        records: list[dict[str, Any]] = []
        for path in self._directory.glob("*.json"):
            try:
                uuid.UUID(path.stem)
                if path.is_symlink() or path.stat().st_size > _MAX_RECEIPT_BYTES:
                    continue
                value = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(value, dict) or value.get("job_id") != path.stem:
                    continue
                created = datetime.fromisoformat(str(value["created_at"]))
                if created.tzinfo is None or created < cutoff:
                    continue
                if value.get("status") not in {"queued", "running", "success", "partial", "failed", "interrupted"}:
                    continue
                if not isinstance(value.get("payload"), dict):
                    continue
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
            records.append(value)
        records.sort(key=lambda value: value["created_at"], reverse=True)
        # The operation receipt is retained separately; keep only the most
        # recent bounded job-status snapshots in the local registry.
        for record in records[_MAX_JOBS:]:
            (self._directory / f"{record['job_id']}.json").unlink(missing_ok=True)
        for record in records[:_MAX_JOBS]:
            if record["status"] in {"queued", "running"}:
                record["status"] = "interrupted"
                record["error"] = "Server restarted during an unconfirmed operation; inspect WordPress before retrying"
                record["updated_at"] = _utc_now()
                try:
                    self._persist(record)
                except (OSError, ValueError):
                    pass
            self._jobs[record["job_id"]] = record

    def create_job(self, *, kind: str, payload: Dict[str, Any], runner: JobRunner) -> Dict[str, Any]:
        job_id = str(uuid.uuid4())
        job = {
            "job_id": job_id,
            "kind": kind,
            "status": "queued",
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "payload": {key: value for key, value in dict(payload).items() if key in _PAYLOAD_FIELDS},
            "result": None,
            "error": None,
        }
        with self._lock:
            oldest = (
                min(self._jobs.values(), key=lambda item: item["created_at"])
                if len(self._jobs) >= _MAX_JOBS else None
            )
            # A failed new write must not erase an older durable receipt.
            self._persist(job)
            self._jobs[job_id] = job
            if oldest:
                self._jobs.pop(oldest["job_id"])
                (self._directory / f"{oldest['job_id']}.json").unlink(missing_ok=True)
        thread = threading.Thread(
            target=self._run_job,
            kwargs={"job_id": job_id, "runner": runner, "payload": dict(payload)},
            daemon=True,
        )
        try:
            thread.start()
        except Exception:
            with self._lock:
                self._jobs.pop(job_id, None)
                (self._directory / f"{job_id}.json").unlink(missing_ok=True)
            raise
        return self.get_job(job_id)

    def _run_job(self, *, job_id: str, runner: JobRunner, payload: Dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job["status"] = "running"
            job["updated_at"] = _utc_now()
            try:
                self._persist(job)
            except (OSError, ValueError):
                # Never execute an irreversible publisher without a durable
                # 'running' receipt that will survive an application crash.
                job["status"] = "failed"
                job["error"] = "Job state could not be persisted; no work was started"
                return

        try:
            result = runner(payload)
            final_status = classify_job_result(result.get("status"))
            with self._lock:
                job = self._jobs[job_id]
                job["status"] = final_status
                job["updated_at"] = _utc_now()
                job["result"] = result
                try:
                    self._persist(job)
                except (OSError, ValueError):
                    # Remote side effects may have occurred. Report uncertainty.
                    job["status"] = "partial"
                    job["error"] = "Job finished but terminal state could not be saved; inspect WordPress"
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                job["status"] = "failed"
                job["updated_at"] = _utc_now()
                job["error"] = f"Job failed ({type(exc).__name__})"
                try:
                    self._persist(job)
                except (OSError, ValueError):
                    job["status"] = "partial"
                    job["error"] = "Job failed and could not persist state; inspect WordPress"

    def get_job(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            return dict(job)

    def list_jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            jobs = [dict(job) for job in self._jobs.values()]
        jobs.sort(key=lambda item: item["created_at"], reverse=True)
        return jobs


job_registry = JobRegistry()


__all__ = ["JobRegistry", "job_registry"]
