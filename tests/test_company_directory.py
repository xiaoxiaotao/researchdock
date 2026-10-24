import unittest
from app.company_directory import directory

class CompanyDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.rows=[{'stock_id':'a','name':'公司甲','catalog_code':'002353','security':{'pinyin':'gsj'},'document_ids':{'d1','d2'},'doc_count':2,'industries':['机械设备'],'last_at':'2026-10-21','member_ids':['old-a']},{'stock_id':'b','name':'公司乙','document_ids':{'d2','d3'},'doc_count':2,'industries':['半导体'],'last_at':'2026-10-22'},{'stock_id':'c','name':'无日期公司','document_ids':set(),'doc_count':0,'last_at':None}]
        self.states={'d2':{'read':True}}
    def test_counts_deduplicate_sources_and_follow_merged_member(self):
        result=directory(self.rows,self.states,['old-a'])
        self.assertEqual(result['stats'],{'companies':3,'documents':3,'unread':2,'followed':1})
        self.assertEqual(result['rows'][0]['stock_id'],'b')
        self.assertEqual(directory(self.rows,self.states,['old-a'],scope='followed')['rows'][0]['stock_id'],'a')
        self.assertNotIn('unread_count',self.rows[0])
    def test_search_filter_and_pagination_preserve_matching_scope(self):
        for q in ['002353','GSJ','公司甲']:
            self.assertEqual(directory(self.rows,self.states,[],q=q)['stats']['companies'],1)
        self.assertEqual(directory(self.rows,self.states,[],industry='半导体')['rows'][0]['stock_id'],'b')
        self.assertEqual(directory(self.rows,self.states,[],scope='unread')['stats']['companies'],2)
        result=directory(self.rows,self.states,[],page=99,size=2)
        self.assertEqual(result['page'],2);self.assertEqual(len(result['rows']),1)
        self.assertEqual(directory([],{},[])['pages'],1)
    def test_page_renders_filters_safe_names_and_validates_enums(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from types import SimpleNamespace
        from fastapi.testclient import TestClient
        from app.storage import Storage
        from app.web import app as web
        with tempfile.TemporaryDirectory() as tmp:
            storage=Storage(Path(tmp)/'kb',allow_create=True);storage.ensure_layout()
            rows=[{**self.rows[0],'name':'<script>bad</script>'}]
            with patch.object(web,'storage',storage),patch.object(web,'research',SimpleNamespace(reading_state=lambda:self.states)),patch.object(web,'Publications',return_value=SimpleNamespace(stocks=lambda:rows)):
                client=TestClient(web.app)
                response=client.get('/stocks?layout=list&sort=coverage')
                self.assertEqual(response.status_code,200)
                self.assertIn('&lt;script&gt;bad&lt;/script&gt;',response.text)
                self.assertIn('公司展示方式',response.text);self.assertIn('原文证据库',response.text)
                self.assertEqual(client.get('/stocks?scope=unknown').status_code,422)
                self.assertEqual(client.get('/stocks?layout=bad').status_code,422)
