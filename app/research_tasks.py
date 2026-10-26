"""Small authenticated research queue, separate from attachment and ingestion jobs."""
import json,re,secrets
from datetime import datetime,timedelta
from fastapi import HTTPException,Request,Query
from pydantic import BaseModel,ConfigDict,Field
from .utils import now_iso,TZ

class ResearchRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    request_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    question:str=Field(min_length=2,max_length=600)
    target:str=Field(default='',max_length=100)
    kind:str=Field(default='auto',pattern='^(auto|company|industry)$')
    days:int=Field(default=0,ge=0,le=365)
    parent_id:str=Field(default='',pattern=r'^(?:[a-f0-9]{32})?$')

async def bounded_json(request,limit=262144):
    parts=[];size=0
    async for chunk in request.stream():
        size+=len(chunk)
        if size>limit:raise HTTPException(413,'请求过大')
        parts.append(chunk)
    try:return json.loads(b''.join(parts))
    except (ValueError,TypeError):raise HTTPException(422,'请求格式无效') from None

def install(app,db,authorize):
    def schema(conn):
        conn.execute('''CREATE TABLE IF NOT EXISTS research_tasks(id TEXT PRIMARY KEY,request TEXT NOT NULL,status TEXT NOT NULL,
          created_at TEXT NOT NULL,updated_at TEXT NOT NULL,lease TEXT,lease_until TEXT,result TEXT,message TEXT NOT NULL DEFAULT '')''')
    def config(conn):
        row=conn.execute("SELECT value FROM meta WHERE key='research_config'").fetchone()
        return json.loads(row[0]) if row else {'enabled':False,'daily_limit':10,'worker_at':''}
    def item(row,full=False):
        r=json.loads(row['request']);out={k:row[k] for k in ('id','status','created_at','updated_at','message')}
        out.update(question=r['question'],target=r['target'],kind=r['kind'],days=r['days'],parent_id=r['parent_id'])
        if full:out['report']=json.loads(row['result']) if row['result'] else None
        return out
    @app.get('/v1/research/tasks')
    def listing(request:Request,limit:int=Query(30,ge=1,le=50)):
        authorize(request)
        with db() as conn:
            schema(conn);cfg=config(conn);rows=conn.execute('SELECT * FROM research_tasks ORDER BY created_at DESC,id DESC LIMIT ?',(limit,)).fetchall()
        return {'config':cfg,'tasks':[item(r) for r in rows]}
    @app.post('/v1/research/config')
    async def settings(request:Request):
        authorize(request,True);data=await bounded_json(request,2048)
        if not isinstance(data,dict) or set(data)!={'enabled','daily_limit'} or type(data['enabled'])is not bool or type(data['daily_limit'])is not int or not 1<=data['daily_limit']<=30:raise HTTPException(422,'设置无效')
        with db() as conn:conn.execute("INSERT OR REPLACE INTO meta VALUES('research_config',?)",(json.dumps({**data,'worker_at':now_iso()}),))
        return {'accepted':True}
    @app.post('/v1/research/tasks')
    async def create(request:Request):
        authorize(request)
        try:r=ResearchRequest.model_validate(await bounded_json(request,8192)).model_dump()
        except HTTPException:raise
        except Exception:raise HTTPException(422,'调研请求无效') from None
        r['question']=r['question'].strip();r['target']=r['target'].strip()
        if len(r['question'])<2:raise HTTPException(422,'请输入调研问题')
        with db() as conn:
            schema(conn);conn.execute('BEGIN IMMEDIATE');old=conn.execute('SELECT * FROM research_tasks WHERE id=?',(r['request_id'],)).fetchone()
            if old:
                prior=json.loads(old['request'])
                if any(prior[k]!=r[k] for k in ('question','parent_id')) or any(r[k] not in ('',0,'auto') and prior[k]!=r[k] for k in ('target','kind','days')):raise HTTPException(409,'请求编号已用于其他问题')
                return item(old)
            cfg=config(conn)
            if not cfg['enabled']:raise HTTPException(403,'AI调研尚未启用，请在Mac启用研究执行器')
            if r['parent_id']:
                parent=conn.execute('SELECT * FROM research_tasks WHERE id=?',(r['parent_id'],)).fetchone()
                if not parent or parent['status']!='completed':raise HTTPException(422,'追问来源报告不可用')
                prior=json.loads(parent['request'])
                if not r['target']:r['target']=prior['target'] or (json.loads(parent['result']) or {}).get('target','')
                if r['kind']=='auto':r['kind']=(json.loads(parent['result']) or {}).get('kind',prior['kind'])
                if not r['days']:r['days']=(json.loads(parent['result']) or {}).get('days',30)
            today=now_iso()[:10]
            if conn.execute('SELECT count(*) FROM research_tasks WHERE created_at LIKE ?',(today+'%',)).fetchone()[0]>=cfg['daily_limit']:raise HTTPException(429,'已达到今日调研任务上限，所有阅读设备共享此额度')
            if conn.execute("SELECT count(*) FROM research_tasks WHERE status IN ('queued','running')").fetchone()[0]>=3:raise HTTPException(429,'已有调研任务等待，请完成后再提交')
            stamp=now_iso();conn.execute('INSERT INTO research_tasks(id,request,status,created_at,updated_at) VALUES(?,?,?,?,?)',(r['request_id'],json.dumps(r,ensure_ascii=False),'queued',stamp,stamp));row=conn.execute('SELECT * FROM research_tasks WHERE id=?',(r['request_id'],)).fetchone()
            return item(row)
    @app.get('/v1/research/tasks/{task_id}')
    def detail(task_id:str,request:Request):
        authorize(request)
        with db() as conn:
            schema(conn);row=conn.execute('SELECT * FROM research_tasks WHERE id=?',(task_id,)).fetchone()
        if not row:raise HTTPException(404,'报告不存在')
        return item(row,True)
    @app.post('/v1/research/claim')
    def claim(request:Request):
        authorize(request,True)
        with db() as conn:
            schema(conn);conn.execute('BEGIN IMMEDIATE')
            if not config(conn)['enabled']:return {'task':None}
            now=now_iso();row=conn.execute("SELECT * FROM research_tasks WHERE status='queued' OR (status='running' AND lease_until<?) ORDER BY created_at,id LIMIT 1",(now,)).fetchone()
            if not row:return {'task':None}
            lease=secrets.token_hex(24);until=(datetime.now(TZ)+timedelta(minutes=10)).isoformat(timespec='seconds')
            conn.execute("UPDATE research_tasks SET status='running',lease=?,lease_until=?,updated_at=? WHERE id=?",(lease,until,now,row['id']))
            return {'task':{'id':row['id'],'lease':lease,'request':json.loads(row['request'])}}
    @app.post('/v1/research/tasks/{task_id}/complete')
    async def complete(task_id:str,request:Request):
        authorize(request,True);d=await bounded_json(request)
        if not isinstance(d,dict) or set(d)!={'lease','status','message','report'} or d['status'] not in ('completed','no_evidence','needs_input','failed') or not isinstance(d['message'],str) or len(d['message'])>300 or not isinstance(d['lease'],str) or d['report'] is not None and not isinstance(d['report'],dict):raise HTTPException(422,'任务结果无效')
        if d['status']=='completed' and not d['report']:raise HTTPException(422,'缺少报告')
        with db() as conn:
            schema(conn);conn.execute('BEGIN IMMEDIATE');row=conn.execute('SELECT * FROM research_tasks WHERE id=?',(task_id,)).fetchone()
            if not row or row['status']!='running' or not secrets.compare_digest(row['lease'] or '',d['lease']) or row['lease_until']<now_iso():raise HTTPException(409,'任务租约已失效')
            conn.execute('UPDATE research_tasks SET status=?,message=?,result=?,updated_at=? WHERE id=?',(d['status'],d['message'],json.dumps(d['report'],ensure_ascii=False) if d['report'] is not None else None,now_iso(),task_id))
        return {'accepted':True}
