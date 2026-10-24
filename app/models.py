"""导入记录的数据结构与字段校验。

来源：设计文档 7.2（字段规则）与 8.1（WorkBuddy 输出契约）。
原则：源里没有的字段一律保留为未知，不用导入时间或模型猜测填补。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .utils import normalize_body

CONTENT_TYPES = {
    "company_report": "公司研报",
    "industry_report": "行业研报",
    "macro_report": "宏观报告",
    "strategy_report": "策略报告",
    "quarterly_report": "季报",
    "interim_report": "半年报",
    "community_post": "星球帖",
    "research_note": "调研纪要",
    "annual_report": "年报",
    "monthly_report": "月报",
    "announcement": "公告",
    "news": "资讯",
    "other": "其他",
}

CONTENT_TYPE_ALIASES = {
    "公司研报": "company_report",
    "行业研报": "industry_report",
    "宏观报告": "macro_report",
    "策略报告": "strategy_report",
    "季报": "quarterly_report",
    "半年报": "interim_report",
    "帖子": "community_post",
    "星球帖": "community_post",
    "调研": "research_note",
    "调研纪要": "research_note",
    "纪要": "research_note",
    "年报": "annual_report",
    "年度报告": "annual_report",
    "月报": "monthly_report",
    "月度报告": "monthly_report",
    "公告": "announcement",
    "资讯": "news",
    "新闻": "news",
    "其他": "other",
}

DATE_PRECISIONS = {"second", "date", "unknown"}

_CODE_RE = re.compile(r"^\d{5,6}$")


class RecordError(ValueError):
    """单条记录无法解析；不影响同批其它记录。"""


@dataclass
class StockRef:
    code: str
    name: str = ""
    market: str = "CN"
    exchange: str = ""
    evidence: str = "mentioned"  # mentioned | inferred | user_confirmed

    @property
    def stock_id(self) -> str:
        code = self.code.zfill(6) if self.code.isdigit() else self.code
        ex = (self.exchange or self._guess_exchange(code)).upper()
        return f"{self.market.upper()}.{ex}.{code}"

    @staticmethod
    def _guess_exchange(code: str) -> str:
        if code.startswith(("60", "68", "51", "58", "11")):
            return "SH"
        if code.startswith(("00", "30", "12", "15")):
            return "SZ"
        if code.startswith(("43", "83", "87", "92")):
            return "BJ"
        return "SZ"


@dataclass
class ParsedRecord:
    title: str
    content_text: str
    source_platform: str = ""
    source_space_id: str = ""
    source_space_name: str = ""
    source_item_id: str = ""
    source_url: str = ""
    author_id: str = ""
    author_name: str = ""
    published_at: str | None = None
    source_updated_at: str | None = None
    event_date: str | None = None
    date_precision: str = "unknown"
    content_type: str = "community_post"
    language: str = "zh-CN"
    stocks: list[StockRef] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    institution: str = ""
    report_period: str = ""
    source_attachments: list[dict] = field(default_factory=list)
    # Only trusted import adapters set attachment/page data, never arbitrary JSON paths.
    attachment: dict | None = None
    pages: list[dict] = field(default_factory=list)

    @property
    def source_key(self) -> str | None:
        """平台|空间|帖子 ID。任一缺失即视为无稳定身份（设计文档 10.2）。"""
        if self.source_platform and self.source_item_id:
            return f"{self.source_platform}|{self.source_space_id or '-'}|{self.source_item_id}"
        return None

    @property
    def body(self) -> str:
        return normalize_body(self.content_text)

    @property
    def first_paragraph(self) -> str:
        for block in self.body.split("\n\n"):
            text = block.strip().lstrip("#").strip()
            if text and not text.startswith("|"):
                return text[:160]
        return self.body[:160]


def _first(payload: dict, *keys, default=None):
    for key in keys:
        if key in payload and payload[key] not in (None, "", []):
            return payload[key]
    return default


def _as_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return str(value).strip()


def _parse_stocks(raw) -> list[StockRef]:
    refs: list[StockRef] = []
    if not raw:
        return refs
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return refs
    for item in raw:
        if isinstance(item, str):
            text = item.strip()
            if not text:
                continue
            if _CODE_RE.match(text):
                refs.append(StockRef(code=text))
            else:
                refs.append(StockRef(code=text, name=text))
            continue
        if isinstance(item, dict):
            code = _as_str(_first(item, "code", "stock_code", "symbol"))
            name = _as_str(_first(item, "name", "stock_name", "display_name"))
            if not code and not name:
                continue
            exchange = _as_str(_first(item, "exchange", default=""))
            market = _as_str(_first(item, "market", default="CN")) or "CN"
            evidence = _as_str(_first(item, "evidence", "source", default="mentioned")) or "mentioned"
            if evidence not in {"mentioned", "inferred", "user_confirmed"}:
                evidence = "inferred"
            if not code:
                # 只有名称、没有代码：无法确定上市主体，标记为待确认而非硬编码
                refs.append(
                    StockRef(code=name, name=name, market=market, exchange=exchange, evidence="inferred")
                )
                continue
            refs.append(
                StockRef(
                    code=code,
                    name=name,
                    market=market,
                    exchange=exchange,
                    evidence=evidence,
                )
            )
    return refs


def record_from_dict(payload: dict, line_hint: str = "") -> ParsedRecord:
    if not isinstance(payload, dict):
        raise RecordError("记录必须是 JSON 对象")

    content_text = _first(payload, "content_text", "content", "body", "text", default="")
    if not isinstance(content_text, str) or not content_text.strip():
        raise RecordError("缺少正文（content_text）")

    title = _as_str(_first(payload, "title", "subject", default=""))
    if not title:
        first_line = content_text.strip().split("\n", 1)[0].strip()
        title = first_line[:60] or (line_hint or "无标题")

    content_type_raw = _as_str(_first(payload, "content_type", "type", default="community_post"))
    content_type = CONTENT_TYPE_ALIASES.get(content_type_raw, content_type_raw)
    if content_type not in CONTENT_TYPES:
        content_type = "other"

    published_at = _first(payload, "published_at", "publish_time", "created_at", default=None)
    published_at = _as_str(published_at) or None

    precision = _as_str(_first(payload, "date_precision", default="")) or (
        "unknown" if not published_at else ("date" if len(str(published_at)) <= 10 else "second")
    )
    if precision not in DATE_PRECISIONS:
        precision = "unknown"

    tags_raw = _first(payload, "tags", "source_tags", default=[]) or []
    if isinstance(tags_raw, str):
        tags_raw = [t.strip() for t in tags_raw.replace("，", ",").split(",")]
    if not isinstance(tags_raw, list):
        raise RecordError("tags 必须为列表或逗号分隔文本")
    tags = [str(t).strip() for t in tags_raw if str(t).strip()]

    author_raw = payload.get("author")
    author_name = ""
    author_id = ""
    if isinstance(author_raw, dict):
        author_name = _as_str(author_raw.get("name"))
        author_id = _as_str(author_raw.get("id"))
    author_name = author_name or _as_str(_first(payload, "author_name", default=""))
    author_id = author_id or _as_str(_first(payload, "author_id", default=""))

    return ParsedRecord(
        title=title,
        content_text=content_text,
        source_platform=_as_str(_first(payload, "source_platform", "platform", default="")),
        source_space_id=_as_str(_first(payload, "source_space_id", "space_id", default="")),
        source_space_name=_as_str(_first(payload, "source_space_name", "space_name", default="")),
        source_item_id=_as_str(_first(payload, "source_item_id", "item_id", "topic_id", default="")),
        source_url=_as_str(_first(payload, "source_url", "url", default="")),
        author_id=author_id,
        author_name=author_name,
        published_at=published_at,
        source_updated_at=_as_str(_first(payload, "source_updated_at", default="")) or None,
        event_date=_as_str(_first(payload, "event_date", default="")) or None,
        date_precision=precision,
        content_type=content_type,
        language=_as_str(_first(payload, "language", default="zh-CN")) or "zh-CN",
        stocks=_parse_stocks(_first(payload, "stocks", "stock_refs", default=[])),
        tags=tags,
        institution=_as_str(payload.get("institution")),
        report_period=_as_str(payload.get("report_period")),
        source_attachments=payload.get("source_attachments") if isinstance(payload.get("source_attachments"), list) else [],
    )


def frontmatter_for(record: ParsedRecord, document_id: str, revision: int, imported_at: str) -> dict:
    return {
        "schema_version": 1,
        "document_id": document_id,
        "revision": revision,
        "title": record.title,
        "content_type": record.content_type,
        "source": {
            "platform": record.source_platform or None,
            "space_id": record.source_space_id or None,
            "space_name": record.source_space_name or None,
            "item_id": record.source_item_id or None,
            "url": record.source_url or None,
        },
        "author": {"id": record.author_id or None, "name": record.author_name or None},
        "published_at": record.published_at,
        "source_updated_at": record.source_updated_at,
        "event_date": record.event_date,
        "imported_at": imported_at,
        "date_precision": record.date_precision,
        "source_provided_stock_refs": [
            {"stock_id": s.stock_id, "name": s.name or None, "evidence": s.evidence}
            for s in record.stocks
        ],
        "source_tags": record.tags,
        "language": record.language,
        "institution": record.institution or None,
        "report_period": record.report_period or None,
        "source_attachments": record.source_attachments,
    }
