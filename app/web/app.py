"""本机 Web 服务：首页、资料库、详情、个股档案、导入记录。"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt

from .. import index
from ..processing import inventory
from ..config import Config, load_config
from ..frontmatter import split_frontmatter
from ..models import CONTENT_TYPES, RecordError
from ..importers import SUPPORTED_SUFFIXES
from ..jobs import ImportJobs
from ..sources import SourceManager, SourceError
from ..research import Research, ResearchError
from ..industries import CATEGORIES, categories, group_notes
from ..publication import Publications
from ..llm import LLMError
from ..pipeline import Pipeline
from ..storage import Storage, StorageNotReady, atomic_write_json, read_json
from ..utils import TZ, parse_iso, now_iso, date_only, human_date, rel_age, today_str

BASE_DIR = Path(__file__).resolve().parent
md = MarkdownIt("commonmark", {"html": False, "linkify": True, "typographer": False}).enable("table")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

cfg: Config = load_config()
storage = Storage(cfg.data_dir, allow_create=cfg.allow_create_data_dir)
pipeline = Pipeline(cfg, storage)
jobs = ImportJobs(pipeline)
sources: SourceManager | None = None
research: Research | None = None
recovery_problems: list[str] = []


@asynccontextmanager
async def lifespan(app):
    on_startup()
    try:
        yield
    finally:
        on_shutdown()


app = FastAPI(title="股票研究知识库", docs_url=None, redoc_url=None, lifespan=lifespan)
from starlette.middleware.trustedhost import TrustedHostMiddleware
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost','127.0.0.1','[::1]','testserver'])


@app.middleware('http')
async def local_mutation_origin(request: Request, call_next):
    origin=request.headers.get('origin')
    if request.method in {'POST','PUT','PATCH','DELETE'} and origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):
        return JSONResponse({'detail':'不接受其他网站发起的修改请求'},status_code=403)
    return await call_next(request)


app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# ---------- 模板过滤器 ----------

def _fmt_date(value, precision=None):
    return human_date(value, precision)


def _fmt_day(value):
    return date_only(value) or "未知"


def _fmt_age(value):
    return rel_age(value)


def _type_label(value):
    return CONTENT_TYPES.get(value or "other", value or "其他")


templates.env.filters["dt"] = _fmt_date
templates.env.filters["day"] = _fmt_day
templates.env.filters["age"] = _fmt_age
templates.env.filters["type_label"] = _type_label
templates.env.globals["CONTENT_TYPES"] = CONTENT_TYPES


def _render(request: Request, name: str, status_code: int = 200, **context) -> HTMLResponse:
    payload = {
        "request": request,
        "storage_ready": storage.ready,
        "storage_path": str(cfg.data_dir),
        "today": today_str(),
        **context,
    }
    return templates.TemplateResponse(
        request=request, name=name, context=payload, status_code=status_code
    )


def _conn():
    return index.connect(cfg.db_path)


# ---------- 生命周期 ----------

def on_startup() -> None:
    global sources, research
    try:
        storage.ensure_layout()
        index.init_schema(cfg.db_path)
        recovery_problems[:] = pipeline.reconcile()["problems"]
        jobs.start()
        sources = SourceManager(pipeline)
        sources.start()
        research = Research(pipeline, sources)
        research.start()
    except StorageNotReady as exc:
        print(f"[storage] 未就绪：{exc}")


def on_shutdown() -> None:
    if research:
        research.close()
    if sources:
        sources.close()
    jobs.close()


@app.get('/mobile-preview')
def mobile_preview():
    return FileResponse(BASE_DIR/'static/mobile-preview.html',media_type='text/html',headers={'Cache-Control':'no-store'})


@app.get('/setup', response_class=HTMLResponse)
def setup_page(request: Request):
    from ..doctor import checks
    return _render(request,'setup.html',diagnostics=checks(cfg))


# ---------- 页面 ----------

@app.get("/", response_class=HTMLResponse)
def home(request: Request, view: str = Query("imported", pattern="^(imported|published)$")):
    if not storage.ready:
        return _render(request, "storage_offline.html", error="知识库目录未就绪")
    with _conn() as conn:
        s = index.stats(conn, today_str())
        field = "imported_at" if view == "imported" else "published_at"
        rows, _ = index.list_documents(conn, limit=20, date_field=field, start=today_str())
        recent, _ = index.list_documents(conn, limit=12)
        batches = index.recent_batches(conn, 3)
        stocks = index.list_stocks(conn)[:8]
        stock_map = _stocks_by_doc(conn, [r["document_id"] for r in recent])
    inventory_rows,processing_counts=inventory(pipeline,research)
    metadata={r['document_id']:r['meta'] for r in inventory_rows}
    rows=[_attachment_presentation(r,metadata.get(r['document_id'],{})) for r in rows]
    recent=[_attachment_presentation(r,metadata.get(r['document_id'],{})) for r in recent]
    if research:
        company_rows=Publications(research).stocks()
        stocks=company_rows[:8]
        s['stocks']=len(company_rows)
    usage = storage.disk_usage()
    return _render(
        request, "home.html",
        stats=s, today_rows=rows, recent=recent, batches=batches,
        stocks=stocks, stock_map=stock_map, view=view, usage=usage,
        marker=storage.marker, processing_counts=processing_counts,
    )


def _attachment_presentation(row, meta):
    """Describe source-only attachment posts without modifying archived originals."""
    item = dict(row)
    files = meta.get("source_attachments") or []
    placeholder = item.get("title", "").strip() in {"「文件」", "[文件]", "【文件】", "此主题仅含附件，附件清单已登记，原件请到知识星球查看。"}
    if files:
        names = [f.get("name") or "图片附件" for f in files]
        item["source_attachment_count"] = len(files)
        if placeholder:
            item["title"] = names[0] + (f" 等 {len(files)} 个附件" if len(files) > 1 else "")
            item["excerpt"] = "；".join(names[:4])
            item["attachment_only"] = True
    elif placeholder:
        item["attachment_only"] = True
        item["title"] = "附件帖（未获取附件清单）"
        item["excerpt"] = "来源正文只有文件占位符，尚无可阅读正文，请查看星球原文。"
    return item


@app.get("/documents", response_class=HTMLResponse)
def documents(request: Request, q: str = "", file_type: str = "", processing: str = "", content_type: str = "", platform: str = "",
              source_space_id: str = "",
              stock_id: str = "", date_field: str = "imported_at", start: str = "",
              end: str = "", page: int = Query(1, ge=1)):
    if not storage.ready:
        return _render(request, "storage_offline.html", error="知识库目录未就绪")
    limit = 30
    with _conn() as conn:
        if file_type or processing or q:
            candidates, _ = inventory(pipeline,research)
            search_rows,_=index.list_documents(conn,q=q,limit=100000) if q else ([],0)
            search_map={r['document_id']:dict(r) for r in search_rows}
            rows=[]
            for row in candidates:
                files=row['source_attachments']
                names=' '.join(f.get('name','') for f in files)
                if file_type and not any((f.get('name','').lower().endswith('.pdf') if file_type=='pdf' else f.get('name','').lower().endswith(('.mp3','.m4a','.wav','.aac','.flac')) if file_type=='audio' else f.get('kind')=='file') for f in files): continue
                if processing and row['processing_state']!=processing: continue
                if q and row['document_id'] not in search_map and q.casefold() not in names.casefold(): continue
                if row['document_id'] in search_map: row.update(search_map[row['document_id']])
                if content_type and row['content_type']!=content_type: continue
                if platform and row['source_platform']!=platform: continue
                if source_space_id and row.get('source_space_id')!=source_space_id: continue
                stamp=row.get(date_field if date_field in {'imported_at','published_at'} else 'imported_at') or ''
                if start and stamp<start or end and stamp>=end: continue
                if stock_id and stock_id not in [st['stock_id'] for st in index.stocks_of_document(conn,row['document_id'])]: continue
                rows.append(_attachment_presentation(row,row['meta']))
            total=len(rows)
            rows=rows[(page-1)*limit:page*limit]
        else:
            rows,total=index.list_documents(conn,limit=limit,offset=(page-1)*limit,date_field=date_field,start=start or None,end=end or None,content_type=content_type or None,platform=platform or None,stock_id=stock_id or None,source_space_id=source_space_id or None)
            candidates,_=inventory(pipeline,research)
            metadata={r['document_id']:r['meta'] for r in candidates}
            rows=[_attachment_presentation(r,metadata.get(r['document_id'],{})) for r in rows]
        s = index.stats(conn, today_str())
        stock_map = _stocks_by_doc(conn, [r["document_id"] for r in rows])
        stock = index.get_stock(conn, stock_id) if stock_id else None
    pages = max(1, (total + limit - 1) // limit)
    return _render(
        request, "documents.html", rows=rows, total=total, page=page, pages=pages,
        stats=s, stock_map=stock_map, stock=stock,
        filters={"q": q, "file_type": file_type, "processing": processing, "content_type": content_type, "platform": platform,
                 "stock_id": stock_id, "date_field": date_field, "start": start, "end": end},
        source_space_id=source_space_id,
    )


@app.get("/documents/{document_id}", response_class=HTMLResponse)
def document_detail(request: Request, document_id: str, revision: int | None = None, find: str=Query('',max_length=200), hit: int=Query(1,ge=1)):
    if not storage.ready:
        return _render(request, "storage_offline.html", error="知识库目录未就绪")
    with _conn() as conn:
        row = index.get_document(conn, document_id)
        if row is None:
            raise HTTPException(status_code=404, detail="资料不存在")
        revisions = index.get_revisions(conn, document_id)
        stocks = index.stocks_of_document(conn, document_id)

    target = None
    if revision is not None:
        target = next((r for r in revisions if r["revision"] == revision), None)
        if target is None:
            raise HTTPException(404, "该版本不存在")
    if target is None:
        target = next((r for r in revisions if r["revision"] == row["current_revision"]), None)
    if target is None:
        raise HTTPException(status_code=500, detail="缺少可用版本")

    try:
        raw = storage.read_revision_text(target["archive_path"])
    except StorageNotReady as exc:
        return _render(request, "storage_offline.html", error=str(exc))
    meta, body = split_frontmatter(raw)
    from ..youdao import local_images
    html_body = md.render(local_images(body))
    from ..company_search import source_focus
    search_focus=source_focus(body,find,hit)
    try:
        manifest = storage.read_manifest(document_id) or {}
        source_revision = next((r for r in manifest.get("revisions", [])
                                if r["revision"] == target["revision"]), {})
        pages = pipeline.pages_for_revision(source_revision)
    except StorageNotReady as exc:
        return _render(request, "storage_offline.html", error=str(exc), status_code=503)
    is_old = target["revision"] != row["current_revision"]
    display_doc = dict(row)
    if is_old:
        for key in ("title", "content_type", "published_at", "date_precision"):
            if key in meta:
                display_doc[key] = meta[key]
        display_doc["imported_at"] = target["imported_at"]
        source = meta.get("source") or {}
        display_doc.update(source_platform=source.get("platform"), source_space_name=source.get("space_name"),
                           source_url=source.get("url"), author_name=(meta.get("author") or {}).get("name"))
        stocks = [{"stock_id": ref["stock_id"], "name": ref.get("name"),
                   "code": ref["stock_id"].split(".")[-1],
                   "status": "pending" if ref.get("evidence") == "inferred" else "confirmed"}
                  for ref in meta.get("source_provided_stock_refs", []) if ref.get("stock_id")]
    from ..evidence import Evidence,TOPICS
    evidence_store=Evidence(storage)
    companies=Publications(research).stocks() if research else []
    focus=evidence_store.get(request.query_params.get('excerpt',''))
    if focus and (focus['document_id']!=document_id or focus['revision']!=target['revision'] or body[focus['start_offset']:focus['end_offset']]!=focus['quote']):focus=None
    focus_context={'before':body[max(0,focus['start_offset']-150):focus['start_offset']],'after':body[focus['end_offset']:focus['end_offset']+150]} if focus else {}
    display_doc = _attachment_presentation(display_doc, meta)
    return _render(
        request, "document_detail.html", doc=display_doc, revision_row=target, revisions=revisions,
        stocks=stocks, meta=meta, body_html=html_body, is_old=is_old, search_focus=search_focus,
        body_chars=len(body), evidence_companies=companies, evidence_topics=TOPICS, evidence_focus=focus, evidence_context=focus_context, document_clips=evidence_store.list(document_id=document_id), industry_options=CATEGORIES, current_industries=((research.editorial().get(document_id,{}) or {}).get('industries') or (read_json(storage.path(f'derived/summaries/{document_id}.json')) or {}).get('industries',[])) if research else [],
        pdf_pages=pages, attachment=source_revision.get("attachment"),
    )


@app.get('/documents/{document_id}/export.pdf')
def export_document_pdf(document_id: str,revision: int | None=Query(None,ge=1)):
    if not storage.ready:raise HTTPException(503,'知识库目录未就绪')
    from ..document_pdf import export
    try:path,filename=export(storage,document_id,revision)
    except FileNotFoundError as exc:raise HTTPException(404,str(exc))
    except ValueError as exc:raise HTTPException(400,str(exc))
    return FileResponse(path,media_type='application/pdf',filename=filename,headers={'Cache-Control':'private','X-Content-Type-Options':'nosniff'})


@app.get('/youdao/{share_key}/images/{digest}')
def youdao_image(share_key: str,digest: str):
    from ..youdao import image
    try:path,mime=image(storage,share_key,digest)
    except Exception:raise HTTPException(404,'有道原图暂不可用，请查看原笔记')
    return FileResponse(path,media_type=mime,headers={'X-Content-Type-Options':'nosniff','Cache-Control':'private, max-age=86400'})


@app.get('/documents/{document_id}/images/{image_id}')
def source_image(document_id: str,image_id: str,revision: int=Query(...,ge=1)):
    if not storage.ready or not sources:raise HTTPException(503,'知识库或信源服务尚未就绪')
    with _conn() as conn:
        doc=index.get_document(conn,document_id)
        if not doc:raise HTTPException(404,'资料不存在')
        target=next((r for r in index.get_revisions(conn,document_id) if r['revision']==revision),None)
    if not target:raise HTTPException(404,'版本不存在')
    meta,_=split_frontmatter(storage.read_revision_text(target['archive_path']))
    from ..source_images import load
    try:
        path,media_type=load(storage,sources.client,document_id,revision,meta,image_id)
        return FileResponse(path,media_type=media_type,headers={'Cache-Control':'private, max-age=86400','X-Content-Type-Options':'nosniff','Cross-Origin-Resource-Policy':'same-origin','Content-Disposition':'inline'})
    except SourceError as exc:raise HTTPException(502,str(exc)) from None


@app.get("/documents/{document_id}/attachments/{file_id}/download")
def download_source_attachment(document_id: str, file_id: str, request: Request):
    if not storage.ready or not sources:
        raise HTTPException(503, "知识库或信源服务尚未就绪")
    with _conn() as conn:
        row = index.get_document(conn, document_id)
        if row is None:
            raise HTTPException(404, "资料不存在")
        rev = next((r for r in index.get_revisions(conn, document_id) if r["revision"] == row["current_revision"]), None)
    if not rev or row["source_platform"] != "zsxq":
        raise HTTPException(404, "附件不存在")
    meta, _ = split_frontmatter(storage.read_revision_text(rev["archive_path"]))
    file = next((f for f in meta.get("source_attachments", []) if f.get("kind") == "file" and str(f.get("file_id")) == file_id), None)
    if not file:
        raise HTTPException(404, "此资料中没有该附件")
    try:
        url = sources.client.download_url(file_id)
    except SourceError as exc:
        return _render(request, "error.html", code=502, error=str(exc), message=str(exc), status_code=502)
    return RedirectResponse(url, status_code=303, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@app.get("/stocks", response_class=HTMLResponse)
def stocks(request: Request, q: str = "", industry: str='', scope: str=Query('all',pattern='^(all|followed|unread)$'), sort: str=Query('recent',pattern='^(recent|coverage|name)$'), layout: str=Query('cards',pattern='^(cards|list)$'), page: int=Query(1,ge=1)):
    if not storage.ready:
        return _render(request, "storage_offline.html", error="知识库目录未就绪")
    if research:
        rows = Publications(research).stocks()

    else:
        with _conn() as conn:
            rows = index.list_stocks(conn, q or None)
    from ..company_directory import directory
    from ..following import preferences
    from urllib.parse import urlencode
    result=directory(rows,research.reading_state() if research else {},preferences(storage)['stocks'],q,industry,scope,sort,page)
    filters={'q':q,'industry':industry,'scope':scope,'sort':sort,'layout':layout}
    result.update(q=q,industry=industry,scope=scope,sort=sort,layout=layout,industries=CATEGORIES,
        page_url='/stocks?'+urlencode(filters),cards_url='/stocks?'+urlencode({**filters,'layout':'cards'}),list_url='/stocks?'+urlencode({**filters,'layout':'list'}))
    return _render(request, "stocks.html", **result)


@app.get("/stocks/{stock_id}", response_class=HTMLResponse)
def stock_detail(request: Request, stock_id: str, order: str = Query('desc', pattern='^(asc|desc)$'), show_hidden: bool=False, tab: str=Query('overview',pattern='^(overview|financials|timeline|files|notes)$'), financial_period: str=Query('latest',pattern='^(latest|annual|h1|q3|q1|all)$'), financial_metric: str='revenue', timeline_q: str='', timeline_start: str='', timeline_end: str=''):
    if not research:
        raise HTTPException(503, "研究服务尚未启动")
    publication=Publications(research)
    result = publication.stock_timeline(stock_id, order)
    if not result:
        raise HTTPException(404, "股票不存在")
    from ..company_search import filter_entries
    try:timeline_entries=filter_entries(result['entries'],publication.bodies,timeline_q,timeline_start,timeline_end)
    except ValueError as exc:raise HTTPException(400,str(exc))
    result.update(timeline_entries=timeline_entries,timeline_q=timeline_q.strip(),timeline_start=timeline_start,timeline_end=timeline_end)
    from ..company_research import journal
    from ..financials import cache,LABELS,display
    result.update(financials=cache(storage,result['stock']['stock_id']),financial_labels=LABELS,financial_display=display)
    from ..financial_views import periods,trend,PERIODS
    if financial_metric not in LABELS:raise HTTPException(400,'财务指标无效')
    financial_rows=periods(result['financials'].get('periods',[]),financial_period)
    result.update(financial_rows=financial_rows,financial_period=financial_period,financial_metric=financial_metric,financial_period_options=PERIODS,financial_chart=trend(financial_rows,financial_metric,LABELS[financial_metric]))
    ids={result['stock']['stock_id'],*result['stock'].get('member_ids',[])}
    result['personal_notes']=sorted([n for n in journal(storage).values() if n['company_id'] in ids and (show_hidden or not n.get('deleted'))],key=lambda n:n['created_at'],reverse=True)
    related=set(e['document_id'] for e in result['entries'])
    names=[result['stock'].get('name',''),*result['stock'].get('aliases',[])]
    attachment_rows=[]
    for manifest in storage.iter_manifests():
        fields=manifest.get('fields',{})
        for file in fields.get('source_attachments',[]):
            if file.get('kind')!='file':continue
            linked=manifest['document_id'] in related
            if not linked and not any(len(name)>=3 and name in file.get('name','') for name in names if name):continue
            attachment_rows.append({**file,'document_id':manifest['document_id'],'document_title':manifest.get('title',''),'match_kind':'关联调研附件' if linked else '文件名匹配，待核对'})
    recent=sorted(result['entries'],key=lambda e:e.get('published_at') or '',reverse=True)
    from ..company_research import QUESTION_STATES
    for note in result['personal_notes']:
        if note.get('topic')=='待验证' and 'known_document_versions' in note:
            note['new_evidence']=[entry for entry in recent if note['known_document_versions'].get(entry['document_id'])!=entry['revision']]
    from ..evidence import Evidence
    result['evidence_clips']=Evidence(storage).list(company_ids=ids)
    result.update(tab=tab,attachment_rows=attachment_rows,recent_entries=recent[:3],metric_change_count=sum(len(e['changes']) for e in result['entries']),question_count=sum(n['topic']=='待验证' and n.get('question_state','open') in ('open','inconclusive') for n in result['personal_notes']),question_states=QUESTION_STATES)
    return _render(request, "stock_detail.html", **result)


@app.get("/imports", response_class=HTMLResponse)
def imports(request: Request):
    if not storage.ready:
        return _render(request, "storage_offline.html", error="知识库目录未就绪")
    with _conn() as conn:
        batches = index.recent_batches(conn, 20)
        results = index.recent_results(conn, 50)
    pending = [p.name for p in pipeline.inbox_files()]
    return _render(request, "imports.html", batches=batches, results=results, pending=pending,
                   jobs=jobs.recent(), max_file_mb=cfg.max_file_mb, recovery_problems=recovery_problems)


# ---------- 接口 ----------

@app.get("/health")
def health():
    ready = storage.ready
    payload = {
        "service": "ok",
        "storage_ready": ready,
        "data_dir": str(cfg.data_dir),
        "recovery_problems": recovery_problems,
    }
    return JSONResponse(payload, status_code=200 if ready else 503)


@app.post("/api/v1/imports/scan")
def scan():
    if not storage.ready:
        return JSONResponse({"code": "storage_unavailable", "message": "知识库目录未就绪"}, status_code=503)
    return JSONResponse(jobs.enqueue(), status_code=202)


@app.post("/imports/scan")
def scan_form():
    if not storage.ready:
        return RedirectResponse("/", status_code=303)
    jobs.enqueue()
    return RedirectResponse("/imports", status_code=303)


@app.get("/api/v1/imports/jobs")
def import_jobs():
    return {"jobs": jobs.recent()}


@app.get("/sources", response_class=HTMLResponse)
def source_page(request: Request):
    if not storage.ready or not sources:
        return _render(request, "storage_offline.html", error="知识库目录未就绪")
    items = sources.list()
    with _conn() as conn:
        for item in items:
            item["document_count"] = conn.execute("SELECT COUNT(*) FROM documents WHERE source_platform='zsxq' "
                "AND source_space_id=? AND deleted_at IS NULL", (item["group_id"],)).fetchone()[0]
    return _render(request, "sources.html", sources=items)


@app.get("/api/v1/sources")
def source_list():
    return {"sources": sources.list() if sources else []}


@app.post("/api/v1/sources/zsxq")
async def add_source(request: Request):
    if not sources:
        raise HTTPException(503, "信源服务尚未启动")
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise SourceError("请提供星球 ID 和名称")
        return sources.register(str(payload.get("group_id", "")), str(payload.get("name", "")))
    except (SourceError, ValueError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v1/sources/zsxq/{group_id}/sync")
def sync_source(group_id: str, mode: str = "latest"):
    if not sources:
        raise HTTPException(503, "信源服务尚未启动")
    try:
        return JSONResponse(sources.enqueue(group_id, mode), status_code=202)
    except SourceError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v1/imports/upload")
async def upload(request: Request, filename: str = Query(..., max_length=180)):
    if not storage.ready:
        raise HTTPException(503, "知识库目录未就绪")
    if (Path(filename).name != filename or "\\" in filename or filename.startswith(".")
            or any(ord(c) < 32 for c in filename) or len(filename.encode("utf-8")) > 240):
        raise HTTPException(400, "文件名无效")
    if Path(filename).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise HTTPException(400, "支持 PDF、JSONL、Markdown 和 TXT")
    fd, temp_name = tempfile.mkstemp(dir=cfg.inbox_dir, prefix=".upload-")
    temporary = Path(temp_name)
    total = 0
    try:
        with os.fdopen(fd, "wb") as out:
            async for chunk in request.stream():
                total += len(chunk)
                if total > cfg.max_file_mb * 1024 * 1024:
                    raise HTTPException(413, f"文件超过 {cfg.max_file_mb}MB 上限")
                out.write(chunk)
            if total == 0:
                raise HTTPException(400, "不能上传空文件")
            out.flush()
            os.fsync(out.fileno())
        try:
            os.link(temporary, cfg.inbox_dir / filename)
        except FileExistsError:
            raise HTTPException(409, "同名文件正在等待导入，请稍后重试")
        if cfg.require_ready_marker:
            atomic_write_json(cfg.inbox_dir / (filename + ".ready.json"), {"ready": True})
    finally:
        temporary.unlink(missing_ok=True)
    return JSONResponse(jobs.enqueue(), status_code=202)


@app.post("/imports/{batch_id}/retry")
def retry_import(batch_id: str):
    if not storage.ready:
        raise HTTPException(503, "知识库目录未就绪")
    if not batch_id.startswith("imp_") or not batch_id[4:].isalnum():
        raise HTTPException(404, "批次不存在")
    payload = read_json(storage.path(f"jobs/imports/{batch_id}.json"))
    if not payload:
        raise HTTPException(404, "批次不存在")
    name = payload["file_name"]
    source = storage.resolve_path(f"processed/{batch_id}/{name}")
    if not source.is_file():
        raise HTTPException(404, "原始导入包不存在，请重新上传")
    # Publish a complete file atomically so another scan cannot read a partial copy.
    fd, tmp = tempfile.mkstemp(dir=cfg.inbox_dir, prefix=".retry-")
    os.close(fd)
    try:
        shutil.copy2(source, tmp)
        try:
            os.link(tmp, cfg.inbox_dir / name)
        except FileExistsError:
            raise HTTPException(409, "同名文件已在待导入目录")
        if cfg.require_ready_marker:
            atomic_write_json(cfg.inbox_dir / (name + ".ready.json"), {"ready": True})
    finally:
        Path(tmp).unlink(missing_ok=True)
    jobs.enqueue()
    return RedirectResponse("/imports", status_code=303)


def _original_response(attachment: dict):
    path = storage.resolve_path(attachment["path"])
    if not path.is_file():
        raise HTTPException(404, "PDF 原件缺失")
    return FileResponse(path, media_type="application/pdf", filename=attachment["file_name"],
                        content_disposition_type="inline", headers={"X-Content-Type-Options": "nosniff"})


@app.get("/documents/{document_id}/original")
def original_document(document_id: str, revision: int | None = None):
    if not document_id.startswith("doc_") or not document_id[4:].isalnum():
        raise HTTPException(404, "资料不存在")
    manifest = storage.read_manifest(document_id)
    if not manifest:
        raise HTTPException(404, "资料不存在")
    number = revision if revision is not None else manifest["current_revision"]
    rev = next((r for r in manifest["revisions"] if r["revision"] == number), None)
    if not rev or not rev.get("attachment"):
        raise HTTPException(404, "该版本没有 PDF 原件")
    return _original_response(rev["attachment"])


@app.get("/imports/{batch_id}/original")
def original_import(batch_id: str):
    if not batch_id.startswith("imp_") or not batch_id[4:].isalnum():
        raise HTTPException(404, "批次不存在")
    payload = read_json(storage.path(f"jobs/imports/{batch_id}.json"))
    if not payload or not payload.get("original"):
        raise HTTPException(404, "该批次没有 PDF 原件")
    return _original_response(payload["original"])


@app.post("/api/v1/documents/{document_id}/metadata")
async def edit_metadata(document_id: str, request: Request):
    if not storage.ready:
        raise HTTPException(503, "知识库目录未就绪")
    if not document_id.startswith("doc_") or not document_id[4:].isalnum():
        raise HTTPException(404, "资料不存在")
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise RecordError("元信息必须是对象")
        # File/index writes run in a thread, keeping the event loop responsive.
        from starlette.concurrency import run_in_threadpool
        result = await run_in_threadpool(pipeline.update_metadata, document_id, payload)
        return {"document_id": result.document_id, "revision": result.revision, "status": result.status}
    except (RecordError, ValueError) as exc:
        raise HTTPException(400, str(exc))


# ---------- 辅助 ----------

def _stocks_by_doc(conn, document_ids: list[str]) -> dict[str, list]:
    mapping: dict[str, list] = {}
    for document_id in document_ids:
        mapping[document_id] = index.stocks_of_document(conn, document_id)
    return mapping


@app.exception_handler(404)
def not_found(request: Request, exc):  # pragma: no cover
    return _render(request, "error.html", status_code=404,
                   error=getattr(exc, "detail", None) or "页面或资料不存在", code=404)


def run() -> None:
    import uvicorn

    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")


@app.get("/settings", response_class=HTMLResponse)
def research_settings(request: Request):
    if not research:
        raise HTTPException(503, "整理服务未启动")
    try:
        has_key = bool(research.secrets.get())
    except ResearchError:
        has_key = False
    return _render(request, "research_settings.html", settings=research.settings(), has_key=has_key, state=research.state(), usage=research.provider.usage())


@app.post("/api/v1/research/settings")
async def save_research_settings(request: Request):
    if not research:
        raise HTTPException(503, "整理服务未启动")
    try:
        research.save(await request.json())
        return {"ok": True}
    except ResearchError as exc:
        raise HTTPException(400, str(exc)) from None


@app.post("/api/v1/research/run")
def run_research(collect: bool = True):
    if not research:
        raise HTTPException(503, "整理服务未启动")
    try:
        return research.enqueue(collect)
    except ResearchError as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/api/v1/research/status")
def research_status():
    return research.state() if research else {"status": "offline"}


@app.get("/reading", response_class=HTMLResponse)
def reading(request: Request, q: str = "", industry: str = "", unread: bool = False, start: str = "", end: str = "", starred: bool = False, selected: bool = False, dedup: bool = False, days: int = 0, page: int = Query(1, ge=1)):
    from datetime import date
    for value in (start, end):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                raise HTTPException(400, "日期格式无效") from None
    from ..research_views import views, link, date_range, unread_counts, matches
    try:start,end=date_range({'days':days,'start':start,'end':end})
    except ValueError as exc:raise HTTPException(400,str(exc))
    if start and end and start>end:raise HTTPException(400,'开始日期不能晚于结束日期')
    saved_views=[{**v,"url":link(v["filters"])} for v in views(storage)] if storage.ready else []
    publication = Publications(research) if research else None
    notes = publication.notes if publication else []
    stock_names = {}
    if publication:
        for item in publication.stocks():
            stock_names.setdefault(item.get("name"),item["stock_id"])
        event_by_doc = {n["document_id"]:e for e in publication.events() for n in e["reports"]}
        for note in notes:
            for item in note.get("stocks",[]):
                item["timeline_id"] = stock_names.get(item.get("name"))
            event = event_by_doc.get(note["document_id"],{})
            note["event_id"] = event.get("event_id")
            note["event_report_count"] = event.get("report_count",1)
    states = research.reading_state() if research else {}
    for note in notes:
        note['is_read'] = states.get(note['document_id'], {}).get('read', False)
        note['is_starred'] = states.get(note['document_id'], {}).get('starred', False)
        stamp = parse_iso(note.get('published_at'))
        note['reading_day'] = stamp.astimezone(TZ).date().isoformat() if stamp else '日期未知'
        note['reading_time'] = stamp.astimezone(TZ).strftime('%H:%M') if stamp else '—'
        note['industries'] = categories(note.get('industries', []))
    saved_views=unread_counts(notes,saved_views)
    notes = [n for n in notes if matches(n,{'unread':unread,'starred':starred,'selected':selected,'start':start,'end':end})]
    all_groups, _ = group_notes(notes, q=q)
    counts = {g['name']: g['count'] for g in all_groups}
    category_counts = [{'name': name, 'count': counts.get(name, 0)} for name in (*CATEGORIES, '待分类')]
    groups, total = group_notes(notes, q=q, industry=industry)
    feed_notes = [n for n in notes if (not industry or industry in n["industries"]) and
                  (not q or q.casefold() in json.dumps({k: n.get(k) for k in ("title", "summary", "industries", "stocks", "key_points", "risks")}, ensure_ascii=False).casefold())]
    if selected and publication:
        feed_notes=publication.selected_reports(feed_notes)
        groups,total=group_notes(feed_notes,q='',industry=industry)
        counted,_=group_notes(feed_notes)
        counts={g['name']:g['count'] for g in counted}
        category_counts=[{'name':name,'count':counts.get(name,0)} for name in (*CATEGORIES,'待分类')]
    raw_report_count=len(feed_notes)
    if dedup and publication:
        feed_notes=publication.reading_groups(feed_notes)
        total=len(feed_notes)
    page_count = max(1, (len(feed_notes) + 29) // 30)
    page = min(page, page_count)
    feed_notes = feed_notes[(page - 1) * 30:page * 30]
    return _render(request, "reading.html", groups=groups, feed_notes=feed_notes, category_counts=category_counts,
                   page=page, page_count=page_count, starred=starred, selected=selected, dedup=dedup, raw_report_count=raw_report_count, saved_views=saved_views,
                   total=total, q=q, industry=industry, unread=unread, start=start, end=end, days=days,
                   state=research.state() if research else {'status':'offline'})


@app.post("/api/v1/research/reading/{document_id}")
async def mark_reading(document_id: str, request: Request):
    if not research:
        raise HTTPException(503, "整理服务未启动")
    data = await request.json()
    if type(data.get('read')) is not bool:
        raise HTTPException(400, "read 必须为布尔值")
    try:
        research.mark_read(document_id, data['read'])
        return {'ok': True}
    except ResearchError as exc:
        raise HTTPException(400, str(exc)) from None


@app.post("/api/v1/research/starred/{document_id}")
async def star_reading(document_id: str, request: Request):
    if not research:
        raise HTTPException(503, "整理服务未启动")
    data = await request.json()
    if type(data.get('starred')) is not bool:
        raise HTTPException(400, "starred 必须为布尔值")
    try:
        research.mark_starred(document_id, data['starred'])
        return {'ok': True}
    except ResearchError as exc:
        raise HTTPException(400, str(exc)) from None


@app.post('/api/v1/research/enrich')
def enrich_research():
    if not research:
        raise HTTPException(503, '研究服务尚未启动')
    try:
        return research.enqueue_enrichment()
    except ResearchError as exc:
        raise HTTPException(400,str(exc)) from None


@app.post('/api/v1/research/selection/{document_id}')
async def editorial_selection(document_id: str, request: Request):
    if not research:
        raise HTTPException(503, '研究服务尚未启动')
    value = (await request.json()).get('selected')
    if value is not None and type(value) is not bool:
        raise HTTPException(400,'selected 必须为布尔值或 null')
    try:
        research.edit_selection(document_id,value)
        return {'ok':True}
    except ResearchError as exc:
        raise HTTPException(400,str(exc)) from None


@app.get('/events', response_class=HTMLResponse)
def events_page(request: Request, industry: str = ''):
    if not research:
        raise HTTPException(503,'研究服务尚未启动')
    events = Publications(research).events()
    if industry:
        events = [e for e in events if industry in e['industries']]
    return _render(request,'events.html',events=events,industry=industry,industries=CATEGORIES)


@app.get('/events/{event_id}', response_class=HTMLResponse)
def event_page(request: Request, event_id: str):
    if not research:
        raise HTTPException(503,'研究服务尚未启动')
    event = next((e for e in Publications(research).events() if e['event_id']==event_id),None)
    if not event:
        raise HTTPException(404,'事件不存在')
    return _render(request,'event.html',event=event,event_overrides=research.event_overrides())


def brief_window(value, period):
    from datetime import date, timedelta
    try:
        default=today_str()
        if not value and research:
            available=[n['published_at'][:10] for n in research.notes() if n.get('published_at') and n['published_at'][:10]<=default]
            default=max(available,default=default)
        day = date.fromisoformat(value or default)
    except ValueError:
        raise HTTPException(400,'日期格式无效') from None
    if period=='week':
        start = day-timedelta(days=day.weekday())
        end = start+timedelta(days=6)
    elif period=='month':
        from calendar import monthrange
        start,end = day.replace(day=1), day.replace(day=monthrange(day.year,day.month)[1])
    elif period=='day':
        start=end=day
    else:
        raise HTTPException(400,'周期无效')
    return start.isoformat(),end.isoformat()


@app.get('/briefing', response_class=HTMLResponse)
def briefing_page(request: Request, date: str = '', period: str = 'day', industry: str = ''):
    if not research:
        raise HTTPException(503,'研究服务尚未启动')
    start,end = brief_window(date,period)
    publication = Publications(research)
    report = publication.digest(start,end,industry)
    days = sorted({n['published_at'][:10] for n in publication.notes if n.get('published_at')},reverse=True)
    return _render(request,'briefing.html',report=report,date=date or start,period=period,industry=industry,industries=CATEGORIES,days=days[:30])


@app.get('/api/v1/research/events')
def event_api():
    if not research:
        raise HTTPException(503,'研究服务尚未启动')
    return {'events':Publications(research).events()}


@app.get('/api/v1/stocks/{stock_id}/timeline')
def stock_timeline_api(stock_id: str, order: str = Query('desc',pattern='^(asc|desc)$')):
    if not research:
        raise HTTPException(503,'研究服务尚未启动')
    result = Publications(research).stock_timeline(stock_id,order)
    if not result:
        raise HTTPException(404,'个股不存在')
    return result


@app.get('/api/v1/research/briefing')
def briefing_api(date: str = '', period: str = 'day', industry: str = ''):
    if not research:
        raise HTTPException(503,'研究服务尚未启动')
    start,end = brief_window(date,period)
    return Publications(research).digest(start,end,industry)


@app.get('/api/v1/research/search')
def research_search_api(q: str = Query('',max_length=200)):
    if not research:
        raise HTTPException(503,'研究服务尚未启动')
    return {'documents':Publications(research).search(q)}


@app.get('/rss.xml')
def research_rss(request: Request, selected: bool = False):
    from xml.etree.ElementTree import Element,SubElement,tostring
    from email.utils import format_datetime
    if not research:
        raise HTTPException(503,'研究服务尚未启动')
    root = Element('rss',version='2.0')
    channel = SubElement(root,'channel')
    base = str(request.base_url).rstrip('/')
    for tag,text in [('title','财经研究知识库'),('link',base+'/reading'),('description','本机研究资料摘要与原文链接')]:
        SubElement(channel,tag).text = text
    publication=Publications(research)
    for note in (publication.selected_reports() if selected else publication.notes)[:50]:
        item=SubElement(channel,'item')
        for tag,text in [('title',note['title']),('link',base+'/documents/'+note['document_id']),('description',note['summary']),('guid',note['document_id']+'-r'+str(note['revision']))]:
            node=SubElement(item,tag)
            node.text=text
            if tag=='guid':
                node.set('isPermaLink','false')
        stamp=parse_iso(note.get('published_at'))
        if stamp:
            SubElement(item,'pubDate').text = format_datetime(stamp)
    return Response(tostring(root,encoding='utf-8',xml_declaration=True),media_type='application/rss+xml')


@app.get('/api/v1/research/receipts')
def model_receipts():
    if not research:
        raise HTTPException(503,'研究服务尚未启动')
    fields = ('id','model','purpose','status','updated_at','attempts','document_ids')
    rows = [{k:r.get(k) for k in fields} for r in research.provider.receipts()]
    return {'usage':research.provider.usage(),'receipts':sorted(rows,key=lambda r:r.get('updated_at',''),reverse=True)[:100]}


@app.post('/api/v1/research/receipts/{identity}/release')
def release_receipt(identity: str):
    if not research:
        raise HTTPException(503,'研究服务尚未启动')
    try:
        research.provider.release(identity)
        return {'ok':True}
    except LLMError as exc:
        raise HTTPException(400,str(exc)) from None


@app.get('/agent', response_class=HTMLResponse)
def agent_page(request: Request):
    return _render(request,'agent.html',base=str(request.base_url).rstrip('/'))


@app.get('/llms.txt')
def agent_index(request: Request):
    base=str(request.base_url).rstrip('/')
    return Response(f'# 财经研究知识库\n\n本机私有资料库。只读接口，不在阅读或检索时调用模型。\n\n- 研究动态: {base}/reading\n- 事件: {base}/events\n- 个股时间线: {base}/stocks\n- 简报: {base}/briefing\n- RSS: {base}/rss.xml\n- MCP (2025-11-25): POST {base}/mcp\n- 接入说明: {base}/agent\n',media_type='text/plain')


def validate_mcp_origin(request):
    from urllib.parse import urlparse
    if request.url.hostname not in {'localhost','127.0.0.1','::1','testserver'}:
        raise HTTPException(403,'仅允许本机访问')
    origin=request.headers.get('origin')
    if origin and (urlparse(origin).hostname not in {'localhost','127.0.0.1','::1'} or urlparse(origin).netloc != request.url.netloc):
        raise HTTPException(403,'Origin 不被允许')


@app.get('/mcp')
def mcp_get(request: Request):
    validate_mcp_origin(request)
    return Response(status_code=405,headers={'Allow':'POST'})


@app.post('/mcp')
async def mcp_post(request: Request):
    from ..agent import TOOLS, call_tool
    validate_mcp_origin(request)
    accept=request.headers.get('accept','')
    if 'application/json' not in accept or 'text/event-stream' not in accept:
        raise HTTPException(406,'Accept 需包含 application/json 和 text/event-stream')
    try:
        body=await request.json()
    except Exception:
        return JSONResponse({'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'JSON 无效'}},status_code=400)
    if not isinstance(body,dict) or body.get('jsonrpc')!='2.0' or not isinstance(body.get('method'),str):
        return JSONResponse({'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'JSON-RPC 请求无效'}},status_code=400)
    method,identity=body['method'],body.get('id')
    if identity is None:
        return Response(status_code=202)
    if method=='initialize':
        result={'protocolVersion':'2025-11-25','serverInfo':{'name':'stock-kb','version':'1.0.0'},'capabilities':{'tools':{'listChanged':False}},'instructions':'本机只读财经资料库；投资观点来自原文，请保留来源和报告期。'}
    elif method=='ping':
        result={}
    elif method=='tools/list':
        result={'tools':TOOLS}
    elif method=='tools/call':
        if not research:
            raise HTTPException(503,'研究服务尚未启动')
        params=body.get('params') or {}
        if not isinstance(params,dict):
            return {'jsonrpc':'2.0','id':identity,'error':{'code':-32602,'message':'参数无效'}}
        try:
            data=call_tool(Publications(research),params.get('name'),params.get('arguments') or {},brief_window)
            result={'content':[{'type':'text','text':json.dumps(data,ensure_ascii=False)}],'isError':False}
        except (ValueError, HTTPException) as exc:
            result={'content':[{'type':'text','text':str(exc.detail) if isinstance(exc,HTTPException) else str(exc)}],'isError':True}
    else:
        return {'jsonrpc':'2.0','id':identity,'error':{'code':-32601,'message':'方法不存在'}}
    return JSONResponse({'jsonrpc':'2.0','id':identity,'result':result},headers={'Cache-Control':'no-store'})


@app.post('/api/v1/research/events/separate/{document_id}')
async def separate_event_api(document_id: str, request: Request):
    if not research:
        raise HTTPException(503,'研究服务尚未启动')
    separate=(await request.json()).get('separate')
    if type(separate) is not bool:
        raise HTTPException(400,'separate 必须为布尔值')
    try:
        research.separate_event(document_id,separate)
        return {'ok':True}
    except ResearchError as exc:
        raise HTTPException(400,str(exc)) from None


@app.get('/api/v1/research/calibration')
def calibration_api():
    if not research:
        raise HTTPException(503,'研究服务尚未启动')
    notes={n['document_id']:n for n in research.notes()}
    labels={k:v['selected'] for k,v in research.editorial().items() if k in notes and type(v.get('selected')) is bool}
    covered=correct=tp=fp=fn=0
    for key,label in labels.items():
        score=notes[key].get('intelligence',{}).get('score')
        if type(score) is not int:
            continue
        covered+=1
        predicted=score>=research.settings()['selection_threshold']
        correct+=predicted==label
        tp+=predicted and label
        fp+=predicted and not label
        fn+=not predicted and label
    return {'labelled':len(labels),'scored':covered,'accuracy':correct/covered if covered else None,
            'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None,
            'coverage':covered/len(labels) if labels else None,'note':'仅反映当前人工样本，不能作为总体效果结论'}


@app.get('/api/v1/research/reading-state/export')
def export_reading_state():
    if not research:
        raise HTTPException(503,'研究服务尚未启动')
    return JSONResponse({'format':'stock-kb-reading-state','version':1,'entries':research.reading_state()},headers={'Content-Disposition':'attachment; filename="reading-state.json"'})


@app.post('/api/v1/research/reading-state/import')
async def import_reading_state(request: Request):
    import re
    if not research:
        raise HTTPException(503,'研究服务尚未启动')
    raw=await request.body()
    if len(raw)>2_000_000:
        raise HTTPException(400,'导入文件超过2MB')
    try:
        value=json.loads(raw)
    except Exception:
        raise HTTPException(400,'JSON 文件无效') from None
    if not isinstance(value,dict) or value.get('format')!='stock-kb-reading-state' or value.get('version')!=1 or not isinstance(value.get('entries'),dict):
        raise HTTPException(400,'不是本程序的阅读状态文件')
    updates={}
    skipped=0
    for key,row in value['entries'].items():
        if not isinstance(row,dict) or not re.fullmatch(r'doc_[0-9A-Z]{26}',key) or not storage.read_manifest(key):
            skipped+=1
            continue
        if any(type(row[field]) is not bool for field in ('read','starred') if field in row):
            raise HTTPException(400,'阅读或收藏字段无效，未写入任何状态')
        updates[key]={k:row[k] for k in ('read','starred') if k in row}
    with research.lock:
        states=research.reading_state()
        for key,row in updates.items():
            states[key]={**states.get(key,{}),**row,'updated_at':now_iso()}
        atomic_write_json(storage.path('catalog/reading-state.json'),states)
    return {'ok':True,'imported':len(updates),'skipped':skipped}


@app.get('/api/v1/research/runs')
def research_run_history():
    if not research:
        raise HTTPException(503,'研究服务尚未启动')
    paths=sorted(storage.path('jobs/research-runs').glob('res_*.json'),reverse=True)[:30]
    return {'runs':[read_json(path) for path in paths]}


@app.get('/following', response_class=HTMLResponse)
def following_page(request: Request, industry: str='', topic: str='', new: bool=False):
    from ..following import preferences, matched_notes, subtopics, SUBTOPICS
    if not research: raise HTTPException(503,'研究服务未启动')
    publication=Publications(research)
    prefs=preferences(storage)
    followed=matched_notes(publication,prefs)
    notes=publication.notes if industry else followed
    notes=[n for n in notes if not industry or industry in n.get('industries',[])]
    viewed=[]
    for note in notes:
        labels=subtopics(note,publication.bodies.get(note['document_id'],''))
        if topic and (industry,topic) not in labels: continue
        if new and not note.get('is_new',False): continue
        viewed.append({**note,'subtopics':labels})
    return _render(request,'following.html',prefs=prefs,companies=publication.stocks(),industries=CATEGORIES,industry=industry,topic=topic,topics=SUBTOPICS.get(industry,{}),notes=viewed,new_count=sum(n['is_new'] for n in followed),total=len(viewed))


@app.post('/api/v1/following')
async def save_following(request: Request):
    from ..following import save_preferences
    if not research: raise HTTPException(503,'研究服务未启动')
    try:
        with research.lock:
            save_preferences(storage,await request.json(),{s['stock_id'] for s in Publications(research).stocks()})
        return {'saved':True}
    except ValueError as exc: raise HTTPException(400,str(exc))


@app.post('/api/v1/following/seen')
def mark_following_seen():
    from ..following import preferences,matched_notes
    if not research: raise HTTPException(503,'研究服务未启动')
    with research.lock:
        prefs=preferences(storage)
        prefs['seen']=sorted(set(prefs['seen'])|{f"{n['document_id']}:{n['revision']}" for n in matched_notes(Publications(research),prefs)})
        prefs['last_reviewed_at']=now_iso()
        atomic_write_json(storage.path('catalog/following.json'),prefs)
    return {'saved':True}


@app.post('/api/v1/research/industries/{document_id}')
async def correct_industries(document_id: str, request: Request):
    if not research: raise HTTPException(503,'研究服务未启动')
    import re
    if not re.fullmatch(r'doc_[0-9A-Z]{26}',document_id) or not storage.read_manifest(document_id): raise HTTPException(404,'资料不存在')
    data=await request.json()
    labels=data.get('industries') if isinstance(data,dict) else False
    if labels is not None and (not isinstance(labels,list) or not labels or any(x not in CATEGORIES for x in labels)):
        raise HTTPException(400,'请选择有效行业，或传 null 恢复自动分类')
    with research.lock:
        editorial=research.editorial()
        item=editorial.setdefault(document_id,{})
        if labels is None: item.pop('industries',None)
        else: item['industries']=list(dict.fromkeys(labels))
        item['updated_at']=now_iso()
        atomic_write_json(storage.path('catalog/editorial.json'),editorial)
    return {'saved':True}


@app.get('/companies/manage', response_class=HTMLResponse)
def manage_companies(request: Request):
    from ..company_research import identities
    if not research: raise HTTPException(503,'研究服务未启动')
    return _render(request,'companies_manage.html',companies=Publications(research).stocks(),links=identities(storage))


@app.post('/api/v1/companies/merge')
async def merge_companies(request: Request):
    from ..company_research import merge,identities
    if not research: raise HTTPException(503,'研究服务未启动')
    data=await request.json()
    if not isinstance(data,dict):raise HTTPException(400,'参数无效')
    try:
        with research.lock:
            if data.get('undo'):
                links=identities(storage)
                links.pop(str(data.get('source','')),None)
                atomic_write_json(storage.path('catalog/company-identities.json'),links)
            else:
                catalog={s['stock_id']:s for s in Publications(research).stocks()}
                merge(storage,data.get('source'),data.get('target'),set(catalog))
                links=identities(storage)
                links[data['source']].update(source_name=catalog[data['source']].get('name'),target_name=catalog[data['target']].get('name'))
                atomic_write_json(storage.path('catalog/company-identities.json'),links)
        return {'saved':True}
    except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))


@app.post('/api/v1/stocks/{stock_id}/notes')
async def add_stock_note(stock_id: str, request: Request):
    from ..company_research import save_note
    if not research: raise HTTPException(503,'研究服务未启动')
    timeline=Publications(research).stock_timeline(stock_id)
    if not timeline:raise HTTPException(404,'公司不存在')
    data=await request.json()
    try:
        with research.lock:
            note=save_note(storage,timeline['stock']['stock_id'],data,{timeline['stock']['stock_id']},{e['document_id'] for e in timeline['entries']},known_versions={e['document_id']:e['revision'] for e in timeline['entries']})
        return {'id':note['id']}
    except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))


@app.post('/api/v1/stocks/notes/{note_id}/visibility')
async def hide_stock_note(note_id: str, request: Request):
    from ..company_research import journal
    if not research:raise HTTPException(503,'研究服务未启动')
    data=await request.json()
    if not isinstance(data,dict) or type(data.get('deleted')) is not bool:raise HTTPException(400,'参数无效')
    with research.lock:
        notes=journal(storage)
        if note_id not in notes:raise HTTPException(404,'笔记不存在')
        notes[note_id]['deleted']=data['deleted']
        atomic_write_json(storage.path('catalog/company-journal.json'),notes)
    return {'saved':True}


@app.get('/stocks/{stock_id}/export.md')
def export_stock_research(stock_id: str, request: Request, personal: bool=False):
    from ..research_export import dossier
    from ..company_research import journal
    if not research:raise HTTPException(503,'研究服务未启动')
    timeline=Publications(research).stock_timeline(stock_id,'asc')
    if not timeline:raise HTTPException(404,'公司不存在')
    notes=None
    if personal:
        ids={timeline['stock']['stock_id'],*timeline['stock'].get('member_ids',[])}
        notes=sorted([n for n in journal(storage).values() if n['company_id'] in ids and not n.get('deleted')],key=lambda n:n['created_at'])
    return Response(dossier(timeline,str(request.base_url).rstrip('/'),notes),media_type='text/markdown',headers={'Content-Disposition':'attachment; filename="company-research.md"','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


@app.get('/api/v1/stocks/{stock_id}/financials')
def stock_financials(stock_id: str):
    from ..financials import cache
    if not research:raise HTTPException(503,'研究服务未启动')
    timeline=Publications(research).stock_timeline(stock_id)
    if not timeline:raise HTTPException(404,'公司不存在')
    return cache(storage,timeline['stock']['stock_id'])


@app.post('/api/v1/stocks/{stock_id}/financials')
async def refresh_stock_financials(stock_id: str, request: Request):
    from ..financials import refresh,FinancialError
    from starlette.concurrency import run_in_threadpool
    if not research:raise HTTPException(503,'研究服务未启动')
    timeline=Publications(research).stock_timeline(stock_id)
    if not timeline:raise HTTPException(404,'公司不存在')
    data=await request.json()
    if not isinstance(data,dict):raise HTTPException(400,'参数无效')
    security=timeline['stock'].get('security') if data.get('use_directory') is True else None
    if not security and data.get('confirmed') is not True:raise HTTPException(400,'未能唯一匹配证券，请核对代码或在证券目录中查找')
    try:
        value=await run_in_threadpool(refresh,storage,timeline['stock']['stock_id'],security['code'] if security else data.get('code',''),security['exchange'] if security else data.get('exchange',''),expected_name=security['name'] if security else None)
        return {'updated':True,'company_name':value['company_name'],'fetched_at':value['fetched_at']}
    except FinancialError as exc:raise HTTPException(400,str(exc))


@app.get('/securities',response_class=HTMLResponse)
def securities_page(request: Request,q: str=''):
    from ..securities import Securities
    master=Securities(storage)
    return _render(request,'securities.html',q=q,rows=master.search(q),stats=master.stats())


@app.get('/api/v1/securities')
def search_securities(q: str=''):
    from ..securities import Securities
    master=Securities(storage)
    return {'securities':master.search(q),'stats':master.stats()}


@app.post('/api/v1/securities/sync')
def update_security_directory():
    from ..securities import Securities
    try:return Securities(storage).sync()
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.post('/api/v1/securities/sync-hk')
def update_hk_security_directory():
    from ..securities import Securities
    try:return Securities(storage).sync_hk()
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.post('/api/v1/stocks/notes/{note_id}/question')
async def update_research_question(note_id: str,request: Request):
    from ..company_research import journal,update_question
    if not research:raise HTTPException(503,'研究服务未启动')
    note=journal(storage).get(note_id)
    if not note:raise HTTPException(404,'记录不存在')
    timeline=Publications(research).stock_timeline(note['company_id'])
    if not timeline:raise HTTPException(404,'公司不存在')
    data=await request.json()
    try:
        with research.lock:
            update_question(storage,note_id,data,{entry['document_id']:entry['revision'] for entry in timeline['entries']})
        return {'saved':True}
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.get('/evidence',response_class=HTMLResponse)
def evidence_library(request: Request,q: str='',topic: str='',company_id: str='',hidden: bool=False,page: int=Query(1,ge=1)):
    from ..evidence import Evidence,TOPICS
    if not storage.ready:raise HTTPException(503,'知识库未就绪')
    companies=Publications(research).stocks() if research else []
    ids=None
    if company_id:
        timeline=Publications(research).stock_timeline(company_id) if research else None
        ids={timeline['stock']['stock_id'],*timeline['stock'].get('member_ids',[])} if timeline else {company_id}
    from urllib.parse import urlencode
    store=Evidence(storage);total=store.count(q,topic,ids,hidden=hidden)
    pages=max(1,(total+29)//30);page=min(page,pages)
    base='/evidence?'+urlencode({'q':q,'topic':topic,'company_id':company_id,'hidden':str(hidden).lower()})
    return _render(request,'evidence.html',rows=store.list(q,topic,ids,hidden=hidden,limit=30,offset=(page-1)*30),total=total,page=page,pages=pages,page_url=base,q=q,topic=topic,company_id=company_id,hidden=hidden,topics=TOPICS,companies=companies)


@app.post('/api/v1/documents/{document_id}/evidence')
async def create_evidence_clip(document_id: str,request: Request):
    from ..evidence import Evidence
    if not research:raise HTTPException(503,'研究服务未启动')
    data=await request.json()
    if not isinstance(data,dict):raise HTTPException(400,'摘录参数无效')
    try:
        row,created=Evidence(storage).create(document_id,data.get('revision'),data,{s['stock_id']:s.get('name') or s.get('code') for s in Publications(research).stocks()})
        return {'id':row['id'],'created':created,'hidden':bool(row['hidden']),'url':f"/documents/{row['document_id']}?revision={row['revision']}&excerpt={row['id']}#source-evidence"}
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.post('/api/v1/evidence/{clip_id}/visibility')
async def hide_evidence(clip_id: str,request: Request):
    from ..evidence import Evidence
    if not storage.ready:raise HTTPException(503,'知识库未就绪')
    data=await request.json()
    try:
        Evidence(storage).hide(clip_id,data.get('hidden') if isinstance(data,dict) else None)
        return {'saved':True}
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.post('/api/v1/research/views')
async def save_reading_view(request: Request):
    from ..research_views import save,link
    if not storage.ready:raise HTTPException(503,'知识库未就绪')
    try:
        row=save(storage,await request.json())
        return {**row,'url':link(row['filters'])}
    except ValueError as exc:raise HTTPException(400,str(exc))

@app.delete('/api/v1/research/views/{view_id}')
def remove_reading_view(view_id: str):
    from ..research_views import remove
    if not storage.ready:raise HTTPException(503,'知识库未就绪')
    try:remove(storage,view_id);return {'saved':True}
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.get('/international',response_class=HTMLResponse)
def international_page(request: Request):
    from ..international_sources import PROVIDERS,states
    if not storage.ready:raise HTTPException(503,'知识库尚未就绪')
    status=states(storage)
    with _conn() as conn:
        rows=[dict(r) for r in conn.execute("SELECT document_id,title,source_platform,published_at,imported_at FROM documents WHERE source_platform IN ("+','.join('?' for _ in PROVIDERS)+") AND deleted_at IS NULL ORDER BY imported_at DESC LIMIT 40",tuple(PROVIDERS))]
        counts={r['source_platform']:r['n'] for r in conn.execute("SELECT source_platform,COUNT(*) n FROM documents WHERE deleted_at IS NULL GROUP BY source_platform")}
    return _render(request,'international.html',providers=PROVIDERS,status=status,rows=rows,counts=counts)


@app.get('/api/v1/international/providers')
def international_providers():
    from ..international_sources import PROVIDERS,states
    return {'providers':PROVIDERS,'status':states(storage),'native_report_api_connected':False}


@app.post('/api/v1/international/{provider_id}/sync')
def sync_international_source(provider_id: str):
    from ..international_sources import sync_public
    if not storage.ready:raise HTTPException(503,'知识库尚未就绪')
    try:return sync_public(pipeline,provider_id)
    except ValueError as exc:raise HTTPException(400,str(exc)) from None


@app.post('/api/v1/international/{provider_id}/reports')
async def import_international_reports(provider_id: str,request: Request):
    from ..international_sources import import_reports
    if not storage.ready:raise HTTPException(503,'知识库尚未就绪')
    data=await request.json()
    if not isinstance(data,dict):raise HTTPException(400,'请提交包含reports数组的对象')
    try:return import_reports(pipeline,provider_id,data.get('reports'))
    except ValueError as exc:raise HTTPException(400,str(exc)) from None


@app.get('/international/reports',response_class=HTMLResponse)
def public_report_library(request: Request):
    from ..international_reports import reports
    from ..international_sources import PROVIDERS
    return _render(request,'public_reports.html',reports=reports(storage),providers=PROVIDERS)


@app.get('/international/reports/{report_id}',response_class=HTMLResponse)
def public_report_reader(report_id: str,request: Request,lang: str=Query('zh',pattern='^(zh|en)$'),page: int=Query(1,ge=1)):
    from ..international_reports import report
    from ..international_sources import PROVIDERS
    try:row=report(storage,report_id)
    except ValueError as exc:raise HTTPException(404,str(exc)) from None
    return _render(request,'public_report.html',report=row,provider=PROVIDERS[row['provider']],lang=lang,page=min(page,row['asset'].get('pages',1)))


@app.post('/api/v1/international/reports/{report_id}/download')
def download_public_report(report_id: str):
    from ..international_reports import download
    try:return download(storage,report_id)
    except ValueError as exc:raise HTTPException(400,str(exc)) from None


@app.get('/international/reports/{report_id}/original.pdf')
def public_report_pdf(report_id: str,download: bool=False):
    from ..international_reports import asset_path
    try:path=asset_path(storage,report_id)
    except ValueError as exc:raise HTTPException(404,str(exc)) from None
    return FileResponse(path,media_type='application/pdf',filename=report_id+'.pdf',content_disposition_type='attachment' if download else 'inline',headers={'X-Content-Type-Options':'nosniff','Cache-Control':'private, max-age=86400'})


@app.get('/documents/{document_id}/translation',response_class=HTMLResponse)
def supplied_report_translation(document_id: str,request: Request,revision: int=Query(...,ge=1)):
    from ..report_translation import state
    try:result=state(storage,document_id,revision)
    except ValueError as exc:raise HTTPException(400,str(exc)) from None
    from ..storage import read_json
    uploaded=read_json(storage.path(f'catalog/international-upload-files/{document_id}.json'))
    return _render(request,'report_translation.html',translation=result,document_id=document_id,revision=revision,uploaded=uploaded)


@app.post('/api/v1/documents/{document_id}/translation')
def translate_supplied_report(document_id: str,revision: int=Query(...,ge=1)):
    from ..report_translation import enqueue
    if not research:raise HTTPException(503,'模型服务尚未就绪')
    try:return enqueue(storage,document_id,revision,research)
    except ValueError as exc:raise HTTPException(400,str(exc)) from None


@app.post('/api/v1/international/{provider_id}/upload-pdf')
async def upload_institution_pdf(provider_id: str,request: Request,title: str,url: str=''):
    from ..international_uploads import upload
    from urllib.parse import unquote
    from starlette.concurrency import run_in_threadpool
    if not storage.ready:raise HTTPException(503,'知识库尚未就绪')
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>25*1024*1024:raise HTTPException(400,'PDF不能超过25MB')
    try:return await run_in_threadpool(upload,pipeline,provider_id,bytes(data),title,url,unquote(request.headers.get('X-File-Name','report.pdf')))
    except ValueError as exc:raise HTTPException(400,str(exc)) from None


@app.get('/documents/{document_id}/international-upload.pdf')
def uploaded_institution_pdf(document_id: str):
    from ..international_uploads import uploaded_file
    try:path,meta=uploaded_file(storage,document_id)
    except ValueError as exc:raise HTTPException(404,str(exc)) from None
    return FileResponse(path,media_type='application/pdf',filename=meta['filename'],headers={'X-Content-Type-Options':'nosniff','Cache-Control':'private, max-age=86400'})


@app.get('/international/reports/{report_id}/pages/{page}.png')
def public_report_page_image(report_id: str,page: int):
    from ..international_reports import preview
    try:path=preview(storage,report_id,page)
    except ValueError as exc:raise HTTPException(400,str(exc)) from None
    return FileResponse(path,media_type='image/png',headers={'Cache-Control':'private, max-age=86400','X-Content-Type-Options':'nosniff'})
