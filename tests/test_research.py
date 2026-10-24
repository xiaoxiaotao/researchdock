import json
import unittest
from unittest.mock import patch
import httpx
from app.research import Research, ResearchError, classify
from test_sources import SourceTests, GROUP

class MemorySecrets:
    value = None
    def get(self): return self.value
    def set(self, value): self.value = value

class ResearchTests(SourceTests):
    def setUp(self):
        super().setUp()
        from app.storage import atomic_write_json
        atomic_write_json(self.storage.path('catalog/research-settings.json'),{'intelligence_enabled':False})
        self.secrets = MemorySecrets()
        self.research = Research(self.pipeline, self.manager, self.secrets)

    def tearDown(self):
        self.research.close()
        super().tearDown()

    def test_economy_skips_automatic_deep_analysis(self):
        from app.storage import atomic_write_json
        from datetime import datetime
        atomic_write_json(self.storage.path('catalog/research-settings.json'),{'intelligence_enabled':True,'economy_enabled':True})
        self.secrets.value='secret'
        result=dict(summary='摘要',industries=[],stocks=[],key_points=[],risks=[])
        with patch('app.research.classify',side_effect=lambda *a,**kw:dict(result)) as paid, patch.object(self.research,'enrich') as deep, patch('app.research.datetime') as clock:
            clock.now.return_value=datetime.fromisoformat('2026-10-21T10:03:00+08:00')
            self.research.run(True)
        self.assertEqual(paid.call_count,3)
        deep.assert_not_called()
        self.assertEqual(len(self.research.pending()),0)

    def test_same_prose_revision_reuses_summary_without_call(self):
        self.manager.sync(GROUP)
        self.secrets.value='secret'
        result=dict(summary='摘要',industries=[],stocks=[],key_points=[],risks=[])
        with patch('app.research.classify',side_effect=lambda *a,**kw:dict(result)):
            self.research.run(False)
        self.client.items['101']['content']+=' https://example.com/updated'
        self.manager.sync(GROUP)
        with patch('app.research.classify') as paid:
            self.research.run(False)
        paid.assert_not_called()
        self.assertEqual(len(self.research.pending()),0)

    def test_attachment_posts_skip_paid_summary(self):
        for t in self.client.items.values():
            t['content']='「文件」'
            t['files']=[{'file_id':'123','name':'测试.pdf','size':100}]
        self.manager.sync(GROUP)
        self.secrets.value='secret'
        with patch('app.research.classify') as paid:
            self.research.run(False)
        paid.assert_not_called()
        self.assertEqual(self.research.state()['skipped'],3)
        self.assertEqual(len(self.research.pending()),0)

    def test_catchup_uses_completed_watermark_and_preserves_on_failure(self):
        from app.storage import read_json,atomic_write_json
        from datetime import datetime
        source=read_json(self.manager.path(GROUP))
        source['collected_through']='2026-10-19T22:00:00+08:00'
        atomic_write_json(self.manager.path(GROUP),source)
        self.secrets.value='secret'
        with patch.object(self.manager,'sync',return_value={'status':'succeeded','window_complete':True}) as sync, patch('app.research.datetime') as clock:
            clock.now.return_value=datetime.fromisoformat('2026-10-22T22:00:00+08:00')
            self.research.run(True)
        self.assertEqual(sync.call_args.kwargs['window_start'],'2026-10-19T21:55:00+08:00')
        self.assertEqual(read_json(self.manager.path(GROUP))['collected_through'],'2026-10-22T22:00:00+08:00')
        with patch.object(self.manager,'sync',side_effect=__import__('app.sources',fromlist=['SourceError']).SourceError('暂时断网')):
            self.research.run(True)
        self.assertEqual(read_json(self.manager.path(GROUP))['collected_through'],'2026-10-22T22:00:00+08:00')

    def test_window(self):
        result = self.manager.sync(GROUP, 'daily', window_start='2026-10-21T10:01:00+08:00', window_end='2026-10-21T10:02:00+08:00')
        self.assertEqual(result['counts']['created'], 2)
        result = self.manager.sync(GROUP, 'daily', window_start='2026-10-21T10:01:00+08:00', window_end='2026-10-21T10:02:00+08:00')
        self.assertEqual(result['counts']['created'], 0)

    def test_settings_no_secret_on_disk(self):
        self.research.save(dict(api_key='private-secret', enabled=True, daily_time='22:00', model='deepseek-flash'))
        self.assertNotIn('private-secret', self.storage.path('catalog/research-settings.json').read_text())
        self.assertTrue(self.research.settings()['enabled'])

    def test_read_state_persists_separately(self):
        self.manager.sync(GROUP)
        doc = next(iter(self.storage.iter_manifests()))
        self.research.mark_read(doc['document_id'], True)
        self.assertTrue(self.research.reading_state()[doc['document_id']]['read'])
        self.assertEqual(self.storage.read_manifest(doc['document_id']), doc)
        with self.assertRaises(ResearchError):
            self.research.mark_read('../storage', True)

    def test_collection_failure_does_not_block_archived_notes(self):
        from app.sources import SourceError
        self.manager.sync(GROUP)
        self.secrets.value = 'secret'
        result = dict(summary='摘要', industries=['半导体'], stocks=[], key_points=[], risks=[])
        from datetime import datetime
        with patch.object(self.manager, 'sync', side_effect=SourceError('主题缺少正文')), patch('app.research.classify', return_value=result), patch('app.research.datetime') as clock:
            clock.now.return_value = datetime.fromisoformat('2026-10-21T10:03:00+08:00')
            self.research.run(True)
        state = self.research.state()
        self.assertEqual(state['status'], 'partial')
        self.assertIn('主题缺少正文', state['collection_errors'][0])
        self.assertEqual(state['processed'], 3)
        # The archived documents belong to a fixed historical day; run(False) can always process them.
        with patch('app.research.classify', return_value=result):
            self.research.run(False)
        self.assertEqual(self.research.state()['status'], 'succeeded')
        self.assertEqual(len(self.research.notes()), 3)

    def test_starred_and_read_states_preserve_each_other(self):
        self.manager.sync(GROUP)
        doc = next(iter(self.storage.iter_manifests()))
        key = doc['document_id']
        self.research.mark_read(key, True)
        self.research.mark_starred(key, True)
        self.assertTrue(self.research.reading_state()[key]['read'])
        self.assertTrue(self.research.reading_state()[key]['starred'])
        self.research.mark_read(key, False)
        self.assertTrue(self.research.reading_state()[key]['starred'])
        self.research.mark_starred(key, False)
        self.assertFalse(self.research.reading_state()[key]['starred'])
        with self.assertRaises(ResearchError):
            self.research.mark_starred('../storage', True)

    def test_daily_budget_interruption_keeps_backlog_across_windows(self):
        from datetime import datetime
        self.secrets.value='secret'
        with patch('app.research.datetime') as clock, patch('app.research.classify',side_effect=ResearchError('今日请求上限')):
            clock.now.return_value=datetime.fromisoformat('2026-10-21T10:03:00+08:00')
            self.research.run(True)
        self.assertEqual(len(self.research.pending()),3)
        result=dict(summary='摘要',industries=['半导体'],stocks=[],key_points=[],risks=[])
        with patch('app.research.datetime') as clock, patch('app.research.classify',side_effect=lambda *a,**kw:dict(result)):
            clock.now.return_value=datetime.fromisoformat('2026-10-23T10:03:00+08:00')
            self.research.run(True)
        self.assertEqual(self.research.state()['status'],'succeeded')
        self.assertEqual(len(self.research.notes()),3)
        self.assertFalse(self.research.pending())
        self.assertTrue(all(n['published_at'].startswith('2026-10-21') for n in self.research.notes()))

    def test_cache_and_stale_revision(self):
        self.manager.sync(GROUP)
        self.secrets.value = 'secret'
        result = dict(summary='摘要', industries=['科技'], stocks=[], key_points=['要点'], risks=[])
        with patch('app.research.classify', return_value=result) as call:
            self.research.run(False)
            self.assertEqual(call.call_count, 3)
            self.assertEqual(self.research.state()['status'], 'succeeded')
            self.research.run(False)
            self.assertEqual(call.call_count, 3)
            self.assertEqual(len(self.research.notes()), 3)
            manifest = next(iter(self.storage.iter_manifests()))
            # A changed version is hidden until it is processed again.
            manifest['current_revision'] += 1
            self.storage.write_manifest(manifest)
            self.assertEqual(len(self.research.notes()), 2)

class ModelTests(unittest.TestCase):
    def test_json_and_evidence(self):
        def handler(request):
            self.assertIn('json', request.content.decode())
            value = dict(summary='摘要', industries=['行业'], key_points=[], risks=[], stocks=[dict(name='公司', code='', evidence='不存在')])
            return httpx.Response(200, json={'choices':[{'message':{'content':json.dumps(value)}}]})
        result = classify('公司原文', 'secret', 'deepseek-flash', httpx.MockTransport(handler))
        self.assertEqual(result['stocks'], [])

    def test_safe_failure(self):
        with self.assertRaises(ResearchError) as exc:
            classify('正文', 'secret', 'deepseek-flash', httpx.MockTransport(lambda request: httpx.Response(401, text='secret')))
        self.assertNotIn('secret', str(exc.exception))
