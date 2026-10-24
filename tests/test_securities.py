import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from app.storage import Storage
from app.securities import Securities,exchange_for

class SecuritiesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.storage=Storage(Path(self.tmp.name)/'kb',allow_create=True);self.master=Securities(self.storage)
    def tearDown(self):self.tmp.cleanup()
    def row(self,code='002353',name='杰瑞股份',category='A股'):return {'code':code,'zwjc':name,'category':category,'pinyin':'jrgf','orgId':'test'}
    def test_leading_zeros_and_market_identity(self):
        self.master.ingest([self.row(),self.row('600519','贵州茅台'),self.row('920001','纬达光电'),self.row('200001','B公司','B股')])
        self.assertEqual(self.master.stats()['count'],3)
        self.assertEqual(self.master.resolve('杰瑞股份')['code'],'002353')
        self.assertEqual(self.master.resolve('纬达光电')['exchange'],'bj')
        self.assertEqual(self.master.search('jrgf')[0]['code'],'002353')
        self.assertEqual(self.master.search("' OR 1=1 --"),[])
        self.assertEqual(exchange_for('002353'),'sz')
    def test_rename_history_and_ambiguous_names(self):
        self.master.ingest([self.row(name='原简称')])
        self.master.ingest([self.row(name='新简称')])
        self.assertEqual(self.master.resolve('原简称')['name'],'新简称')
        self.master.ingest([self.row(name='新简称'),self.row('600519','新简称')])
        self.assertIsNone(self.master.resolve('新简称'))
        self.assertIsNone(self.master.matches([{'stock_id':'a','name':'新简称'}]).get('a'))
        self.assertIsNone(self.master.resolve('新简'))
    def test_partial_feed_keeps_previous_directory(self):
        self.master.ingest([self.row(),self.row('600519','贵州茅台')])
        with self.assertRaises(ValueError):self.master.ingest([self.row()])
        self.assertEqual(self.master.stats()['count'],2)
        self.assertEqual(self.master.resolve('贵州茅台')['code'],'600519')
    def test_directory_auto_finance_does_not_need_code_input(self):
        from fastapi.testclient import TestClient
        from app.web import app as web
        self.master.ingest([self.row()]);security=self.master.resolve('杰瑞股份')
        pub=SimpleNamespace(stock_timeline=lambda key:{'stock':{'stock_id':'company','security':security}})
        with patch.object(web,'research',object()),patch.object(web,'Publications',return_value=pub),patch('app.financials.refresh',return_value={'company_name':'杰瑞股份','fetched_at':'2026-10-22'}) as refresh:
            response=TestClient(web.app).post('/api/v1/stocks/company/financials',json={'use_directory':True})
            self.assertEqual(response.status_code,200)
            self.assertEqual(refresh.call_args.args[2:4],('002353','sz'))
            self.assertEqual(refresh.call_args.kwargs['expected_name'],'杰瑞股份')
    def test_hk_names_codes_and_independent_market_snapshots(self):
        self.master.ingest([self.row('688981','中芯国际')])
        hk=[{'code':'00700','name':'騰訊控股','english_name':'TENCENT'},{'code':'00981','name':'中芯國際','english_name':'SMIC'},{'code':'01810','name':'小米集團－Ｗ','english_name':'XIAOMI-W'}]
        self.master.ingest_hk(hk)
        for name in ['腾讯控股','騰訊控股','腾讯','TENCENT']:
            self.assertEqual(self.master.resolve(name)['code'],'00700')
        for code in ['700.HK','HK00700','00700']:
            self.assertEqual(self.master.search(code)[0]['security_id'],'hk00700')
        self.assertEqual(self.master.resolve('小米集团')['code'],'01810')
        self.assertIsNone(self.master.resolve('中芯国际'))
        self.assertEqual(self.master.resolve('中芯国际','981.HK')['exchange'],'hk')
        result=self.master.matches([{'stock_id':'h','name':'中芯国际','code':'00981.HK'},{'stock_id':'a','name':'中芯国际','code':'688981'},{'stock_id':'unknown','name':'中芯国际'}])
        self.assertEqual(result['h']['exchange'],'hk');self.assertEqual(result['a']['exchange'],'sh');self.assertNotIn('unknown',result)
        self.master.ingest([self.row('688981','中芯国际')])
        self.assertEqual(self.master.stats()['hk_count'],3)
        with self.assertRaises(ValueError):self.master.ingest_hk(hk[:1])
        self.assertEqual(self.master.stats()['count'],4)
    def test_hk_directory_groups_only_confirmed_same_security_research(self):
        from app.publication import Publications
        self.master.ingest_hk([{'code':'00700','name':'騰訊控股','english_name':'TENCENT'}])
        security=self.master.get('hk00700')
        pub=Publications.__new__(Publications);pub.storage=self.storage
        companies=[{'stock_id':key,'name':name,'security':security,'document_ids':{doc},'industries':['传媒']} for key,name,doc in [('tencent','腾讯','d1'),('holdings','腾讯控股','d2')]]
        pub.stocks=lambda:companies;pub.docs={d:{'current_revision':1,'title':'腾讯研究','published_at':'2026-10-22'} for d in ('d1','d2')};pub.by_doc={}
        timeline=pub.stock_timeline('security-hk00700')
        self.assertEqual(timeline['total'],2)
        self.assertEqual(set(timeline['stock']['member_ids']),{'tencent','holdings'})
        self.assertEqual(timeline['stock']['catalog_code'],'00700')
