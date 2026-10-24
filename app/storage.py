"""数据目录、原子写入与 manifest 读写。

权威性约定（设计文档 6.2）：
- 原文与 manifest 是不可重建的资产，SQLite 只是它们的运行视图；
- 所有文件更新走「同目录临时文件 → flush+fsync → os.replace」；
- 数据根目录不存在时，只有父目录存在且允许创建才初始化，禁止对未挂载的卷路径递归建目录。
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from .utils import now_iso, sha256_bytes, sha256_text, normalize_body

LAYOUT = [
    "originals",
    "jobs/imports",
    "inbox",
    "processed",
    "quarantine",
    "archive",
    "manifests/documents",
    "catalog",
    "annotations",
    "notes",
    "reports",
    "conversations",
    "derived/summaries",
    "derived/embeddings",
    "index",
    "jobs",
    "backups",
]

STORAGE_MARKER = "storage.json"
LIBRARY_SCHEMA_VERSION = 1


class StorageNotReady(RuntimeError):
    """数据根目录不可用：未挂载、只读或结构损坏。"""


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, payload: dict) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise StorageNotReady(f"JSON 解析失败：{path}：{exc}") from exc


class Storage:
    def __init__(self, data_dir: Path, allow_create: bool = True) -> None:
        self.root = Path(data_dir).resolve()
        self.allow_create = allow_create
        self._ready = False

    # ---------- 初始化与守卫 ----------

    def ensure_layout(self) -> None:
        """建立目录结构并写入库标记；父目录不存在时拒绝创建。"""
        if not self.root.exists():
            if not self.allow_create:
                raise StorageNotReady(
                    f"数据目录不存在且未允许创建：{self.root}。"
                    "若这是外置盘路径，请先确认硬盘已挂载。"
                )
            parent = self.root.parent
            if not parent.exists():
                raise StorageNotReady(
                    f"上级目录不存在，疑似外置盘未挂载，拒绝创建：{self.root}"
                )
            self.root.mkdir(parents=False, exist_ok=False)

        if not os.access(self.root, os.W_OK):
            raise StorageNotReady(f"数据目录不可写：{self.root}")

        for rel in LAYOUT:
            (self.root / rel).mkdir(parents=True, exist_ok=True)

        marker_path = self.root / STORAGE_MARKER
        marker = read_json(marker_path)
        if marker is None:
            import uuid

            atomic_write_json(
                marker_path,
                {
                    "library_id": "lib_" + uuid.uuid4().hex[:20],
                    "schema_version": LIBRARY_SCHEMA_VERSION,
                    "created_at": now_iso(),
                    "note": "本文件标识知识库身份，请勿删除或修改。",
                },
            )
        elif marker.get("schema_version") != LIBRARY_SCHEMA_VERSION:
            raise StorageNotReady(
                f"库结构版本不匹配：文件为 {marker.get('schema_version')}，"
                f"程序期望 {LIBRARY_SCHEMA_VERSION}，请先迁移。"
            )
        self._ready = True

    @property
    def ready(self) -> bool:
        return self._ready

    def require_ready(self) -> None:
        if not self._ready:
            raise StorageNotReady("知识库尚未就绪")

    # ---------- 路径 ----------

    @property
    def marker(self) -> dict:
        return read_json(self.root / STORAGE_MARKER) or {}

    def path(self, rel: str) -> Path:
        return self.root / rel

    def archive_dir(self, document_id: str, imported_at: str) -> Path:
        """archive/YYYY/MM/<document_id>/，年月取自导入时间。"""
        year = imported_at[0:4]
        month = imported_at[5:7]
        return self.root / "archive" / year / month / document_id

    def revision_path(self, document_id: str, revision: int, imported_at: str) -> Path:
        return self.archive_dir(document_id, imported_at) / f"r{revision:04d}.md"

    def manifest_path(self, document_id: str) -> Path:
        return self.root / "manifests" / "documents" / f"{document_id}.json"

    # ---------- manifest ----------

    def read_manifest(self, document_id: str) -> dict | None:
        return read_json(self.manifest_path(document_id))

    def write_manifest(self, manifest: dict) -> None:
        atomic_write_json(self.manifest_path(manifest["document_id"]), manifest)

    def iter_manifests(self):
        base = self.root / "manifests" / "documents"
        if not base.exists():
            return
        for path in sorted(base.glob("doc_*.json")):
            try:
                payload = read_json(path)
            except StorageNotReady:
                continue
            if payload:
                yield payload

    # ---------- 归档写入 ----------

    def write_revision(self, document_id: str, revision: int, imported_at: str, text: str) -> dict:
        path = self.revision_path(document_id, revision, imported_at)
        if path.exists():
            raise FileExistsError(f"版本文件已存在，拒绝覆盖：{path}")
        atomic_write_text(path, text)
        data = path.read_bytes()
        return {
            "revision": revision,
            "archive_path": str(path.relative_to(self.root)),
            "file_hash": "sha256:" + sha256_bytes(data),
            "body_hash": "sha256:" + sha256_text(normalize_body(_split_body(text))),
            "imported_at": imported_at,
            "body_chars": len(_split_body(text)),
        }

    def read_revision_text(self, rel_path: str) -> str:
        path = self.resolve_path(rel_path)
        if not path.exists():
            raise StorageNotReady(f"归档文件缺失：{rel_path}")
        return path.read_text(encoding="utf-8")

    def resolve_path(self, rel_path: str) -> Path:
        path = (self.root / rel_path).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise StorageNotReady("文件路径超出知识库目录")
        return path

    def preserve_original(self, path: Path, file_hash: str) -> dict:
        """Preserve bytes before parsing, including encrypted/scanned/broken PDFs."""
        digest = file_hash.removeprefix("sha256:")
        target = self.root / "originals" / digest[:2] / f"{digest}.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as out, path.open("rb") as src:
                    shutil.copyfileobj(src, out)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(tmp, target)
            finally:
                Path(tmp).unlink(missing_ok=True)
        return {"path": str(target.relative_to(self.root)), "file_hash": file_hash,
                "file_name": path.name, "mime_type": "application/pdf", "size": target.stat().st_size}

    def quarantine(self, batch_id: str, file_name: str, payload: bytes | str, reason: str) -> Path:
        target_dir = self.root / "quarantine" / batch_id
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_name = file_name.replace("/", "_")
        if isinstance(payload, str):
            data: bytes | str = payload
        else:
            data = payload
        if isinstance(data, str):
            atomic_write_text(target_dir / safe_name, data)
        else:
            (target_dir / safe_name).write_bytes(data)
        atomic_write_text(target_dir / "reason.txt", reason + "\n")
        return target_dir

    def archive_copy(self, batch_id: str, path: Path) -> Path:
        """把已消费的导入包复制到 processed/ 保留追溯。"""
        target_dir = self.root / "processed" / batch_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / path.name
        shutil.copy2(path, target)
        return target

    def disk_usage(self) -> dict:
        try:
            usage = shutil.disk_usage(self.root)
        except OSError:
            return {"total": None, "free": None, "used_pct": None}
        pct = round(usage.used / usage.total * 100, 1) if usage.total else None
        return {"total": usage.total, "free": usage.free, "used_pct": pct}


def _split_body(file_text: str) -> str:
    from .frontmatter import split_frontmatter

    _, body = split_frontmatter(file_text)
    return body
