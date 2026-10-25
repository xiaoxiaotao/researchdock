import hashlib,json,tempfile,unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from app.config import load_config
from app.storage import Storage
from app.pipeline import Pipeline
from app import index
from app.mobile_sync import records
from app.mobile_cloud import create_app
from app.mobile_attachments import inventory,prepare,identifier,safe_download_url,media_type

P='p'*40;R='r'*40;ID='doc_'+'A'*26;KEY='a'*64
class AttachmentTests(unittest.TestCase):
 def test_inventory_keeps_all_formats_without_urls_or_model(self):
  with tempfile.TemporaryDirectory() as tmp:
   st=Storage(Path(tmp)/'kb');st.ensure_layout()
   meta={'source_attachments':[{'kind':'image','image_id':'123'},{'kind':'file','file_id':'124','name':'合成.pdf','size':50},{'kind':'file','file_id':'125','name':'合成.mp3','size':200},{'kind':'file','file_id':'126','name':'合成.xlsx','size':100}]}
   items,assets=inventory(st,ID,1,meta)
   self.assertEqual([a['type'] for a in items],['image','pdf','audio','file']);self.assertEqual(len(items),4);self.assertFalse(assets);self.assertTrue(all(a['status']=='missing' for a in items));self.assertNotIn('http',json.dumps(items))
   cache=st.path(f'cache/source-images/{ID}-r1-123.bin');cache.parent.mkdir(parents=True,exist_ok=True);cache.write_bytes(b'\xff\xd8\xff synthetic')
   items,assets=inventory(st,ID,1,meta);self.assertEqual(items[0]['status'],'ready');self.assertEqual(len(assets),1)
 def test_queue_auth_membership_idempotency_retry_and_binary_formats(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=TestClient(create_app(tmp,P,R));read={'Authorization':'Bearer '+R};push={'Authorization':'Bearer '+P}
   attachment=dict(id=KEY,name='合成.mp3',type='audio',size=20,status='missing',asset_id='',message='等待获取')
   doc=dict(document_id=ID,revision=1,title='合成',body='原文',attachments=[attachment])
   self.assertEqual(c.post('/v1/sync',headers=push,json={'library_id':'test','documents':[doc]}).status_code,200)
   route=f'/v1/documents/{ID}/attachments/{KEY}/prepare'
   self.assertEqual(c.post(route).status_code,401);self.assertEqual(c.post(route,headers=read).json()['status'],'queued');self.assertEqual(c.post(route,headers=read).json()['status'],'queued')
   state=route.replace('/prepare','/preparation');self.assertEqual(c.get(state).status_code,401);self.assertEqual(c.get(state,headers=read).json()['status'],'queued')
   self.assertEqual(c.get('/v1/attachment-jobs',headers=read).status_code,401)
   jobs=c.get('/v1/attachment-jobs',headers=push).json()['jobs'];self.assertEqual(len(jobs),1)
   self.assertEqual(c.post('/v1/attachment-jobs/'+jobs[0]['job_id'],headers=read,json={'status':'ready'}).status_code,401)
   c.post('/v1/attachment-jobs/'+jobs[0]['job_id'],headers=push,json={'status':'failed'});self.assertEqual(c.get(state,headers=read).json()['status'],'failed');self.assertEqual(c.get('/v1/attachment-jobs',headers=push).json()['jobs'],[])
   self.assertEqual(c.post(route,headers=read).json()['status'],'queued')
   self.assertEqual(c.post(route.replace(KEY,'b'*64),headers=read).status_code,404)
   for data,typ,name in [(b'ID3 synthetic audio','audio','合成.mp3'),(b'PK\x03\x04 synthetic workbook','file','合成.xlsx')]:
    digest=hashlib.sha256(data).hexdigest();self.assertEqual(c.post('/v1/assets/'+digest,headers=push,content=data).status_code,200)
    ready={**attachment,'status':'ready','asset_id':digest,'type':typ,'name':name};updated={**doc,'attachments':[ready],'assets':[dict(id=digest,name=name,type=typ)]}
    self.assertEqual(c.post('/v1/sync',headers=push,json={'library_id':'test','documents':[updated]}).status_code,200)
    self.assertEqual(c.get('/v1/assets/'+digest,headers=read).content,data)
   bad={**doc,'attachments':[{**attachment,'status':'ready','asset_id':'c'*64}]};self.assertEqual(c.post('/v1/sync',headers=push,json={'library_id':'test','documents':[bad]}).status_code,422)
 def test_prepare_uses_archived_membership_and_streamed_original(self):
  with tempfile.TemporaryDirectory() as tmp:
   cfg=replace(load_config(),data_dir=Path(tmp)/'kb');st=Storage(cfg.data_dir);st.ensure_layout();index.init_schema(cfg.db_path)
   a={'kind':'file','file_id':'123','name':'合成.pdf','size':30}
   f=st.path('inbox/synthetic.jsonl');f.write_text(json.dumps({'schema_version':1,'title':'附件测试','content_text':'原文不变','source_platform':'manual','source_item_id':'att-test','content_type':'research_note','source_attachments':[a]})+'\n');Pipeline(cfg,st).import_file(f)
   d=next(records(cfg,st));self.assertEqual(len(d['attachments']),1)
   class Client:
    def download_url(self,file_id):assert file_id=='123';return 'https://files.zsxq.com/synthetic.pdf'
   job=dict(document_id=d['document_id'],revision=1,attachment_id=identifier(a))
   with patch('app.llm.ReceiptClient.call',side_effect=AssertionError('no model')):
    prepare(cfg,st,job,Client(),httpx.MockTransport(lambda r:httpx.Response(200,content=b'%PDF-1.7 synthetic original')))
   ready=next(records(cfg,st));self.assertEqual(ready['attachments'][0]['status'],'ready');self.assertEqual(ready['body'],d['body']);self.assertEqual(ready['assets'][0]['type'],'pdf')
   with self.assertRaises(ValueError):prepare(cfg,st,{**job,'attachment_id':'f'*64},Client())
 def test_new_revision_discards_old_queued_requests(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=TestClient(create_app(tmp,P,R));read={'Authorization':'Bearer '+R};push={'Authorization':'Bearer '+P}
   a=dict(id=KEY,name='合成.pdf',type='pdf',size=20,status='missing',asset_id='',message='等待获取')
   d=dict(document_id=ID,revision=1,title='合成',body='旧版本',attachments=[a])
   c.post('/v1/sync',headers=push,json={'library_id':'test','documents':[d]});c.post(f'/v1/documents/{ID}/attachments/{KEY}/prepare',headers=read)
   c.post('/v1/sync',headers=push,json={'library_id':'test','documents':[{**d,'revision':2,'body':'新版本'}]})
   self.assertEqual(c.get('/v1/attachment-jobs',headers=push).json()['jobs'],[])
   import sqlite3
   conn=sqlite3.connect(Path(tmp)/'reader.sqlite3')
   try:self.assertEqual(conn.execute('select count(*) from attachment_jobs').fetchone()[0],0)
   finally:conn.close()
 def test_download_domain_and_format_limits(self):
  for url in ['http://files.zsxq.com/a','https://zsxq.com.evil.test/a','https://127.0.0.1/a','https://user:pass@files.zsxq.com/a','https://files.zsxq.com:8000/a']:
   with self.assertRaises(ValueError):safe_download_url(url)
  self.assertIsNone(media_type(b'<html>login page'))
