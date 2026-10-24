"""Persistent securities reference catalog; distinct from document-derived companies."""
import re
from contextlib import contextmanager
import sqlite3
import unicodedata
import httpx
from opencc import OpenCC
from .hk_securities import HK_SOURCE
_CONVERTER=OpenCC('t2s')
from .utils import now_iso

SOURCE='https://www.cninfo.com.cn/new/data/szse_stock.json'

def normalized(value):
    return re.sub(r'\s+','',_CONVERTER.convert(unicodedata.normalize('NFKC',str(value)))).casefold()

def code_hint(value):
    value=str(value or '').strip().upper()
    match=re.fullmatch(r'(?:HK)?(\d{1,5})(?:[.]HK)?',value)
    if match:return match[1].zfill(5),'hk'
    match=re.fullmatch(r'(\d{6})(?:[.](SZ|SH|BJ|CH))?',value)
    if match:return match[1],(match[2].lower() if match[2] and match[2]!='CH' else None)
    return None,None

def hk_aliases(name):
    stripped=re.sub(r'[-－](?:SW|SS|SP|W|S|B|P)$','',unicodedata.normalize('NFKC',name),flags=re.I)
    return {name,stripped}

def exchange_for(code):
    if re.fullmatch(r'(00|30)\d{4}',code):return 'sz'
    if re.fullmatch(r'6\d{5}',code):return 'sh'
    if re.fullmatch(r'(92\d{4}|[48]\d{5})',code):return 'bj'
    return None

