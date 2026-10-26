"""Immutable metadata journal for consistent sync, plus literal archived-text search."""
import json,re,uuid
from datetime import datetime,timedelta
from fastapi import Request,Query,HTTPException
from .utils import TZ

def metadata(document):return {k:v for k,v in document.items() if k!='body'}

def initialize(conn):
    columns={r[1] for r in conn.execute('PRAGMA table_info(changes)')}
    ready=conn.execute("SELECT value FROM meta WHERE key='catalog_v2_floor'").fetchone()
    epoch=conn.execute("SELECT value FROM meta WHERE key='catalog_epoch'").fetchone()
    if 'payload' in columns and ready and epoch and not conn.execute('SELECT 1 FROM changes WHERE payload IS NULL AND sequence>? LIMIT 1',(int(ready[0]),)).fetchone():return
    conn.execute('BEGIN IMMEDIATE')
    try:
        if 'payload' not in {r[1] for r in conn.execute('PRAGMA table_info(changes)')}:conn.execute('ALTER TABLE changes ADD COLUMN payload TEXT')
        conn.execute("INSERT OR IGNORE INTO meta VALUES('catalog_epoch',?)",(uuid.uuid4().hex,))
        conn.execute('CREATE INDEX IF NOT EXISTS changes_unjournaled ON changes(sequence) WHERE payload IS NULL')
        ready=conn.execute("SELECT value FROM meta WHERE key='catalog_v2_floor'").fetchone()
        if not ready or conn.execute('SELECT 1 FROM changes WHERE payload IS NULL AND sequence>? LIMIT 1',(int(ready[0]),)).fetchone():
            # Only current legacy versions are recoverable. Earlier cursors must bootstrap.
            floor=conn.execute('SELECT COALESCE(MAX(sequence),0) FROM changes').fetchone()[0]
            if ready:conn.execute("INSERT OR REPLACE INTO meta VALUES('catalog_epoch',?)",(uuid.uuid4().hex,))
            for row in conn.execute('SELECT payload,sequence FROM documents').fetchall():conn.execute('UPDATE changes SET payload=? WHERE sequence=?',(json.dumps(metadata(json.loads(row['payload'])),ensure_ascii=False),row['sequence']))
            conn.execute("INSERT OR REPLACE INTO meta VALUES('catalog_v2_floor',?)",(str(floor),))
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS document_fts USING fts5(document_id UNINDEXED,title,body,keywords,tokenize='trigram')")
            conn.execute('DELETE FROM document_fts')
            for row in conn.execute('SELECT payload FROM documents').fetchall():update_search(conn,json.loads(row['payload']))
        conn.commit()
    except Exception:conn.rollback();raise

def update_search(conn,document):
    conn.execute('DELETE FROM document_fts WHERE document_id=?',(document['document_id'],))
    keywords=json.dumps([document.get('companies',[]),document.get('company_securities',[]),document.get('industries',[]),[a.get('name','') for a in document.get('attachments',[])]],ensure_ascii=False)
    conn.execute('INSERT INTO document_fts VALUES(?,?,?,?)',(document['document_id'],document['title'],document['body'],keywords))

