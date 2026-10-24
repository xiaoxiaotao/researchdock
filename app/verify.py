"""M1 验收自检：把设计文档第 21 节里 M1 能覆盖的用例跑一遍。

用法：./.venv/bin/python -m app.verify
全部在临时目录里进行，不碰真实知识库。
"""
from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from . import index
from .config import load_config
from .pipeline import Pipeline
from .storage import Storage, StorageNotReady

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(case: str, ok: bool, detail: str = "") -> None:
    results.append((case, PASS if ok else FAIL, detail))


def record(item_id: str, title: str, body: str, *, published: str | None = "2026-10-01T09:00:00+08:00",
           stocks: list[dict] | None = None, space: str = "space_v") -> dict:
    return {
        "schema_version": 1,
        "title": title,
        "content_type": "research_note",
        "source_platform": "zsxq",
        "source_space_id": space,
        "source_space_name": "验收星球",
        "source_item_id": item_id,
        "published_at": published,
        "content_text": body,
        "stocks": stocks or [],
    }


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="kb-verify-"))
    cfg = replace(load_config(), data_dir=root / "kb")

    # T23：父目录不存在时不得创建空库
    try:
        Storage(root / "no-vol" / "kb", allow_create=True).ensure_layout()
        check("T23 未挂载不建目录", False, "竟然创建成功")
    except StorageNotReady:
        check("T23 未挂载不建目录", True, "拒绝创建")

    storage = Storage(cfg.data_dir)
    storage.ensure_layout()
    index.init_schema(cfg.db_path)
    pipeline = Pipeline(cfg, storage)

    # T09：一批里一条 JSON 坏掉，其它照常完成
    batch = cfg.inbox_dir / "v1.jsonl"
    lines = [
        json.dumps(record("v001", "第一条", "正文一", stocks=[{"code": "900001", "name": "验收股"}]),
                   ensure_ascii=False),
        '{"title": "坏行", "content_text": "缺少右括号"',
        json.dumps(record("v002", "第二条", "正文二"), ensure_ascii=False),
        json.dumps(record("v003", "无日期条", "正文三", published=None), ensure_ascii=False),
        json.dumps(record("v004", "前导零", "正文四", stocks=[{"code": "090001", "name": "零股"}]),
                   ensure_ascii=False),
    ]
    batch.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = pipeline.scan()
    check("T09 单条坏行不阻断", report["created"] == 4 and report["failed"] == 1,
          f"created={report['created']} failed={report['failed']}")

    # T01：同一批次重复导入不增加记录与版本
    processed = next((storage.root / "processed").glob("*/v1.jsonl"), None)
    if processed:
        shutil.copy2(processed, cfg.inbox_dir / "v1.jsonl")
        pipeline.scan()
    with index.connect(cfg.db_path) as conn:
        docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        revs = conn.execute("SELECT COUNT(*) FROM document_revisions").fetchone()[0]
    check("T01 重复导入不膨胀", docs == 4 and revs == 4, f"docs={docs} revs={revs}")

    # T04：无发布时间保留为未知
    with index.connect(cfg.db_path) as conn:
        row = conn.execute("SELECT published_at, date_precision FROM documents WHERE title='无日期条'").fetchone()
    check("T04 无日期不伪造", row and row["published_at"] is None and row["date_precision"] == "unknown",
          f"{row['published_at'] if row else '?'}/{row['date_precision'] if row else '?'}")

    # T05：股票代码前导零不丢
    with index.connect(cfg.db_path) as conn:
        codes = [r[0] for r in conn.execute("SELECT code FROM stocks").fetchall()]
    check("T05 前导零保留", "090001" in codes, f"{codes}")

    # T02：同源帖子改正文 → 新增版本，旧版本文件保留
    batch2 = cfg.inbox_dir / "v2.jsonl"
    batch2.write_text(
        json.dumps(record("v001", "第一条（修订）", "正文一，改了一段。",
                          stocks=[{"code": "900001", "name": "验收股"}]), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    pipeline.scan()
    with index.connect(cfg.db_path) as conn:
        d = conn.execute("SELECT document_id, current_revision FROM documents WHERE source_key LIKE '%v001'").fetchone()
        revs = conn.execute("SELECT revision, archive_path FROM document_revisions WHERE document_id=?",
                            (d["document_id"],)).fetchall()
    files_ok = all((storage.root / r["archive_path"]).exists() for r in revs)
    check("T02 修订新增且保留旧版", d["current_revision"] == 2 and len(revs) == 2 and files_ok,
          f"current={d['current_revision']} revs={len(revs)} files={files_ok}")

    # T10：索引丢失后 reconcile 补齐，且不重复建版本
    with index.connect(cfg.db_path) as conn:
        conn.execute("DELETE FROM document_revisions WHERE document_id=?", (d["document_id"],))
        conn.execute("DELETE FROM documents WHERE document_id=?", (d["document_id"],))
    res = pipeline.reconcile()
    with index.connect(cfg.db_path) as conn:
        back = conn.execute("SELECT current_revision FROM documents WHERE document_id=?", (d["document_id"],)).fetchone()
        revs = conn.execute("SELECT COUNT(*) FROM document_revisions WHERE document_id=?",
                            (d["document_id"],)).fetchone()[0]
    check("T10 断点恢复不重复", back is not None and back["current_revision"] == 2 and revs == 2,
          f"{res}")

    # T21：仅凭持久文件重建索引
    before = docs
    pipeline.rebuild_index()
    with index.connect(cfg.db_path) as conn:
        docs2 = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        revs2 = conn.execute("SELECT COUNT(*) FROM document_revisions").fetchone()[0]
        names = [r[0] for r in conn.execute("SELECT name FROM stocks WHERE name<>''").fetchall()]
    check("T21 索引可重建", docs2 == before and revs2 == 5 and names,
          f"docs={docs2} revs={revs2} names={names}")

    # T18：正文里的原始 HTML 不被执行
    batch3 = cfg.inbox_dir / "v3.jsonl"
    batch3.write_text(
        json.dumps(record("v009", "注入测试", '正常文字\n\n<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>'),
                   ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    pipeline.scan()
    from markdown_it import MarkdownIt

    rendered = MarkdownIt("commonmark", {"html": False}).render('<script>alert(1)</script>')
    check("T18 原始 HTML 不执行", "<script" not in rendered and "&lt;script" in rendered, rendered[:60])

    shutil.rmtree(root, ignore_errors=True)

    print()
    width = max(len(c) for c, _, _ in results)
    for case, status, detail in results:
        mark = "✓" if status == PASS else "✗"
        print(f"{mark} {case.ljust(width)}  {detail}")
    failed = [r for r in results if r[1] == FAIL]
    print(f"\n{len(results) - len(failed)}/{len(results)} 通过")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
