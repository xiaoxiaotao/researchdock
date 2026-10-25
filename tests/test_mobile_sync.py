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
