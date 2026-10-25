"""Complete source inventory and explicit, bounded, read-only attachment preparation."""
import hashlib,json,os,re,tempfile
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from .storage import read_json,atomic_write_json
from .frontmatter import split_frontmatter
from . import index

MAX_BYTES=100_000_000
_DIGESTS={}

def asset_digest(path):
    stat=path.stat();key=(str(path),stat.st_size,stat.st_mtime_ns)
    if key not in _DIGESTS:
        h=hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b""):h.update(chunk)
        if len(_DIGESTS)>1000:_DIGESTS.clear()
        _DIGESTS[key]=h.hexdigest()
    return _DIGESTS[key]

def kind(name):
    ext=Path(name).suffix.lower()
    return 'pdf' if ext=='.pdf' else 'audio' if ext in ('.mp3','.wav','.m4a') else 'file'

def identifier(a):
    return hashlib.sha256((str(a.get('kind'))+':'+str(a.get('image_id') or a.get('file_id') or '')).encode()).hexdigest()

def cache_path(storage,document_id,revision,key):
    if not re.fullmatch(r'doc_[0-9A-Z]{26}',document_id) or not re.fullmatch('[a-f0-9]{64}',key) or type(revision)!=int or revision<1:raise ValueError('附件编号无效')
    return storage.path(f'cache/mobile-attachments/{document_id}-r{revision}-{key}.bin')

def inventory(storage,document_id,revision,meta):
    result=[];assets={}
    for n,a in enumerate(meta.get('source_attachments') or []):
        if a.get('kind') not in ('image','file'):continue
        key=identifier(a);name=Path(a.get('name') or f'星球图片 {n+1}').name[:300]
        typ='image' if a['kind']=='image' else kind(name)
        path=cache_path(storage,document_id,revision,key);info=read_json(path.with_suffix('.json')) or {}
        # Existing desktop image cache is immediately reusable.
        if typ=='image':
            old=storage.path(f"cache/source-images/{document_id}-r{revision}-{a.get('image_id')}.bin")
            if old.is_file():path=old
        size=a.get('size') if type(a.get('size'))==int and a['size']>=0 else 0
        item=dict(id=key,name=name,type=typ,size=size,status='missing',asset_id='',message='等待从 Mac 获取原件')
        if path.is_file() and path.stat().st_size<=MAX_BYTES:
            digest=asset_digest(path);assets[digest]=path
            item.update(status='ready',asset_id=digest,size=path.stat().st_size,message='原件已同步，可按需下载')
        elif info.get('status')=='failed':item.update(status='failed',message='原件获取失败，可重试或查看来源')
        if size>MAX_BYTES:item.update(status='unavailable',message='超过100MB，请在原始来源下载')
        result.append(item)
    return result,assets

def safe_download_url(url):
    try:p=urlsplit(url)
    except ValueError:raise ValueError('下载地址无效') from None
    if p.scheme!='https' or not p.hostname or not (p.hostname=='zsxq.com' or p.hostname.endswith('.zsxq.com')) or p.username or p.password or p.port not in (None,443):raise ValueError('下载域名异常')
    return url

def media_type(head):
    if head.startswith(b'%PDF-'):return 'application/pdf'
    if head.startswith(b'\x89PNG\r\n\x1a\n'):return 'image/png'
    if head.startswith(b'\xff\xd8\xff'):return 'image/jpeg'
    if head.startswith((b'GIF87a',b'GIF89a')):return 'image/gif'
    if head[:4]==b'RIFF':return 'image/webp' if head[8:12]==b'WEBP' else 'audio/wav' if head[8:12]==b'WAVE' else None
    if head.startswith(b'ID3') or len(head)>1 and head[0]==255 and head[1]&0xe0==0xe0:return 'audio/mpeg'
    if len(head)>12 and head[4:8]==b'ftyp':return 'audio/mp4' if head[8:12] in (b'M4A ',b'isom',b'mp42') else None
    if head.startswith(b'PK\x03\x04'):return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    if head.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):return 'application/vnd.ms-excel'
    return None

