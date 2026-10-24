"""导入流水线：发现 → 解析 → 身份识别 → 去重 → 归档 → 索引 → 报告。

关键顺序（设计文档 8.5）：先把原文与 manifest 落盘，再提交 SQLite 事务。
两者之间崩溃时，重启的 `reconcile()` 会依据 manifest 补齐索引，且不会重复建版本。
"""
from __future__ import annotations

import threading
from dataclasses import asdict

from .frontmatter import split_frontmatter
from dataclasses import dataclass, field
from pathlib import Path

from . import index
from .config import Config
from .frontmatter import build_document
from .importers import SUPPORTED_SUFFIXES, find_importer
from .models import ParsedRecord, frontmatter_for, record_from_dict, RecordError, CONTENT_TYPES
from .storage import Storage, StorageNotReady, atomic_write_json, read_json
from .utils import (
    new_batch_id,
    new_document_id,
    normalize_body,
    now_iso,
    sha256_bytes,
    sha256_text,
    today_str,
)

_WRITE_LOCK = threading.RLock()


def _hash_of_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


@dataclass
class RecordOutcome:
    line_no: int | None
    status: str  # created | updated | duplicated | failed
    document_id: str | None = None
    revision: int | None = None
    title: str | None = None
    message: str | None = None


@dataclass
class BatchReport:
    batch_id: str
    file_name: str
    file_format: str
    status: str = "running"
    created: int = 0
    updated: int = 0
    duplicated: int = 0
    failed: int = 0
    outcomes: list[RecordOutcome] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    def summary(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "file_name": self.file_name,
            "file_format": self.file_format,
            "status": self.status,
            "total": self.total,
            "created": self.created,
            "updated": self.updated,
            "duplicated": self.duplicated,
            "failed": self.failed,
        }


