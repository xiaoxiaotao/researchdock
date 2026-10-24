"""Offline installation checks: no source calls, keyring reads or model requests."""
from __future__ import annotations
import argparse
import importlib.util
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from contextlib import closing

PROJECT_ROOT=Path(__file__).resolve().parents[1]


def checks(config=None):
    rows=[]
    def add(key,title,status,detail,required=False):
        rows.append(dict(key=key,title=title,status=status,detail=detail,required=required))
    supported=sys.version_info>=(3,13)
    add('python','Python', 'ok' if supported else 'error',f'{sys.version_info.major}.{sys.version_info.minor}；需要 3.13 或更新版本',True)
    for module,label in [('fastapi','FastAPI'),('yaml','PyYAML'),('markdown_it','MarkdownIt'),('pypdf','pypdf'),('reportlab','ReportLab'),('keyring','keyring'),('httpx','HTTPX'),('jinja2','Jinja2'),('uvicorn','Uvicorn'),('opencc','OpenCC')]:
        installed=importlib.util.find_spec(module) is not None
        add(module,label,'ok' if installed else 'error','已安装' if installed else '未安装，请安装 requirements.txt',True)
    try:
        with closing(sqlite3.connect(':memory:')) as conn:conn.execute('CREATE VIRTUAL TABLE probe USING fts5(body)')
        add('fts5','SQLite FTS5','ok','可用',True)
    except sqlite3.Error:
        add('fts5','SQLite FTS5','error','当前 Python 的 SQLite 未启用 FTS5',True)
    try:
        if config is None:
            from .config import load_config
            cfg=load_config()
        else:
            cfg=config
        # The loader also checks the loopback-only policy.
        writable=cfg.data_dir if cfg.data_dir.exists() else cfg.data_dir.parent
        ready=writable.is_dir() and os.access(writable,os.W_OK)
        add('storage','数据目录','ok' if ready else 'error','目录或其父目录可写' if ready else '目录或父目录不存在或不可写；检查挂载和配置',True)
    except (SystemExit,ValueError,TypeError,OSError,ImportError):
        add('config','本机配置','error','配置无效，请检查 config.yaml 的格式、路径和回环地址',True)
    cli=(PROJECT_ROOT/'.tools/zsxq/node_modules/.bin/zsxq-cli')
    installed=cli.is_file() and os.access(cli,os.X_OK) or bool(shutil.which('zsxq-cli'))
    add('zsxq','知识星球 CLI','ok' if installed else 'optional','已找到；登录和星球权限需自行授权' if installed else '未安装；不影响手动导入和阅读')
    poppler=bool(shutil.which('pdftoppm'))
    add('poppler','公开 PDF 逐页预览','ok' if poppler else 'optional','已找到 pdftoppm' if poppler else 'PATH 未找到 pdftoppm；可选安装 Poppler，正文 PDF 导出不受影响')
    add('ai','DeepSeek（可选）','ok' if bool(os.environ.get('DEEPSEEK_API_KEY','').strip()) else 'optional','已检测到环境变量（不显示内容）' if os.environ.get('DEEPSEEK_API_KEY','').strip() else '可在 AI 设置页配置系统密钥环；本检查不读取密钥环')
    return {'ok':not any(r['required'] and r['status']=='error' for r in rows),'checks':rows,'network_accessed':False,'paid_requests':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--json',action='store_true');args=parser.parse_args()
    report=checks()
    if args.json:
        import json
        print(json.dumps(report,ensure_ascii=False,indent=2))
    else:
        for item in report['checks']:print(f"[{item['status']}] {item['title']}：{item['detail']}")
        print('离线检查完成：未读取登录凭据，未访问外部接口，未调用模型。')
    raise SystemExit(0 if report['ok'] else 1)


if __name__=='__main__':main()
