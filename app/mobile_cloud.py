"""Separate private mobile mirror; never expose the local desktop admin application."""
from __future__ import annotations
import hashlib,json,os,secrets,sqlite3,re,tempfile
from contextlib import contextmanager
from pathlib import Path
from fastapi import FastAPI,HTTPException,Request,Query
from pydantic import BaseModel,Field,ConfigDict,model_validator
from .utils import now_iso
from .mobile_attachments import media_type,MAX_BYTES

class Asset(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    id:str=Field(pattern=r'^[a-f0-9]{64}$')
    name:str=Field(max_length=300)
    type:str=Field(pattern=r'^(image|pdf|audio|file)$')

class Attachment(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    id:str=Field(pattern=r'^[a-f0-9]{64}$')
    name:str=Field(min_length=1,max_length=300)
    type:str=Field(pattern=r'^(image|pdf|audio|file)$')
    size:int=Field(ge=0)
    status:str=Field(pattern=r'^(missing|ready|failed|unavailable)$')
    asset_id:str=Field(default='',pattern=r'^$|^[a-f0-9]{64}$')
    message:str=Field(default='',max_length=200)

class JobResult(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    status:str=Field(pattern=r'^(ready|failed)$')

class SourceState(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    name:str=Field(min_length=1,max_length=200)
    status:str=Field(pattern=r'^(queued|running|failed|interrupted|succeeded|partial|idle|unknown)$')
    last_success_at:str=Field(default='',max_length=80)
    last_attempt_at:str=Field(default='',max_length=80)
    unavailable_count:int=Field(default=0,ge=0)

class SourceHealth(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    reported_at:str=Field(max_length=80)
    poll_enabled:bool
    poll_minutes:int=Field(ge=5,le=60)
    sources:list[SourceState]=Field(default_factory=list,max_length=100)

class CompanySecurity(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    name:str=Field(min_length=1,max_length=200)
    canonical_name:str=Field(min_length=1,max_length=200)
    security_id:str=Field(pattern=r'^(sh|sz|bj)[0-9]{6}$|^hk[0-9]{5}$|^us[A-Z]{1,5}(?:[.][A-Z])?$')
    code:str=Field(pattern=r'^(?:[0-9]{5,6}|[A-Z]{1,5}(?:[.][A-Z])?)$')
    exchange:str=Field(pattern=r'^(sh|sz|bj|hk|us)$')
    @model_validator(mode='after')
    def consistent(self):
        if self.security_id!=self.exchange+self.code or (self.exchange!='us' and (not self.code.isdigit() or len(self.code)!=(5 if self.exchange=='hk' else 6))) or (self.exchange=='us' and not re.fullmatch(r'[A-Z]{1,5}(?:[.][A-Z])?',self.code)):raise ValueError('证券标识不一致')
        return self

class Document(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    document_id:str=Field(pattern=r'^doc_[0-9A-Z]{26}$')
    revision:int=Field(ge=1)
    title:str=Field(min_length=1,max_length=500)
    body:str=Field(max_length=300000)
    summary:str=Field(default='',max_length=10000)
    key_points:list[str]=Field(default_factory=list,max_length=50)
    risks:list[str]=Field(default_factory=list,max_length=50)
    analysis_revision:int=Field(default=0,ge=0)
    first_imported_at:str=Field(default='',max_length=80)
    body_chars:int=Field(default=0,ge=0,le=300000)
    content_kind:str=Field(default='note',pattern=r'^(note|brief|attachment_only)$')
    display_title:str=Field(default='',max_length=500)
    published_at:str=Field(default='',max_length=80)
    source_name:str=Field(default='',max_length=200)
    source_url:str=Field(default='',max_length=2000)
    industries:list[str]=Field(default_factory=list,max_length=30)
    companies:list[str]=Field(default_factory=list,max_length=80)
    company_securities:list[CompanySecurity]=Field(default_factory=list,max_length=80)
    assets:list[Asset]=Field(default_factory=list,max_length=200)
    attachments:list[Attachment]=Field(default_factory=list,max_length=200)


def create_app(data_dir=None,push_token=None,read_token=None):
    app=FastAPI(title='ResearchDock Private Reader',docs_url=None,redoc_url=None,openapi_url=None)
    root=Path(data_dir or os.environ.get('RESEARCHDOCK_CLOUD_DATA','./reader-data'))
    @contextmanager
    def db():
        root.mkdir(parents=True,exist_ok=True)
        conn=sqlite3.connect(root/'reader.sqlite3',timeout=20);conn.row_factory=sqlite3.Row
        try:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.executescript('''CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,revision INTEGER,payload TEXT,digest TEXT,sequence INTEGER);
              CREATE TABLE IF NOT EXISTS revisions(id TEXT,revision INTEGER,body_hash TEXT,PRIMARY KEY(id,revision));
              CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
              CREATE TABLE IF NOT EXISTS attachment_jobs(job_id TEXT PRIMARY KEY,document_id TEXT,revision INTEGER,attachment_id TEXT,status TEXT);
              CREATE TABLE IF NOT EXISTS changes(sequence INTEGER PRIMARY KEY AUTOINCREMENT,document_id TEXT);
            ''')
            with conn:yield conn
        finally:conn.close()
    def authorize(request,write=False):
        p=push_token if push_token is not None else os.environ.get('RESEARCHDOCK_PUSH_TOKEN','')
        r=read_token if read_token is not None else os.environ.get('RESEARCHDOCK_READ_TOKEN','')
        if len(p)<32 or len(r)<32 or secrets.compare_digest(p,r):raise HTTPException(503,'阅读服务未完成私有凭据配置')
        header=request.headers.get('authorization','');value=header[7:] if header.startswith('Bearer ') else ''
        if not secrets.compare_digest(value,p if write else r):raise HTTPException(401,'未授权',headers={'WWW-Authenticate':'Bearer'})
    @app.get('/health')
    def health():return {'service':'ok','schema_version':1}
    @app.post('/v1/sync')
    async def sync(request:Request):
        authorize(request,True);parts=[];size=0
        async for chunk in request.stream():
            size+=len(chunk)
            if size>8_000_000:raise HTTPException(413,'批次过大')
            parts.append(chunk)
        try:
            batch=json.loads(b''.join(parts));library=batch['library_id'];rows=batch['documents']
            deleted=batch.get('deleted_ids',[])
            if not isinstance(deleted,list) or len(deleted)>100 or any(not isinstance(x,str) or not re.fullmatch(r'doc_[0-9A-Z]{26}',x) for x in deleted):raise ValueError()
            if set(batch)-{'library_id','documents','deleted_ids'} or not isinstance(library,str) or not 1<=len(library)<=100 or not isinstance(rows,list) or len(rows)>20:raise ValueError()
            validated=[Document.model_validate(d).model_dump() for d in rows]
            if any(any(len(s)>4000 for s in d['key_points']+d['risks']) or (d['key_points'] or d['risks']) and d['analysis_revision']!=d['revision'] for d in validated):raise ValueError()
            if len({d['document_id'] for d in validated})!=len(validated):raise ValueError()
            if any(any(len(s)>200 for s in d['industries']+d['companies']) for d in validated):raise ValueError()
            if any(any(a['status']=='ready' and not any(x['id']==a['asset_id'] and x['type']==a['type'] for x in d['assets']) for a in d['attachments']) for d in validated):raise ValueError()
            if any(any(s['name'] not in d['companies'] for s in d['company_securities']) for d in validated):raise ValueError()
        except Exception:raise HTTPException(422,'同步格式无效；只接受明确的阅读字段')
        changed=0
        with db() as conn:
            bound=conn.execute("SELECT value FROM meta WHERE key='library'").fetchone()
            if bound and bound[0]!=library:raise HTTPException(409,'此服务已绑定另一资料库')
            conn.execute("INSERT OR IGNORE INTO meta VALUES('library',?)",(library,))
            for d in validated:
                content=json.dumps(d,sort_keys=True,ensure_ascii=False);digest=hashlib.sha256(content.encode()).hexdigest();body_hash=hashlib.sha256(d['body'].encode()).hexdigest()
                old=conn.execute('SELECT * FROM documents WHERE id=?',(d['document_id'],)).fetchone()
                pinned=conn.execute('SELECT body_hash FROM revisions WHERE id=? AND revision=?',(d['document_id'],d['revision'])).fetchone()
                if pinned and pinned[0]!=body_hash:raise HTTPException(409,'同一修订不能改写原文')
                if old and old['revision']>d['revision']:raise HTTPException(409,'拒绝旧版本覆盖新版本')
                if old and old['digest']==digest:continue
                seq=conn.execute('INSERT INTO changes(document_id) VALUES(?)',(d['document_id'],)).lastrowid
                conn.execute('DELETE FROM attachment_jobs WHERE document_id=? AND revision<>?',(d['document_id'],d['revision']))
                conn.execute('INSERT OR IGNORE INTO revisions VALUES(?,?,?)',(d['document_id'],d['revision'],body_hash))
                conn.execute('INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?)',(d['document_id'],d['revision'],content,digest,seq));changed+=1
            for document_id in deleted:
                conn.execute('DELETE FROM documents WHERE id=?',(document_id,))
                conn.execute('DELETE FROM attachment_jobs WHERE document_id=?',(document_id,))
                conn.execute('INSERT INTO changes(document_id) VALUES(?)',(document_id,))
            conn.execute("INSERT OR REPLACE INTO meta VALUES('last_sync',?)",(now_iso(),))
        return {'changed':changed,'accepted':len(validated),'deleted':len(deleted)}
    @app.post('/v1/assets/{asset_id}')
    async def put_asset(asset_id:str,request:Request):
        authorize(request,True)
        if not re.fullmatch('[a-f0-9]{64}',asset_id):raise HTTPException(400,'资源编号无效')
        folder=root/'assets';folder.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(dir=folder);digest=hashlib.sha256();size=0;head=b''
        try:
            with os.fdopen(fd,'wb') as fh:
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>MAX_BYTES:raise HTTPException(413,'资源过大')
                    if len(head)<16:head=(head+chunk)[:16]
                    digest.update(chunk);fh.write(chunk)
            if digest.hexdigest()!=asset_id:raise HTTPException(422,'资源校验失败')
            if not media_type(head):raise HTTPException(415,'资源类型不支持')
            os.replace(tmp,folder/asset_id)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
        return {'id':asset_id}
    @app.get('/v1/assets/{asset_id}')
    def get_asset(asset_id:str,request:Request):
        authorize(request)
        if not re.fullmatch('[a-f0-9]{64}',asset_id):raise HTTPException(404,'资源不存在')
        with db() as conn:
            linked=conn.execute("SELECT 1 FROM documents d,json_each(d.payload,'$.assets') a WHERE json_extract(a.value,'$.id')=? LIMIT 1",(asset_id,)).fetchone()
        if not linked:raise HTTPException(404,'资源未关联可阅读资料')
        file=root/'assets'/asset_id
        if not file.is_file():raise HTTPException(404,'资源不存在')
        with file.open('rb') as fh:head=fh.read(16)
        mime=media_type(head) or 'application/octet-stream'
        from fastapi.responses import FileResponse
        return FileResponse(file,media_type=mime,headers={'Cache-Control':'private, max-age=86400','X-Content-Type-Options':'nosniff'})

    @app.post('/v1/documents/{document_id}/attachments/{attachment_id}/prepare')
    def request_attachment(document_id:str,attachment_id:str,request:Request):
        authorize(request)
        if not re.fullmatch('[a-f0-9]{64}',attachment_id):raise HTTPException(404,'附件不存在')
        with db() as conn:
            row=conn.execute('SELECT payload FROM documents WHERE id=?',(document_id,)).fetchone()
            if not row:raise HTTPException(404,'资料不存在')
            d=json.loads(row['payload']);a=next((a for a in d.get('attachments',[]) if a['id']==attachment_id),None)
            if not a:raise HTTPException(404,'此资料没有该附件')
            if a['status']=='ready':return {'status':'ready'}
            if a['status']=='unavailable':raise HTTPException(413,'请到原始来源获取原件')
            key=hashlib.sha256(f"{document_id}:{d['revision']}:{attachment_id}".encode()).hexdigest()
            old=conn.execute('SELECT status FROM attachment_jobs WHERE job_id=?',(key,)).fetchone()
            if old and old[0]=='queued':return {'status':'queued'}
            if conn.execute("SELECT count(*) FROM attachment_jobs WHERE status='queued'").fetchone()[0]>=100:raise HTTPException(429,'附件队列已满，请稍后重试')
            conn.execute("INSERT OR REPLACE INTO attachment_jobs VALUES(?,?,?,?,'queued')",(key,document_id,d['revision'],attachment_id))
        return {'status':'queued'}

    @app.get('/v1/documents/{document_id}/attachments/{attachment_id}/preparation')
    def attachment_preparation(document_id:str,attachment_id:str,request:Request):
        authorize(request)
        with db() as conn:
            row=conn.execute('SELECT payload FROM documents WHERE id=?',(document_id,)).fetchone()
            if not row:raise HTTPException(404,'资料不存在')
            d=json.loads(row['payload']);a=next((a for a in d.get('attachments',[]) if a['id']==attachment_id),None)
            if not a:raise HTTPException(404,'此资料没有该附件')
            if a['status']=='ready':return {'status':'ready'}
            key=hashlib.sha256(f"{document_id}:{d['revision']}:{attachment_id}".encode()).hexdigest()
            job=conn.execute('SELECT status FROM attachment_jobs WHERE job_id=?',(key,)).fetchone()
        return {'status':job[0] if job else a['status']}

    @app.get('/v1/attachment-jobs')
    def attachment_jobs(request:Request):
        authorize(request,True)
        with db() as conn:
            rows=conn.execute("SELECT j.* FROM attachment_jobs j JOIN documents d ON j.document_id=d.id AND j.revision=d.revision WHERE j.status='queued' ORDER BY j.rowid LIMIT 3").fetchall()
        return {'jobs':[dict(r) for r in rows]}

    @app.post('/v1/attachment-jobs/{job_id}')
    def complete_attachment_job(job_id:str,result:JobResult,request:Request):
        authorize(request,True)
        with db() as conn:
            conn.execute('UPDATE attachment_jobs SET status=? WHERE job_id=?',(result.status,job_id))
        return {'status':result.status}
    @app.post('/v1/source-health')
    def put_source_health(report:SourceHealth,request:Request):
        authorize(request,True)
        with db() as conn:
            conn.execute("INSERT OR REPLACE INTO meta VALUES('source_health',?)",(json.dumps(report.model_dump(),ensure_ascii=False),))
            conn.execute("INSERT OR REPLACE INTO meta VALUES('health_received_at',?)",(now_iso(),))
        return {'accepted':True}
    @app.get('/v1/status')
    def status(request:Request):
        authorize(request)
        with db() as conn:
            cursor=conn.execute('SELECT COALESCE(MAX(sequence),0) FROM changes').fetchone()[0]
            last=conn.execute("SELECT value FROM meta WHERE key='last_sync'").fetchone()
            health=conn.execute("SELECT value FROM meta WHERE key='source_health'").fetchone()
            received=conn.execute("SELECT value FROM meta WHERE key='health_received_at'").fetchone()
        return {'cursor':cursor,'last_sync':last[0] if last else None,'source_health':json.loads(health[0]) if health else None,'health_received_at':received[0] if received else None}
    @app.get('/v1/documents')
    def documents(request:Request,limit:int=Query(100,ge=1,le=100),offset:int=Query(0,ge=0),since:int=Query(0,ge=0)):
        authorize(request)
        with db() as conn:
            rows=conn.execute('SELECT payload,sequence FROM documents WHERE sequence>? ORDER BY json_extract(payload,\'$.published_at\') DESC,id LIMIT ? OFFSET ?',(since,limit+1,offset)).fetchall()
            cursor=conn.execute('SELECT COALESCE(MAX(sequence),0) FROM changes').fetchone()[0]
            last=conn.execute("SELECT value FROM meta WHERE key='last_sync'").fetchone()
        result=[]
        for row in rows[:limit]:
            d=json.loads(row['payload']);d.pop('body');d['sequence']=row['sequence'];result.append(d)
        return {'documents':result,'has_more':len(rows)>limit,'cursor':cursor,'last_sync':last[0] if last else None}
    @app.get('/v1/documents/{document_id}')
    def document(document_id:str,request:Request):
        authorize(request)
        with db() as conn:row=conn.execute('SELECT payload,digest,sequence FROM documents WHERE id=?',(document_id,)).fetchone()
        if not row:raise HTTPException(404,'资料不存在')
        from fastapi.responses import JSONResponse
        payload=json.loads(row['payload']);payload['sequence']=row['sequence']
        return JSONResponse(payload,headers={'ETag':'"'+row['digest']+'"','Cache-Control':'private, no-store'})
    return app

app=create_app()