class Pipeline:
    def __init__(self, cfg: Config, storage: Storage) -> None:
        self.cfg = cfg
        self.storage = storage

    def inbox_files(self) -> list[Path]:
        if not self.cfg.inbox_dir.exists():
            return []
        return [p for p in sorted(self.cfg.inbox_dir.iterdir())
                if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
                and not p.name.startswith(".")
                and (not self.cfg.require_ready_marker or p.with_name(p.name + ".ready.json").is_file())]

    def scan(self) -> dict:
        reports = []
        with _WRITE_LOCK:
            recovery = self.reconcile()
            if recovery["problems"]:
                raise StorageNotReady("归档校验失败，请先修复：" + "; ".join(recovery["problems"]))
            for path in self.inbox_files():
                try:
                    reports.append(self.import_file(path).summary())
                except (OSError, StorageNotReady) as exc:
                    reports.append({"file_name": path.name, "status": "storage_error", "failed": 1,
                                    "message": str(exc)})
        return {"scanned_files": len(reports), "batches": reports,
                **{key: sum(r.get(key, 0) for r in reports)
                   for key in ("created", "updated", "duplicated", "failed")}}

    def import_file(self, path: Path) -> BatchReport:
        # Public callers and the background worker share one writer lock.
        with _WRITE_LOCK:
            return self._import_file(path)

    def _import_file(self, path: Path) -> BatchReport:
        self.storage.require_ready()
        if path.stat().st_size > self.cfg.max_file_mb * 1024 * 1024:
            raise StorageNotReady(f"文件超过 {self.cfg.max_file_mb}MB 上限：{path.name}")
        file_hash = _hash_of_file(path)
        importer = find_importer(path)
        if importer is None:
            raise StorageNotReady(f"不支持的文件格式：{path.name}")
        original = self.storage.preserve_original(path, file_hash) if path.suffix.lower() == ".pdf" else None
        with index.connect(self.cfg.db_path) as conn:
            done = conn.execute(
                "SELECT batch_id FROM import_batches WHERE file_hash=? AND status='succeeded'",
                (file_hash,),
            ).fetchone()
        if done:
            self._consume_file(path, done["batch_id"])
            return BatchReport(done["batch_id"], path.name, importer.format_name,
                               status="already_processed", duplicated=1,
                               outcomes=[RecordOutcome(None, "duplicated", message="同一文件已处理")])

        report = BatchReport(new_batch_id(), path.name, importer.format_name)
        payload = {"schema_version": 1, "batch_id": report.batch_id, "file_name": path.name,
                   "file_hash": file_hash, "file_format": importer.format_name,
                   "started_at": now_iso(), "finished_at": None, "status": "running",
                   "outcomes": [], "original": original}
        # Batch history is durable independently of SQLite.
        self._persist_batch(payload, report)
        try:
            parsed = importer.parse(path)
            for item in parsed.items:
                if item.error or item.record is None:
                    outcome = RecordOutcome(item.line_no, "failed", message=item.error or "未知解析错误")
                else:
                    if original:
                        item.record.source_item_id = file_hash
                        item.record.attachment = {**original, **(item.record.attachment or {})}
                    try:
                        outcome = self._archive_record(item.record, item.line_no)
                    except Exception as exc:
                        outcome = RecordOutcome(item.line_no, "failed", title=item.record.title,
                                                message=f"{type(exc).__name__}: {exc}")
                report.outcomes.append(outcome)
                setattr(report, outcome.status, getattr(report, outcome.status) + 1)
        except Exception as exc:
            report.failed += 1
            report.outcomes.append(RecordOutcome(None, "failed", message=f"文件解析失败：{exc}"))
        successes = report.created + report.updated + report.duplicated
        report.status = "partial" if report.failed and successes else ("failed" if report.failed else "succeeded")
        payload["finished_at"] = now_iso()
        self._persist_batch(payload, report)
        self._consume_file(path, report.batch_id)
        return report

    def _persist_batch(self, payload: dict, report: BatchReport) -> None:
        payload.update(report.summary())
        payload["outcomes"] = [asdict(o) for o in report.outcomes]
        atomic_write_json(self.storage.path(f"jobs/imports/{report.batch_id}.json"), payload)
        with index.connect(self.cfg.db_path) as conn:
            self._index_batch(conn, payload)

    @staticmethod
    def _index_batch(conn, payload: dict) -> None:
        names = ["batch_id", "file_name", "file_hash", "file_format", "started_at", "finished_at",
                 "total", "created", "updated", "duplicated", "failed", "status"]
        updates = ",".join(f"{name}=excluded.{name}" for name in names[1:])
        conn.execute(f"INSERT INTO import_batches({','.join(names)}) VALUES ({','.join('?' for _ in names)}) "
                     f"ON CONFLICT(batch_id) DO UPDATE SET {updates}", [payload.get(n) for n in names])
        conn.execute("DELETE FROM import_results WHERE batch_id=?", (payload["batch_id"],))
        for outcome in payload.get("outcomes", []):
            conn.execute("INSERT INTO import_results(batch_id,line_no,status,document_id,revision,title,message) "
                         "VALUES (?,?,?,?,?,?,?)", [payload["batch_id"], *[outcome.get(n) for n in
                         ("line_no", "status", "document_id", "revision", "title", "message")]])

    @staticmethod
    def _fields(record: ParsedRecord) -> dict:
        return {"content_type": record.content_type, "source_platform": record.source_platform or None,
                "source_space_id": record.source_space_id or None,
                "source_space_name": record.source_space_name or None,
                "source_item_id": record.source_item_id or None, "source_url": record.source_url or None,
                "author_name": record.author_name or None, "author_id": record.author_id or None,
                "published_at": record.published_at, "date_precision": record.date_precision,
                "source_updated_at": record.source_updated_at, "event_date": record.event_date,
                "institution": record.institution or None, "report_period": record.report_period or None,
                "tags": record.tags, "language": record.language,
                "source_attachments": record.source_attachments,
                "excerpt": next((p["text"][:160] for p in record.pages if p["text"].strip()), record.first_paragraph),
                "stocks": [{"stock_id": st.stock_id, "code": st.code.zfill(6) if st.code.isdigit() else st.code,
                            "name": st.name or None, "market": st.market, "exchange": st.exchange,
                            "evidence": st.evidence,
                            "status": "pending" if st.evidence == "inferred" else "confirmed"}
                           for st in record.stocks]}

    def _archive_record(self, record: ParsedRecord, line_no: int | None) -> RecordOutcome:
        body = normalize_body(record.content_text)
        source_key = record.source_key
        fields = self._fields(record)
        with index.connect(self.cfg.db_path) as conn:
            existing = None
            if source_key:
                existing = conn.execute("SELECT * FROM documents WHERE source_key=? AND deleted_at IS NULL",
                                        (source_key,)).fetchone()
            else:
                # Use normalized archived content, also tolerating legacy hashes with final newline.
                candidates = conn.execute("SELECT d.*, r.archive_path FROM documents d JOIN document_revisions r "
                    "ON r.document_id=d.document_id AND r.revision=d.current_revision "
                    "WHERE IFNULL(d.source_platform,'')=? AND d.deleted_at IS NULL",
                    (record.source_platform or "",)).fetchall()
                for candidate in candidates:
                    _, archived = split_frontmatter(self.storage.read_revision_text(candidate["archive_path"]))
                    if normalize_body(archived) == body:
                        existing = candidate
                        break
        imported_at = now_iso()
        if existing:
            manifest = self.storage.read_manifest(existing["document_id"])
            if not manifest:
                raise StorageNotReady("索引存在但 manifest 缺失，拒绝覆盖")
            current_number = manifest["current_revision"]
            current = next(r for r in manifest["revisions"] if r["revision"] == current_number)
            _, old_body = split_frontmatter(self.storage.read_revision_text(current["archive_path"]))
            old_fields = manifest.get("fields", {})
            # New metadata is deliberately versioned even when the text has not changed.
            if (normalize_body(old_body) == body and manifest.get("title") == record.title
                    and old_fields == fields):
                return RecordOutcome(line_no, "duplicated", existing["document_id"], current_number,
                                     record.title, "正文与元信息一致")
            document_id = existing["document_id"]
            # A crash before manifest commit may leave an orphan revision. Keep it
            # untouched and allocate a fresh number rather than blocking retries.
            disk_numbers = [int(p.stem[1:]) for p in self.storage.path("archive").glob(f"*/*/{document_id}/r*.md")
                            if p.stem[1:].isdigit()]
            revision = max([current_number, *disk_numbers]) + 1
            status = "updated"
        else:
            document_id, revision, status = new_document_id(), 1, "created"
            manifest = {"schema_version": 1, "document_id": document_id,
                        "created_at": imported_at, "deleted_at": None, "revisions": []}
        meta = frontmatter_for(record, document_id, revision, imported_at)
        revision_row = self.storage.write_revision(document_id, revision, imported_at, build_document(meta, body))
        revision_row["document_id"] = document_id
        if record.attachment:
            revision_row["attachment"] = record.attachment
            page_path = self.storage.resolve_path(revision_row["archive_path"]).with_suffix(".pages.json")
            atomic_write_json(page_path, {"schema_version": 1, "pages": record.pages})
            revision_row["pages_path"] = str(page_path.relative_to(self.storage.root))
            revision_row["pages_hash"] = _hash_of_file(page_path)
        manifest.update(current_revision=revision, title=record.title, source_key=source_key, fields=fields)
        manifest["revisions"].append(revision_row)
        self.storage.write_manifest(manifest)
        with index.connect(self.cfg.db_path) as conn:
            self._index_manifest(conn, manifest)
        self._sync_catalog(record)
        return RecordOutcome(line_no, status, document_id, revision, record.title,
                             "; ".join(record.warnings) or None)

    def _index_manifest(self, conn, manifest: dict, catalog: dict | None = None) -> None:
        document_id = manifest["document_id"]
        fields = manifest.get("fields", {})
        current = next(r for r in manifest["revisions"] if r["revision"] == manifest["current_revision"])
        for rev in manifest["revisions"]:
            conn.execute("INSERT INTO document_revisions(document_id,revision,archive_path,body_hash,file_hash,imported_at,body_chars) "
                         "VALUES (?,?,?,?,?,?,?) ON CONFLICT(document_id,revision) DO UPDATE SET "
                         "archive_path=excluded.archive_path,body_hash=excluded.body_hash,file_hash=excluded.file_hash",
                         (document_id, rev["revision"], rev["archive_path"], rev["body_hash"], rev["file_hash"],
                          rev["imported_at"], rev.get("body_chars", 0)))
        index.upsert_document(conn, {**fields, "document_id": document_id,
            "title": manifest.get("title") or "无标题", "source_key": manifest.get("source_key"),
            "current_revision": current["revision"], "imported_at": current["imported_at"],
            "first_imported_at": manifest.get("created_at") or current["imported_at"],
            "body_chars": current.get("body_chars", 0), "deleted_at": manifest.get("deleted_at")},
            {**current, "document_id": document_id})
        meta, body = split_frontmatter(self.storage.read_revision_text(current["archive_path"]))
        legacy_evidence = {ref.get("stock_id"): ref.get("evidence")
                           for ref in meta.get("source_provided_stock_refs", [])}
        index.replace_search(conn, document_id, manifest.get("title") or "无标题", body)
        for rev in manifest["revisions"]:
            pages = self.pages_for_revision(rev)
            index.replace_pages(conn, document_id, rev["revision"], pages)
        # Replace only source-exported associations; future manual associations remain intact.
        conn.execute("DELETE FROM document_stocks WHERE document_id=? AND method='export'", (document_id,))
        refs = fields.get("stocks")
        if refs is None:
            refs = [{"stock_id": sid} for sid in fields.get("stock_ids", [])]
        for ref in refs:
            sid = ref.get("stock_id")
            if not sid:
                continue
            parts = sid.split(".")
            name = ref.get("name") or ((catalog or {}).get(sid) or {}).get("display_name") or ""
            index.upsert_stock(conn, sid, ref.get("code") or parts[-1], name,
                               ref.get("market") or parts[0], ref.get("exchange") or (parts[1] if len(parts) == 3 else ""))
            state = ref.get("status")
            if state not in {"pending", "confirmed"}:
                state = "pending" if ref.get("evidence", legacy_evidence.get(sid)) == "inferred" else "confirmed"
            index.link_document_stock(conn, document_id, sid, "export", state)

    def pages_for_revision(self, revision: dict) -> list[dict]:
        if not revision.get("pages_path"):
            return []
        payload = read_json(self.storage.resolve_path(revision["pages_path"]))
        if payload is None:
            raise StorageNotReady("PDF 按页正文缺失，请恢复归档文件")
        return payload["pages"]

    def update_metadata(self, document_id: str, changes: dict) -> RecordOutcome:
        """User edits become immutable versions, including PDF provenance/page data."""
        with _WRITE_LOCK:
            manifest = self.storage.read_manifest(document_id)
            if not manifest:
                raise RecordError("资料不存在")
            revision = next(r for r in manifest["revisions"] if r["revision"] == manifest["current_revision"])
            _, body = split_frontmatter(self.storage.read_revision_text(revision["archive_path"]))
            payload = {**manifest["fields"], "title": manifest["title"], "content_text": body}
            for key in ("title", "content_type", "institution", "report_period", "published_at"):
                if key in changes:
                    if changes[key] is not None and not isinstance(changes[key], str):
                        raise RecordError(f"{key} 必须是文本")
                    payload[key] = changes[key]
            if not str(payload.get("title") or "").strip():
                raise RecordError("标题不能为空")
            if payload.get("content_type") not in CONTENT_TYPES:
                raise RecordError("资料类型无效")
            if "published_at" in changes:
                value = changes["published_at"]
                if value:
                    from datetime import date
                    try:
                        date.fromisoformat(value)
                    except ValueError:
                        raise RecordError("发布日期应为 YYYY-MM-DD")
                payload["date_precision"] = "date" if value else "unknown"
            if "stock_codes" in changes:
                codes = changes["stock_codes"]
                if not isinstance(codes, str):
                    raise RecordError("股票代码必须是文本")
                import re
                values = list(dict.fromkeys(re.split(r"[,，\s]+", codes.strip()))) if codes.strip() else []
                if any(not re.fullmatch(r"\d{6}", v) for v in values):
                    raise RecordError("此编辑入口接受六位 A 股代码，多个代码用逗号分隔")
                old = {st.get("code"): st for st in payload.get("stocks", [])}
                payload["stocks"] = [{**old.get(code, {}), "code": code, "evidence": "user_confirmed"}
                                     for code in values]
            record = record_from_dict(payload)
            record.attachment = revision.get("attachment")
            record.pages = self.pages_for_revision(revision)
            outcome = self._archive_record(record, None)
            # Preserve deliberate user classifications when the source is refreshed.
            saved = self.storage.read_manifest(document_id)
            overrides = saved.setdefault("manual_fields", {})
            for key in ("title", "content_type", "institution", "report_period", "published_at"):
                if key in changes:
                    overrides[key] = getattr(record, key)
            if "published_at" in changes:
                overrides["date_precision"] = record.date_precision
            if "stock_codes" in changes:
                overrides["stocks"] = saved["fields"]["stocks"]
            self.storage.write_manifest(saved)
            return outcome

    def _sync_catalog(self, record: ParsedRecord) -> None:
        if not record.stocks:
            return
        path = self.storage.path("catalog/stocks.json")
        catalog = read_json(path) or {"schema_version": 1, "stocks": {}}
        for stock in record.stocks:
            entry = catalog["stocks"].setdefault(stock.stock_id, {
                "market": stock.market, "exchange": stock.exchange,
                "code": stock.code.zfill(6) if stock.code.isdigit() else stock.code,
                "display_name": stock.name or stock.stock_id, "aliases": [],
                "mapping_source": "import", "first_seen_at": now_iso()})
            if stock.name:
                entry["display_name"] = stock.name
        atomic_write_json(path, catalog)

    def _consume_file(self, path: Path, batch_id: str) -> None:
        self.storage.archive_copy(batch_id, path)
        path.unlink()
        path.with_name(path.name + ".ready.json").unlink(missing_ok=True)

    def reconcile(self) -> dict:
        inserted = fixed = 0
        problems = []
        with _WRITE_LOCK:
            catalog = (read_json(self.storage.path("catalog/stocks.json")) or {}).get("stocks", {})
            for manifest_path in sorted(self.storage.path("manifests/documents").glob("doc_*.json")):
                document_id = manifest_path.stem
                try:
                    manifest = read_json(manifest_path)
                    if not manifest or manifest.get("document_id") != document_id:
                        raise StorageNotReady("manifest 文档身份无效")
                    revisions = manifest.get("revisions") or []
                    if not revisions or not any(r["revision"] == manifest.get("current_revision") for r in revisions):
                        raise StorageNotReady("manifest 当前版本无效")
                    for rev in revisions:
                        path = self.storage.resolve_path(rev["archive_path"])
                        if not path.exists() or _hash_of_file(path) != rev["file_hash"]:
                            raise StorageNotReady(f"归档文件缺失或校验失败：{rev['archive_path']}")
                        attachment = rev.get("attachment")
                        if attachment:
                            original = self.storage.resolve_path(attachment["path"])
                            if not original.is_file() or _hash_of_file(original) != attachment["file_hash"]:
                                raise StorageNotReady("PDF 原件缺失或校验失败")
                        if rev.get("pages_hash"):
                            page_file = self.storage.resolve_path(rev["pages_path"])
                            if not page_file.is_file() or _hash_of_file(page_file) != rev["pages_hash"]:
                                raise StorageNotReady("PDF 按页正文缺失或校验失败")
                    with index.connect(self.cfg.db_path) as conn:
                        existed = index.get_document(conn, document_id)
                        count = conn.execute("SELECT COUNT(*) FROM document_revisions WHERE document_id=?", (document_id,)).fetchone()[0]
                        self._index_manifest(conn, manifest, catalog)
                        inserted += int(existed is None)
                        fixed += max(0, len(revisions) - count)
                except (StorageNotReady, OSError, KeyError, ValueError) as exc:
                    problems.append(f"{document_id}：{exc}")
            for path in sorted(self.storage.path("jobs/imports").glob("imp_*.json")):
                try:
                    payload = read_json(path)
                    if payload:
                        if payload.get("status") == "running":
                            payload["status"] = "interrupted"
                            atomic_write_json(path, payload)
                        with index.connect(self.cfg.db_path) as conn:
                            self._index_batch(conn, payload)
                except (StorageNotReady, OSError, KeyError, ValueError) as exc:
                    problems.append(f"{path.name}：{exc}")
        return {"inserted": inserted, "revisions_fixed": fixed, "problems": problems}

    def rebuild_index(self) -> dict:
        self.storage.require_ready()
        with _WRITE_LOCK:
            for suffix in ("", "-wal", "-shm"):
                Path(str(self.cfg.db_path) + suffix).unlink(missing_ok=True)
            index.init_schema(self.cfg.db_path)
            return {"rebuilt": True, **self.reconcile()}


def ensure_ready(cfg: Config, storage: Storage) -> None:
    storage.ensure_layout()
    index.init_schema(cfg.db_path)


def today_stats(cfg: Config) -> dict:
    with index.connect(cfg.db_path) as conn:
        return index.stats(conn, today_str())
