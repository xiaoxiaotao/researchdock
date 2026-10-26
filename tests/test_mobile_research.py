import json,tempfile,unittest,uuid
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.config import load_config
from app.storage import Storage,atomic_write_json
from app.pipeline import Pipeline
from app import index
from app.mobile_cloud import create_app
from app.research_assistant import prepare,generate,validate
from app.utils import now_iso
P={'Authorization':'Bearer '+'p'*40};R={'Authorization':'Bearer '+'r'*40}
def req(**kw):return dict(request_id=uuid.uuid4().hex,question='调研半导体行业近期需求和风险',target='半导体',kind='industry',days=30,**kw)
class Model:
 document_ids=[]
 def __init__(self):self.calls=0;self.invalid=False
 def settings(self):return {'model':'test'}
 def call(self,*a,**kw):
  self.calls+=1
  return {'title':'研究报告','sections':[{'title':'结论摘要','items':[{'text':'来源认为需求有变化，仍需核实。','citations':['E1']}]}]}
 def invalidate(self,*a):self.invalid=True
class QueueTests(unittest.TestCase):
 def test_roles_quota_idempotence_and_lease(self):
  with tempfile.TemporaryDirectory() as t:
   c=TestClient(create_app(t,'p'*40,'r'*40));q=req()
   self.assertEqual(c.get('/v1/research/tasks').status_code,401)
   self.assertEqual(c.get('/v1/research/tasks',headers=R).headers['Cache-Control'],'private, no-store')
   self.assertEqual(c.post('/v1/research/config',headers=R,json={'enabled':True,'daily_limit':2}).status_code,401)
   self.assertEqual(c.post('/v1/research/tasks',headers=R,json=q).status_code,403)
   self.assertEqual(c.post('/v1/research/config',headers=P,json={'enabled':True,'daily_limit':2}).status_code,200)
   self.assertEqual(c.post('/v1/research/tasks',headers=R,json=q).status_code,200)
   self.assertEqual(c.post('/v1/research/tasks',headers=R,json=q).json()['id'],q['request_id'])
   self.assertEqual(c.post('/v1/research/tasks',headers=R,json={**q,'question':'其他问题'}).status_code,409)
   self.assertEqual(c.post('/v1/research/claim',headers=R).status_code,401)
   task=c.post('/v1/research/claim',headers=P).json()['task'];self.assertIsNone(c.post('/v1/research/claim',headers=P).json()['task'])
   out={'lease':'wrong','status':'completed','message':'done','report':{'target':'半导体','kind':'industry','days':30}}
   self.assertEqual(c.post('/v1/research/tasks/'+task['id']+'/complete',headers=P,json=out).status_code,409)
   out['lease']=task['lease'];self.assertEqual(c.post('/v1/research/tasks/'+task['id']+'/complete',headers=P,json=out).status_code,200)
   parent=req(parent_id=task['id']);parent.update(target='',kind='auto',days=0)
   self.assertEqual(c.post('/v1/research/tasks',headers=R,json=parent).json()['target'],'半导体')
   self.assertEqual(c.post('/v1/research/tasks',headers=R,json=parent).status_code,200)
   self.assertEqual(c.post('/v1/research/tasks',headers=R,json=req()).status_code,429)
   self.assertNotIn('lease',c.get('/v1/research/tasks/'+task['id'],headers=R).text)
 def test_limits_and_expired_claim(self):
  import sqlite3
  with tempfile.TemporaryDirectory() as t:
   c=TestClient(create_app(t,'p'*40,'r'*40));c.post('/v1/research/config',headers=P,json={'enabled':True,'daily_limit':10})
   self.assertEqual(c.post('/v1/research/tasks',headers=R,content='x'*9000).status_code,413)
   self.assertEqual(c.post('/v1/research/tasks',headers=R,json={**req(),'days':True}).status_code,422)
   for n in range(3):self.assertEqual(c.post('/v1/research/tasks',headers=R,json=req()).status_code,200)
   self.assertEqual(c.post('/v1/research/tasks',headers=R,json=req()).status_code,429)
   first=c.post('/v1/research/claim',headers=P).json()['task']
   with sqlite3.connect(Path(t)/'reader.sqlite3') as db:db.execute("UPDATE research_tasks SET lease_until='2000-01-01' WHERE id=?",(first['id'],))
   again=c.post('/v1/research/claim',headers=P).json()['task'];self.assertEqual(again['id'],first['id']);self.assertNotEqual(again['lease'],first['lease'])
