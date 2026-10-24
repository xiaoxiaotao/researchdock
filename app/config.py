"""配置加载：config.yaml + 环境变量覆盖。

对应设计文档第 18 节。M1 只读取必需字段，未知字段保留在 config 对象里不报错，
但非法值（如数据目录指向不存在的父目录）必须直接拒绝启动，而不是静默使用危险默认值。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

DEFAULT_CONFIG = {
    "app": {
        "host": "127.0.0.1",
        "port": 8001,
        "timezone": "Asia/Shanghai",
        "data_dir": "./kb-data",
    },
    "storage": {
        "require_bound_volume": False,
        "allow_automatic_local_fallback": False,
        "allow_create_data_dir": True,
    },
    "ingestion": {
        "poll_seconds": 60,
        "require_ready_marker": False,
        "max_file_mb": 20,
    },
}


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 8001
    timezone: str = "Asia/Shanghai"
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "kb-data")
    require_bound_volume: bool = False
    allow_automatic_local_fallback: bool = False
    allow_create_data_dir: bool = True
    require_ready_marker: bool = False
    poll_seconds: int = 60
    max_file_mb: int = 20
    raw: dict = field(default_factory=dict)

    @property
    def inbox_dir(self) -> Path:
        return self.data_dir / "inbox"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "index" / "research.sqlite3"


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _expand(path_value: str) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(str(path_value)))
    p = Path(expanded)
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    return p


def load_config(config_path: Path | None = None) -> Config:
    path = config_path or CONFIG_PATH
    raw = dict(DEFAULT_CONFIG)
    if path.exists():
        with path.open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        if not isinstance(loaded, dict):
            raise SystemExit(f"配置文件格式错误，应为映射结构：{path}")
        raw = _deep_merge(raw, loaded)

    app = raw.get("app", {})
    storage = raw.get("storage", {})
    ingestion = raw.get("ingestion", {})

    data_dir = _expand(app.get("data_dir", "./kb-data"))

    cfg = Config(
        host=str(app.get("host", "127.0.0.1")),
        port=int(app.get("port", 8001)),
        timezone=str(app.get("timezone", "Asia/Shanghai")),
        data_dir=data_dir,
        require_bound_volume=bool(storage.get("require_bound_volume", False)),
        allow_automatic_local_fallback=bool(storage.get("allow_automatic_local_fallback", False)),
        allow_create_data_dir=bool(storage.get("allow_create_data_dir", True)),
        require_ready_marker=bool(ingestion.get("require_ready_marker", False)),
        poll_seconds=int(ingestion.get("poll_seconds", 60)),
        max_file_mb=int(ingestion.get("max_file_mb", 20)),
        raw=raw,
    )

    if cfg.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit(
            f"拒绝启动：host 只能绑定回环地址，当前为 {cfg.host!r}。"
            "本项目默认不监听 0.0.0.0（设计文档 16、5.2）。"
        )
    return cfg
