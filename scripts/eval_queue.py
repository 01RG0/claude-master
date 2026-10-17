"""Queue management with atomic file leases for parallel eval swarm."""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "data" / "eval"
QUEUE_PATH = EVAL_DIR / "queue.jsonl"
LEDGER_PATH = EVAL_DIR / "swarm_ledger.jsonl"
BUGS_PATH = EVAL_DIR / "bugs.jsonl"
RESULTS_DIR = EVAL_DIR / "results"


class SwarmQueue:
    """Atomic file-based job queue for parallel evaluation workers."""

    def __init__(self, queue_path: Optional[Path] = None):
        self.queue_path = queue_path or QUEUE_PATH
        self.eval_dir = self.queue_path.parent
        self.eval_dir.mkdir(parents=True, exist_ok=True)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    def _lock_and_read(self) -> List[Dict[str, Any]]:
        """Read all jobs from queue.jsonl safely with retry loop for Windows concurrency."""
        if not self.queue_path.exists():
            return []
        import random
        for attempt in range(10):
            try:
                jobs = []
                with open(self.queue_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                jobs.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
                return jobs
            except (PermissionError, OSError):
                time.sleep(0.05 * (2 ** attempt) + random.uniform(0.01, 0.05))
        return []

    def _atomic_write_all(self, jobs: List[Dict[str, Any]]) -> None:
        """Atomically overwrite queue.jsonl with retry loop for Windows concurrency."""
        import random
        tmp_path = self.queue_path.with_name(f"queue_{os.getpid()}_{time.time_ns()}_{random.randint(1000, 9999)}.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            for j in jobs:
                f.write(json.dumps(j, ensure_ascii=False) + "\n")
        
        # Retry loop for Windows file locking contention
        for attempt in range(10):
            try:
                os.replace(tmp_path, self.queue_path)
                return
            except (PermissionError, OSError):
                time.sleep(0.05 * (2 ** attempt) + random.uniform(0.01, 0.05))
        
        # Final attempt if retries exhausted
        if tmp_path.exists():
            try:
                os.replace(tmp_path, self.queue_path)
            except Exception:
                shutil.copyfile(tmp_path, self.queue_path)
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def initialize_queue(self, jobs: List[Dict[str, Any]], overwrite: bool = False) -> int:
        """Initialize queue with jobs. If already exists and not overwrite, returns count."""
        if self.queue_path.exists() and not overwrite:
            existing = self._lock_and_read()
            if existing:
                return len(existing)

        self._atomic_write_all(jobs)
        return len(jobs)

    def claim_job(
        self,
        worker_id: str,
        stage: int,
        provider: Optional[str] = None,
        lease_duration: float = 120.0,
    ) -> Optional[Dict[str, Any]]:
        """Atomically claim a queued or expired job for given stage and provider."""
        now = time.time()
        jobs = self._lock_and_read()
        claimed_job = None

        s1_passed = {j["route"] for j in jobs if j.get("stage") == 1 and j.get("state") == "done"} if stage == 2 else set()

        for job in jobs:
            # Check stage
            if job.get("stage") != stage:
                continue
            # For stage 2, ensure stage 1 passed
            if stage == 2 and job.get("route") not in s1_passed:
                continue
            # Check provider if specified
            if provider and job.get("provider") != provider:
                continue

            state = job.get("state")
            lease_expiry = job.get("lease_expiry", 0) or 0

            # Eligible if queued OR expired lease
            is_eligible = (state == "queued") or (state == "leased" and now > lease_expiry)

            if is_eligible:
                attempts = job.get("attempts", 0) + 1
                if attempts > 3 and state == "leased":
                    job["state"] = "failed"
                    job["reason_code"] = "max_lease_attempts_exceeded"
                    continue

                job["state"] = "leased"
                job["lease_owner"] = worker_id
                job["lease_expiry"] = round(now + lease_duration, 2)
                job["attempts"] = attempts
                claimed_job = dict(job)
                break

        if claimed_job:
            self._atomic_write_all(jobs)
        return claimed_job

    def heartbeat(self, worker_id: str, job_id: str, lease_duration: float = 120.0) -> bool:
        """Extend lease expiry for an active job."""
        now = time.time()
        jobs = self._lock_and_read()
        updated = False

        for job in jobs:
            if job.get("job_id") == job_id and job.get("lease_owner") == worker_id and job.get("state") == "leased":
                job["lease_expiry"] = round(now + lease_duration, 2)
                updated = True
                break

        if updated:
            self._atomic_write_all(jobs)
        return updated

    def complete_job(
        self,
        job_id: str,
        worker_id: str,
        state: str = "done",
        result_path: Optional[str] = None,
        reason_code: Optional[str] = None,
    ) -> bool:
        """Mark a job completed (done, failed, excluded)."""
        jobs = self._lock_and_read()
        updated = False

        for job in jobs:
            if job.get("job_id") == job_id:
                job["state"] = state
                job["result_path"] = result_path or job.get("result_path")
                if reason_code:
                    job["reason_code"] = reason_code
                job["lease_expiry"] = None
                job["completed_by"] = worker_id
                job["completed_at"] = time.time()
                updated = True
                break

        if updated:
            self._atomic_write_all(jobs)
        return updated

    def reclaim_expired_leases(self) -> int:
        """Reclaim any leased jobs whose lease has expired."""
        now = time.time()
        jobs = self._lock_and_read()
        reclaimed = 0

        for job in jobs:
            if job.get("state") == "leased":
                expiry = job.get("lease_expiry", 0) or 0
                if now > expiry:
                    attempts = job.get("attempts", 0)
                    if attempts >= 3:
                        job["state"] = "failed"
                        job["reason_code"] = "reclaim_max_attempts"
                    else:
                        job["state"] = "queued"
                        job["lease_owner"] = None
                        job["lease_expiry"] = None
                    reclaimed += 1

        if reclaimed > 0:
            self._atomic_write_all(jobs)
        return reclaimed

    def get_stats(self) -> Dict[str, Any]:
        """Get summary statistics of queue state."""
        jobs = self._lock_and_read()
        stats = {
            "total_jobs": len(jobs),
            "by_state": {},
            "by_stage": {},
            "by_provider": {},
        }
        for j in jobs:
            s = j.get("state", "unknown")
            st = j.get("stage", 0)
            p = j.get("provider", "unknown")

            stats["by_state"][s] = stats["by_state"].get(s, 0) + 1
            stats["by_stage"][st] = stats["by_stage"].get(st, 0) + 1
            if p not in stats["by_provider"]:
                stats["by_provider"][p] = {}
            stats["by_provider"][p][s] = stats["by_provider"][p].get(s, 0) + 1
        return stats


def log_ledger_event(
    worker_id: str,
    scope: str,
    event: str,  # started, heartbeat, finished, failed
    jobs_done: int = 0,
    jobs_failed: int = 0,
    cost_usd: float = 0.0,
    notes: str = "",
) -> None:
    """Record worker activity into data/eval/swarm_ledger.jsonl."""
    entry = {
        "timestamp": time.time(),
        "worker_id": worker_id,
        "scope": scope,
        "event": event,
        "jobs_done": jobs_done,
        "jobs_failed": jobs_failed,
        "cost_usd": round(cost_usd, 6),
        "notes": notes,
    }
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_bug(
    bug_id: str,
    worker_id: str,
    component: str,
    description: str,
    reproduction: Dict[str, Any],
    status: str = "open",  # open, fixed, verified
) -> None:
    """Record bug into data/eval/bugs.jsonl."""
    entry = {
        "bug_id": bug_id,
        "timestamp": time.time(),
        "worker_id": worker_id,
        "component": component,
        "description": description,
        "reproduction": reproduction,
        "status": status,
    }
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    with open(BUGS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
