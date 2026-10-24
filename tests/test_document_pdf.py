import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from pypdf import PdfReader
from app.config import load_config
from app.storage import Storage
from app.pipeline import Pipeline
from app import index
from app.document_pdf import export

class DocumentPdfTests(unittest.TestCase):
 def test_export_source_revision_cache_and_download(self):
  with tempfile.TemporaryDirectory() as tmp:
   cfg=replace(load_config(),data_dir=Path(tmp)/'kb');storage=Storage(cfg.data_dir);storage.ensure_layout();index.init_schema(cfg.db_path);pipeline=Pipeline(cfg,storage)
   def ingest(body,title='测试纪要'):
    p=storage.path('inbox/test.jsonl');p.write_text(json.dumps({'schema_version':1,'title':title,'content_text':body,'source_platform':'zsxq','source_space_id':'1','source_item_id':'2','content_type':'research_note','source_url':'https://wx.zsxq.com/group/1/topic/2'},ensure_ascii=False)+'\n');return pipeline.import_file(p)
   ingest('营业收入123亿元，同比增长20%。\n\n'+'现金流信息，未经模型处理。'*300)
   doc=next(storage.iter_manifests());docid=doc['document_id'];old=storage.read_revision_text(doc['revisions'][0]['archive_path'])
   path,name=export(storage,docid);reader=PdfReader(path);text=''.join(p.extract_text() for p in reader.pages)
   self.assertIn('营业收入123亿元',text);self.assertIn('测试纪要',text);self.assertGreater(len(reader.pages),1);self.assertIn('测试纪要',name)
   stat=path.stat().st_mtime_ns;self.assertEqual(export(storage,docid)[0].stat().st_mtime_ns,stat)
   ingest('收入456亿元。','新标题')
   self.assertEqual(export(storage,docid,1)[0],path)
   self.assertNotEqual(export(storage,docid)[0],path)
   self.assertEqual(storage.read_revision_text(doc['revisions'][0]['archive_path']),old)
   from app.web import app as web
   with patch.multiple(web,storage=storage,cfg=cfg,pipeline=pipeline),TestClient(web.app) as client:
    response=client.get(f'/documents/{docid}/export.pdf?revision=1')
    self.assertEqual(response.status_code,200);self.assertEqual(response.headers['content-type'],'application/pdf');self.assertIn('attachment',response.headers['content-disposition']);self.assertTrue(response.content.startswith(b'%PDF'))
    self.assertEqual(client.get(f'/documents/{docid}/export.pdf?revision=999').status_code,404)
    self.assertEqual(client.get('/documents/invalid/export.pdf').status_code,400)
    self.assertIn('导出 PDF',client.get('/documents').text)
