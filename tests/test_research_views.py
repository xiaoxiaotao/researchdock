import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
from app.storage import Storage
from app.research_views import save,views,link,remove

class ResearchViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.storage=Storage(Path(self.tmp.name)/'kb',allow_create=True);self.storage.ensure_layout()
    def tearDown(self):self.tmp.cleanup()
    def test_roundtrip_and_duplicate(self):
        data={'name':'半导体未读','filters':{'industry':'半导体','q':'订单 & 现金流','unread':True,'dedup':True}}
        row=save(self.storage,data)
        self.assertEqual(save(self.storage,data)['id'],row['id'])
        self.assertEqual(len(views(self.storage)),1)
        query=parse_qs(urlsplit(link(row['filters'])).query)
        self.assertEqual(query['q'],['订单 & 现金流']);self.assertEqual(query['unread'],['true'])
        self.assertNotIn('page',query)
        remove(self.storage,row['id']);self.assertEqual(views(self.storage),[])
    def test_validation_and_url_allowlist(self):
        for data in [None,{'name':'','filters':{}},{'name':'x','filters':{'industry':'不存在'}},{'name':'x','filters':{'unread':'true'}},{'name':'x','filters':{'start':'2026-10-22','end':'2026-10-21'}}]:
            with self.assertRaises(ValueError):save(self.storage,data)
        row=save(self.storage,{'name':'<script>','filters':{'url':'https://foreign.example','page':9}})
        self.assertTrue(link(row['filters']).startswith('/reading?'));self.assertNotIn('foreign',link(row['filters']))
    def test_api_and_reading_render(self):
        from fastapi.testclient import TestClient
        from app.web import app as web
        with patch.object(web,'storage',self.storage),patch.object(web,'research',None):
            client=TestClient(web.app)
            r=client.post('/api/v1/research/views',json={'name':'我的订单','filters':{'q':'订单','dedup':True}})
            self.assertEqual(r.status_code,200)
            page=client.get('/reading');self.assertEqual(page.status_code,200);self.assertIn('我的订单',page.text);self.assertIn('0 篇未读',page.text)
            self.assertEqual(client.post('/api/v1/research/views',json=[],headers={'Origin':'https://foreign.example'}).status_code,403)
            self.assertEqual(client.post('/api/v1/research/views',json=[]).status_code,400)
            self.assertEqual(client.delete('/api/v1/research/views/'+r.json()['id']).status_code,200)
    def test_rolling_window_recalculates_and_clears_fixed_dates(self):
        from datetime import date
        from app.research_views import date_range
        row=save(self.storage,{'name':'七日未读','filters':{'days':7,'start':'2026-09-01','end':'2026-09-02'}})
        self.assertEqual(row['filters']['start'],'')
        self.assertEqual(date_range(row['filters'],date(2026,10,22)),('2026-10-16','2026-10-22'))
        self.assertEqual(date_range(row['filters'],date(2026,11,1)),('2026-10-26','2026-11-01'))
        for value in (True,1,8,'7',None):
            with self.assertRaises(ValueError):save(self.storage,{'name':'bad','filters':{'days':value}})
    def test_unread_count_matches_source_filters(self):
        from app.research_views import unread_counts,matches
        base={'title':'订单增长','industries':['半导体'],'reading_day':'2026-10-21','is_read':False}
        notes=[base,{**base,'is_read':True},{**base,'industries':['医药生物']},{**base,'reading_day':'日期未知'},{**base,'is_starred':True}]
        filters={'industry':'半导体','start':'2026-10-20','end':'2026-10-22','q':'订单','dedup':True}
        self.assertEqual(unread_counts(notes,[{'filters':filters}])[0]['unread_count'],2)
        self.assertEqual(unread_counts(notes,[{'filters':{**filters,'starred':True}}])[0]['unread_count'],1)
        self.assertFalse(matches(base,{**filters,'selected':True}))
    def test_rolling_query_is_kept_in_controls_and_pagination(self):
        from fastapi.testclient import TestClient
        from app.web import app as web
        with patch.object(web,'storage',self.storage),patch.object(web,'research',None):
            client=TestClient(web.app)
            response=client.get('/reading?days=7&unread=true&dedup=true')
            self.assertEqual(response.status_code,200)
            self.assertIn('name="days" value="7"',response.text)
            self.assertIn('&days=7',response.text)
            self.assertEqual(client.get('/reading?days=9').status_code,400)
            self.assertEqual(client.get('/reading?start=2026-10-22&end=2026-10-21').status_code,400)
