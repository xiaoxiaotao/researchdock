"""写入一批合成样例数据，用于验证导入 → 归档 → 首页 → 详情这条闭环。

内容全部是合成的示例文本，不代表任何真实公司、真实财报或投资观点。
其中故意包含一条坏 JSON 行（验证 T09 单条失败不阻断整批）
和一条无日期 TXT（验证 T04 未知日期不伪造）。
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import load_config
from .pipeline import Pipeline
from .storage import Storage

DISCLAIMER = "本条为合成样例数据，用于验证导入与页面渲染，不代表任何真实公司或投资观点。"


def _body(*paragraphs: str) -> str:
    return "\n\n".join([DISCLAIMER, *paragraphs])


ANNUAL = _body(
    "## 一、经营概况\n\n报告期内公司实现营业收入 12.40 亿元，同比增长 18.6%；归属于母公司股东的净利润 1.62 亿元，同比增长 22.3%。毛利率 31.4%，较上年提升 1.8 个百分点。",
    "## 二、主要财务数据\n\n"
    "| 指标 | 2025 年 | 2024 年 | 同比 |\n"
    "| --- | --- | --- | --- |\n"
    "| 营业收入（亿元） | 12.40 | 10.46 | +18.6% |\n"
    "| 归母净利润（亿元） | 1.62 | 1.32 | +22.3% |\n"
    "| 毛利率 | 31.4% | 29.6% | +1.8pct |\n"
    "| 研发费用（亿元） | 0.98 | 0.81 | +21.0% |",
    "## 三、主营业务分析\n\n精密结构件业务收入占比 64%，同比提升 5 个百分点；海外收入占比 27%，主要来自东南亚与欧洲客户。前五大客户合计销售占比 41%，集中度较上年下降 3 个百分点。",
    "## 四、风险提示\n\n原材料价格波动、汇率变动、下游需求不及预期。以上均为示例文本，不构成任何投资建议。",
)

MONTHLY = _body(
    "2026 年 9 月，公司实现出货量 1,840 万件，环比增长 6.2%，同比增长 14.1%。产能利用率 86%，环比提升 2 个百分点。",
    "分产品看，精密结构件出货 1,210 万件，精密模具出货 630 万件。原材料端，主要金属材料采购均价环比下降 1.4%。",
    "订单方面，截至 9 月末在手订单覆盖约 2.3 个月产能，与上月基本持平。",
)

RESEARCH = _body(
    "**调研时间**：2026 年 9 月 18 日\n**调研形式**：现场交流\n**参与机构**：示例证券、示例基金（合成）",
    "### 问：三季度产能利用率提升的主要原因？\n\n答：一是海外客户订单在 8 月集中交付，二是新产线在 7 月完成调试进入爬坡，两条因素共同推动。",
    "### 问：毛利率后续怎么看？\n\n答：原材料价格相对平稳，产品结构上高毛利的精密模具占比提升，管理层认为毛利率有望维持在当前水平附近，但具体数字不便给出指引。",
    "### 问：海外产能规划？\n\n答：越南工厂一期已投产，二期预计 2027 年上半年投产，届时海外产能占比将提升至 35% 左右。",
    "以上问答为合成样例，仅用于验证版式与检索，不代表真实调研内容。",
)

POST = _body(
    "看到一个说法：精密结构件行业 2027 年可能出现产能过剩，理由是过去两年行业扩产幅度较大。",
    "我倾向于认为这个判断需要分产品看：消费电子结构件确实扩产明显，但车规级结构件的认证周期长，实际有效产能释放要慢于规划产能。",
    "这只是个人思考，没有数据支撑，先记下来等后续验证。",
)

NEWMAT = _body(
    "公司 2026 年 8 月经营数据：出货量环比增长 3.1%，主要来自光伏边框业务。",
    "调研中提到，边框业务毛利率低于结构件业务约 6 个百分点，产品结构变化对整体毛利率有稀释作用。",
)

LEADZERO = _body(
    "该条用于验证股票代码前导零不丢失：代码 090001 在存储与检索中应保持 6 位。",
)


def build_records() -> list[dict]:
    base_source = {"source_platform": "zsxq", "source_space_name": "示例星球", "source_space_id": "space_demo"}
    return [
        {
            "schema_version": 1,
            "content_type": "annual_report",
            "title": "【示例】示例精密 2025 年年度报告摘要",
            "source_platform": "manual",
            "source_space_name": "年报归档",
            "source_item_id": "demo_ar_2025",
            "author_name": "示例精密",
            "published_at": "2026-04-18",
            "date_precision": "date",
            "stocks": [{"code": "900001", "name": "示例精密", "exchange": "SZ"}],
            "tags": ["精密制造", "年报"],
            "content_text": ANNUAL,
        },
        {
            "schema_version": 1,
            "content_type": "monthly_report",
            "title": "【示例】示例精密 2026 年 9 月经营月报",
            "source_platform": "manual",
            "source_space_name": "月度跟踪",
            "source_item_id": "demo_mr_202609",
            "published_at": "2026-10-09T18:30:00+08:00",
            "date_precision": "second",
            "stocks": [{"code": "900001", "name": "示例精密", "exchange": "SZ"}],
            "tags": ["精密制造", "月报"],
            "content_text": MONTHLY,
        },
        {
            "schema_version": 1,
            "content_type": "research_note",
            "title": "【示例】示例精密 2026 年 9 月机构调研纪要",
            **base_source,
            "source_item_id": "demo_topic_9001",
            "author_name": "示例作者甲",
            "published_at": "2026-09-19T09:30:00+08:00",
            "date_precision": "second",
            "stocks": [{"code": "900001", "name": "示例精密", "exchange": "SZ"}],
            "tags": ["调研纪要", "产能"],
            "content_text": RESEARCH,
        },
        {
            "schema_version": 1,
            "content_type": "research_note",
            "title": "【示例】示例新材 2026 年 8 月调研纪要",
            **base_source,
            "source_item_id": "demo_topic_9002",
            "author_name": "示例作者乙",
            "published_at": "2026-08-22T14:10:00+08:00",
            "date_precision": "second",
            "stocks": [{"code": "900002", "name": "示例新材", "exchange": "SH"}],
            "tags": ["光伏", "调研纪要"],
            "content_text": NEWMAT,
        },
        {
            "schema_version": 1,
            "content_type": "community_post",
            "title": "【示例】关于结构件行业产能过剩的一个反问",
            **base_source,
            "source_item_id": "demo_topic_9003",
            "author_name": "示例作者甲",
            "published_at": "2026-10-12T21:04:00+08:00",
            "date_precision": "second",
            "stocks": [{"code": "900001", "name": "示例精密", "exchange": "SZ"}],
            "tags": ["观点", "产能"],
            "content_text": POST,
        },
        {
            "schema_version": 1,
            "content_type": "other",
            "title": "【示例】前导零代码校验条目",
            "source_platform": "manual",
            "source_item_id": "demo_leadzero",
            "stocks": [{"code": "090001", "name": "示例前导零", "exchange": "SZ"}],
            "content_text": LEADZERO,
        },
    ]


BROKEN_LINE = '{"schema_version":1,"title":"【示例】这条故意写坏","content_text":"缺少右括号"'


def main() -> None:
    cfg = load_config()
    storage = Storage(cfg.data_dir, allow_create=cfg.allow_create_data_dir)
    storage.ensure_layout()
    from . import index

    index.init_schema(cfg.db_path)

    inbox = cfg.inbox_dir
    inbox.mkdir(parents=True, exist_ok=True)

    jsonl_path = inbox / "sample_batch_20261021.jsonl"
    lines = [json.dumps(rec, ensure_ascii=False) for rec in build_records()]
    lines.insert(3, BROKEN_LINE)
    jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    md_path = inbox / "sample_single_note.md"
    md_path.write_text(
        """---
