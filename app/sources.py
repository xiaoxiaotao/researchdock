"""Read-only knowledge-source ingestion through the official zsxq CLI/API."""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .config import PROJECT_ROOT
from . import index
from .pipeline import Pipeline
from .storage import atomic_write_json, atomic_write_text, read_json
from .utils import new_batch_id, now_iso, parse_iso


class SourceError(RuntimeError):
    pass


class ContentUnavailable(SourceError):
    """A readable topic exists, but its full body is not available yet."""


class ZsxqClient:
    def __init__(self, executable: str | None = None):
        local = PROJECT_ROOT / ".tools/zsxq/node_modules/.bin/zsxq-cli"
        self.executable = executable or (str(local) if local.exists() else shutil.which("zsxq-cli"))

    def call(self, *args) -> dict:
        if not self.executable:
            raise SourceError("请先安装官方 zsxq-cli，安装方法见 README")
        for attempt in range(3):
            try:
                # The CLI's Go HTTP/2 client intermittently receives EOF in this
                # environment. HTTP/1.1 uses the same official HTTPS API/auth.
                env = {**os.environ, "GODEBUG": os.environ.get("GODEBUG", "") + ",http2client=0"}
                process = subprocess.Popen([self.executable, *args, *([] if args and args[0] == "api" else ["--json"])], stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, start_new_session=True, env=env)
                try:
                    stdout, stderr = process.communicate(timeout=45)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                    raise
                payload = json.loads(stdout or stderr)
            except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
                if attempt < 2:
                    time.sleep(attempt + 1)
                    continue
                raise SourceError("官方 API 暂时不可达或返回格式异常，请稍后重试") from None
            error = payload.get("error") or {}
            if process.returncode or payload.get("ok") is False or payload.get("success") is False:
                kind = error.get("type", "") if isinstance(error, dict) else ""
                if kind in {"network", "rate_limit", "rate_limited"} and attempt < 2:
                    time.sleep(attempt + 1)
                    continue
                # Never expose CLI stderr, authorization URLs, headers, or credentials.
                if kind in {"auth", "authentication", "not_authenticated"}:
                    raise SourceError("API 登录已失效，请运行官方 CLI 重新授权")
                raise SourceError("官方 API 调用失败，请检查登录状态与星球访问权限")
            data = payload.get("data", payload)
            if not isinstance(data, dict):
                raise SourceError("官方 API 返回格式异常")
            return data
        raise SourceError("官方 API 暂不可用")

    def download_url(self, file_id: str) -> str:
        if not re.fullmatch(r"\d+", file_id):
            raise SourceError("附件 ID 无效")
        data = self.call("api", "raw", "--method", "GET", "--path", f"/v2/files/{file_id}/download_url")
        body = data.get("body") or {}
        result = body.get("resp_data") or {}
        url = result.get("download_url") or ""
        parsed = urlsplit(url)
        if not body.get("succeeded") or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise SourceError("未取得附件下载地址，请检查星球权限或稍后重试")
        if not (parsed.hostname == "zsxq.com" or parsed.hostname.endswith(".zsxq.com")):
            raise SourceError("附件下载地址域名异常")
        return url

    def status(self) -> dict:
        data = self.call("auth", "status")
        return {"installed": True, "logged_in": bool(data.get("loggedIn"))}

    def topics(self, group_id: str, limit: int, end_time: str | None = None) -> dict:
        args = ["group", "+topics", "--group-id", group_id, "--limit", str(limit)]
        if end_time:
            args += ["--end-time", end_time]
        return self.call(*args)

    def detail(self, topic_id: str) -> dict:
        data = self.call("topic", "+detail", "--topic-id", topic_id)
        topic = data.get("topic")
        if not isinstance(topic, dict):
            raise SourceError("未返回主题全文，不导入列表摘要")
        return topic


