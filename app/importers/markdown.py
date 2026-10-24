"""单篇 Markdown 导入：支持设计文档 7.1 的嵌套头信息，也兼容扁平字段。"""
from __future__ import annotations

from pathlib import Path

from ..frontmatter import split_frontmatter
from ..models import RecordError, record_from_dict
from . import Importer, ParseResult, RawItem


def _flatten(meta: dict) -> dict:
    """把嵌套头信息摊平到 8.1 契约的字段名上。"""
    payload: dict = {}
    for key, value in (meta or {}).items():
        if key in {"source", "author"} and isinstance(value, dict):
            continue
        payload[key] = value

    source = meta.get("source") if isinstance(meta.get("source"), dict) else {}
    author = meta.get("author") if isinstance(meta.get("author"), dict) else {}

    mapping = {
        "source_platform": ("platform", "source_platform"),
        "source_space_id": ("space_id", "source_space_id"),
        "source_space_name": ("space_name", "source_space_name"),
        "source_item_id": ("item_id", "source_item_id"),
        "source_url": ("url", "source_url"),
    }
    for target, (nested_key, flat_key) in mapping.items():
        value = source.get(nested_key) or meta.get(flat_key)
        if value:
            payload[target] = value

    if author.get("name") or meta.get("author_name"):
        payload["author_name"] = author.get("name") or meta.get("author_name")
    if author.get("id") or meta.get("author_id"):
        payload["author_id"] = author.get("id") or meta.get("author_id")

    refs = meta.get("source_provided_stock_refs")
    if refs and "stocks" not in payload:
        payload["stocks"] = refs
    return payload


class MarkdownImporter(Importer):
    format_name = "markdown"
    suffixes = (".md", ".markdown")

    def parse(self, path: Path) -> ParseResult:
        text = path.read_text(encoding="utf-8", errors="replace")
        meta, body = split_frontmatter(text)
        payload = _flatten(meta)
        payload["content_text"] = body
        if not payload.get("title"):
            payload["title"] = path.stem
        try:
            record = record_from_dict(payload, line_hint=path.name)
        except RecordError as exc:
            return ParseResult(self.format_name, [RawItem(line_no=None, error=str(exc))])
        record.warnings.append("来源：Markdown 文件级导入")
        return ParseResult(self.format_name, [RawItem(line_no=None, record=record)])
