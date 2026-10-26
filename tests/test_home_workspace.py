import json,tempfile,unittest
from pathlib import Path
from dataclasses import replace
from datetime import datetime
from app.home_workspace import collection_status
from app.storage import Storage,atomic_write_json
from app.config import load_config
from app.pipeline import Pipeline
from app import index
from app.utils import TZ

class HomeWorkspaceTests(unittest.TestCase):
 def test_collection_health_never_confuses_configured_polling_with_success(self):
  with tempfile.TemporaryDirectory() as tmp:
   st=Storage(Path(tmp));st.ensure_layout();now=datetime(2026,10,26,10,0,tzinfo=TZ)
   self.assertEqual(collection_status(st,now)['label'],'请添加信源')
   atomic_write_json(st.path('catalog/research-settings.json'),{'poll_enabled':True,'poll_minutes':5})
   path=st.path('catalog/sources/zsxq_123.json');source={'name':'合成信源','status':'failed','message':'API 网络错误','token':'private-value'}
   atomic_write_json(path,source);result=collection_status(st,now);self.assertTrue(result['warning']);self.assertEqual(result['label'],'采集需要检查');self.assertNotIn('private-value',json.dumps(result))
   for state,stamp,warn in [('succeeded','2026-10-26T09:59:00+08:00',False),('succeeded','2026-10-26T09:00:00+08:00',True),('succeeded','',True),('partial','2026-10-26T09:59:00+08:00',True),('running','',False)]:
    atomic_write_json(path,{**source,'status':state,'last_synced_at':stamp});self.assertEqual(collection_status(st,now)['warning'],warn)
 def test_new_collection_count_excludes_old_documents_updated_today(self):
  with tempfile.TemporaryDirectory() as tmp:
   cfg=replace(load_config(),data_dir=Path(tmp)/'kb');st=Storage(cfg.data_dir);st.ensure_layout();index.init_schema(cfg.db_path)
   f=st.path('inbox/test.jsonl');f.write_text('\n'.join(json.dumps({'schema_version':1,'title':'合成资料'+str(n),'content_text':'完整的合成正文'+str(n),'source_platform':'manual','source_item_id':str(n),'content_type':'research_note'}) for n in range(2)));Pipeline(cfg,st).import_file(f)
   with index.connect(cfg.db_path) as conn:
    ids=[r[0] for r in conn.execute('SELECT document_id FROM documents ORDER BY document_id')]
    conn.execute("UPDATE documents SET imported_at='2026-10-26T09:00:00+08:00',first_imported_at='2026-10-25T09:00:00+08:00'")
    conn.execute("UPDATE documents SET first_imported_at='2026-10-26T09:00:00+08:00' WHERE document_id=?",(ids[0],));conn.commit()
    stats=index.stats(conn,'2026-10-26');self.assertEqual(stats['imported_today'],2);self.assertEqual(stats['first_imported_today'],1)
    rows,total=index.list_documents(conn,date_field='first_imported_at',start='2026-10-26');self.assertEqual(total,1);self.assertEqual(rows[0]['document_id'],ids[0])
    conn.execute('DELETE FROM document_stocks');conn.execute('DELETE FROM documents');conn.commit();empty=index.stats(conn,'2026-10-26');self.assertEqual(empty['first_imported_today'],0);self.assertEqual(empty['total'],0)
