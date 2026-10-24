"""纯文本导入：支持可选的「标题: 值」头信息块，兼容只有正文的情况。"""
from __future__ import annotations

import re
from pathlib import Path

from ..models import RecordError, record_from_dict
from . import Importer, ParseResult, RawItem

HEADER_KEYS = {
    "标题": "title",
    "来源": "source_platform",
    "星球": "source_space_name",
    "空间": "source_space_id",
    "帖子id": "source_item_id",
    "帖子": "source_item_id",
    "作者": "author_name",
    "发布时间": "published_at",
    "日期": "published_at",
    "类型": "content_type",
    "代码": "stock_codes",
    "股票": "stock_codes",
    "标签": "tags",
}

_LINE = re.compile(r"^([\u4e00-\u9fa5A-Za-z]{2,8})\s*[:：]\s*(.+)$")


def _parse(path: Path, text: str) -> dict:
    payload: dict = {}
    lines = text.split("\n")
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if not line:
            idx += 1
            continue
        match = _LINE.match(line)
        if not match:
            break
        key = match.group(1).strip().lower()
        target = HEADER_KEYS.get(key)
        if not target:
            break
        value = match.group(2).strip()
        if target == "stock_codes":
            payload.setdefault("stocks", []).extend(
                part.strip() for part in re.split(r"[,，、;；\s]+", value) if part.strip()
            )
        elif target == "tags":
            payload["tags"] = [p.strip() for p in re.split(r"[,，、;；\s]+", value) if p.strip()]
        else:
            payload[target] = value
        idx += 1

    body = "\n".join(lines[idx:]).strip("\n")
    if not body:
        raise RecordError("解析头信息后正文为空")
    payload["content_text"] = body
    if not payload.get("title"):
        first = body.split("\n", 1)[0].strip().lstrip("#").strip()
        payload["title"] = first[:60] or path.stem
    return payload


class TxtImporter(Importer):
    format_name = "txt"
    suffixes = (".txt",)

    def parse(self, path: Path) -> ParseResult:
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            payload = _parse(path, text)
            record = record_from_dict(payload, line_hint=path.name)
        except RecordError as exc:
            return ParseResult(self.format_name, [RawItem(line_no=None, error=str(exc))])
        if not record.published_at:
            record.warnings.append("无发布时间，按未知处理（文件名日期不作为发表日期）")
        return ParseResult(self.format_name, [RawItem(line_no=None, record=record)])
