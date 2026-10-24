import copy
import tempfile
import unittest
from pathlib import Path
import httpx
from app.storage import Storage,atomic_write_json
from app.financials import parse_statements,refresh,cache,FinancialError,display


def raw_reports():
    result={}
    fields={'lrb':[('BIZINCO','100000000'),('NETPROFIT','20000000'),('PARENETP','15000000')],'llb':[('MANANETR','-5000000')],'fzb':[('TOTASSET','200000000'),('TOTLIAB','100000000')]}
    for kind,items in fields.items():
        result[kind]={'result':{'status':{'code':0},'data':{'report_list':{period:{'rType':'合并期末','rCurrency':'CNY','publish_date':'20261022','data':[{'item_field':field,'item_value':value} for field,value in items]} for period in ['20260930','20250930']}}}}
    return result

class FinancialTests(unittest.TestCase):
    def test_cumulative_period_missing_is_not_zero_and_negative_base_no_yoy(self):
        raw=raw_reports();raw['lrb']['result']['data']['report_list']['20260930']['data'][0]['item_value']='120000000'
        rows=parse_statements(raw)
        self.assertEqual(rows[0]['period_label'],'2026年前三季度')
        self.assertEqual(rows[0]['yoy']['revenue'],'20.0')
        self.assertNotIn('operating_cash',rows[0]['yoy'])
        self.assertIsNone(rows[0]['values']['investing_cash'])
        self.assertEqual(display('120000000'),'1.20')
        self.assertEqual(display(None),'—')
    def test_non_cny_or_individual_statements_not_mixed(self):
        raw=raw_reports()
        for v in raw.values():
            for report in v['result']['data']['report_list'].values():report['rCurrency']='USD'
        with self.assertRaises(FinancialError):parse_statements(raw)
    def test_failure_preserves_previous_cache_and_success_archives_raw(self):
        with tempfile.TemporaryDirectory() as d:
            s=Storage(Path(d)/'kb',allow_create=True);s.path('derived/financials').mkdir(parents=True,exist_ok=True)
            atomic_write_json(s.path('derived/financials/company.json'),{'previous':True})
            def failed(request):return httpx.Response(503)
            with httpx.Client(transport=httpx.MockTransport(failed)) as client:
                with self.assertRaises(FinancialError):refresh(s,'company','002353','sz',client)
            self.assertTrue(cache(s,'company')['previous'])
            raw=raw_reports()
            def success(request):
                if request.url.host=='qt.gtimg.cn':return httpx.Response(200,content='v_sz002353="51~测试公司~002353~89";'.encode('gb18030'))
                return httpx.Response(200,json=raw[request.url.params['source']])
            with httpx.Client(transport=httpx.MockTransport(success)) as client:
                result=refresh(s,'company','002353','sz',client)
            self.assertEqual(result['company_name'],'测试公司')
            self.assertEqual(len(list(s.path('derived/financials/raw/company').glob('*.json'))),1)
            self.assertEqual(cache(s,'company')['code'],'002353')
    def test_invalid_code_does_not_request(self):
        with tempfile.TemporaryDirectory() as d:
            s=Storage(Path(d)/'kb',allow_create=True)
            with self.assertRaises(FinancialError):refresh(s,'company','../../secret','sz')
            with self.assertRaises(FinancialError):refresh(s,'company','002353','us')
    def test_refresh_api_requires_human_identity_confirmation(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from fastapi.testclient import TestClient
        from app.web import app as web
        pub=SimpleNamespace(stock_timeline=lambda key:{'stock':{'stock_id':'known'}})
        with patch.object(web,'research',object()),patch.object(web,'Publications',return_value=pub),patch('app.financials.refresh') as request:
            client=TestClient(web.app)
            self.assertEqual(client.post('/api/v1/stocks/a/financials',json={'code':'002353','exchange':'sz'}).status_code,400)
            request.assert_not_called()

    def test_comparable_period_filter_and_missing_chart_points(self):
        from app.financial_views import periods,trend
        rows=[{'period':'2026-09-30','values':{'revenue':'200000000'}},{'period':'2026-06-30','values':{'revenue':'130000000'}},{'period':'2025-12-31','values':{'revenue':'250000000'}},{'period':'2025-09-30','values':{'revenue':None}},{'period':'2024-09-30','values':{'revenue':'100000000'}}]
        comparable=periods(rows)
        self.assertEqual([r['period'] for r in comparable],['2026-09-30','2025-09-30','2024-09-30'])
        self.assertEqual(len(periods(rows,'annual')),1)
        svg=trend(comparable,'revenue','收入')
        self.assertEqual(svg.count('<circle '),2)
        self.assertNotIn('<polyline ',svg)
        self.assertIn('2026-09-30',svg)
        with self.assertRaises(ValueError):periods(rows,'bogus')