schema_version: 1
title: "【示例】单篇 Markdown 导入：示例智造产能跟踪"
content_type: "research_note"
source:
  platform: "zsxq"
  space_id: "space_demo"
  space_name: "示例星球"
  item_id: "demo_topic_9004"
  url: null
author:
  id: null
  name: "示例作者丙"
published_at: "2026-10-15T10:20:00+08:00"
date_precision: "second"
source_provided_stock_refs:
  - code: "900003"
    name: "示例智造"
    exchange: "SZ"
source_tags: ["自动化", "调研纪要"]
---

""" + DISCLAIMER + """

示例智造 2026 年三季度订单同比增长 21%，主要来自锂电设备与工业机器人两条线。

产线方面，公司在 9 月新增两条装配线，预计四季度产能提升约 15%。
""",
        encoding="utf-8",
    )

    txt_path = inbox / "sample_no_date.txt"
    txt_path.write_text(
        """标题: 【示例】无发布时间的旧资料
来源: manual
作者: 佚名
代码: 900001
标签: 旧资料

""" + DISCLAIMER + """

这条资料没有发布时间，程序应显示「未知」，不能用导入时间冒充发表日期。
""",
        encoding="utf-8",
    )

    pipeline = Pipeline(cfg, storage)
    report = pipeline.scan()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
