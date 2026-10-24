import tempfile,unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import httpx
from app.config import load_config
from app.storage import Storage
from app.pipeline import Pipeline
from app import index
from app.international_sources import checked_url,public_records,import_reports,sync_public,states

HTML='<a href="/insights/articles/test-research">A public research article title</a><a href="/insights/articles/test-research">Duplicate article title to ignore</a><a href="https://evil.test/insights/articles/other">Foreign article title to exclude</a>'
class InternationalSourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.cfg=replace(load_config(),data_dir=Path(self.tmp.name)/'kb');self.storage=Storage(self.cfg.data_dir);self.storage.ensure_layout();index.init_schema(self.cfg.db_path);self.pipeline=Pipeline(self.cfg,self.storage)
    def tearDown(self):self.tmp.cleanup()
    def test_first_party_public_index_and_duplicate_imports(self):
        rows=public_records('goldman_sachs',HTML)
        self.assertEqual(len(rows),1);self.assertIsNone(rows[0]['published_at'])
        first=import_reports(self.pipeline,'goldman_sachs',rows);second=import_reports(self.pipeline,'goldman_sachs',rows)
        self.assertEqual(first['created'],1);self.assertEqual(second['created'],0)
        manifest=next(self.storage.iter_manifests());self.assertEqual(manifest['fields']['source_platform'],'goldman_sachs')
        raw=self.storage.read_revision_text(manifest['revisions'][0]['archive_path'])
        self.assertIn('公开索引（非全文）',raw);self.assertNotIn('2026-10-',str(manifest['fields'].get('published_at')))
    def test_rss_date_and_official_url_validation(self):
        rows=public_records('bloomberg','<rss><channel><item><title>Market news</title><link>https://www.bloomberg.com/news/articles/example</link><pubDate>Fri, 23 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>')
        self.assertTrue(rows[0]['published_at'].startswith('2026-10-23'))
        for url in ['http://www.goldmansachs.com/a','https://goldmansachs.com.evil.test/a','https://127.0.0.1/a','https://www.goldmansachs.com/a?token=secret','https://user@www.goldmansachs.com/a']:
            with self.assertRaises(ValueError):checked_url('goldman_sachs',url)
    def test_failed_sync_keeps_previous_success_and_restricted_adapter_is_explicit(self):
        sync_public(self.pipeline,'goldman_sachs',httpx.MockTransport(lambda r:httpx.Response(200,text=HTML)))
        before=states(self.storage)['goldman_sachs']['last_success_at']
        with self.assertRaises(ValueError):sync_public(self.pipeline,'goldman_sachs',httpx.MockTransport(lambda r:httpx.Response(403)))
        self.assertEqual(states(self.storage)['goldman_sachs']['last_success_at'],before)
        self.assertEqual(states(self.storage)['goldman_sachs']['status'],'failed')
        with self.assertRaises(ValueError):sync_public(self.pipeline,'jpmorgan')
    def test_supplied_text_requires_correct_label_and_api_is_origin_protected(self):
        from fastapi.testclient import TestClient
        from app.web import app as web
        payload={'reports':[{'title':'Exported report','url':'https://www.jpmorgan.com/research/report','coverage':'supplied_text','text':'Externally supplied original research body.'}]}
        with patch.object(web,'storage',self.storage),patch.object(web,'pipeline',self.pipeline),patch.object(web,'_conn',side_effect=lambda:index.connect(self.cfg.db_path)):
            client=TestClient(web.app)
            self.assertEqual(client.post('/api/v1/international/jpmorgan/reports',json=payload).status_code,200)
            self.assertEqual(client.post('/api/v1/international/jpmorgan/reports',json=payload,headers={'Origin':'https://foreign.example'}).status_code,403)
            response=client.get('/international');self.assertEqual(response.status_code,200);self.assertIn('官方研报API：未连接',response.text)
        payload['reports'][0]['coverage']='public_index'
        with self.assertRaises(ValueError):import_reports(self.pipeline,'jpmorgan',payload['reports'])