class EvidenceTests(unittest.TestCase):
 def setup_library(self,t,body='半导体行业需求增长，来源认为订单改善但价格竞争仍是风险，需要结合后续实际收入验证。',date=None):
  cfg=replace(load_config(),data_dir=Path(t)/'kb');st=Storage(cfg.data_dir);st.ensure_layout();index.init_schema(cfg.db_path)
  f=st.path('inbox/research.jsonl');f.write_text(json.dumps({'schema_version':1,'title':'半导体需求观察','content_text':body,'published_at':date or now_iso(),'source_platform':'manual','source_item_id':'research-test','content_type':'research_note'},ensure_ascii=False)+'\n');Pipeline(cfg,st).import_file(f)
  return cfg,st,body
 def test_exact_quotes_reuse_and_no_model_on_no_evidence(self):
  with tempfile.TemporaryDirectory() as t:
   cfg,st,body=self.setup_library(t);q=req();prepared=prepare(cfg,st,q)
   self.assertTrue(prepared['evidence']);e=prepared['evidence'][0];self.assertEqual(body[e['offset']:e['offset']+len(e['quote'])],e['quote'])
   model=Model();a=generate(cfg,st,{'id':uuid.uuid4().hex,'request':q},model);self.assertEqual(a['status'],'completed');self.assertEqual(model.calls,1)
   b=generate(cfg,st,{'id':uuid.uuid4().hex,'request':q},model);self.assertTrue(b['report']['reused']);self.assertEqual(model.calls,1)
   no=generate(cfg,st,{'id':uuid.uuid4().hex,'request':{**q,'target':'没有资料的行业'}},model);self.assertEqual(no['status'],'no_evidence');self.assertEqual(model.calls,1)
 def test_old_date_and_ambiguous_question(self):
  with tempfile.TemporaryDirectory() as t:
   cfg,st,_=self.setup_library(t,date='2020-01-01T10:00:00+08:00');model=Model()
   self.assertFalse(prepare(cfg,st,req())['evidence'])
   r=generate(cfg,st,{'id':uuid.uuid4().hex,'request':{**req(),'question':'帮我调研一下','target':'','kind':'auto'}},model);self.assertEqual(r['status'],'needs_input');self.assertEqual(model.calls,0)
 def test_reject_invented_citations_and_uncited_claims(self):
  for citations in (['E99'],[],['https://evil.example']):
   with self.assertRaises(ValueError):validate({'title':'报告','sections':[{'title':'结论摘要','items':[{'text':'陈述','citations':citations}]}]},[{'id':'E1'}])
  self.assertTrue(validate({'title':'报告','sections':[{'title':'资料缺口与后续跟踪','items':[{'text':'缺少现金流数据','citations':[]}]}]},[]))
 def test_attachment_only_and_current_revision_guard(self):
  with tempfile.TemporaryDirectory() as t:
   cfg,st,_=self.setup_library(t,body='此主题仅含附件，附件清单已登记，原件请到知识星球查看。')
   with index.connect(cfg.db_path) as db:db.execute("UPDATE documents SET title='半导体附件'")
   r=prepare(cfg,st,req());self.assertEqual(r['scope']['attachment_documents'],1);self.assertFalse(r['evidence'])
  with tempfile.TemporaryDirectory() as t:
   cfg,st,_=self.setup_library(t)
   with index.connect(cfg.db_path) as db:db.execute("UPDATE document_search SET body='半导体行业需求此处与原始存档不一致，不可以生成引句。'")
   self.assertFalse(prepare(cfg,st,req())['evidence'])
 def test_narrow_industry_does_not_expand_to_all_energy(self):
  from app.research_assistant import resolve_target
  with tempfile.TemporaryDirectory() as t:
   cfg,st,_=self.setup_library(t)
   target,kind,terms,_=resolve_target(st,[],{},{**req(),'target':'光伏'})
   self.assertEqual(terms,['光伏']);self.assertNotIn('风电',terms)
 def test_invalid_model_result_is_durable_without_automatic_retry(self):
  with tempfile.TemporaryDirectory() as t:
   cfg,st,_=self.setup_library(t);model=Model();task={'id':uuid.uuid4().hex,'request':req()}
   with patch.object(model,'call',return_value={'title':'不合规','sections':[]}):
    first=generate(cfg,st,task,model);self.assertEqual(first['status'],'failed');self.assertTrue(model.invalid)
   self.assertTrue(st.path('jobs/research-assistant/'+task['id']+'-invalid.json').exists())
   self.assertEqual(generate(cfg,st,task,model),first);self.assertEqual(model.calls,0)
