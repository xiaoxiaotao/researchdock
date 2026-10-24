"""导入适配器注册表。

每个适配器把文件切成若干「条目」，每个条目要么解析成 ParsedRecord，
要么带一个可定位的错误（行号），由流水线写入 import_results。
新增格式（PDF/OCR/HTML）时只需在此注册，不改流水线。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..models import ParsedRecord


@dataclass
class RawItem:
    line_no: int | None
    record: ParsedRecord | None = None
    error: str | None = None


@dataclass
class ParseResult:
    file_format: str
    items: list[RawItem]


class Importer:
    format_name = "base"
    suffixes: tuple[str, ...] = ()

    def parse(self, path: Path) -> ParseResult:  # pragma: no cover - 接口定义
        raise NotImplementedError

    def matches(self, path: Path) -> bool:
        return path.suffix.lower() in self.suffixes


def registry() -> list[Importer]:
    from .jsonl import JsonlImporter
    from .markdown import MarkdownImporter
    from .txt import TxtImporter
    from .pdf import PdfImporter

    return [JsonlImporter(), MarkdownImporter(), TxtImporter(), PdfImporter()]


def find_importer(path: Path) -> Importer | None:
    for importer in registry():
        if importer.matches(path):
            return importer
    return None


SUPPORTED_SUFFIXES = (".jsonl", ".md", ".markdown", ".txt", ".pdf")
