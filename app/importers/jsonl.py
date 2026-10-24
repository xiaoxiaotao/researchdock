"""JSONL 批次导入：一行一条记录，错误定位到行号。"""
from __future__ import annotations

import json
from pathlib import Path

from ..models import RecordError, record_from_dict
from . import Importer, ParseResult, RawItem


class JsonlImporter(Importer):
    format_name = "jsonl"
    suffixes = (".jsonl", ".json")

    def parse(self, path: Path) -> ParseResult:
        items: list[RawItem] = []
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for idx, line in enumerate(fh, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    items.append(RawItem(line_no=idx, error=f"JSON 解析失败：{exc.msg}（第 {exc.colno} 列）"))
                    continue
                try:
                    record = record_from_dict(payload, line_hint=f"{path.stem} 第{idx}行")
                except RecordError as exc:
                    items.append(RawItem(line_no=idx, error=str(exc)))
                    continue
                items.append(RawItem(line_no=idx, record=record))
        return ParseResult(file_format=self.format_name, items=items)
