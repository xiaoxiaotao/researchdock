"""Markdown 头信息（YAML front matter）的读写。

格式沿用设计文档 7.1 的示例。头信息只描述这条资料本身，
不含正文哈希（正文哈希存在 manifest，避免自指）。
"""
from __future__ import annotations

import yaml

DELIM = "---"


def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith(DELIM):
        return {}, text
    lines = text.split("\n")
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == DELIM:
            end = idx
            break
    if end is None:
        return {}, text
    raw = "\n".join(lines[1:end])
    try:
        meta = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(meta, dict):
        return {}, text
    body = "\n".join(lines[end + 1 :])
    return meta, body.lstrip("\n")


def build_document(meta: dict, body: str) -> str:
    header = yaml.safe_dump(
        meta,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=1000,
    )
    return f"{DELIM}\n{header}{DELIM}\n\n{body.rstrip()}\n"
