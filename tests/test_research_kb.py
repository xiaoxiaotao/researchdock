"""Regression coverage in isolated temporary libraries, never the user's data."""
import io
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from app import index
from app.config import load_config
from app.jobs import ImportJobs
from app.pipeline import Pipeline
from app.storage import Storage, atomic_write_json


def pdf_bytes(texts, encrypted=False):
    writer = PdfWriter()
    writer.add_metadata({'/Title': 'Synthetic industry report'})
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    for text in texts:
        page = writer.add_blank_page(width=595, height=842)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        safe = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        stream.set_data(f'BT /F1 12 Tf 40 780 Td ({safe}) Tj ET'.encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    if encrypted:
        writer.encrypt('password')
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


class LibraryCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='stock-kb-test-')
        self.cfg = replace(load_config(), data_dir=Path(self.temp.name) / 'kb')
        self.storage = Storage(self.cfg.data_dir)
        self.storage.ensure_layout()
        index.init_schema(self.cfg.db_path)
        self.pipeline = Pipeline(self.cfg, self.storage)

    def tearDown(self):
        self.temp.cleanup()

    def import_record(self, **changes):
        record = {'title': '公司报告', 'content_text': '摘要段落\n\n' + '背景。' * 100 + '\n\n液冷服务器订单增长 35%，金额 1.2 亿元。',
                  'source_platform': 'test', 'source_item_id': 'stable-1', 'stocks': []}
        record.update(changes)
        (self.cfg.inbox_dir / 'records.jsonl').write_text(json.dumps(record, ensure_ascii=False) + '\n')
        return self.pipeline.scan()

    def query(self, q):
        with index.connect(self.cfg.db_path) as conn:
            return index.list_documents(conn, q=q)

    def only_manifest(self):
        return next(self.storage.iter_manifests())

    def test_search_full_body_and_short_chinese(self):
        self.import_record()
        for term in ['液冷服务器', '液冷', '液', '35%', '1.2 亿元']:
            rows, total = self.query(term)
            self.assertEqual(total, 1, term)
            self.assertIn(term, rows[0]['search_excerpt'])
        self.assertEqual(self.query('不存在')[1], 0)

    def test_search_literal_syntax_and_injection(self):
        self.import_record(content_text='收益 100% A_B quote"x OR (growth)')
        for term in ['100%', 'A_B', 'quote"x', 'OR (growth)']:
            self.assertEqual(self.query(term)[1], 1, term)
        self.assertEqual(self.query("' OR 1=1 --")[1], 0)
        self.assertEqual(self.query('%')[1], 1)
        self.assertEqual(self.query('___')[1], 0)

    def test_company_code_name_and_institution_search(self):
        self.import_record(stocks=[{'code': '000001', 'name': '示例公司'}], institution='示例证券')
        for term in ['000001', '示例公司', '示例证券']:
            self.assertEqual(self.query(term)[1], 1)

    def test_metadata_only_changes_are_versioned(self):
        self.import_record()
        self.import_record(title='修正标题', institution='研究机构')
        manifest = self.only_manifest()
        self.assertEqual(manifest['current_revision'], 2)
        self.assertEqual(manifest['fields']['institution'], '研究机构')
        # A different JSON serialization still produces no new revision.
        payload = json.loads((next(self.storage.path('processed').glob('*/records.jsonl'))).read_text())
        payload.update(title='修正标题', institution='研究机构')
        (self.cfg.inbox_dir / 'renamed.jsonl').write_text(json.dumps(payload, indent=0).replace('\n', '') + '\n')
        self.assertEqual(self.pipeline.scan()['duplicated'], 1)
        self.assertEqual(self.only_manifest()['current_revision'], 2)

    def test_reconcile_repairs_existing_stale_document(self):
        self.import_record()
        self.import_record(title='新版', content_text='最新正文与证据')
        manifest = self.only_manifest()
        with index.connect(self.cfg.db_path) as conn:
            conn.execute("UPDATE documents SET title='旧版',current_revision=1")
            conn.execute('DELETE FROM document_revisions WHERE revision=2')
        self.pipeline.reconcile()
        with index.connect(self.cfg.db_path) as conn:
            doc = index.get_document(conn, manifest['document_id'])
            self.assertEqual((doc['title'], doc['current_revision']), ('新版', 2))
        self.assertEqual(self.query('最新正文')[1], 1)
        self.assertEqual(self.query('液冷服务器')[1], 0)

    def test_pending_and_removed_associations_survive_rebuild(self):
        self.import_record(stocks=[{'code': '000001', 'name': '待确认', 'evidence': 'inferred'}, {'code': '600000'}])
        self.pipeline.rebuild_index()
        with index.connect(self.cfg.db_path) as conn:
            states = {r['code']: r['status'] for r in index.stocks_of_document(conn, self.only_manifest()['document_id'])}
        self.assertEqual(states['000001'], 'pending')
        self.import_record(stocks=[{'code': '000001', 'name': '待确认', 'evidence': 'inferred'}])
        self.pipeline.rebuild_index()
        with index.connect(self.cfg.db_path) as conn:
            refs = index.stocks_of_document(conn, self.only_manifest()['document_id'])
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]['status'], 'pending')

    def test_import_history_survives_rebuild(self):
        self.import_record()
        self.pipeline.rebuild_index()
        with index.connect(self.cfg.db_path) as conn:
            self.assertEqual(len(index.recent_batches(conn)), 1)
            self.assertEqual(len(index.recent_results(conn)), 1)

    def test_pdf_page_search_original_and_rebuild(self):
        raw = pdf_bytes(['Executive summary', 'Liquid cooling revenue increased 35 percent.'])
        (self.cfg.inbox_dir / 'report.pdf').write_bytes(raw)
        report = self.pipeline.scan()
        self.assertEqual(report['created'], 1, report)
        manifest = self.only_manifest()
        rev = manifest['revisions'][0]
        self.assertEqual(self.storage.resolve_path(rev['attachment']['path']).read_bytes(), raw)
        self.assertIsNone(manifest['fields']['published_at'])
        self.pipeline.rebuild_index()
        rows, total = self.query('cooling revenue')
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]['search_page'], 2)
        (self.cfg.inbox_dir / 'renamed.pdf').write_bytes(raw)
        self.assertEqual(self.pipeline.scan()['duplicated'], 1)
        self.assertFalse((self.cfg.inbox_dir / 'renamed.pdf').exists())
        self.assertEqual(len(list(self.storage.path('originals').rglob('*.pdf'))), 1)

    def test_failed_pdf_original_retained_and_retryable(self):
        for filename, raw in [('empty.pdf', pdf_bytes([''])), ('locked.pdf', pdf_bytes(['secret'], True)), ('broken.pdf', b'not-a-pdf')]:
            with self.subTest(filename=filename):
                (self.cfg.inbox_dir / filename).write_bytes(raw)
                report = self.pipeline.scan()
                self.assertEqual(report['failed'], 1, report)
                batch = read_batch(self.storage, report['batches'][0]['batch_id'])
                self.assertEqual(self.storage.resolve_path(batch['original']['path']).read_bytes(), raw)
                self.assertEqual(batch['status'], 'failed')
                self.assertTrue(batch['outcomes'][0]['message'])

    def test_partial_batch_retries_valid_records_without_new_revision(self):
        record = {'content_text': '正常正文', 'source_platform': 'test', 'source_item_id': 'one'}
        data = json.dumps(record) + '\n{bad\n'
        (self.cfg.inbox_dir / 'partial.jsonl').write_text(data)
        self.assertEqual(self.pipeline.scan()['created'], 1)
        (self.cfg.inbox_dir / 'partial.jsonl').write_text(data)
        report = self.pipeline.scan()
        self.assertEqual((report['created'], report['duplicated'], report['failed']), (0, 1, 1))
        self.assertEqual(self.only_manifest()['current_revision'], 1)

    def test_archive_integrity_blocks_new_import(self):
        self.import_record()
        rev = self.only_manifest()['revisions'][0]
        self.storage.resolve_path(rev['archive_path']).write_text('corrupted')
        result = self.pipeline.reconcile()
        self.assertTrue(result['problems'])
        with self.assertRaisesRegex(Exception, '校验失败'):
            self.pipeline.scan()

    def test_ready_marker_required(self):
        self.cfg.require_ready_marker = True
        (self.cfg.inbox_dir / 'note.txt').write_text('正文')
        self.assertEqual(self.pipeline.scan()['scanned_files'], 0)
        atomic_write_json(self.cfg.inbox_dir / 'note.txt.ready.json', {})
        self.assertEqual(self.pipeline.scan()['created'], 1)
        self.assertFalse((self.cfg.inbox_dir / 'note.txt.ready.json').exists())

    def test_pdf_metadata_edit_preserves_original_pages_and_history(self):
        raw = pdf_bytes(['Introduction', 'Cooling order evidence'])
        (self.cfg.inbox_dir / 'report.pdf').write_bytes(raw)
        self.pipeline.scan()
        doc_id = self.only_manifest()['document_id']
        result = self.pipeline.update_metadata(doc_id, {'title': '行业报告', 'content_type': 'industry_report',
            'institution': '示例证券', 'report_period': '2026Q3', 'published_at': '2026-10-20',
            'stock_codes': '000001,600000'})
        self.assertEqual(result.revision, 2)
        manifest = self.only_manifest()
        self.assertEqual(manifest['fields']['date_precision'], 'date')
        first, second = manifest['revisions']
        self.assertEqual(first['attachment']['path'], second['attachment']['path'])
        self.assertEqual(self.pipeline.pages_for_revision(second)[1]['text'], 'Cooling order evidence')
        self.assertEqual(len(list(self.storage.path('originals').rglob('*.pdf'))), 1)
        self.pipeline.rebuild_index()
        self.assertEqual(self.query('Cooling')[0][0]['search_page'], 2)
        self.assertEqual(self.query('000001')[1], 1)
        with self.assertRaisesRegex(Exception, 'YYYY-MM-DD'):
            self.pipeline.update_metadata(doc_id, {'published_at': 'yesterday'})
        with self.assertRaisesRegex(Exception, '六位'):
            self.pipeline.update_metadata(doc_id, {'stock_codes': 'bad-code'})

    def test_actual_manifest_commit_before_sql_failure_recovers(self):
        self.import_record()
        real_upsert = index.upsert_document
        def fail_new_revision(conn, doc, revision):
            if doc['current_revision'] == 2:
                raise RuntimeError('simulated interrupted commit')
            return real_upsert(conn, doc, revision)
        with patch('app.index.upsert_document', side_effect=fail_new_revision):
            result = self.import_record(title='崩溃前提交的新标题', content_text='新正文证据')
        self.assertEqual(result['failed'], 1)
        self.assertEqual(self.only_manifest()['current_revision'], 2)
        recovery = self.pipeline.reconcile()
        self.assertFalse(recovery['problems'])
        with index.connect(self.cfg.db_path) as conn:
            row = index.get_document(conn, self.only_manifest()['document_id'])
            self.assertEqual((row['title'], row['current_revision']), ('崩溃前提交的新标题', 2))

    def test_orphan_revision_never_overwritten(self):
        self.import_record()
        manifest = self.only_manifest()
        orphan = self.storage.resolve_path(manifest['revisions'][0]['archive_path']).with_name('r0002.md')
        orphan.write_text('Uncommitted original - preserve me')
        self.import_record(title='后续修订', content_text='另一段新正文')
        self.assertEqual(self.only_manifest()['current_revision'], 3)
        self.assertEqual(orphan.read_text(), 'Uncommitted original - preserve me')

    def test_v1_index_migration_recovers_full_text(self):
        self.import_record()
        with index.connect(self.cfg.db_path) as conn:
            conn.execute('DROP TABLE document_search')
            conn.execute('DROP TABLE document_pages')
            conn.execute('ALTER TABLE documents DROP COLUMN institution')
            conn.execute('ALTER TABLE documents DROP COLUMN report_period')
            conn.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
        index.init_schema(self.cfg.db_path)
        index.init_schema(self.cfg.db_path)
        self.pipeline.reconcile()
        self.assertEqual(self.query('液冷服务器')[1], 1)

    def test_invalid_manifest_is_reported(self):
        self.import_record()
        self.storage.manifest_path(self.only_manifest()['document_id']).write_text('{invalid-json')
        self.assertTrue(self.pipeline.reconcile()['problems'])

    def test_pdf_empty_pages_are_explicit(self):
        (self.cfg.inbox_dir / 'mixed.pdf').write_bytes(pdf_bytes(['Text evidence', '']))
        self.assertEqual(self.pipeline.scan()['created'], 1)
        self.assertEqual(self.only_manifest()['revisions'][0]['attachment']['empty_pages'], [2])

    def test_durable_job_resumes(self):
        (self.cfg.inbox_dir / 'note.txt').write_text('后台导入正文')
        job_id = 'scan_01TEST'
        atomic_write_json(self.storage.path(f'jobs/scans/{job_id}.json'), {
            'job_id': job_id, 'status': 'running', 'created_at': '2026-10-21'})
        jobs = ImportJobs(self.pipeline)
        jobs.start()
        jobs.close()
        self.assertEqual(jobs.recent()[0]['status'], 'succeeded')
        self.assertEqual(self.query('后台导入')[1], 1)


