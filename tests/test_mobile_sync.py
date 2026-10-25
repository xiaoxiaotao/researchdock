import json,tempfile,unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from app.config import load_config
from app.storage import Storage
from app.pipeline import Pipeline
from app import index
from app.mobile_cloud import create_app
from app.mobile_sync import sync_once

class MobileSyncTests(unittest.TestCase):
 def test_outbound_sync_is_incremental_without_secrets_or_model(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);cfg=replace(load_config(),data_dir=root/'kb');storage=Storage(cfg.data_dir);storage.ensure_layout();index.init_schema(cfg.db_path);pipeline=Pipeline(cfg,storage)
   file=storage.path('inbox/example.jsonl');file.write_text(json.dumps({'schema_version':1,'title':'合成公司交流','content_text':'这是未做AI分析的原文。','source_platform':'manual','source_item_id':'demo-1','content_type':'research_note'})+'\n');pipeline.import_file(file)
   token='p'*40;reader='r'*40;cloud=TestClient(create_app(root/'cloud',token,reader));sent=[]
   def handler(request):
    sent.append(json.loads(request.content));response=cloud.post(request.url.path,content=request.content,headers=dict(request.headers))
    return httpx.Response(response.status_code,json=response.json())
   with patch('app.llm.ReceiptClient.call',side_effect=AssertionError('no model')):
    result=sync_once(cfg,storage,'https://example.com',token,httpx.MockTransport(handler));self.assertEqual(result,{'sent':1,'model_requests':0})
    self.assertEqual(sync_once(cfg,storage,'https://example.com',token,httpx.MockTransport(handler))['sent'],0)
   self.assertEqual(sent[0]['documents'][0]['summary'],'');self.assertNotIn(token,json.dumps(sent));self.assertNotIn(str(root),json.dumps(sent))
   self.assertNotIn(token,storage.path('jobs/mobile-sync.json').read_text())
 def test_failed_request_does_not_advance_watermark(self):
  with tempfile.TemporaryDirectory() as tmp:
   cfg=replace(load_config(),data_dir=Path(tmp)/'kb');storage=Storage(cfg.data_dir);storage.ensure_layout();index.init_schema(cfg.db_path)
   doc={'document_id':'doc_'+'A'*26,'revision':1,'title':'example','body':'original','summary':'','published_at':'','source_name':'test','source_url':'','industries':[],'companies':[]}
   with patch('app.mobile_sync.records',return_value=iter([doc])):
    with self.assertRaises(RuntimeError):sync_once(cfg,storage,'https://example.com','p'*40,httpx.MockTransport(lambda r:httpx.Response(500)))
   self.assertFalse(storage.path('jobs/mobile-sync.json').exists())

 def test_company_codes_use_local_catalog_and_leave_ambiguities_unbound(self):
  from app.securities import Securities
  from app.mobile_sync import records
  from app.storage import atomic_write_json
  with tempfile.TemporaryDirectory() as tmp:
   cfg=replace(load_config(),data_dir=Path(tmp)/'kb');storage=Storage(cfg.data_dir);storage.ensure_layout();index.init_schema(cfg.db_path)
   body='合成沪股、合成港股、同名公司和未上市企业参加交流。'
   file=storage.path('inbox/example.jsonl');file.write_text(json.dumps({'schema_version':1,'title':'代码匹配测试','content_text':body,'source_platform':'manual','source_item_id':'demo-codes','content_type':'research_note'})+'\n');Pipeline(cfg,storage).import_file(file)
   with index.connect(cfg.db_path) as conn:row=conn.execute('SELECT document_id,current_revision FROM documents').fetchone()
   atomic_write_json(storage.path(f"derived/summaries/{row['document_id']}.json"),{'revision':row['current_revision'],'stocks':[{'name':name,'evidence':body} for name in ['合成沪股','合成港股','同名公司','未上市企业']]})
   catalog=Securities(storage);catalog.ingest([{'category':'A股','code':'600001','zwjc':'合成沪股'},{'category':'A股','code':'600002','zwjc':'同名公司'}]);catalog.ingest_hk([{'code':'00123','name':'合成港股'},{'code':'00124','name':'同名公司'}])
   with patch('app.llm.ReceiptClient.call',side_effect=AssertionError('no model')),patch('httpx.get',side_effect=AssertionError('no network')):
    record=next(records(cfg,storage))
   refs={s['name']:s for s in record['company_securities']}
   self.assertEqual(refs['合成沪股']['security_id'],'sh600001');self.assertEqual(refs['合成港股']['code'],'00123')
   self.assertNotIn('同名公司',refs);self.assertNotIn('未上市企业',refs);self.assertIn('未上市企业',record['companies']);self.assertEqual(record['body'],body+'\n')