class ZsxqText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.tags = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style"}:
            self.hidden += 1
        elif not self.hidden:
            if tag in {"br", "p", "div", "li"}:
                self.parts.append("\n")
            elif tag == "e":
                title = unquote(attrs.get("title", ""))
                href = unquote(attrs.get("href", ""))
                # Display titles can be shortened; retain the actual destination.
                if attrs.get("type") == "web" and href.startswith(("https://", "http://")):
                    self.parts.append(href)
                else:
                    self.parts.append(title)
                if attrs.get("type") == "hashtag" and title:
                    self.tags.append(title.strip("#"))

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in {"p", "div", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def topic_record(topic: dict, group_id: str, group_name: str) -> dict:
    topic_id = str(topic.get("topic_id", ""))
    if not re.fullmatch(r"\d+", topic_id):
        raise SourceError("主题缺少有效 ID")
    group = topic.get("group") or {}
    if group.get("group_id") and str(group["group_id"]) != group_id:
        raise SourceError("主题所属星球不匹配")
    parser = ZsxqText()
    parser.feed(topic.get("content") or "")
    parser.close()  # Flush buffered text, including unterminated entity-like ampersands.
    body = "".join(parser.parts).strip()
    files = topic.get("files") or []
    images = topic.get("images") or []
    attachments = [{"kind": "file", "file_id": str(f.get("file_id", "")),
                    "name": str(f.get("name") or f.get("file_name") or "未命名附件"),
                    "size": f.get("size"), "status": "metadata_only"} for f in files]
    attachments += [{"kind": "image", "image_id": str(i.get("image_id", "")),
                     "status": "metadata_only"} for i in images]
    if not body or body in {"「文件」", "[文件]", "【文件】"}:
        if not attachments:
            raise ContentUnavailable("未获取到正文，不保存空白或截断的主题")
        body = "此主题仅含附件，附件清单已登记，原件请到知识星球查看。"
    # The API's title can be a truncated digest. Derive a readable title from full content.
    title = re.sub(r"https?://\S+", "", body.splitlines()[0]).strip()[:120] or "星球纪要"
    if body.startswith("此主题仅含附件"):
        names = [a.get("name") or "图片附件" for a in attachments]
        title = names[0] + (f" 等 {len(names)} 个附件" if len(names) > 1 else "")
    owner = topic.get("owner") or {}
    return {"schema_version": 1, "title": title, "content_text": body,
            "content_type": "community_post", "source_platform": "zsxq",
            "source_space_id": group_id, "source_space_name": group.get("name") or group_name,
            "source_item_id": topic_id,
            "source_url": f"https://wx.zsxq.com/group/{group_id}/topic/{topic_id}",
            "author_id": str(owner.get("user_id") or ""), "author_name": owner.get("name") or "",
            "published_at": topic.get("create_time") or None,
            "source_updated_at": topic.get("modify_time") or None,
            "tags": list(dict.fromkeys(parser.tags)), "source_attachments": attachments}


class SourceManager:
    def __init__(self, pipeline: Pipeline, client=None):
        self.pipeline = pipeline
        self.storage = pipeline.storage
        self.client = client or ZsxqClient()
        self.lock = threading.RLock()
        self.executor = None
        self.poll_stop=threading.Event()
        self.poll_thread=None

    def path(self, group_id: str) -> Path:
        if not re.fullmatch(r"\d{5,30}", group_id):
            raise SourceError("星球 ID 应为纯数字")
        return self.storage.path(f"catalog/sources/zsxq_{group_id}.json")

    def register(self, group_id: str, name: str) -> dict:
        with self.lock:
            path = self.path(group_id)
            source = read_json(path) or {"platform": "zsxq", "group_id": group_id,
                                        "created_at": now_iso(), "status": "ready"}
            source.update(name=name.strip()[:120] or group_id,
                          url=f"https://wx.zsxq.com/group/{group_id}")
            atomic_write_json(path, source)
            return source

    def list(self) -> list[dict]:
        with self.lock:
            return [read_json(p) for p in sorted(self.storage.path("catalog/sources").glob("zsxq_*.json"))]

    def start(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kb-source")
        for source in self.list():
            if source.get("status") in {"queued", "running"}:
                source.update(status="interrupted", message="服务中断，请重新同步；已归档内容会去重")
                atomic_write_json(self.path(source["group_id"]), source)

        self.poll_stop.clear()
        self.poll_thread=threading.Thread(target=self.poll_schedule,daemon=True,name='kb-source-poll')
        self.poll_thread.start()

    def poll_schedule(self):
        while not self.poll_stop.wait(30):
            try:self.poll_once()
            except Exception:pass  # Source sync persists its own safe error status.

    def poll_once(self,now=None):
        from datetime import datetime,timedelta
        from .utils import TZ
        now=now or datetime.now(TZ)
        settings=read_json(self.storage.path('catalog/research-settings.json')) or {}
        if not settings.get('poll_enabled',False):return
        minutes=settings.get('poll_minutes',5)
        if type(minutes) is not int or minutes not in (5,10,15,30,60):return
        path=self.storage.path('jobs/source-poll.json');state=read_json(path) or {}
        for source in self.list():
            if source.get('status') in {'running','queued'}:continue
            last=parse_iso(state.get(source['group_id'],''))
            delay=max(minutes,15) if source.get('status')=='failed' else minutes
            if last and now<last+timedelta(minutes=delay):continue
            self.enqueue(source['group_id'],'live')
            state[source['group_id']]=now.isoformat()
            atomic_write_json(path,state)

    def close(self):
        self.poll_stop.set()
        if self.poll_thread:self.poll_thread.join(timeout=2)
        if self.executor:
            self.executor.shutdown(wait=True)
            self.executor = None

    def enqueue(self, group_id: str, mode="latest") -> dict:
        if mode not in {"latest", "history", "live"}:
            raise SourceError("同步模式无效")
        with self.lock:
            source = read_json(self.path(group_id))
            if not source:
                raise SourceError("请先添加信源")
            if source.get("status") in {"running", "queued"}:
                return source
            if not self.executor:
                raise SourceError("同步服务尚未启动")
            source.update(status="queued", message="等待 API 同步", mode=mode)
            atomic_write_json(self.path(group_id), source)
            self.executor.submit(self._run, group_id, mode)
            return source

    def _run(self, group_id: str, mode: str):
        try:
            self.sync(group_id, mode)
        except Exception:
            # sync() has already persisted the safe error message.
            pass

    def sync(self, group_id: str, mode="latest", limit=20, max_pages=3, window_start=None, window_end=None) -> dict:
        with self.lock:
            return self._sync(group_id, mode, limit, max_pages, window_start, window_end)

    def _sync(self, group_id: str, mode="latest", limit=20, max_pages=3, window_start=None, window_end=None) -> dict:
        """Bounded API collection. Latest cursor advances only after all imports succeed."""
        with self.lock:
            source = read_json(self.path(group_id))
            if not source:
                raise SourceError("信源不存在")
            source.update(status="running", message="正在通过官方 API 读取全文", started_at=now_iso())
            atomic_write_json(self.path(group_id), source)
        run_id = new_batch_id()
        cursor = None if mode in {"daily","live"} else (source.get("history_cursor") if mode == "history" else source.get("latest_pending_cursor"))
        watermark = (source.get("live_latest_at") or source.get("collected_through")) if mode=="live" else source.get("latest_at")
        newest = source.get("latest_pending_newest") if mode == "latest" else None
        seen = set()
        unavailable = dict(source.get("unavailable_topics") or {})
        totals = {key: 0 for key in ("created", "updated", "duplicated", "failed")}
        exhausted = False
        try:
            recovery = self.pipeline.reconcile()
            if recovery["problems"]:
                raise SourceError("归档校验失败，请先修复资料库后重试同步")
            for page in range(max_pages):
                listing = self.client.topics(group_id, limit, cursor)
                briefs = listing.get("topics_brief", listing.get("topics", []))
                if not isinstance(briefs, list):
                    raise SourceError("API 主题列表格式异常")
                if not briefs:
                    exhausted = True
                    break
                records = []
                candidates = list(briefs)
                if page == 0:
                    candidates += [{"topic_id":tid,"create_time":item.get("published_at")} for tid,item in list(unavailable.items())[:20]]
                for brief in candidates:
                    tid = str(brief.get("topic_id", ""))
                    if tid in seen:
                        continue
                    seen.add(tid)
                    if mode == "daily":
                        stamp = brief.get("create_time")
                        if not stamp:
                            raise SourceError("主题缺少发布时间，无法确认每日采集范围")
                        if not (parse_iso(window_start) <= parse_iso(stamp) <= parse_iso(window_end)):
                            continue
                    if mode=='live' and watermark and tid not in unavailable:
                        stamp=parse_iso(brief.get('create_time'))
                        if stamp and stamp<parse_iso(watermark):continue
                    detail = self.client.detail(tid)
                    try:
                        record = topic_record(detail, group_id, source["name"])
                    except ContentUnavailable as exc:
                        unavailable[tid] = {"published_at":brief.get("create_time"), "message":str(exc)}
                        continue
                    unavailable.pop(tid, None)
                    from .youdao import enrich
                    record = enrich(self.storage, record)
                    with index.connect(self.pipeline.cfg.db_path) as conn:
                        row = conn.execute("SELECT document_id FROM documents WHERE source_key=?",
                            (f"zsxq|{group_id}|{tid}",)).fetchone()
                    if row:
                        manifest = self.storage.read_manifest(row["document_id"]) or {}
                        record.update(manifest.get("manual_fields", {}))
                    records.append(record)
                if records:
                    # Only normalized content is persisted. Signed avatar URLs/credentials are excluded.
                    path = self.storage.path(f"sources/zsxq/{group_id}/{run_id}-{page}.jsonl")
                    atomic_write_text(path, "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n")
                    report = self.pipeline.import_file(path)
                    if report.status == "already_processed":
                        totals["duplicated"] += len(records)
                    else:
                        for key in totals:
                            totals[key] += getattr(report, key)
                    if report.failed:
                        raise SourceError("部分主题归档失败，游标未推进，请查看导入记录后重试")
                dates = [b.get("create_time") for b in briefs if b.get("create_time")]
                if dates:
                    newest = max([v for v in [newest, *dates] if v], key=lambda v: parse_iso(v))
                next_cursor = listing.get("next_end_time") or (dates[-1] if dates else None)
                crossed = bool(watermark and dates and any(parse_iso(d) < parse_iso(watermark) for d in dates))
                exhausted = not listing.get("has_more", len(briefs) >= limit) or (mode in {"latest","live"} and crossed)
                if mode == "daily" and dates and any(parse_iso(d) < parse_iso(window_start) for d in dates):
                    exhausted = True
                if next_cursor == cursor and not exhausted:
                    raise SourceError("API 分页游标未推进，已停止；可稍后重试")
                cursor = next_cursor
                if exhausted or not cursor:
                    break
                time.sleep(0.3)
            if mode == "daily" and not exhausted:
                raise SourceError("最近 24 小时内容超过本次分页上限，请重试或提高分页上限；已归档内容会去重")
            if mode == "latest":
                if exhausted or not watermark:
                    source.update(latest_at=newest, latest_pending_cursor=None, latest_pending_newest=None)
                else:
                    source.update(latest_pending_cursor=cursor, latest_pending_newest=newest)
                if not source.get("history_cursor"):
                    source["history_cursor"] = cursor
            elif mode == "live" and exhausted:
                source["live_latest_at"]=max((v for v in (watermark,newest) if v),key=parse_iso,default=None)
            elif mode == "history":
                source.update(history_cursor=cursor, history_complete=exhausted)
            source["window_complete"] = exhausted
            window_pending = len(unavailable)
            if mode == 'daily':
                window_pending = sum(not item.get('published_at') or parse_iso(window_start)<=parse_iso(item['published_at'])<=parse_iso(window_end) for item in unavailable.values())
            source.update(status="partial" if unavailable else "succeeded", unavailable_topics=unavailable, unavailable_count=len(unavailable), window_unavailable_count=window_pending, last_synced_at=now_iso(), counts=totals,
                          message=f"新增 {totals['created']} / 更新 {totals['updated']} / 重复 {totals['duplicated']}；{len(unavailable)} 条正文待补，附件仅登记清单",
                          has_pending_latest=bool(source.get("latest_pending_cursor")))
            return source
        except Exception as exc:
            message = str(exc) if isinstance(exc, SourceError) else "同步失败，进度未推进，可安全重试"
            source.update(status="failed", message=message, counts=totals)
            raise SourceError(message) from None
        finally:
            with self.lock:
                source["unavailable_topics"] = unavailable
                source["unavailable_count"] = len(unavailable)
                source["finished_at"] = now_iso()
                atomic_write_json(self.path(group_id), source)
