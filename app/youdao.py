"""Read public Youdao shares linked from authorized ZSXQ posts (no login bypass)."""
import hashlib
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit, parse_qs
import httpx
from .storage import atomic_write_json, read_json
from .utils import now_iso


def share_id(url):
    p=urlsplit(url)
    if p.scheme!='https' or p.hostname not in {'share.note.youdao.com','note.youdao.com'} or p.username or p.password or p.port not in (None,443):
        raise ValueError('不是有效的有道分享链接')
    key=(parse_qs(p.query).get('id') or [''])[0]
    if not re.fullmatch(r'[a-fA-F0-9]{32}',key):raise ValueError('分享链接缺少完整 ID')
    return key.lower()


def links(body):
    result=[]
    for url in re.findall(r'https://(?:share\.)?note\.youdao\.com/[^\s<>"\]]+',body):
        try:key=share_id(url)
        except ValueError:continue
        if key not in [x[0] for x in result]:result.append((key,f'https://share.note.youdao.com/ynoteshare/index.html?id={key}&type=note'))
    return result


def plain(value):
    return re.sub(r'([\\`*_{}\[\]<>#!|])',r'\\\1',value.replace('\\u0026','&'))


class Legacy(HTMLParser):
    def __init__(self):super().__init__();self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.hidden+=1
        if tag in ('p','div','br','li'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
        if tag in ('p','div','li'):self.parts.append('\n')
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)


def extract(payload,key):
    content=payload.get('content')
    if not isinstance(content,str) or not content.strip():raise ValueError('分享需要授权、已失效或未返回正文')
    try:tree=json.loads(content)
    except json.JSONDecodeError:
        parser=Legacy();parser.feed(content)
        body=plain(''.join(parser.parts).strip())
    else:
        def walk(node):
            if isinstance(node,list):return ''.join(walk(x) for x in node)
            if not isinstance(node,dict):return ''
            if isinstance(node.get('8'),str):return plain(node['8'])
            if node.get('6')=='im':
                url=(node.get('4') or {}).get('u','');p=urlsplit(url)
                if p.scheme=='https' and p.netloc in ('note.youdao.com','share.note.youdao.com') and p.path.startswith('/yws/public/resource/'+key+'/'):
                    return '\n\n![有道笔记原图]('+url+')\n\n'
                return ''
            text=''.join(walk(node[k]) for k in ('5','7') if k in node)
            return text+ ('\n\n' if '5' in node and node.get('2')!='3' else '')
        body=walk(tree).strip()
    if len(body)<40:raise ValueError('未提取到足够正文，保留原文入口')
    return {'title':str(payload.get('tl') or '有道云笔记'),'body':body}


def fetch(storage,key,transport=None):
    if not re.fullmatch('[a-f0-9]{32}',key):raise ValueError('无效分享 ID')
    path=storage.path(f'catalog/youdao/{key}.json')
    cached=read_json(path)
    if cached and cached.get('status')=='succeeded':return cached
    # Endpoint and parameters are used by Youdao's public share-page bundle.
    with httpx.Client(timeout=25,follow_redirects=False,transport=transport) as client:
        response=client.get(f'https://share.note.youdao.com/yws/api/note/{key}',params={'sev':'j1','editorType':1,'editorVersion':'new-json-editor'})
        response.raise_for_status()
        if len(response.content)>8_000_000:raise ValueError('笔记正文超过提取上限')
        payload=response.json()
    result=extract(payload,key)
    digest=hashlib.sha256(response.content).hexdigest()
    atomic_write_json(storage.path(f'originals/youdao/{key}/{digest}.json'),payload)
    result.update(status='succeeded',fetched_at=now_iso(),sha256=digest)
    atomic_write_json(path,result)
    return result


def enrich(storage,record):
    body=record['content_text'];items=links(body)
    for key,url in items[:10]:
        try:
            note=fetch(storage,key)
            body+='\n\n---\n\n## 有道笔记正文：'+plain(note['title'])+'\n\n来源：'+url+'\n\n'+note['body']
        except (httpx.HTTPError,ValueError,TypeError,KeyError) as exc:
            atomic_write_json(storage.path(f'catalog/youdao/{key}-error.json'),{'status':'failed','message':type(exc).__name__,'at':now_iso()})
            body+='\n\n有道笔记正文暂未获取（可能需要授权或链接失效），请打开原文：'+url
    record['content_text']=body
    return record


def image_links(body):
    return re.findall(r'!\[有道笔记原图\]\((https://[^\s)]+)\)',body)


def local_images(body):
    for url in image_links(body):
        match=re.search(r'/resource/([a-f0-9]{32})/',url)
        if match:
            digest=hashlib.sha256(url.encode()).hexdigest()
            body=body.replace('('+url+')',f'(/youdao/{match[1]}/images/{digest})')
    return body


def image(storage,key,digest):
    if not re.fullmatch('[a-f0-9]{32}',key) or not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('无效图片')
    note=read_json(storage.path(f'catalog/youdao/{key}.json')) or {}
    url=next((u for u in image_links(note.get('body','')) if hashlib.sha256(u.encode()).hexdigest()==digest),None)
    if not url:raise ValueError('图片不属于已归档笔记')
    path=storage.path(f'cache/youdao-images/{key}/{digest}')
    if not path.exists():
        with httpx.Client(timeout=25,follow_redirects=False) as client:
            for _ in range(4):
                p=urlsplit(url)
                if p.scheme!='https' or p.netloc not in {'note.youdao.com','share.note.youdao.com','bucket-ynote-online-cdn.note.youdao.com'}:raise ValueError('图片地址不受支持')
                with client.stream('GET',url) as response:
                    if response.is_redirect:
                        url=response.headers['location'];continue
                    response.raise_for_status();parts=[];size=0
                    for chunk in response.iter_bytes():
                        size+=len(chunk)
                        if size>25_000_000:raise ValueError('图片过大')
                        parts.append(chunk)
                    data=b''.join(parts)
                break
            else:raise ValueError('图片跳转过多')
        if not (data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff') or data.startswith(b'GIF8') or (data[:4]==b'RIFF' and data[8:12]==b'WEBP')):raise ValueError('不是支持的图片格式')
        import os,tempfile
        path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd,'wb') as fh:fh.write(data);fh.flush();os.fsync(fh.fileno())
            os.replace(tmp,path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    data=path.read_bytes()[:12]
    mime='image/png' if data.startswith(b'\x89PNG') else 'image/jpeg' if data.startswith(b'\xff\xd8') else 'image/gif' if data.startswith(b'GIF8') else 'image/webp'
    return path,mime