def install(app,db,authorize):
    @app.middleware('http')
    async def private_catalog(request,call_next):
        response=await call_next(request)
        if request.url.path in ('/v1/catalog','/v1/search'):
            response.headers['Cache-Control']='private, no-store'
            response.headers['X-Content-Type-Options']='nosniff'
        return response

    @app.get('/v1/catalog')
    def catalog(request:Request,mode:str=Query('snapshot',pattern='^(snapshot|delta)$'),after:int=Query(0,ge=0),after_id:str=Query('',max_length=40),until:int|None=Query(None,ge=0),limit:int=Query(100,ge=1,le=100)):
        authorize(request)
        if after_id and not re.fullmatch(r'doc_[0-9A-Z]{26}',after_id):raise HTTPException(422,'分页位置无效')
        with db() as conn:
            high=conn.execute('SELECT COALESCE(MAX(sequence),0) FROM changes').fetchone()[0]
            floor=int(conn.execute("SELECT value FROM meta WHERE key='catalog_v2_floor'").fetchone()[0]);watermark=high if until is None else until
            if watermark<floor or watermark>high or mode=='delta' and (after<floor or after>watermark):raise HTTPException(409,'同步游标已失效，请重新完整同步')
            if mode=='snapshot':
                rows=conn.execute('''SELECT c.* FROM changes c JOIN
                  (SELECT document_id,MAX(sequence) AS latest FROM changes WHERE sequence<=? GROUP BY document_id) s ON c.sequence=s.latest
                  WHERE c.payload IS NOT NULL AND c.payload!='null' AND c.document_id>? ORDER BY c.document_id LIMIT ?''',(watermark,after_id,limit+1)).fetchall()
            else:rows=conn.execute('SELECT * FROM changes WHERE sequence>? AND sequence<=? ORDER BY sequence LIMIT ?',(after,watermark,limit+1)).fetchall()
            events=[];size=0
            for row in rows[:limit]:
                d=json.loads(row['payload']) if row['payload'] else None
                if d:d['sequence']=row['sequence']
                event=dict(sequence=row['sequence'],document_id=row['document_id'],deleted=d is None,document=d)
                length=len(json.dumps(event,ensure_ascii=False).encode())
                if events and size+length>3_000_000:break
                if length>7_000_000:raise HTTPException(413,'单条目录记录过大，请在Mac检查资料元数据')
                events.append(event);size+=length
            more=len(rows)>len(events)
            epoch=conn.execute("SELECT value FROM meta WHERE key='catalog_epoch'").fetchone()[0]
            return dict(mode=mode,cursor=watermark,epoch=epoch,events=events,has_more=more,next_after=events[-1]['sequence'] if events else after,next_id=events[-1]['document_id'] if events else after_id)

    @app.get('/v1/search')
    def search(request:Request,q:str=Query(min_length=2,max_length=120),company:str=Query('',max_length=200),industry:str=Query('',max_length=200),source:str=Query('',max_length=200),days:int=Query(0,ge=0,le=365),limit:int=Query(40,ge=1,le=50)):
        authorize(request);q=q.strip()
        if len(q)<2:raise HTTPException(422,'请输入至少两个字符')
        if any(ord(char)<32 for char in q):raise HTTPException(422,'搜索词不能包含控制字符')
        where=[];params=[];fts=len(q)>=3
        if fts:where.append('document_fts MATCH ?');params.append('"'+q.replace('"','""')+'"')
        else:
            literal='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            where.append("(f.title LIKE ? ESCAPE '\\' OR f.body LIKE ? ESCAPE '\\' OR f.keywords LIKE ? ESCAPE '\\')");params.extend([literal]*3)
        if source:where.append("json_extract(d.payload,'$.source_name')=?");params.append(source)
        if industry:where.append("EXISTS(SELECT 1 FROM json_each(d.payload,'$.industries') WHERE value=?)");params.append(industry)
        if company:
            where.append("(EXISTS(SELECT 1 FROM json_each(d.payload,'$.companies') WHERE value=?) OR EXISTS(SELECT 1 FROM json_each(d.payload,'$.company_securities') WHERE json_extract(value,'$.canonical_name')=?))");params.extend([company,company])
        if days:
            now=datetime.now(TZ);start=(now-timedelta(days=days-1)).replace(hour=0,minute=0,second=0,microsecond=0)
            where.append("julianday(json_extract(d.payload,'$.published_at'))>=julianday(?) AND julianday(json_extract(d.payload,'$.published_at'))<=julianday(?)");params.extend([start.isoformat(timespec='seconds'),now.isoformat(timespec='seconds')])
        alias='document_fts' if fts else 'document_fts f'
        body_col='document_fts.document_id' if fts else 'f.document_id'
        order='bm25(document_fts,0,4,1,2),' if fts else ''
        with db() as conn:
            rows=conn.execute('SELECT d.payload FROM '+alias+' JOIN documents d ON d.id='+body_col+' WHERE '+' AND '.join(where)+' ORDER BY '+order+"json_extract(d.payload,'$.published_at') DESC,d.id LIMIT ?",(*params,limit+1)).fetchall()
            cursor=conn.execute('SELECT COALESCE(MAX(sequence),0) FROM changes').fetchone()[0]
        results=[]
        for row in rows[:limit]:
            d=json.loads(row['payload']);body=d['body'];match=re.search(re.escape(q),body,re.I);field='body'
            if not match:body=d['title'];match=re.search(re.escape(q),body,re.I);field='title'
            if not match:body=d.get('summary') or '命中公司、代码、行业或附件名称';field='metadata'
            offset=max(0,match.start()-65) if match else 0;snippet=body[offset:offset+210]
            compact={k:d.get(k) for k in ('document_id','revision','title','published_at','source_name','content_kind')}
            results.append(dict(document=compact,snippet=snippet,match_field=field,offset=offset,match_start=match.start()-offset if match else -1,match_end=match.end()-offset if match else -1))
        return dict(query=q,scope='cloud_archived_text',offset_encoding='unicode_codepoints',cursor=cursor,results=results,has_more=len(rows)>limit,limit=limit,model_requests=0)
