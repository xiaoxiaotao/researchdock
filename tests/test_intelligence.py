import copy
import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import httpx

from app.intelligence import assess, validate, assessment_path
from app.llm import ReceiptClient, LLMError
from app.publication import Publications
from app.research import Research
from app.storage import atomic_write_json, read_json
from app.utils import now_iso
from test_sources import SourceTests, GROUP
from test_research import MemorySecrets


def assessment(body, period='2026Q3', value='12'):
    return {'axes':{k:8 for k in ('significance','novelty','evidence','relevance','traceability')},'reason':'提供同报告期盈利预测与原文证据',
            'event':{'subject':'测试公司','type':'earnings','period':period,'object':period+'业绩','evidence':body},
            'observations':[{'company':'测试公司','topic':'业绩','metric':'归母净利润','period':period,'value':value,'unit':'亿元','kind':'forecast','statement':body,'evidence':body}]}


class IntelligenceTests(SourceTests):
    def setUp(self):
        super().setUp()
        self.secrets = MemorySecrets()
        self.secrets.value='never-print-this-key'
        self.research=Research(self.pipeline,self.manager,self.secrets)

    def tearDown(self):
        self.research.close()
        super().tearDown()

    def seed(self):
        for tid,period,value in [('101','2026Q3','12'),('102','2026Q3','10'),('103','2025Q3','20')]:
            self.client.items[tid]['content']=f'测试公司{period}业绩，预计归母净利润{value}亿元。'
        self.manager.sync(GROUP)
        for manifest in self.storage.iter_manifests():
            tid=manifest['fields']['source_item_id']
            body=self.client.items[tid]['content']
            period='2025Q3' if tid=='103' else '2026Q3'
            value={'101':'12','102':'10','103':'20'}[tid]
            note={'document_id':manifest['document_id'],'revision':manifest['current_revision'],'model':'deepseek-flash','title':manifest['title'],
                  'summary':body,'published_at':self.client.items[tid]['create_time'],'generated_at':now_iso(),
                  'industries':['半导体'],'stocks':[{'name':'测试公司','code':'000001','evidence':body}], 'key_points':[body],'risks':[]}
            atomic_write_json(self.storage.path(f"derived/summaries/{note['document_id']}.json"),note)
            parsed=validate(assessment(body,period,value),body)
            ai={'document_id':note['document_id'],'revision':note['revision'],'model':note['model'],'status':'assessed','score':80,'scores':[80,80],
                'event':parsed['event'],'observations':parsed['observations'],'independent_agreement':True,'reason':'原文证据'}
            atomic_write_json(assessment_path(self.storage,note,note['model']),ai)

    def test_manual_alias_merge_keeps_both_names_and_source_observations(self):
        from app.company_research import merge,identities
        self.seed()
        note=self.research.notes()[0]
        path=self.storage.path(f"derived/summaries/{note['document_id']}.json")
        data=read_json(path)
        data['stocks'][0]['name']='公司'
        atomic_write_json(path,data)
        ai_path=assessment_path(self.storage,note,note['model'])
        ai=read_json(ai_path)
        ai['observations'][0]['company']='公司'
        atomic_write_json(ai_path,ai)
        before=Publications(self.research).stocks()
        source=next(x for x in before if x['name']=='公司')['stock_id']
        target=next(x for x in before if x['name']=='测试公司')['stock_id']
        merge(self.storage,source,target,{x['stock_id'] for x in before})
        publication=Publications(self.research)
        timeline=publication.stock_timeline(source)
        self.assertEqual(timeline['total'],3)
        self.assertIn('公司',timeline['stock']['aliases'])
        self.assertEqual(sum(len(x['observations']) for x in timeline['entries']),3)
        atomic_write_json(self.storage.path('catalog/company-identities.json'),{})
        self.assertEqual(len(Publications(self.research).stocks()),len(before))

    def test_reading_groups_preserve_all_sources_and_filtered_representatives(self):
        self.seed()
        publication=Publications(self.research)
        groups=publication.reading_groups(publication.notes)
        self.assertEqual(sum(g['reading_group_count'] for g in groups),3)
        self.assertEqual(len(groups),2)
        first=publication.notes[0]
        filtered=publication.reading_groups([first])
        self.assertEqual(filtered[0]['document_id'],first['document_id'])
        self.assertEqual(filtered[0]['reading_group_count'],1)
        pair=next(g for g in groups if g['reading_group_count']==2)
        ids={r['document_id'] for r in pair['reading_group_reports']}
        preferred=next(n for n in publication.notes if n['document_id'] in ids and n['document_id']!=pair['document_id'])
        preferred['editorial']={'selected':True}
        chosen=next(g for g in publication.reading_groups(publication.notes) if g['reading_group_count']==2)
        self.assertEqual(chosen['document_id'],preferred['document_id'])

    def test_company_dossier_preserves_quotes_and_notes_are_explicit(self):
        from app.research_export import dossier
        self.seed()
        publication=Publications(self.research)
        timeline=publication.stock_timeline(publication.stocks()[0]['stock_id'],'asc')
        output=dossier(timeline,'http://127.0.0.1:8001')
        self.assertIn('原文证据',output)
        for entry in timeline['entries']:
            self.assertIn('/documents/'+entry['document_id'],output)
        self.assertNotIn('个人调研笔记',output)
        with_notes=dossier(timeline,'http://127.0.0.1:8001',[{'created_at':'2026-10-22','topic':'待验证','text':'只属于我的笔记 <script>','document_id':''}])
        self.assertIn('个人调研笔记',with_notes)
        self.assertNotIn('<script>',with_notes)

    def test_directory_company_workspace_without_archived_research(self):
        from app.securities import Securities
        Securities(self.storage).ingest([{'code':'002353','zwjc':'杰瑞股份','category':'A股','pinyin':'jrgf'},{'code':'600519','zwjc':'贵州茅台','category':'A股','pinyin':'gzmt'}])
        timeline=Publications(self.research).stock_timeline('security-sz002353')
        self.assertEqual(timeline['stock']['name'],'杰瑞股份')
        self.assertEqual(timeline['stock']['security']['code'],'002353')
        self.assertEqual(timeline['total'],0)
        self.assertIsNone(Publications(self.research).stock_timeline('security-sz999999'))
        from fastapi.testclient import TestClient
        from app.web import app as web
        with patch.object(web,'storage',self.storage),patch.object(web,'research',self.research):
            client=TestClient(web.app)
            response=client.get('/stocks/security-sz002353?tab=financials')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.context['tab'],'financials')
            self.assertIn('直接点击获取即可',response.text)
            self.assertIn('002353',response.text)
            self.assertEqual(client.get('/stocks/security-sz002353?tab=unknown').status_code,422)

    def test_question_api_saves_history_and_renders_personal_judgment(self):
        from fastapi.testclient import TestClient
        from app.web import app as web
        from app.company_research import journal
        self.seed()
        publication=Publications(self.research)
        stock=publication.stocks()[0]
        doc=next(iter(stock['document_ids']))
        with patch.object(web,'storage',self.storage),patch.object(web,'research',self.research):
            client=TestClient(web.app)
            result=client.post('/api/v1/stocks/'+stock['stock_id']+'/notes',json={'topic':'待验证','text':'盈利预测能否兑现？'})
            self.assertEqual(result.status_code,200)
            note_id=result.json()['id']
            self.assertEqual(len(journal(self.storage)[note_id]['known_document_versions']),3)
            changed=client.post('/api/v1/stocks/notes/'+note_id+'/question',json={'state':'supported','conclusion':'个人复核了原文预测口径','document_ids':[doc]})
            self.assertEqual(changed.status_code,200)
            page=client.get('/stocks/'+stock['stock_id']+'?tab=notes')
            self.assertEqual(page.status_code,200)
            self.assertIn('个人判断：证据支持',page.text)
            self.assertEqual(page.context['question_count'],0)
            self.assertEqual(journal(self.storage)[note_id]['question_evidence_revisions'][doc],1)
            self.assertEqual(page.context['personal_notes'][0]['new_evidence'],[])
            self.assertEqual(client.post('/api/v1/stocks/notes/'+note_id+'/question',headers={'Origin':'https://foreign.example'},json={'state':'open'}).status_code,403)

    def test_receipt_reuse_budget_and_secret_redaction(self):
        calls=[]
        def handler(request):
            calls.append(request)
            return httpx.Response(200,json={'choices':[{'message':{'content':'{"ok": true}'}}],'usage':{'total_tokens':17}})
        settings=lambda:{'model':'deepseek-flash','daily_request_limit':1}
        provider=ReceiptClient(self.storage,settings,self.secrets.get,httpx.MockTransport(handler))
        self.assertEqual(provider.call('json','body','a'),{'ok':True})
        self.assertEqual(provider.call('json','body','a'),{'ok':True})
        self.assertEqual(len(calls),1)
        with self.assertRaises(LLMError): provider.call('json','body','b')
        self.assertEqual(provider.usage()['tokens'],17)
        for receipt in provider.receipts(): self.assertNotIn(self.secrets.value,json.dumps(receipt))

    def test_uncertain_request_is_not_automatically_repeated(self):
        def handler(request): raise httpx.ReadTimeout('failure')
        provider=ReceiptClient(self.storage,lambda:{'model':'deepseek-flash','daily_request_limit':5},self.secrets.get,httpx.MockTransport(handler))
        with self.assertRaises(LLMError): provider.call('json','body','test')
        with self.assertRaises(LLMError): provider.call('json','body','test')
        self.assertEqual(provider.usage()['requests'],1)
        row=provider.receipts()[0]
        provider.release(row['id'])
        with self.assertRaises(LLMError): provider.call('json','body','test')
        self.assertEqual(provider.usage()['requests'],2)

    def test_double_assessment_independent_cache(self):
        body='测试公司2026Q3业绩，预计归母净利润12亿元。'+'具体经营数据说明。'*10
        calls=[]
        class Provider:
            def call(self,system,content,purpose,max_tokens):
                calls.append((content,purpose))
                result=assessment(body)
                if len(calls)==2: result['axes']['novelty']=5
                return result
        note={'document_id':'doc_example','revision':1}
        first=assess(self.storage,Provider(),note,body,'deepseek-flash')
        second=assess(self.storage,Provider(),note,body,'deepseek-flash')
        self.assertEqual(len(calls),2)
        self.assertNotEqual(calls[0][1],calls[1][1])
        self.assertEqual(first['score'],74)
        self.assertEqual(first,second)
        self.assertTrue(first['independent_agreement'])

    def test_evidence_rejects_invented_value(self):
        body='测试公司2026Q3业绩，预计归母净利润12亿元。'
        value=assessment(body)
        value['observations'][0]['value']='999'
        self.assertEqual(validate(value,body)['observations'][0]['value'],'')
        value['event']['subject']='另一家公司'
        self.assertEqual(validate(value,body)['event'],{})

    def test_same_company_different_period_not_merged(self):
        self.seed()
        events=Publications(self.research).events(datetime.fromisoformat('2026-10-22T10:00:00+08:00'))
        self.assertEqual(sorted(e['report_count'] for e in events),[1,2])
        combined=next(e for e in events if e['report_count']==2)
        self.assertEqual(combined['source_count'],1)
        # A duplicate post from the same source cannot double heat.
        latest=max(n['published_at'] for n in combined['reports'])
        expected=100*2**(-((datetime.fromisoformat('2026-10-22T10:00:00+08:00')-datetime.fromisoformat(latest)).total_seconds()/86400))
        self.assertAlmostEqual(combined['heat'],expected,places=1)

    def test_stock_timeline_dates_periods_and_two_source_evidence(self):
        self.seed()
        publication=Publications(self.research)
        stock=next(s for s in publication.stocks() if s['name']=='测试公司')
        timeline=publication.stock_timeline(stock['stock_id'],'asc')
        self.assertEqual(timeline['total'],3)
        self.assertEqual(len(timeline['entries'][1]['changes']),0)
        change=timeline['entries'][2]['changes'][0]
        self.assertEqual((change['before'],change['after'],change['period']),('10','12','2026Q3'))
        self.assertIn('10亿元',change['before_evidence'])
        self.assertIn('12亿元',change['after_evidence'])
        digest=publication.digest('2026-10-21','2026-10-21')
        self.assertEqual(digest['report_count'],3)
        self.assertEqual(digest['event_count'],2)

    def test_publication_http_read_paths_and_mcp_are_model_free(self):
        from fastapi.testclient import TestClient
        import app.web.app as web
        self.seed()
        client = TestClient(web.app)
        with patch.object(web,'research',self.research), patch.object(web,'storage',self.storage), patch.object(web,'cfg',self.cfg), patch.object(self.research.provider,'call',side_effect=AssertionError('Read must not call models')):
            for url in ['/stocks','/events','/briefing?date=2026-10-21','/reading','/reading?selected=true','/rss.xml','/agent']:
                response=client.get(url)
                self.assertEqual(response.status_code,200,(url,response.text[:400]))
            from xml.etree.ElementTree import fromstring
            rss=fromstring(client.get('/rss.xml').content)
            self.assertEqual(rss.find('channel/item/guid').get('isPermaLink'),'false')
            response=client.get('/reading?page=2')
            self.assertEqual(response.status_code,200)
            headers={'Accept':'application/json, text/event-stream'}
            response=client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}})
            self.assertEqual(response.json()['result']['protocolVersion'],'2025-11-25')
            response=client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'list_stocks','arguments':{'query':'测试公司'}}})
            self.assertFalse(response.json()['result']['isError'])
            self.assertIn('测试公司',response.text)
            forbidden=client.post('/mcp',headers={**headers,'Origin':'https://example.invalid'},json={'jsonrpc':'2.0','id':2,'method':'tools/list'})
            self.assertEqual(forbidden.status_code,403)
            stock=next(s for s in Publications(self.research).stocks() if s['name']=='测试公司')
            self.assertEqual(client.get('/stocks/'+stock['stock_id']).status_code,200)
            event=Publications(self.research).events()[0]
            self.assertEqual(client.get('/events/'+event['event_id']).status_code,200)

    def test_manual_event_separation_survives_regrouping(self):
        self.seed()
        publication=Publications(self.research)
        event=next(e for e in publication.events() if e['report_count']==2)
        docid=event['reports'][0]['document_id']
        self.research.separate_event(docid,True)
        self.assertEqual(len(Publications(self.research).events()),3)
        self.research.separate_event(docid,False)
        self.assertEqual(len(Publications(self.research).events()),2)

    def test_invalid_business_output_can_be_retried(self):
        count=[]
        def handler(request):
            count.append(1)
            return httpx.Response(200,json={'choices':[{'message':{'content':'{"ok": true}'}}]})
        provider=ReceiptClient(self.storage,lambda:{'model':'deepseek-flash','daily_request_limit':4},self.secrets.get,httpx.MockTransport(handler))
        provider.call('json','body','test')
        provider.invalidate('json','body','test')
        provider.call('json','body','test')
        self.assertEqual(len(count),2)

    def test_larger_output_capacity_reuses_paid_success(self):
        calls=[]
        def handler(request):
            calls.append(1)
            return httpx.Response(200,json={'choices':[{'message':{'content':'{"ok": true}'}}]})
        provider=ReceiptClient(self.storage,lambda:{'model':'deepseek-flash','daily_request_limit':4},self.secrets.get,httpx.MockTransport(handler))
        provider.call('json','body','finance-assessment-a:test',4500)
        provider.document_ids=['doc_example']
        self.assertEqual(provider.call('json','body','finance-assessment-a:test',6500),{'ok':True})
        self.assertEqual(len(calls),1)
        self.assertEqual(provider.receipts()[0]['document_ids'],['doc_example'])

    def test_unknown_publication_date_is_not_import_date(self):
        self.client.items['103']['create_time']=None
        self.seed()
        publication=Publications(self.research)
        stock=next(s for s in publication.stocks() if s['name']=='测试公司')
        result=publication.stock_timeline(stock['stock_id'],'asc')
        unknown=next(e for e in result['entries'] if e['published_at'] is None)
        self.assertIsNone(unknown['published_at'])
        self.assertEqual(unknown['changes'],[])

    def test_period_comparison_keeps_quarter_and_cumulative_distinct(self):
        from app.measurements import period_key, comparison_key, different_value
        self.assertEqual(period_key('26Q3',2026),'2026Q3')
        self.assertEqual(period_key('2026年前三季度',2026),'2026YTDQ3')
        self.assertNotEqual(period_key('26Q3',2026),period_key('26Q1-3',2026))
        self.assertIsNone(period_key('Q3',2026))
        self.assertIsNone(period_key('26Q3',None))
        self.assertFalse(different_value('1.0','1'))
        a={'metric':'营收','period':'26Q3','unit':'亿元','value':'1','kind':'fact'}
        b={**a,'metric':'营业收入','period':'2026Q3'}
        self.assertEqual(comparison_key(a,2026),comparison_key(b,2026))
        self.assertNotEqual(comparison_key(a,2026),comparison_key({**b,'unit':'万美元'},2026))

    def test_metric_value_must_be_in_its_own_quote(self):
        body='测试公司2026Q3营收43.3亿元。归母净利润6.9亿元。'
        value=assessment(body,value='43.3')
        value['observations'][0]['evidence']='归母净利润6.9亿元。'
        result=validate(value,body)['observations'][0]
        self.assertIn('测试公司',result['evidence'])
        self.assertEqual(result['value'],'')

    def test_manual_selection_survives_scoring(self):
        self.seed()
        note=self.research.notes()[0]
        self.assertTrue(note['is_selected'])
        self.research.edit_selection(note['document_id'],False)
        self.assertFalse(next(n for n in self.research.notes() if n['document_id']==note['document_id'])['is_selected'])