class Securities:
    def __init__(self,storage):
        self.path=storage.path('catalog/securities.sqlite3')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS securities (
              security_id TEXT PRIMARY KEY, code TEXT NOT NULL, exchange TEXT NOT NULL,
              name TEXT NOT NULL, pinyin TEXT NOT NULL, org_id TEXT, source TEXT NOT NULL,
              fetched_at TEXT NOT NULL, in_directory INTEGER NOT NULL DEFAULT 1);
              CREATE INDEX IF NOT EXISTS security_code ON securities(code);
              CREATE TABLE IF NOT EXISTS security_names (
              security_id TEXT NOT NULL, name TEXT NOT NULL, normalized TEXT NOT NULL,
              first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
              PRIMARY KEY(security_id,name));
              CREATE INDEX IF NOT EXISTS security_alias ON security_names(normalized);
              CREATE TABLE IF NOT EXISTS security_syncs (id INTEGER PRIMARY KEY,updated_at TEXT NOT NULL,count INTEGER NOT NULL,source TEXT NOT NULL);''')
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=20);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()
    def get(self,key):
        with self.connect() as c:
            row=c.execute('SELECT * FROM securities WHERE security_id=?',(key,)).fetchone()
            return dict(row) if row else None
    def ingest(self,items):
        valid={}
        for row in items:
            code=str(row.get('code',''));name=str(row.get('zwjc','')).strip();exchange=exchange_for(code)
            if row.get('category')!='A股' or not exchange or not name:continue
            key=exchange+code
            if key in valid and valid[key]['name']!=name:raise ValueError('同一证券代码出现不同名称，未更新目录')
            valid[key]={'code':code,'exchange':exchange,'name':name,'pinyin':row.get('pinyin') or '', 'org_id':row.get('orgId') or ''}
        if not valid:raise ValueError('未取得有效A股证券目录')
        stamp=now_iso()
        with self.connect() as c:
            old=c.execute("SELECT count(*) FROM securities WHERE in_directory=1 AND exchange!='hk'").fetchone()[0]
            if old and len(valid)<old*.8:raise ValueError('证券目录数量异常下降，保留原库')
            c.execute("UPDATE securities SET in_directory=0 WHERE exchange!='hk'")
            for key,row in valid.items():
                c.execute('''INSERT INTO securities VALUES (?,?,?,?,?,?,?,?,1) ON CONFLICT(security_id) DO UPDATE SET
                    name=excluded.name,pinyin=excluded.pinyin,org_id=excluded.org_id,source=excluded.source,fetched_at=excluded.fetched_at,in_directory=1''',(key,row['code'],row['exchange'],row['name'],row['pinyin'],row['org_id'],SOURCE,stamp))
                c.execute('INSERT INTO security_names VALUES (?,?,?,?,?) ON CONFLICT(security_id,name) DO UPDATE SET last_seen=excluded.last_seen',(key,row['name'],normalized(row['name']),stamp,stamp))
            c.execute('INSERT INTO security_syncs(updated_at,count,source) VALUES (?,?,?)',(stamp,len(valid),SOURCE))
        return self.stats()
    def ingest_hk(self,items):
        valid={}
        for row in items:
            code=str(row.get('code',''));name=str(row.get('name','')).strip()
            if not re.fullmatch(r'\d{5}',code) or not name:raise ValueError('港股名称或代码无效')
            if code in valid and valid[code]['name']!=name:raise ValueError('港股代码存在冲突，未更新目录')
            valid[code]=row
        if not valid:raise ValueError('港股清单为空，保留原库')
        stamp=now_iso()
        common={'00700':['腾讯'],'09988':['阿里巴巴'],'01810':['小米','小米集团'],'03690':['美团'],'09618':['京东','京东集团'],'09999':['网易'],'09888':['百度','百度集团']}
        with self.connect() as c:
            old=c.execute("SELECT count(*) FROM securities WHERE in_directory=1 AND exchange='hk'").fetchone()[0]
            if old and len(valid)<old*.8:raise ValueError('港股目录数量异常下降，保留原库')
            c.execute("UPDATE securities SET in_directory=0 WHERE exchange='hk'")
            for code,row in valid.items():
                key='hk'+code
                c.execute("""INSERT INTO securities VALUES (?,?,?,?,?,?,?,?,1) ON CONFLICT(security_id) DO UPDATE SET
                    name=excluded.name,pinyin=excluded.pinyin,source=excluded.source,fetched_at=excluded.fetched_at,in_directory=1""",(key,code,'hk',row['name'],row.get('english_name',''),'',HK_SOURCE,stamp))
                aliases=hk_aliases(row['name'])|hk_aliases(row.get('english_name',''))|{alias for alias in common.get(code,[]) if normalized(alias) in normalized(row['name'])}
                for name in aliases:
                    if name:c.execute('INSERT INTO security_names VALUES (?,?,?,?,?) ON CONFLICT(security_id,name) DO UPDATE SET normalized=excluded.normalized,last_seen=excluded.last_seen',(key,name,normalized(name),stamp,stamp))
            c.execute('INSERT INTO security_syncs(updated_at,count,source) VALUES (?,?,?)',(stamp,len(valid),HK_SOURCE))
        return self.stats()
    def sync_hk(self):
        from .hk_securities import fetch
        return self.ingest_hk(fetch())
    def sync(self):
        try:
            response=httpx.get(SOURCE,timeout=30,follow_redirects=False)
            response.raise_for_status();rows=response.json().get('stockList')
            if not isinstance(rows,list) or len(rows)<1000:raise ValueError('目录数据不完整，保留原库')
            return self.ingest(rows)
        except httpx.HTTPError:raise ValueError('证券目录数据源暂不可用，保留原库') from None
    def stats(self):
        with self.connect() as c:
            return {'count':c.execute('SELECT count(*) FROM securities WHERE in_directory=1').fetchone()[0], 'updated_at':c.execute('SELECT max(updated_at) FROM security_syncs').fetchone()[0],'source':SOURCE,'hk_source':HK_SOURCE,'hk_count':c.execute("SELECT count(*) FROM securities WHERE in_directory=1 AND exchange='hk'").fetchone()[0]}
    def search(self,q='',limit=60):
        with self.connect() as c:
            if not q:return [dict(r) for r in c.execute('SELECT * FROM securities WHERE in_directory=1 ORDER BY exchange,code LIMIT ?',(limit,))]
            number,exchange=code_hint(q)
            if number:
                exact=[dict(r) for r in c.execute('SELECT * FROM securities WHERE in_directory=1 AND code=?',(number,)) if not exchange or r['exchange']==exchange]
                if exact:return exact
            q=normalized(q)
            term='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            return [dict(r) for r in c.execute("""SELECT DISTINCT s.* FROM securities s JOIN security_names n USING(security_id)
                WHERE s.in_directory=1 AND (s.code LIKE ? ESCAPE '\\' OR n.normalized LIKE ? ESCAPE '\\' OR s.pinyin LIKE ? ESCAPE '\\')
                ORDER BY s.name=? DESC,s.code LIMIT ?""",(term,term,term,q,limit))]
    def resolve(self,name,code=''):
        # Prefer a current exact name; then accept only an unambiguous historical name.
        with self.connect() as c:
            rows=[dict(r) for r in c.execute('SELECT * FROM securities WHERE in_directory=1') if normalized(r['name'])==normalized(name)]
            if not rows:
                rows=[dict(r) for r in c.execute('SELECT DISTINCT s.* FROM securities s JOIN security_names n USING(security_id) WHERE n.normalized=? AND s.in_directory=1',(normalized(name),))]
        if code:
            number,exchange=code_hint(code)
            if not name and number:
                with self.connect() as c:rows=[dict(r) for r in c.execute('SELECT * FROM securities WHERE in_directory=1 AND code=?',(number,))]
            rows=[r for r in rows if r['code']==number and (not exchange or r['exchange']==exchange)]
        return rows[0] if len(rows)==1 else None
    def matches(self,companies):
        # One catalog read per company page; no network and no fuzzy auto binding.
        with self.connect() as c:
            securities=[dict(r) for r in c.execute('SELECT * FROM securities WHERE in_directory=1')]
            names={}
            for r in securities:names.setdefault(normalized(r['name']),[]).append(r)
            historical={}
            by_key={r['security_id']:r for r in securities}
            for row in c.execute('SELECT * FROM security_names'):
                if row['security_id'] in by_key:historical.setdefault(row['normalized'],{})[row['security_id']]=by_key[row['security_id']]
        result={}
        for company in companies:
            candidates={}
            for name in [company.get('name',''),*company.get('aliases',[])]:
                direct=names.get(normalized(name),[])
                for r in direct or historical.get(normalized(name),{}).values():candidates[r['security_id']]=r
            if company.get('code'):
                number,exchange=code_hint(company['code'])
                candidates={k:r for k,r in candidates.items() if r['code']==number and (not exchange or r['exchange']==exchange)}
            if len(candidates)==1:result[company['stock_id']]=next(iter(candidates.values()))
        return result
