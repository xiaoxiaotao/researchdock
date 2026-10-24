import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.evidence import Evidence,locate
from app.storage import Storage,atomic_write_text

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.storage=Storage(Path(self.tmp.name)/'kb',allow_create=True)
        self.storage.ensure_layout();self.store=Evidence(self.storage);self.doc='doc_'+'A'*26
        self.body='公司订单持续增长。\n\n经营现金流  同比改善，回款仍需观察。'
        self.raw='---\ntitle: 测试公司调研\npublished_at: 2026-10-21\n---\n'+self.body
        self.path='archive/test.md';atomic_write_text(self.storage.path(self.path),self.raw)
        self.patch=patch.object(self.storage,'read_manifest',return_value={'title':'测试公司调研','revisions':[{'revision':1,'archive_path':self.path}]});self.patch.start()
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def test_quote_uses_original_spacing_and_pinned_revision(self):
        quote='经营现金流 同比改善，回款仍需观察。'
        row,created=self.store.create(self.doc,1,{'quote':quote,'topic':'现金流','company_id':'a','note':'我的疑问'},{'a':'测试公司'})
        self.assertTrue(created)
        self.assertEqual(row['quote'],'经营现金流  同比改善，回款仍需观察。')
        self.assertEqual(self.body[row['start_offset']:row['end_offset']],row['quote'])
        self.assertEqual(self.store.get(row['id'])['revision'],1)
        _,again=self.store.create(self.doc,1,{'quote':quote,'topic':'现金流','company_id':'a','note':'我的疑问'},{'a':'测试公司'})
        self.assertFalse(again)
        self.assertEqual(len(self.store.list(company_ids={'a'})),1)
    def test_invented_quote_bad_revision_and_ambiguous_position_rejected(self):
        for quote,rev in [('公司利润增长100%',1),('公司订单持续增长。',2)]:
            with self.assertRaises(ValueError):self.store.create(self.doc,rev,{'quote':quote},{})
        with self.assertRaises(ValueError):locate('公司订单增长。公司订单增长。','公司订单增长。')
        with self.assertRaises(ValueError):locate('现金流  改善；现金流 改善','现金流 改善')
    def test_hidden_records_restore_without_deletion(self):
        row,_=self.store.create(self.doc,1,{'quote':'公司订单持续增长。','topic':'订单'},{})
        self.store.hide(row['id'],True)
        self.assertEqual(self.store.list(),[])
        self.assertEqual(len(self.store.list(hidden=True)),1)
        self.store.hide(row['id'],False)
        self.assertEqual(len(self.store.list(q='订单')),1)
        self.assertEqual(self.store.list(q="' OR 1=1 --"),[])

    def test_api_validates_quote_and_keeps_source_unchanged(self):
        from types import SimpleNamespace
        from fastapi.testclient import TestClient
        from app.web import app as web
        before=self.storage.read_revision_text(self.path)
        publication=SimpleNamespace(stocks=lambda:[{'stock_id':'a','name':'测试公司'}])
        with patch.object(web,'storage',self.storage),patch.object(web,'research',object()),patch.object(web,'Publications',return_value=publication):
            client=TestClient(web.app)
            payload={'revision':1,'quote':'公司订单持续增长。','topic':'订单','company_id':'a'}
            response=client.post('/api/v1/documents/'+self.doc+'/evidence',json=payload)
            self.assertEqual(response.status_code,200)
            self.assertIn('revision=1',response.json()['url'])
            self.assertTrue(response.json()['created'])
            bad=client.post('/api/v1/documents/'+self.doc+'/evidence',json={**payload,'quote':'不存在的财务结论'})
            self.assertEqual(bad.status_code,400)
            self.assertEqual(client.post('/api/v1/documents/'+self.doc+'/evidence',headers={'Origin':'https://foreign.example'},json=payload).status_code,403)
            key=response.json()['id']
            self.assertEqual(client.post('/api/v1/evidence/'+key+'/visibility',json={'hidden':True}).status_code,200)
        self.assertEqual(self.storage.read_revision_text(self.path),before)

    def test_paginated_filters_match_total_and_keep_all_rows(self):
        body='\n'.join(f'第{i:02}项订单与现金流变化。' for i in range(65))
        atomic_write_text(self.storage.path(self.path),'---\ntitle: 分页研究\n---\n'+body)
        for i,line in enumerate(body.splitlines()):
            self.store.create(self.doc,1,{'quote':line,'topic':'订单' if i%2==0 else '现金流','company_id':'a'},{'a':'测试公司'})
        self.assertEqual(self.store.count(),65)
        pages=[self.store.list(limit=30,offset=offset) for offset in (0,30,60)]
        self.assertEqual([len(p) for p in pages],[30,30,5])
        self.assertEqual(len({r['id'] for p in pages for r in p}),65)
        self.assertEqual(self.store.count(topic='订单',company_ids={'a'}),33)
        self.assertEqual(self.store.count(company_ids=set()),0)
        self.store.hide(pages[0][0]['id'],True)
        self.assertEqual(self.store.count(),64);self.assertEqual(self.store.count(hidden=True),1)
        from fastapi.testclient import TestClient
        from app.web import app as web
        with patch.object(web,'storage',self.storage),patch.object(web,'research',None):
            response=TestClient(web.app).get('/evidence?topic=订单&company_id=a&page=2')
            self.assertEqual(response.status_code,200)
            self.assertIn('第 2 / 2 页',response.text)
            self.assertIn('company_id=a',response.text)
