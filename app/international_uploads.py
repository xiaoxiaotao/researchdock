"""User-provided PDF originals and extracted text for optional full translation."""
import io,re,os,tempfile
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
from pypdf import PdfReader
from .international_sources import provider,import_reports
from .storage import atomic_write_json,read_json
from .utils import sha256_bytes,sha256_text
from . import index

def upload(pipeline,key,data,title,url='',filename='report.pdf'):
    info=provider(key)
    if not isinstance(title,str) or not title.strip() or len(title)>500:raise ValueError('请填写报告标题')
    if not data.startswith(b'%PDF-') or len(data)>25*1024*1024:raise ValueError('需为25MB以内的PDF文件')
    try:
        reader=PdfReader(io.BytesIO(data))
        if reader.is_encrypted:raise ValueError('暂不支持加密PDF')
        if len(reader.pages)>100:raise ValueError('报告超过100页，请拆分后上传')
        parts=[];total=0
        for page in reader.pages:
            text=page.extract_text() or '';total+=len(text)
            if total>90000:raise ValueError('提取文字超过9万字，请拆分报告')
            parts.append(text)
    except ValueError:raise
    except Exception:raise ValueError('PDF无法读取，请核对文件') from None
    body='\n\n'.join(parts).strip()
    if len(body)<40:raise ValueError('未提取到足够文字；扫描图片型PDF暂不做OCR')
    digest=sha256_bytes(data);external='user-pdf:'+digest
    if not url:
        parsed=urlsplit(info['home']);url=urlunsplit((parsed.scheme,parsed.netloc,parsed.path,'',''))
    counts=import_reports(pipeline,key,[{'title':title,'url':url,'text':body,'coverage':'supplied_text','external_id':external}])
    with index.connect(pipeline.cfg.db_path) as c:
        doc=c.execute('SELECT document_id,current_revision FROM documents WHERE source_platform=? AND source_item_id=? AND deleted_at IS NULL',(key,sha256_text(external))).fetchone()
    if not doc:raise ValueError('报告已导入但未定位到资料，请查看资料库')
    path=pipeline.storage.path(f'originals/international-uploads/{key}/{digest}.pdf');path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    atomic_write_json(pipeline.storage.path(f'catalog/international-upload-files/{doc["document_id"]}.json'),{'provider':key,'sha256':digest,'filename':Path(filename).name,'size':len(data),'pages':len(reader.pages)})
    return {**counts,'document_id':doc['document_id'],'revision':doc['current_revision'],'url':f'/documents/{doc["document_id"]}/translation?revision={doc["current_revision"]}'}

def uploaded_file(storage,docid):
    if not re.fullmatch(r'doc_[0-9A-Z]{26}',docid):raise ValueError('资料无效')
    meta=read_json(storage.path(f'catalog/international-upload-files/{docid}.json')) or {}
    provider(meta.get('provider'))
    if not re.fullmatch(r'[a-f0-9]{64}',meta.get('sha256','')):raise ValueError('原件不存在')
    path=storage.path(f'originals/international-uploads/{meta["provider"]}/{meta["sha256"]}.pdf')
    if not path.is_file():raise ValueError('原件不存在')
    return path,meta
