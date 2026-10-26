"""Outbound private-reader sync; optional bounded Mac research worker, disabled by default."""
import argparse,hashlib,json,os,time,re
from urllib.parse import urlsplit
import httpx
from .config import load_config
from .storage import Storage,read_json,atomic_write_json
from . import index
from .frontmatter import split_frontmatter
from .mobile_editorial import presentation,source_health
from .mobile_attachments import inventory,MAX_BYTES,asset_digest


def records(cfg,storage):
    with index.connect(cfg.db_path) as conn:
        rows=conn.execute('SELECT d.*,s.body FROM documents d JOIN document_search s ON d.document_id=s.document_id WHERE d.deleted_at IS NULL ORDER BY d.document_id').fetchall()
        summaries={row['document_id']:read_json(storage.path(f"derived/summaries/{row['document_id']}.json")) or {} for row in rows}
        names={r[0] or r[1] for r in conn.execute('SELECT name,code FROM stocks')}
        for row in rows:
            summary=summaries[row['document_id']]
            if summary.get('revision')==row['current_revision']:
                names.update(s['name'] for s in summary.get('stocks',[]) if isinstance(s,dict) and isinstance(s.get('name'),str) and s['name'] in row['body'] and s.get('evidence') and s['evidence'] in row['body'])
        from .securities import Securities
        catalog=Securities(storage)
        matches=catalog.matches([{'stock_id':name,'name':name} for name in sorted(names) if name])
        from .us_securities import matches as us_matches
        american=us_matches(catalog,names)
        for row in rows:
            summary=summaries[row['document_id']]
            if summary.get('revision')!=row['current_revision']:summary={}
            editorial=(read_json(storage.path('catalog/editorial.json')) or {}).get(row['document_id'],{})
            companies=[r[0] or r[1] for r in conn.execute('SELECT DISTINCT s.name,s.code FROM stocks s JOIN document_stocks ds ON ds.stock_id=s.stock_id WHERE ds.document_id=?',(row['document_id'],))]
            companies+= [s['name'] for s in summary.get('stocks',[]) if isinstance(s,dict) and isinstance(s.get('name'),str) and s['name'] in row['body'] and s.get('evidence') and s['evidence'] in row['body']]
            companies=list(dict.fromkeys(companies))
            body=row['body'];assets=[];local_assets={}
            revision=conn.execute('SELECT archive_path FROM document_revisions WHERE document_id=? AND revision=?',(row['document_id'],row['current_revision'])).fetchone()
            meta,_=split_frontmatter(storage.read_revision_text(revision['archive_path'])) if revision else ({},'')
            attachments,prepared=inventory(storage,row['document_id'],row['current_revision'],meta)
            for item in attachments:
                if item['status']=='ready':
                    path=prepared[item['asset_id']]
                    if item['asset_id'] not in local_assets:assets.append(dict(id=item['asset_id'],name=item['name'],type=item['type']));local_assets[item['asset_id']]=path
            def add(path,kind,name):
                if path.is_file() and path.stat().st_size<=MAX_BYTES:
                    digest=asset_digest(path)
                    if digest not in local_assets:assets.append({'id':digest,'name':name,'type':kind});local_assets[digest]=path
                    return digest
            from .youdao import image_links
            for url in image_links(body):
                match=re.search(r'/resource/([a-f0-9]{32})/',url)
                if match:
                    path=storage.path(f"cache/youdao-images/{match[1]}/{hashlib.sha256(url.encode()).hexdigest()}")
                    digest=add(path,'image','笔记原图')
                    if digest:body=body.replace(url,'asset:'+digest)
            for path in storage.path('cache/source-images').glob(f"{row['document_id']}-r{row['current_revision']}-*.bin"):add(path,'image','星球原图')
            for path in storage.path(f"cache/document-pdfs/{row['document_id']}").glob(f"r{row['current_revision']}-*.pdf"):add(path,'pdf',row['title']+'.pdf')
            yield dict(**presentation(row,body,attachments,summary),attachments=attachments,_local_assets=local_assets,assets=assets,document_id=row['document_id'],revision=row['current_revision'],title=row['title'],body=body,summary=summary.get('summary',''),published_at=row['published_at'] or '',source_name=row['source_space_name'] or row['source_platform'] or '',source_url=row['source_url'] or '',industries=editorial.get('industries') or summary.get('industries',[]),companies=companies,company_securities=[dict(name=name,canonical_name=matches[name]['name'],security_id=matches[name]['security_id'],code=matches[name]['code'],exchange=matches[name]['exchange']) for name in companies if name in matches and matches[name]['exchange']!='us']+[dict(name=name,canonical_name=r['name'],security_id=r['security_id'],code=r['code'],exchange='us') for name in companies for r in american.get(name,[])])


