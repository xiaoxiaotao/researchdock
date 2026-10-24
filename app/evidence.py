"""User-curated verbatim evidence, pinned to immutable source revisions."""
import re
import sqlite3
from contextlib import contextmanager
from .frontmatter import split_frontmatter
from .utils import now_iso,ulid

TOPICS=('订单','产能','价格','财务','现金流','盈利预测','行业','风险','其他')

def locate(body,quote):
    chars=[];positions=[];space=False
    for i,char in enumerate(body):
        if char.isspace():
            if chars and not space:chars.append(' ');positions.append(i)
            space=True
        else:chars.append(char);positions.append(i);space=False
    needle=' '.join(quote.split());normalized=''.join(chars);start=normalized.find(needle)
    if not needle or start<0:raise ValueError('摘录必须来自该版本的连续原文，可选取较短片段后重试')
    if normalized.find(needle,start+1)>=0:raise ValueError('该原句出现多次，请多选一些上下文以准确定位')
    exact=body.find(quote)
    if exact>=0:return exact,exact+len(quote)
    return positions[start],positions[start+len(needle)-1]+1

class Evidence:
    def __init__(self,storage):
        self.storage=storage;self.path=storage.path('catalog/evidence.sqlite3');self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:c.executescript('''CREATE TABLE IF NOT EXISTS clips (
          id TEXT PRIMARY KEY,document_id TEXT NOT NULL,revision INTEGER NOT NULL,
          start_offset INTEGER NOT NULL,end_offset INTEGER NOT NULL,quote TEXT NOT NULL,
          topic TEXT NOT NULL,company_id TEXT NOT NULL,company_name TEXT NOT NULL,
          note TEXT NOT NULL,title TEXT NOT NULL,published_at TEXT,created_at TEXT NOT NULL,
          hidden INTEGER NOT NULL DEFAULT 0,
          UNIQUE(document_id,revision,start_offset,end_offset,topic,company_id));
          CREATE INDEX IF NOT EXISTS clips_company ON clips(company_id,created_at);
          CREATE INDEX IF NOT EXISTS clips_document ON clips(document_id,revision);''')
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=20);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()
    def create(self,document_id,revision,data,companies):
        if not re.fullmatch(r'doc_[0-9A-Z]{26}',document_id) or type(revision) is not int or revision<1:raise ValueError('文档或版本无效')
        if not isinstance(data,dict):raise ValueError('摘录参数无效')
        quote=data.get('quote','');note=data.get('note','');topic=data.get('topic','其他');company=data.get('company_id','')
        if not isinstance(quote,str) or not 2<=len(quote.strip())<=2000:raise ValueError('摘录需为2至2000字')
        if not isinstance(note,str) or len(note)>3000:raise ValueError('个人说明不能超过3000字')
        if not isinstance(topic,str) or topic not in TOPICS:raise ValueError('研究主题无效')
        if not isinstance(company,str) or company and company not in companies:raise ValueError('公司关联无效')
        manifest=self.storage.read_manifest(document_id) or {}
        source=next((r for r in manifest.get('revisions',[]) if r['revision']==revision),None)
        if not source:raise ValueError('原文版本不存在')
        meta,body=split_frontmatter(self.storage.read_revision_text(source['archive_path']))
        start,end=locate(body,quote.strip())
        row={'id':'clip_'+ulid(),'document_id':document_id,'revision':revision,'start_offset':start,'end_offset':end,'quote':body[start:end],'topic':topic,'company_id':company,'company_name':companies.get(company,''),'note':note.strip(),'title':str(meta.get('title') or manifest.get('title') or '未命名资料'),'published_at':str(meta.get('published_at') or ''),'created_at':now_iso(),'hidden':0}
        with self.connect() as c:
            old=c.execute('SELECT * FROM clips WHERE document_id=? AND revision=? AND start_offset=? AND end_offset=? AND topic=? AND company_id=?',(document_id,revision,start,end,topic,company)).fetchone()
            if old:
                if old['note']!=row['note']:raise ValueError('该位置已有同主题摘录，未覆盖此前说明；请先查看证据库')
                return dict(old),False
            c.execute('INSERT INTO clips VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',tuple(row.values()))
        return row,True
    def get(self,key):
        with self.connect() as c:
            row=c.execute('SELECT * FROM clips WHERE id=?',(key,)).fetchone()
            return dict(row) if row else None
    def _filters(self,q='',topic='',company_ids=None,document_id='',hidden=False):
        clauses=['hidden=?'];args=[int(hidden)]
        if q:
            term='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            clauses.append("(quote LIKE ? ESCAPE '\\' OR note LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\' OR company_name LIKE ? ESCAPE '\\')");args.extend([term]*4)
        if topic:clauses.append('topic=?');args.append(topic)
        if document_id:clauses.append('document_id=?');args.append(document_id)
        if company_ids is not None:
            if not company_ids:return ['0'],[]
            clauses.append('company_id IN ('+','.join('?' for _ in company_ids)+')');args.extend(company_ids)
        return clauses,args
    def list(self,q='',topic='',company_ids=None,document_id='',hidden=False,limit=100,offset=0):
        clauses,args=self._filters(q,topic,company_ids,document_id,hidden)
        with self.connect() as c:return [dict(r) for r in c.execute('SELECT * FROM clips WHERE '+' AND '.join(clauses)+' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',[*args,limit,offset])]
    def count(self,q='',topic='',company_ids=None,document_id='',hidden=False):
        clauses,args=self._filters(q,topic,company_ids,document_id,hidden)
        with self.connect() as c:return c.execute('SELECT COUNT(*) FROM clips WHERE '+' AND '.join(clauses),args).fetchone()[0]
    def hide(self,key,value):
        if type(value) is not bool:raise ValueError('隐藏状态无效')
        with self.connect() as c:
            cursor=c.execute('UPDATE clips SET hidden=? WHERE id=?',(int(value),key))
            if not cursor.rowcount:raise ValueError('摘录不存在')
