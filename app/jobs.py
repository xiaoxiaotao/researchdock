"""Durable single-worker import queue; interrupted scans resume on startup."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from .pipeline import Pipeline
from .storage import atomic_write_json, read_json
from .utils import new_batch_id, now_iso


class ImportJobs:
    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline
        self.root = pipeline.storage.path("jobs/scans")
        self.executor: ThreadPoolExecutor | None = None
        self.lock = threading.RLock()

    def _save(self, job: dict) -> None:
        atomic_write_json(self.root / f"{job['job_id']}.json", job)

    def recent(self) -> list[dict]:
        with self.lock:
            return [read_json(p) for p in sorted(self.root.glob("scan_*.json"), reverse=True)][:20]

    def start(self) -> None:
        with self.lock:
            if self.executor:
                return
            self.root.mkdir(parents=True, exist_ok=True)
            self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kb-import")
            for path in sorted(self.root.glob("scan_*.json")):
                job = read_json(path)
                if job["status"] in {"queued", "running"}:
                    job.update(status="queued", message="恢复未完成的导入任务")
                    self._save(job)
                    self.executor.submit(self._run, job)

    def enqueue(self) -> dict:
        with self.lock:
            if not self.executor:
                raise RuntimeError("导入队列尚未启动")
            # Coalesce waiting scans, but always queue behind a currently running scan.
            for job in self.recent():
                if job["status"] == "queued":
                    return job
            job = {"job_id": "scan_" + new_batch_id()[4:], "status": "queued",
                   "created_at": now_iso(), "finished_at": None, "message": "等待导入"}
            self._save(job)
            self.executor.submit(self._run, job)
            return dict(job)

    def _run(self, job: dict) -> None:
        with self.lock:
            job.update(status="running", message="正在解析并归档")
            self._save(job)
        try:
            report = self.pipeline.scan()
            state = ("partial" if report["created"] + report["updated"] + report["duplicated"] else "failed") if report["failed"] else "succeeded"
            message = f"新增 {report['created']} / 更新 {report['updated']} / 重复 {report['duplicated']} / 失败 {report['failed']}"
            job.update(status=state, report=report, message=message)
        except Exception as exc:
            job.update(status="failed", message=f"{type(exc).__name__}: {exc}")
        finally:
            with self.lock:
                job["finished_at"] = now_iso()
                self._save(job)

    def close(self) -> None:
        executor = self.executor
        if executor:
            executor.shutdown(wait=True)
            self.executor = None