def sync_once(cfg,storage,url,token,transport=None):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or any(part in ('.','..') for part in parsed.path.split('/')) or len(token)<32:raise ValueError('需要有效 HTTPS 根地址和发布凭据')
    marker=read_json(storage.path('catalog/storage.json')) or read_json(storage.path('storage.json')) or {}
    library=marker.get('library_id')
    if not library:raise ValueError('资料库未初始化')
    receipt_path=storage.path('jobs/mobile-sync.json');receipt=read_json(receipt_path) or {}
    scope=hashlib.sha256((url+'|'+token).encode()).hexdigest()
    hashes=receipt.get('hashes',{}) if receipt.get('scope')==scope else {};changed=[];live_ids=set()
    for record in records(cfg,storage):
        live_ids.add(record['document_id'])
        local_assets=record.pop('_local_assets',{})
        digest=hashlib.sha256(json.dumps(record,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if hashes.get(record['document_id'])!=digest:changed.append((record,digest,local_assets))
    sent=0
    with httpx.Client(timeout=180,follow_redirects=False,transport=transport) as client:
        for offset in range(0,len(changed),20):
            batch=changed[offset:offset+20]
            for _,_,assets in batch:
                for asset_id,path in assets.items():
                    with path.open('rb') as stream:
                        response=client.post(url.rstrip('/')+'/v1/assets/'+asset_id,headers={'Authorization':'Bearer '+token},content=iter(lambda:stream.read(1024*1024),b''))
                    if response.status_code!=200:raise RuntimeError('资源上传未确认，保留旧进度')
            response=client.post(url.rstrip('/')+'/v1/sync',headers={'Authorization':'Bearer '+token},json={'library_id':library,'documents':[r for r,_,_ in batch]})
            if response.status_code!=200:raise RuntimeError(f'同步失败（HTTP {response.status_code}），保留旧进度')
            result=response.json()
            if result.get('accepted')!=len(batch):raise RuntimeError('云端未确认完整批次，未推进水位')
            hashes.update({r['document_id']:digest for r,digest,_ in batch});sent+=len(batch)
            atomic_write_json(receipt_path,{'scope':scope,'hashes':hashes,'sent':sent})
        removed=sorted(set(hashes)-live_ids)
        for offset in range(0,len(removed),100):
            batch=removed[offset:offset+100]
            response=client.post(url.rstrip('/')+'/v1/sync',headers={'Authorization':'Bearer '+token},json={'library_id':library,'documents':[],'deleted_ids':batch})
            if response.status_code!=200 or response.json().get('deleted')!=len(batch):raise RuntimeError('删除事件未确认，保留旧进度')
            for document_id in batch:hashes.pop(document_id,None)
            atomic_write_json(receipt_path,{'scope':scope,'hashes':hashes,'sent':sent})
        # Heartbeat is separate from document changes; its timestamp must not create new research.
        response=client.post(url.rstrip('/')+'/v1/source-health',headers={'Authorization':'Bearer '+token},json=source_health(storage))
        if response.status_code not in (200,404):raise RuntimeError('采集状态未发布')
    return {'sent':sent,'model_requests':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--watch',action='store_true');parser.add_argument('--config',type=__import__('pathlib').Path);args=parser.parse_args()
    cfg=load_config();storage=Storage(cfg.data_dir);storage.ensure_layout()
    url=os.environ.get('RESEARCHDOCK_SYNC_URL','');token=os.environ.get('RESEARCHDOCK_PUSH_TOKEN','');private={}
    if args.config:
        if args.config.stat().st_mode & 0o077:raise SystemExit('私有同步配置权限应为 600')
        private=json.loads(args.config.read_text());url=private.get('url','');token=private.get('push_token','')
    from .mobile_attachments import process_requests,acknowledge,BackgroundPreparations
    preparations=BackgroundPreparations(cfg,storage,url,token) if args.watch else None
    from .research_worker import BackgroundResearch,disable_research
    assistant=BackgroundResearch(cfg,storage,url,token,private.get('research_daily_limit',10)) if args.watch and private.get('research_enabled',False) else None
    while True:
        if assistant:
            try:assistant.tick()
            except Exception:print(json.dumps({'research_queue':'unavailable'}),flush=True)
        elif args.watch and url and token:
            try:disable_research(url,token)
            except Exception:print(json.dumps({'research_queue':'unavailable'}),flush=True)
        try:
            try:results=preparations.tick() if preparations else process_requests(cfg,storage,url,token)
            except Exception:
                # Queue trouble must not suppress normal document publication.
                results=[]
                print(json.dumps({'attachment_queue':'unavailable'}),flush=True)
            print(json.dumps(sync_once(cfg,storage,url,token)),flush=True)
            acknowledge(url,token,results)
            if preparations:preparations.confirm(results)
        except Exception as exc:
            # Never print URL, server response, credentials or source content.
            print(json.dumps({'status':'failed','error':type(exc).__name__}),flush=True)
            if not args.watch:raise SystemExit(1)
        if not args.watch:break
        time.sleep(15)


if __name__=='__main__':main()
