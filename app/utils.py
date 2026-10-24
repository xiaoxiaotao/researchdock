"""通用工具：ULID 生成、时间、哈希、正文规范化。"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import time
import unicodedata
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid() -> str:
    """生成 26 字符 ULID：48 位毫秒时间 + 80 位随机，按字典序近似按时间排序。"""
    ts = int(time.time() * 1000)
    ts_part = ""
    for _ in range(10):
        ts_part = _CROCKFORD[ts % 32] + ts_part
        ts //= 32
    rand = int.from_bytes(secrets.token_bytes(10), "big")
    rand_part = ""
    for _ in range(16):
        rand_part = _CROCKFORD[rand % 32] + rand_part
        rand //= 32
    return ts_part + rand_part


def new_document_id() -> str:
    return "doc_" + ulid()


def new_batch_id() -> str:
    return "imp_" + ulid()


def now_iso() -> str:
    """当前时间，带 +08:00 偏移，秒级。"""
    return datetime.now(TZ).replace(microsecond=0).isoformat()


def today_str() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_BLANK_RUN = re.compile(r"\n{3,}")


def normalize_body(text: str) -> str:
    """正文规范化：仅处理编码形式、换行、行尾空白与多余空行。

    不删除数字与标点，避免把不同财务数据误判为同一份正文（设计文档 8.4）。
    """
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _BLANK_RUN.sub("\n\n", text)
    return text.strip("\n")


def body_hash(text: str) -> str:
    return sha256_text(normalize_body(text))


_INVALID_FS = re.compile(r"[/\\:\x00-\x1f]")


def safe_component(name: str, fallback: str = "untitled", limit: int = 60) -> str:
    """把标题压成可用于文件名的片段，仅用于可读性，不作为主键。"""
    name = _INVALID_FS.sub(" ", name or "").strip()
    name = re.sub(r"\s+", "_", name)
    return (name[:limit] or fallback)


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt


def human_date(value: str | None, precision: str | None = None) -> str:
    """展示用日期；未知返回「未知」，不用导入时间冒充。"""
    dt = parse_iso(value)
    if dt is None:
        return "未知"
    if precision == "date":
        return dt.strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%d %H:%M")


def date_only(value: str | None) -> str:
    dt = parse_iso(value)
    return dt.strftime("%Y-%m-%d") if dt else ""


def rel_age(value: str | None) -> str:
    dt = parse_iso(value)
    if dt is None:
        return ""
    delta = datetime.now(TZ) - dt
    days = delta.days
    if days <= 0:
        return "今天"
    if days == 1:
        return "昨天"
    if days < 30:
        return f"{days} 天前"
    if days < 365:
        return f"{days // 30} 个月前"
    return f"{days // 365} 年前"


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