class WorkerTests(unittest.TestCase):
 def test_execution_is_nonblocking_and_delivers_after_completion(self):
  import threading,time,httpx
  from app.research_worker import BackgroundResearch
  with tempfile.TemporaryDirectory() as t:
   cfg=replace(load_config(),data_dir=Path(t)/'kb');st=Storage(cfg.data_dir);st.ensure_layout();started=threading.Event();release=threading.Event();posted=[];claims=[{'id':'a'*32,'lease':'x','request':req()},None]
   def transport(r):
    if r.url.path.endswith('/config'):return httpx.Response(200,json={'accepted':True})
    if r.url.path.endswith('/claim'):return httpx.Response(200,json={'task':claims.pop(0) if claims else None})
    posted.append(json.loads(r.content));return httpx.Response(200,json={'accepted':True})
   def work(*a):started.set();release.wait(2);return dict(status='no_evidence',message='none',report=None)
   with patch('app.research_worker.generate',side_effect=work):
    w=BackgroundResearch(cfg,st,'https://example.com','p'*40,transport=httpx.MockTransport(transport))
    try:
     before=time.monotonic();w.tick();self.assertLess(time.monotonic()-before,.5);self.assertTrue(started.wait(1));w.tick();self.assertFalse(posted);release.set();w.current[1].result(timeout=2);w.tick();self.assertEqual(posted[0]['status'],'no_evidence');self.assertIsNone(w.current)
    finally:release.set();w.close()

class EntityTests(unittest.TestCase):
 def test_hk_and_us_codes_resolve_to_canonical_names_without_short_ticker_noise(self):
  from app.securities import Securities,normalized
  from app.research_assistant import resolve_target
  with tempfile.TemporaryDirectory() as t:
   cfg,st,_=EvidenceTests().setup_library(t);master=Securities(st)
   with master.connect() as db:
    for code,exchange,name in [('00700','hk','腾讯控股'),('AAPL','us','苹果'),('ON','us','安森美')]:
     sid=exchange+code;db.execute('INSERT INTO securities VALUES(?,?,?,?,?,?,?,?,1)',(sid,code,exchange,name,'',None,'synthetic',now_iso()));db.execute('INSERT INTO security_names VALUES(?,?,?,?,?)',(sid,name,normalized(name),now_iso(),now_iso()))
   for code,name in [('00700.HK','腾讯控股'),('AAPL.US','苹果'),('ON','安森美')]:
    target,kind,terms,security=resolve_target(st,[],{},{**req(),'target':code,'kind':'company'})
    self.assertEqual(target,name);self.assertIn(name,terms);self.assertNotIn('ON',terms)
 def test_compound_ai_topic_is_not_broadened_to_entire_ai_industry(self):
  from app.research_assistant import resolve_target
  with tempfile.TemporaryDirectory() as t:
   cfg,st,_=EvidenceTests().setup_library(t)
   target,kind,terms,_=resolve_target(st,[],{},{**req(),'question':'研究一下最近 AI 眼镜的发展方向','target':'','kind':'auto'})
   self.assertEqual(target,'AI眼镜');self.assertEqual(kind,'industry');self.assertNotIn('人工智能',terms);self.assertIn('智能眼镜',terms)
 def test_unsupported_row_is_removed_instead_of_displayed_or_reinferred(self):
  result=validate({'title':'报告','sections':[{'title':'结论摘要','items':[{'text':'有来源的陈述','citations':['E1']}]},{'title':'财务信息','items':[{'text':'没有引用的陈述，不能让用户当成事实','citations':[]}]}]},[{'id':'E1'}])
  self.assertEqual(result['omitted_uncited_items'],1);self.assertEqual(len(result['sections']),1);self.assertNotIn('没有引用的陈述',json.dumps(result,ensure_ascii=False))

class DisableTests(unittest.TestCase):
 def test_disabling_worker_disables_submissions_without_model_access(self):
  import httpx
  from app.research_worker import disable_research
  with tempfile.TemporaryDirectory() as t:
   c=TestClient(create_app(t,'p'*40,'r'*40));c.post('/v1/research/config',headers=P,json={'enabled':True,'daily_limit':10})
   def transport(r):
    response=c.post(r.url.path,content=r.content,headers=dict(r.headers));return httpx.Response(response.status_code,json=response.json())
   with patch('app.llm.ReceiptClient.call',side_effect=AssertionError('no model')):disable_research('https://example.com','p'*40,httpx.MockTransport(transport))
   self.assertFalse(c.get('/v1/research/tasks',headers=R).json()['config']['enabled']);self.assertEqual(c.post('/v1/research/tasks',headers=R,json=req()).status_code,403)