def read_batch(storage, batch_id):
    return json.loads(storage.path(f'jobs/imports/{batch_id}.json').read_text())


class WebTests(unittest.TestCase):
    def test_upload_search_read_original_and_failure(self):
        from fastapi.testclient import TestClient
        import app.web.app as web
        with tempfile.TemporaryDirectory(prefix='stock-kb-web-') as root:
            cfg = replace(load_config(), data_dir=Path(root) / 'kb')
            storage = Storage(cfg.data_dir)
            pipeline = Pipeline(cfg, storage)
            jobs = ImportJobs(pipeline)
            with patch.multiple(web, cfg=cfg, storage=storage, pipeline=pipeline, jobs=jobs, recovery_problems=[]):
                with TestClient(web.app) as client:
                    self.assertEqual(client.get('/health').status_code, 200)
                    self.assertEqual(client.get('/imports').status_code, 200)
                    for name in ['../escape.pdf', '.hidden.pdf', 'bad.exe']:
                        self.assertEqual(client.post('/api/v1/imports/upload', params={'filename': name}, content=b'x').status_code, 400)
                    self.assertEqual(client.post('/api/v1/imports/upload', params={'filename': 'empty.pdf'}, content=b'').status_code, 400)
                    raw = pdf_bytes(['Summary only', 'Evidence in the second page'])
                    response = client.post('/api/v1/imports/upload', params={'filename': '资料.pdf'}, content=raw)
                    self.assertEqual(response.status_code, 202, response.text)
                    jobs.close()
                    # The queue can be restarted after a controlled shutdown.
                    jobs.start()
                    with index.connect(cfg.db_path) as conn:
                        docs, count = index.list_documents(conn)
                    self.assertEqual(count, 1)
                    doc_id = docs[0]['document_id']
                    page = client.get('/documents', params={'q': 'Evidence'})
                    self.assertEqual(page.status_code, 200, page.text)
                    self.assertIn('命中第 2 页', page.text)
                    self.assertIn(f'/documents/{doc_id}#page-2', page.text)
                    detail = client.get(f'/documents/{doc_id}')
                    self.assertEqual(detail.status_code, 200)
                    self.assertIn('id="page-2"', detail.text)
                    original = client.get(f'/documents/{doc_id}/original')
                    self.assertEqual(original.content, raw)
                    self.assertEqual(original.headers['content-type'], 'application/pdf')
                    self.assertEqual(client.get(f'/documents/{doc_id}?revision=999').status_code, 404)
                    response = client.post(f'/api/v1/documents/{doc_id}/metadata', json={
                        'title': '整理后的行业报告', 'content_type': 'industry_report', 'institution': '示例机构'})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()['revision'], 2)
                    self.assertIn('整理后的行业报告', client.get(f'/documents/{doc_id}').text)
                    old_page = client.get(f'/documents/{doc_id}?revision=1')
                    self.assertIn('<h1>Synthetic industry report</h1>', old_page.text)
                    self.assertEqual(client.get(f'/documents/{doc_id}/original?revision=2').content, raw)
                    self.assertEqual(client.post(f'/api/v1/documents/{doc_id}/metadata', json={'published_at': 'bad'}).status_code, 400)
                    cfg.max_file_mb = 0
                    self.assertEqual(client.post('/api/v1/imports/upload', params={'filename': 'oversize.pdf'}, content=b'nonempty').status_code, 413)
                    self.assertFalse(any(cfg.inbox_dir.glob('.upload-*')))
                    cfg.max_file_mb = 20
                    self.assertEqual(client.get('/stocks').status_code, 200)
                    self.assertEqual(client.get('/').status_code, 200)
                    # Failed PDFs retain downloadable originals and offer a retry.
                    self.assertEqual(client.post('/api/v1/imports/upload', params={'filename': 'scanned.pdf'}, content=pdf_bytes([''])).status_code, 202)
                    jobs.close()
                    jobs.start()
                    with index.connect(cfg.db_path) as conn:
                        failed = conn.execute("SELECT batch_id FROM import_batches WHERE status='failed'").fetchone()[0]
                    page = client.get('/imports')
                    self.assertEqual(page.status_code, 200)
                    self.assertIn('重新导入', page.text)
                    self.assertIn('OCR', page.text)
                    self.assertEqual(client.get(f'/imports/{failed}/original').status_code, 200)
                    self.assertEqual(client.post(f'/imports/{failed}/retry', follow_redirects=False).status_code, 303)
                    jobs.close()


if __name__ == '__main__':
    unittest.main()
