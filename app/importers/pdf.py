"""Local text-PDF adapter. No OCR or inferred financial metadata."""
from __future__ import annotations

from pathlib import Path

import pypdf
from pypdf import PdfReader

from . import Importer, ParseResult, RawItem
from ..models import ParsedRecord
from ..utils import normalize_body


class PdfImporter(Importer):
    format_name = "pdf"
    suffixes = (".pdf",)

    def parse(self, path: Path) -> ParseResult:
        try:
            with path.open("rb") as stream:
                reader = PdfReader(stream)
                if reader.is_encrypted and not reader.decrypt(""):
                    raise ValueError("PDF 已加密，请先提供已解密的副本")
                if len(reader.pages) > 2000:
                    raise ValueError("PDF 超过 2000 页，请拆分后导入")
                pages = []
                empty = []
                for number, page in enumerate(reader.pages, 1):
                    contents = page.get_contents()
                    if contents and len(contents.get_data()) > 25 * 1024 * 1024:
                        raise ValueError(f"第 {number} 页内容流过大，请拆分或重新导出 PDF")
                    text = normalize_body(page.extract_text() or "")
                    pages.append({"number": number, "text": text})
                    if not text.strip():
                        empty.append(number)
                if not any(p["text"].strip() for p in pages):
                    raise ValueError("未提取到文字，可能为扫描件；原件已保留，请 OCR 后重试")
                metadata = reader.metadata
                title = str(metadata.title or "").strip() if metadata else ""
                if title.lower() in {"", "untitled", "无标题"}:
                    title = path.stem
                record = ParsedRecord(
                    title=title, content_type="other", source_platform="local_pdf",
                    content_text="\n\n".join(
                        f"## 第 {p['number']} 页\n\n{p['text']}" for p in pages),
                    pages=pages,
                    warnings=[f"文本 PDF，共 {len(pages)} 页；表格、图表请核对原件"],
                )
                if empty:
                    record.warnings.append("以下页无可提取文字，未做 OCR：" + ", ".join(map(str, empty)))
                # The engine/version is recorded with the attachment by the pipeline.
                record.attachment = {"parser": "pypdf", "parser_version": pypdf.__version__,
                                     "page_count": len(pages), "empty_pages": empty}
                return ParseResult(self.format_name, [RawItem(None, record=record)])
        except Exception as exc:
            return ParseResult(self.format_name, [RawItem(None, error=f"PDF 解析失败：{exc}")])
