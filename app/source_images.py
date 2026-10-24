"""Resolve authorized ZSXQ image IDs and cache image bytes, never signed URLs."""
import os,re,tempfile,threading,time
from urllib.parse import urlsplit
import httpx
from .storage import read_json,atomic_write_json
from .sources import SourceError
from .utils import now_iso

_LOCK=threading.RLock()
_TOPICS={}
_MAX_BYTES=25*1024*1024

def safe_url(value):
    if not isinstance(value,str):raise SourceError('图片地址无效')
    try:
        parsed=urlsplit(value);port=parsed.port
    except ValueError:raise SourceError('图片地址无效') from None
    if parsed.scheme!='https' or parsed.hostname!='images.zsxq.com' or parsed.username or parsed.password or port not in (None,443):
        raise SourceError('图片地址域名异常')
    return value

def image_type(data):
    if data.startswith(b'\xff\xd8\xff'):return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):return 'image/png'
    if data.startswith((b'GIF87a',b'GIF89a')):return 'image/gif'
    if data.startswith(b'RIFF') and data[8:12]==b'WEBP':return 'image/webp'
    if len(data)>12 and data[4:8]==b'ftyp' and data[8:12] in (b'avif',b'avis'):return 'image/avif'
    raise SourceError('返回内容不是受支持的图片')

def load(storage,client,document_id,revision,meta,image_id,transport=None):
    if not re.fullmatch(r'doc_[0-9A-Z]{26}',document_id) or not re.fullmatch(r'\d{1,30}',image_id) or type(revision)is not int or revision<1:
        raise SourceError('图片标识无效')
    if not any(a.get('kind')=='image' and str(a.get('image_id'))==image_id for a in meta.get('source_attachments',[])):
        raise SourceError('该版本没有这张图片')
    source=meta.get('source') or {};topic_id=str(source.get('item_id') or '');group_id=str(source.get('space_id') or '')
    if source.get('platform')!='zsxq' or not re.fullmatch(r'\d+',topic_id) or not re.fullmatch(r'\d+',group_id):raise SourceError('图片来源无效')
    key=f'{document_id}-r{revision}-{image_id}'
    path=storage.path('cache/source-images/'+key+'.bin');info_path=path.with_suffix('.json')
    with _LOCK:
        info=read_json(info_path)
        if info and path.is_file() and info.get('media_type') in ('image/jpeg','image/png','image/gif','image/webp','image/avif'):
            return path,info['media_type']
        cache_key=(group_id,topic_id);cached=_TOPICS.get(cache_key)
        if not cached or time.monotonic()-cached[0]>60:
            topic=client.detail(topic_id)
            if str(topic.get('topic_id'))!=topic_id or str((topic.get('group') or {}).get('group_id'))!=group_id:
                raise SourceError('图片主题来源不匹配')
            if len(_TOPICS)>=100:_TOPICS.clear()
            _TOPICS[cache_key]=(time.monotonic(),topic)
        else:topic=cached[1]
        image=next((i for i in topic.get('images',[]) if str(i.get('image_id'))==image_id),None)
        if not image:raise SourceError('图片已不可用，可到知识星球查看')
        variant=next((image[k] for k in ('original','large','thumbnail') if isinstance(image.get(k),dict) and image[k].get('url')),None)
        if not variant:raise SourceError('知识星球尚未提供图片地址')
        url=safe_url(variant['url'])
        try:
            with httpx.Client(transport=transport,timeout=30,follow_redirects=False) as http:
                with http.stream('GET',url) as response:
                    response.raise_for_status();chunks=[];size=0
                    for chunk in response.iter_bytes():
                        size+=len(chunk)
                        if size>_MAX_BYTES:raise SourceError('图片超过25MB，请到知识星球查看原件')
                        chunks.append(chunk)
            data=b''.join(chunks);media_type=image_type(data)
        except httpx.HTTPError:
            _TOPICS.pop(cache_key,None)
            raise SourceError('图片暂时加载失败，可重试或到知识星球查看') from None
        path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
            os.replace(tmp,path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
        atomic_write_json(info_path,{'media_type':media_type,'fetched_at':now_iso(),'size':len(data)})
        return path,media_type
