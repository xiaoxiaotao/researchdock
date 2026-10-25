import json
import tempfile
import unittest
from unittest.mock import patch
from dataclasses import replace
from pathlib import Path

from app import index
from app.config import load_config
from app.pipeline import Pipeline
from app.sources import SourceManager, SourceError, topic_record
from app.storage import Storage

GROUP = '10000000000001'


def topic(tid, text='完整正文', time='2026-10-21T10:00:00.000+0800'):
    return {'topic_id': tid, 'content': text, 'title': 'API截断摘要...', 'create_time': time,
            'group': {'group_id': GROUP, 'name': '测试星球'},
            'owner': {'name': '作者', 'user_id': '456', 'avatar_url': 'https://example.invalid/?token=secret'},
            'files': [], 'images': []}


class FakeClient:
    def __init__(self):
        self.items = {'101': topic('101', '第一篇的完整正文', '2026-10-21T10:02:00.000+0800'),
                      '102': topic('102', '第二篇的完整正文', '2026-10-21T10:01:00.000+0800'),
                      '103': topic('103', '第三篇的完整正文', '2026-10-21T10:00:00.000+0800')}
        self.fail = False

    def topics(self, group_id, limit, end_time=None):
        if self.fail:
            raise SourceError('API 暂不可达')
        ids = ['101','102'] if end_time is None else ['102','103']
        rows = [self.items[k] for k in ids]
        return {'topics_brief': rows, 'has_more': end_time is None,
                'next_end_time': rows[-1]['create_time']}

    def detail(self, tid):
        return self.items[tid]


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = replace(load_config(), data_dir=Path(self.tmp.name)/'kb')
        self.storage = Storage(self.cfg.data_dir)
        self.storage.ensure_layout()
        index.init_schema(self.cfg.db_path)
        self.pipeline = Pipeline(self.cfg, self.storage)
        self.client = FakeClient()
        self.manager = SourceManager(self.pipeline, self.client)
        self.manager.register(GROUP, '调研纪要')

    def test_missing_body_is_deferred_without_blocking_other_topics(self):
        original = self.client.items['101']['content']
        self.client.items['101']['content'] = ''
        result = self.manager.sync(GROUP)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['counts']['created'], 2)
        self.assertEqual(result['unavailable_count'], 1)
        self.assertIn('101', result['unavailable_topics'])
        self.client.items['101']['content'] = original
        result = self.manager.sync(GROUP)
        self.assertEqual(result['unavailable_count'], 0)
        self.assertEqual(result['counts']['created'], 1)

    def tearDown(self):
        self.manager.close()
        self.tmp.cleanup()

    def test_full_text_normalization_and_no_signed_avatar(self):
        record = topic_record(topic('101', '<p>标题</p><p>完整正文 &amp; 数字35%</p><e type="hashtag" title="%23液冷%23"/><script>bad()</script>'), GROUP, '调研纪要')
        self.assertIn('完整正文 & 数字35%', record['content_text'])
        self.assertEqual(record['tags'], ['液冷'])
        self.assertNotIn('bad()', record['content_text'])
        self.assertEqual(record['title'], '标题')
        self.assertNotIn('secret', json.dumps(record))
        self.assertEqual(record['author_name'], '作者')
        self.assertEqual(record['source_url'], f'https://wx.zsxq.com/group/{GROUP}/topic/101')

    def test_plain_text_ampersands_are_flushed_at_end_of_document(self):
        body = '【研究&A】行业纪要\n收入回升，Q3利润改善&现金流增加'
        record = topic_record(topic('101', body), GROUP, '调研纪要')
        self.assertEqual(record['content_text'], body)
        self.assertNotIn('此主题仅含附件', record['content_text'])

    def test_inclusive_pagination_duplicate_and_repeat(self):
        first = self.manager.sync(GROUP, limit=2, max_pages=2)
        self.assertEqual(first['counts']['created'], 3)
        second = self.manager.sync(GROUP, limit=2, max_pages=2)
        self.assertEqual(second['counts']['created'], 0)
        with index.connect(self.cfg.db_path) as conn:
            self.assertEqual(conn.execute('select count(*) from documents').fetchone()[0], 3)
            self.assertEqual(conn.execute('select count(*) from document_revisions').fetchone()[0], 3)

    def test_failure_does_not_advance_cursor(self):
        first = self.manager.sync(GROUP, limit=2, max_pages=1)
        old = first['latest_at']
        self.client.fail = True
        with self.assertRaises(SourceError):
            self.manager.sync(GROUP)
        saved = json.loads(self.manager.path(GROUP).read_text())
        self.assertEqual(saved['latest_at'], old)
        self.assertEqual(saved['status'], 'failed')

    def test_history_continues_from_sample_boundary(self):
        first = self.manager.sync(GROUP, limit=2, max_pages=1)
        self.assertEqual(first['counts']['created'], 2)
        history = self.manager.sync(GROUP, mode='history', limit=2, max_pages=1)
        self.assertEqual(history['counts']['created'], 1)
        self.assertTrue(history['history_complete'])

    def test_manual_classification_preserved_on_source_refresh(self):
        self.manager.sync(GROUP, limit=2, max_pages=1)
        with index.connect(self.cfg.db_path) as conn:
            doc_id = conn.execute('select document_id from documents where source_item_id=?', ('101',)).fetchone()[0]
        self.pipeline.update_metadata(doc_id, {'content_type': 'research_note', 'institution': '手动机构', 'title': '手动标题'})
        self.client.items['101']['content'] += '\n来源修订的新正文'
        self.manager.sync(GROUP, limit=2, max_pages=1)
        manifest = self.storage.read_manifest(doc_id)
        self.assertEqual(manifest['title'], '手动标题')
        self.assertEqual(manifest['fields']['institution'], '手动机构')
        self.assertEqual(manifest['fields']['content_type'], 'research_note')
        self.assertEqual(manifest['current_revision'], 3)

    def test_attachment_metadata_is_explicit(self):
        t = topic('101', '')
        t['files'] = [{'file_id': '123', 'name': '报告.pdf', 'size': 100}]
        result = topic_record(t, GROUP, '调研纪要')
        self.assertEqual(result['source_attachments'][0]['status'], 'metadata_only')
        self.assertIn('仅含附件', result['content_text'])
        self.assertNotIn('token', json.dumps(result))

    def test_file_placeholder_is_not_readable_body(self):
        t = topic('101', '「文件」')
        t['files'] = [{'file_id': '123', 'name': '晨会.mp3'}]
        result = topic_record(t, GROUP, '调研纪要')
        self.assertEqual(result['title'], '晨会.mp3')
        self.assertIn('仅含附件', result['content_text'])

    def test_group_mismatch_and_invalid_id(self):
        with self.assertRaises(SourceError):
            self.manager.register('../escape', 'bad')
        t = topic('101')
        t['group']['group_id'] = '999999'
        with self.assertRaisesRegex(SourceError, '不匹配'):
            topic_record(t, GROUP, '调研纪要')

    def test_stagnating_cursor_stops_instead_of_looping(self):
        original = self.client.topics
        def stuck(group_id, limit, end_time=None):
            value = original(group_id, limit, None)
            value['has_more'] = True
            value['next_end_time'] = '2026-10-21T10:01:00.000+0800'
            return value
        self.client.topics = stuck
        with self.assertRaisesRegex(SourceError, '未推进'):
            self.manager.sync(GROUP, max_pages=3, limit=2)

    def test_retry_after_manifest_commit_does_not_duplicate_document(self):
        with patch('app.index.upsert_document', side_effect=RuntimeError('commit interrupted')):
            with self.assertRaises(SourceError):
                self.manager.sync(GROUP, max_pages=1, limit=2)
        result = self.manager.sync(GROUP, max_pages=1, limit=2)
        self.assertEqual(result['counts']['created'], 0)
        with index.connect(self.cfg.db_path) as conn:
            self.assertEqual(conn.execute('select count(*) from documents').fetchone()[0], 2)
            self.assertEqual(conn.execute('select count(*) from document_revisions').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()


class AttachmentDownloadTests(unittest.TestCase):
    def test_download_url_requires_https_official_host(self):
        from app.sources import ZsxqClient
        from unittest.mock import Mock
        client = ZsxqClient()
        for url in ['http://files.zsxq.com/a', 'https://evil.example/a', 'https://files.zsxq.com.evil.example/a']:
            client.call = Mock(return_value={'body': {'succeeded': True, 'resp_data': {'download_url': url}}})
            with self.assertRaises(SourceError):
                client.download_url('123')
        client.call = Mock(return_value={'body': {'succeeded': True, 'resp_data': {'download_url': 'https://files.zsxq.com/a?signature=private'}}})
        self.assertEqual(client.download_url('123'), 'https://files.zsxq.com/a?signature=private')
        with self.assertRaises(SourceError):
            client.download_url('../123')
