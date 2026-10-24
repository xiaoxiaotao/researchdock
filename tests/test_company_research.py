import tempfile
import unittest
from pathlib import Path
from app.storage import Storage,atomic_write_json
from app.company_research import merge,resolve,identities,save_note,journal

class CompanyResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Storage(Path(self.tmp.name)/'kb',allow_create=True);self.s.path('catalog').mkdir(parents=True,exist_ok=True)
    def tearDown(self):self.tmp.cleanup()
    def test_links_chain_without_cycles(self):
        merge(self.s,'a','b',{'a','b','c'});merge(self.s,'b','c',{'a','b','c'})
        self.assertEqual(resolve('a',identities(self.s)),'c')
        with self.assertRaises(ValueError):merge(self.s,'c','a',{'a','b','c'})
        links=identities(self.s);links.pop('b');atomic_write_json(self.s.path('catalog/company-identities.json'),links)
        self.assertEqual(resolve('a',identities(self.s)),'b')
    def test_journal_validates_source_and_keeps_original_text(self):
        note=save_note(self.s,'a',{'text':'我的观点 <script>','topic':'待验证','document_id':'doc1'},{'a'},{'doc1'})
        self.assertEqual(journal(self.s)[note['id']]['text'],'我的观点 <script>')
        with self.assertRaises(ValueError):save_note(self.s,'a',{'text':'abc','document_id':'other'},{'a'},{'doc1'})
        with self.assertRaises(ValueError):save_note(self.s,'a',{'text':'','topic':'订单'},{'a'},set())

    def test_journal_api_create_hide_and_restore(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from fastapi.testclient import TestClient
        from app.web import app as web
        import threading
        fake=SimpleNamespace(lock=threading.RLock())
        publication=SimpleNamespace(stock_timeline=lambda key:{'stock':{'stock_id':'a'},'entries':[{'document_id':'doc1','revision':1}]} if key=='a' else None)
        with patch.object(web,'storage',self.s),patch.object(web,'research',fake),patch.object(web,'Publications',return_value=publication):
            client=TestClient(web.app)
            r=client.post('/api/v1/stocks/a/notes',json={'text':'追踪订单兑现情况','topic':'订单','document_id':'doc1'})
            self.assertEqual(r.status_code,200)
            key=r.json()['id']
            self.assertEqual(client.post('/api/v1/stocks/notes/'+key+'/visibility',json={'deleted':True}).status_code,200)
            self.assertTrue(journal(self.s)[key]['deleted'])
            client.post('/api/v1/stocks/notes/'+key+'/visibility',json={'deleted':False})
            self.assertFalse(journal(self.s)[key]['deleted'])
            self.assertEqual(client.post('/api/v1/stocks/a/notes',json={'text':'其他公司资料','document_id':'doc2'}).status_code,400)
            self.assertEqual(client.post('/api/v1/stocks/a/notes',headers={'Origin':'https://foreign.example'},json={'text':'abc'}).status_code,403)

    def test_question_history_requires_source_and_reopens_without_rewriting_original(self):
        from app.company_research import update_question
        note=save_note(self.s,'a',{'text':'订单能否兑现？','topic':'待验证'},{'a'},{'doc1'},known_versions={'doc1':1})
        with self.assertRaises(ValueError):update_question(self.s,note['id'],{'state':'supported','conclusion':'已看到证据','document_ids':[]},{'doc1'})
        with self.assertRaises(ValueError):update_question(self.s,note['id'],{'state':'supported','conclusion':'已看到证据','document_ids':['other']},{'doc1'})
        update_question(self.s,note['id'],{'state':'supported','conclusion':'原文披露了已验收订单','document_ids':['doc1']},{'doc1'})
        update_question(self.s,note['id'],{'state':'open','conclusion':'需要继续跟踪回款','document_ids':[]},{'doc1'})
        saved=journal(self.s)[note['id']]
        self.assertEqual(saved['text'],'订单能否兑现？')
        self.assertEqual(saved['question_state'],'open')
        self.assertEqual(len(saved['question_history']),2)
        self.assertEqual(saved['known_document_versions'],{'doc1':1})
