import json,sqlite3,tempfile,unittest
from pathlib import Path
from fastapi.testclient import TestClient
from app.mobile_cloud import create_app
P={'Authorization':'Bearer '+'p'*40};R={'Authorization':'Bearer '+'r'*40}
def doc(letter,body='只有正文出现的芯片订单增长，现金流仍有风险。',revision=1):return dict(document_id='doc_'+letter*26,revision=revision,title='研究纪要'+letter,body=body,published_at='2026-10-26T08:00:00+08:00',source_name='合成信源',companies=['示例公司'],industries=['半导体'])
def push(c,documents=[],deleted=[]):return c.post('/v1/sync',headers=P,json=dict(library_id='demo',documents=documents,deleted_ids=deleted))
class CatalogTests(unittest.TestCase):
 def test_fixed_snapshot_and_ordered_changes_with_edits_deletes_and_insertions(self):
  with tempfile.TemporaryDirectory() as t:
   c=TestClient(create_app(t,'p'*40,'r'*40));push(c,[doc('A'),doc('B'),doc('C')])
   page=c.get('/v1/catalog?limit=1',headers=R).json();cursor=page['cursor'];self.assertEqual(page['events'][0]['document']['revision'],1)
   push(c,[doc('B','修改后的新正文',2),doc('D')],[doc('C')['document_id']])
   records=page['events']
   while page['has_more']:
    page=c.get('/v1/catalog',headers=R,params=dict(limit=1,until=cursor,after_id=page['next_id'])).json();self.assertEqual(page['cursor'],cursor);records+=page['events']
   self.assertEqual([e['document_id'] for e in records],[doc(x)['document_id'] for x in 'ABC']);self.assertEqual(records[1]['document']['revision'],1);self.assertTrue(all('body' not in e['document'] for e in records))
   delta=c.get('/v1/catalog',headers=R,params=dict(mode='delta',after=cursor,limit=1)).json();watermark=delta['cursor'];changes=delta['events']
   push(c,[doc('E')])
   while delta['has_more']:
    delta=c.get('/v1/catalog',headers=R,params=dict(mode='delta',after=delta['next_after'],until=watermark,limit=1)).json();changes+=delta['events']
   self.assertEqual([e['document_id'] for e in changes],[doc(x)['document_id'] for x in 'BDC']);self.assertTrue(changes[-1]['deleted']);self.assertIsNone(changes[-1]['document'])
   last=c.get('/v1/catalog',headers=R,params=dict(mode='delta',after=watermark)).json();self.assertEqual(last['events'][0]['document_id'],doc('E')['document_id'])
 def test_search_finds_unanalysed_body_literal_two_chars_and_filters(self):
  with tempfile.TemporaryDirectory() as t:
   c=TestClient(create_app(t,'p'*40,'r'*40));self.assertEqual(c.get('/v1/search?q=订单').status_code,401);push(c,[doc('A'),doc('B','100%_中文及AAPL literal "quote"')])
   for q in ['芯片订单','订单','100%_','AAPL','"quote"']:
    response=c.get('/v1/search',headers=R,params={'q':q});self.assertEqual(response.status_code,200,response.text);data=response.json();self.assertTrue(data['results'],q);self.assertEqual(data['model_requests'],0);self.assertNotIn('body',data['results'][0]['document'])
   r=c.get('/v1/search',headers=R,params=dict(q='订单',company='示例公司',industry='半导体',source='合成信源')).json()['results'][0];self.assertEqual(r['match_field'],'body');self.assertEqual(r['snippet'][r['match_start']:r['match_end']],'订单')
   self.assertFalse(c.get('/v1/search',headers=R,params=dict(q='订单',company='不存在')).json()['results'])
   push(c,[doc('A','已修订，旧关键词不再存在',2)])
   self.assertFalse(c.get('/v1/search',headers=R,params=dict(q='订单')).json()['results']);push(c,deleted=[doc('B')['document_id']]);self.assertFalse(c.get('/v1/search?q=AAPL',headers=R).json()['results'])
   self.assertEqual(c.get('/v1/catalog').status_code,401);self.assertEqual(c.get('/v1/catalog?mode=delta&after=999',headers=R).status_code,409)
 def test_legacy_migration_requires_old_cursors_to_bootstrap(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'reader.sqlite3'
   with sqlite3.connect(p) as db:
    db.executescript('CREATE TABLE changes(sequence INTEGER PRIMARY KEY AUTOINCREMENT,document_id TEXT); CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE documents(id TEXT PRIMARY KEY,revision INTEGER,payload TEXT,digest TEXT,sequence INTEGER);')
    d=doc('A');db.execute('INSERT INTO changes(document_id) VALUES(?)',(d['document_id'],));db.execute('INSERT INTO documents VALUES(?,?,?,?,?)',(d['document_id'],1,json.dumps(d),'legacy',1))
   c=TestClient(create_app(t,'p'*40,'r'*40));self.assertEqual(c.get('/v1/catalog?mode=delta&after=0',headers=R).status_code,409)
   page=c.get('/v1/catalog',headers=R).json();self.assertEqual(page['events'][0]['document']['document_id'],d['document_id']);self.assertNotIn('body',page['events'][0]['document'])
   self.assertTrue(c.get('/v1/search?q=订单',headers=R).json()['results'])
   push(c,[doc('B')]);self.assertEqual(len(c.get('/v1/catalog?mode=delta&after=1',headers=R).json()['events']),1)
 def test_older_writer_after_rollback_rebuilds_index_and_resets_floor(self):
  with tempfile.TemporaryDirectory() as t:
   c=TestClient(create_app(t,'p'*40,'r'*40));push(c,[doc('A')]);c.get('/v1/catalog',headers=R)
   updated=doc('A','回退版本写入的全新正文',2)
   with sqlite3.connect(Path(t)/'reader.sqlite3') as db:
    seq=db.execute('INSERT INTO changes(document_id) VALUES(?)',(updated['document_id'],)).lastrowid;db.execute('UPDATE documents SET payload=?,sequence=?,revision=2 WHERE id=?',(json.dumps(updated),seq,updated['document_id']))
   self.assertEqual(c.get('/v1/catalog?mode=delta&after=1',headers=R).status_code,409)
   self.assertTrue(c.get('/v1/search',headers=R,params={'q':'全新正文'}).json()['results']);self.assertFalse(c.get('/v1/search',headers=R,params={'q':'芯片订单'}).json()['results'])
 def test_literal_operators_and_unicode_offsets_do_not_change_query_scope(self):
  with tempfile.TemporaryDirectory() as t:
   c=TestClient(create_app(t,'p'*40,'r'*40));push(c,[doc('A','😀风险提示：芯片订单可能变化。A OR B只是原文中的字面内容。')])
   result=c.get('/v1/search',headers=R,params={'q':'芯片订单'}).json();hit=result['results'][0];self.assertEqual(hit['snippet'][hit['match_start']:hit['match_end']],'芯片订单');self.assertEqual(result['offset_encoding'],'unicode_codepoints')
   self.assertEqual(len(c.get('/v1/search',headers=R,params={'q':'A OR B'}).json()['results']),1)
   self.assertEqual(c.get('/v1/search',headers=R,params={'q':'订单','limit':0}).status_code,422);self.assertIn('no-store',c.get('/v1/search',headers=R,params={'q':'订单'}).headers['cache-control'])
