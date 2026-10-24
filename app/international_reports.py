"""Downloaded first-party public PDF originals, with clearly separate Chinese guides."""
import io,json,os,tempfile,threading
from pathlib import Path
from urllib.parse import urljoin
import httpx
from pypdf import PdfReader
from .international_sources import checked_url
from .storage import read_json,atomic_write_json
from .utils import now_iso,sha256_bytes

_LOCK=threading.RLock()
CATALOG=json.loads((Path(__file__).parent/'data/international-public-reports.json').read_text())

def reports(storage):
    return [{**r,'asset':read_json(storage.path(f'catalog/international-report-assets/{r["id"]}.json')) or {}} for r in CATALOG]

def report(storage,key):
    row=next((r for r in reports(storage) if r['id']==key),None)
    if not row:raise ValueError('报告不存在')
    return row

def asset_path(storage,key):
    row=report(storage,key);path=storage.path(f'originals/international/{key}.pdf')
    if row['asset'].get('status')!='ready' or not path.is_file():raise ValueError('PDF尚未下载或文件不存在')
    return path

def download(storage,key,transport=None):
    with _LOCK:
        row=report(storage,key);path=storage.path(f'originals/international/{key}.pdf');state_path=storage.path(f'catalog/international-report-assets/{key}.json')
        if row['asset'].get('status')=='ready' and path.is_file():return row['asset']
        url=checked_url(row['provider'],row['pdf_url'])
        try:
            with httpx.Client(timeout=60,transport=transport,follow_redirects=False) as client:
                for _ in range(5):
                    with client.stream('GET',url) as response:
                        if response.is_redirect:
                            url=checked_url(row['provider'],urljoin(url,response.headers.get('location','')));continue
                        response.raise_for_status();parts=[];size=0
                        for part in response.iter_bytes():
                            size+=len(part)
                            if size>50*1024*1024:raise ValueError('PDF超过50MB，未保存')
                            parts.append(part)
                        data=b''.join(parts);break
                else:raise ValueError('PDF重定向异常')
            if not data.startswith(b'%PDF-'):raise ValueError('官方地址未返回PDF，可能需要登录或填写表单')
            reader=PdfReader(io.BytesIO(data));pages=len(reader.pages)
            if pages<1:raise ValueError('PDF无有效页面')
            path.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(dir=path.parent)
            try:
                with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
                os.replace(tmp,path)
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
            state={'status':'ready','fetched_at':now_iso(),'size':len(data),'pages':pages,'sha256':sha256_bytes(data)}
            atomic_write_json(state_path,state);return state
        except Exception as exc:
            message=(str(exc) if isinstance(exc,ValueError) else ('官方PDF返回HTTP '+str(exc.response.status_code)+'；访问受限或原地址失效，未保存为可用原件' if isinstance(exc,httpx.HTTPStatusError) else '官方PDF暂不可达或格式无效，未保存为可用原件'))
            atomic_write_json(state_path,{'status':'failed','message':message,'last_attempt_at':now_iso()})
            raise ValueError(message) from None


def preview(storage,key,page):
    import shutil,subprocess
    row=report(storage,key);path=asset_path(storage,key)
    if type(page)is not int or not 1<=page<=row['asset']['pages']:raise ValueError('PDF页码无效')
    target=storage.path(f'cache/international-report-previews/{key}/{row["asset"]["sha256"]}/{page}.png')
    with _LOCK:
        if target.is_file():return target
        renderer=shutil.which('pdftoppm')
        bundled=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/pdftoppm'
        if not renderer and bundled.is_file():renderer=str(bundled)
        if not renderer:raise ValueError('本机未安装PDF预览工具，请下载PDF原件阅读')
        target.parent.mkdir(parents=True,exist_ok=True)
        temp=Path(tempfile.mkdtemp(dir=target.parent));prefix=temp/'page'
        try:
            result=subprocess.run([renderer,'-f',str(page),'-l',str(page),'-singlefile','-scale-to','1800','-png',str(path),str(prefix)],capture_output=True,timeout=45)
            if result.returncode or not prefix.with_suffix('.png').is_file():raise ValueError('该页预览失败，请下载原件阅读')
            os.replace(prefix.with_suffix('.png'),target)
        except subprocess.TimeoutExpired:raise ValueError('PDF预览超时，请下载原件阅读') from None
        except OSError:raise ValueError('PDF预览工具不可用，请下载原件阅读') from None
        finally:shutil.rmtree(temp,ignore_errors=True)
        return target