def prepare(cfg,storage,job,client=None,transport=None):
    from .sources import ZsxqClient
    document_id=job['document_id'];revision=job['revision'];key=job['attachment_id']
    path=cache_path(storage,document_id,revision,key)
    with index.connect(cfg.db_path) as conn:
        row=conn.execute('SELECT r.archive_path FROM documents d JOIN document_revisions r ON d.document_id=r.document_id AND d.current_revision=r.revision WHERE d.document_id=? AND d.current_revision=? AND d.deleted_at IS NULL',(document_id,revision)).fetchone()
    if not row:raise ValueError('归档版本已变化')
    meta,_=split_frontmatter(storage.read_revision_text(row['archive_path']))
    a=next((a for a in meta.get('source_attachments',[]) if identifier(a)==key),None)
    if not a:raise ValueError('此资料没有该附件')
    items,_=inventory(storage,document_id,revision,meta)
    if next(i for i in items if i['id']==key)['status']=='ready':return
    if (a.get('size') or 0)>MAX_BYTES:raise ValueError('附件超过100MB')
    client=client or ZsxqClient()
    try:
        if a['kind']=='image':
            from .source_images import load
            load(storage,client,document_id,revision,meta,str(a['image_id']),transport=transport);return
        url=safe_download_url(client.download_url(str(a['file_id'])))
        path.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd,'wb') as out,httpx.Client(timeout=120,follow_redirects=False,transport=transport) as http:
                size=0;head=b''
                for redirects in range(4):
                    with http.stream('GET',url) as response:
                        if response.status_code in (301,302,303,307,308):url=safe_download_url(response.headers.get('location',''));continue
                        response.raise_for_status()
                        for chunk in response.iter_bytes():
                            size+=len(chunk)
                            if size>MAX_BYTES:raise ValueError('附件超过100MB')
                            if len(head)<32:head=(head+chunk)[:32]
                            out.write(chunk)
                        break
                else:raise ValueError('下载重定向过多')
                mime=media_type(head)
                expected=kind(a.get('name',''))
                if not mime or expected=='pdf' and mime!='application/pdf' or expected=='audio' and not mime.startswith('audio/') or expected=='file' and mime not in ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','application/vnd.ms-excel'):raise ValueError('原件格式不匹配')
                out.flush();os.fsync(out.fileno())
            os.replace(tmp,path)
            atomic_write_json(path.with_suffix('.json'),{'status':'ready','size':size})
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    except Exception:
        atomic_write_json(path.with_suffix('.json'),{'status':'failed'})
        raise

def process_requests(cfg,storage,url,token,transport=None):
    results=[]
    with httpx.Client(timeout=30,transport=transport,headers={'Authorization':'Bearer '+token}) as http:
        response=http.get(url.rstrip('/')+'/v1/attachment-jobs')
        if response.status_code==404:return [] # Older cloud deployment; normal document sync still works.
        response.raise_for_status()
        for job in response.json()['jobs'][:3]:
            try:prepare(cfg,storage,job);status='ready'
            except Exception:status='failed'
            results.append((job['job_id'],status))
    return results

def acknowledge(url,token,results):
    with httpx.Client(timeout=30,headers={'Authorization':'Bearer '+token}) as http:
        for key,status in results:
            r=http.post(url.rstrip('/')+'/v1/attachment-jobs/'+key,json={'status':status});r.raise_for_status()


class BackgroundPreparations:
    """Two bounded source downloads; completed work remains until publication is confirmed."""
    def __init__(self,cfg,storage,url,token,transport=None):
        from concurrent.futures import ThreadPoolExecutor
        self.cfg=cfg;self.storage=storage;self.url=url.rstrip('/');self.token=token;self.transport=transport
        self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='original-download')
        self.pending={}

    def tick(self):
        results=[]
        for key,future in self.pending.items():
            if future.done():
                try:future.result();status='ready'
                except Exception:status='failed'
                results.append((key,status))
        if len(self.pending)>=2:return results
        with httpx.Client(timeout=15,transport=self.transport,headers={'Authorization':'Bearer '+self.token}) as client:
            response=client.get(self.url+'/v1/attachment-jobs')
            if response.status_code==404:return results
            response.raise_for_status()
            for job in response.json()['jobs']:
                key=job['job_id']
                if key not in self.pending and len(self.pending)<2:
                    self.pending[key]=self.pool.submit(prepare,self.cfg,self.storage,dict(job))
        return results

    def confirm(self,results):
        for key,_ in results:
            future=self.pending.get(key)
            if future is not None and future.done():self.pending.pop(key)

    def close(self):
        self.pool.shutdown(wait=True)
