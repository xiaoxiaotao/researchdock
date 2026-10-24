import io,tempfile,unittest
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
from app import index
from app.config import load_config
from app.storage import Storage
from app.pipeline import Pipeline
from app.international_reports import download,asset_path
from app.international_uploads import upload,uploaded_file
from app.report_translation import translate,state,original,chunks,valid_translation

def pdf_bytes():
    writer=PdfWriter();page=writer.add_blank_page(width=400,height=400)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 30 350 Td (Revenue in 2026 is 10 million. This is a user supplied test report.) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(stream);out=io.BytesIO();writer.write(out);return out.getvalue()

class InternationalReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.cfg=replace(load_config(),data_dir=Path(self.tmp.name)/'kb');self.storage=Storage(self.cfg.data_dir);self.storage.ensure_layout();index.init_schema(self.cfg.db_path);self.pipeline=Pipeline(self.cfg,self.storage)
    def tearDown(self):self.tmp.cleanup()
    def test_public_pdf_verified_and_cached_rejects_html(self):
        response=download(self.storage,'gs-americas-first-2026',httpx.MockTransport(lambda r:httpx.Response(200,content=pdf_bytes())))
        self.assertEqual(response['pages'],1);self.assertTrue(asset_path(self.storage,'gs-americas-first-2026').read_bytes().startswith(b'%PDF-'))
        self.assertEqual(download(self.storage,'gs-americas-first-2026')['sha256'],response['sha256'])
        with self.assertRaises(ValueError):download(self.storage,'citi-exec-x-2026',httpx.MockTransport(lambda r:httpx.Response(200,text='<html>Login</html>')))
    def test_uploaded_pdf_and_version_pinned_translation_resume(self):
        result=upload(self.pipeline,'jpmorgan',pdf_bytes(),'Test report',filename='test.pdf')
        doc=result['document_id'];revision=result['revision']
        self.assertEqual(uploaded_file(self.storage,doc)[0].read_bytes(),pdf_bytes())
        _,body=original(self.storage,doc,revision);self.assertIn('Revenue',body)
        calls=[]
        client=SimpleNamespace(settings=lambda:{'model':'test'},call=lambda *a,**kw:(calls.append(a) or {'translation':'2026年收入为10 million。这是用户提供的测试报告。'}))
        translated=translate(self.storage,doc,revision,client)
        self.assertEqual(translated['status'],'succeeded');self.assertEqual(len(calls),1)
        self.assertEqual(translated['segments'][0]['source'],body)
        translate(self.storage,doc,revision,client);self.assertEqual(len(calls),1)
        self.assertEqual(state(self.storage,doc,revision)['revision'],revision)
    def test_translation_does_not_accept_public_index_or_changed_numbers(self):
        from app.international_sources import import_reports
        import_reports(self.pipeline,'jpmorgan',[{'title':'Index only','url':'https://www.jpmorgan.com/research/test'}])
        doc=next(self.storage.iter_manifests())['document_id']
        with self.assertRaises(ValueError):original(self.storage,doc,1)
        with self.assertRaises(ValueError):valid_translation('Revenue is 10 in 2026.','2026年收入为100。')
        source=('Paragraph with 10.\n\n'*1000)
        self.assertEqual(''.join(chunks(source)),source)
        self.assertTrue(all(len(p)<=4500 for p in chunks(source)))
    def test_upload_and_reader_routes(self):
        from fastapi.testclient import TestClient
        from app.web import app as web
        with patch.object(web,'storage',self.storage),patch.object(web,'pipeline',self.pipeline):
            client=TestClient(web.app)
            response=client.post('/api/v1/international/citi/upload-pdf?title=Test',content=pdf_bytes(),headers={'Content-Type':'application/pdf','X-File-Name':'test.pdf'})
            self.assertEqual(response.status_code,200)
            reader=client.get(response.json()['url']);self.assertEqual(reader.status_code,200);self.assertIn('生成完整中文译文',reader.text)
            self.assertEqual(client.get('/international/reports').status_code,200)
            self.assertEqual(client.get('/international/reports/gs-americas-first-2026?lang=zh').status_code,200)
            self.assertEqual(client.get('/international/reports/../../bad').status_code,404)
    def test_translation_number_failure_retains_source_and_can_resume(self):
        result=upload(self.pipeline,'citi',pdf_bytes(),'Test report')
        doc=result['document_id'];revision=result['revision']
        bad=SimpleNamespace(settings=lambda:{'model':'test'},call=lambda *a,**kw:{'translation':'2026年收入为100。'})
        failed=translate(self.storage,doc,revision,bad)
        self.assertEqual(failed['status'],'failed');self.assertEqual(failed['completed'],0)
        self.assertEqual(failed['segments'],[])
        good=SimpleNamespace(settings=lambda:{'model':'test'},call=lambda *a,**kw:{'translation':'2026年收入为10。这是用户提供的测试报告。'})
        completed=translate(self.storage,doc,revision,good)
        self.assertEqual(completed['status'],'succeeded')
        self.assertIn('Revenue',original(self.storage,doc,revision)[1])
