import json,tempfile,unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from app.config import load_config
from app.storage import Storage,atomic_write_json
from app.pipeline import Pipeline
from app import index
from app.mobile_sync import records,sync_once
from app.mobile_editorial import source_health,presentation
from app.mobile_cloud import create_app
P='p'*40;R='r'*40
class WorkspaceTests(unittest.TestCase):
 def setup_library(self,tmp):
  cfg=replace(load_config(),data_dir=Path(tmp)/'kb');st=Storage(cfg.data_dir);st.ensure_layout();index.init_schema(cfg.db_path)
  f=st.path('inbox/sample.jsonl');f.write_text(json.dumps({'schema_version':1,'title':'合成研究','content_text':'只使用已归档原文，不调用模型。','source_platform':'manual','source_item_id':'workspace-test','content_type':'research_note'})+'\n');Pipeline(cfg,st).import_file(f)
  return cfg,st
 def test_current_analysis_preserves_points_and_stale_revision_is_not_exported(self):
  with tempfile.TemporaryDirectory() as tmp:
   cfg,st=self.setup_library(tmp);d=next(records(cfg,st));path=st.path('derived/summaries/'+d['document_id']+'.json')
   atomic_write_json(path,dict(revision=d['revision'],summary='既有摘要',key_points=['原有观点一','原有观点二'],risks=['原有风险']))
   with patch('app.llm.ReceiptClient.call',side_effect=AssertionError('no model')):current=next(records(cfg,st))
   self.assertEqual(current['key_points'],['原有观点一','原有观点二']);self.assertEqual(current['risks'],['原有风险']);self.assertEqual(current['analysis_revision'],d['revision']);self.assertTrue(current['first_imported_at'])
   atomic_write_json(path,dict(revision=d['revision']+1,summary='不匹配摘要',key_points=['不匹配观点'],risks=['不匹配风险']))
   stale=next(records(cfg,st));self.assertEqual(stale['key_points'],[]);self.assertEqual(stale['risks'],[]);self.assertEqual(stale['analysis_revision'],0)
 def test_attachment_card_classification_keeps_original_title_and_no_fabricated_body(self):
  row={'title':'「文件」','current_revision':1,'first_imported_at':'2026-10-24T23:00:00+08:00'};items=[{'name':'合成.pdf'}]
  result=presentation(row,'此主题仅含附件，附件清单已登记，原件请到知识星球查看。',items,{})
  self.assertEqual(result['content_kind'],'attachment_only');self.assertEqual(result['display_title'],'合成.pdf');self.assertEqual(row['title'],'「文件」');self.assertEqual(result['first_imported_at'],row['first_imported_at']);self.assertEqual(presentation({**row,'title':'短消息'},'明确的简短原文',[],{})['content_kind'],'brief')
 def test_health_whitelists_fields_and_reports_partial_or_failure(self):
  with tempfile.TemporaryDirectory() as tmp:
   cfg,st=self.setup_library(tmp);atomic_write_json(st.path('catalog/research-settings.json'),{'poll_enabled':True,'poll_minutes':5});atomic_write_json(st.path('catalog/sources/zsxq_123.json'),{'group_id':'123','name':'合成信源','status':'failed','last_synced_at':'2026-10-25T09:00:00+08:00','message':'secret signed url','token':'do-not-copy'})
   h=source_health(st);self.assertEqual(h['sources'][0]['status'],'failed');self.assertNotIn('secret',json.dumps(h));self.assertNotIn('token',json.dumps(h));self.assertEqual(h['poll_minutes'],5)
 def test_health_auth_and_heartbeat_does_not_create_research(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=TestClient(create_app(tmp,P,R));push={'Authorization':'Bearer '+P};read={'Authorization':'Bearer '+R}
   report={'reported_at':'2026-10-25T09:00:00+08:00','poll_enabled':True,'poll_minutes':5,'sources':[{'name':'合成信源','status':'failed','last_success_at':'2026-10-25T08:00:00+08:00'}]}
   self.assertEqual(c.post('/v1/source-health',headers=read,json=report).status_code,401);self.assertEqual(c.post('/v1/source-health',headers=push,json=report).status_code,200)
   state=c.get('/v1/status',headers=read).json();self.assertEqual(state['cursor'],0);self.assertEqual(state['source_health']['sources'][0]['status'],'failed');self.assertTrue(state['health_received_at'])
   self.assertEqual(c.post('/v1/source-health',headers=push,json={**report,'api_key':'never'}).status_code,422)
   self.assertEqual(c.post('/v1/source-health',headers=push,json={**report,'padding':'x'*128000}).status_code,413)
   self.assertEqual(c.post('/v1/source-health',content=b'not-json').status_code,401)
   doc=dict(document_id='doc_'+'A'*26,revision=1,title='合成',body='原文',key_points=['观点'],risks=['风险'],analysis_revision=2)
   self.assertEqual(c.post('/v1/sync',headers=push,json={'library_id':'test','documents':[doc]}).status_code,422)
 def test_unchanged_documents_still_publish_source_failure_without_advancing_cursor(self):
  with tempfile.TemporaryDirectory() as tmp:
   cfg,st=self.setup_library(tmp);c=TestClient(create_app(Path(tmp)/'cloud',P,R));read={'Authorization':'Bearer '+R}
   def transport(req):
    r=c.post(req.url.path,content=req.content,headers=dict(req.headers));return httpx.Response(r.status_code,json=r.json())
   sync_once(cfg,st,'https://example.com',P,httpx.MockTransport(transport));before=c.get('/v1/status',headers=read).json()['cursor']
   atomic_write_json(st.path('catalog/sources/zsxq_123.json'),{'group_id':'123','name':'合成信源','status':'failed'})
   self.assertEqual(sync_once(cfg,st,'https://example.com',P,httpx.MockTransport(transport))['sent'],0)
   state=c.get('/v1/status',headers=read).json();self.assertEqual(state['cursor'],before);self.assertEqual(state['source_health']['sources'][0]['status'],'failed')
