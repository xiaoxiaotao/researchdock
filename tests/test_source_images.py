import base64,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from contextlib import nullcontext
import httpx
from app.storage import Storage,atomic_write_text
from app.source_images import load,safe_url,_TOPICS
from app.sources import SourceError

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=')
class SourceImageTests(unittest.TestCase):
    def setUp(self):
        _TOPICS.clear();self.tmp=tempfile.TemporaryDirectory();self.storage=Storage(Path(self.tmp.name)/'kb',allow_create=True);self.storage.ensure_layout()
        self.doc='doc_'+'A'*26
        self.meta={'source':{'platform':'zsxq','item_id':'123','space_id':'456'},'source_attachments':[{'kind':'image','image_id':'789'}]}
        self.topic={'topic_id':'123','group':{'group_id':'456'},'images':[{'image_id':'789','large':{'url':'https://images.zsxq.com/picture?signature=secret'}}]}
        self.client=SimpleNamespace(detail=Mock(return_value=self.topic))
        self.transport=httpx.MockTransport(lambda request:httpx.Response(200,content=PNG))
    def tearDown(self):self.tmp.cleanup();_TOPICS.clear()
    def test_load_cache_revision_and_no_signed_url_persisted(self):
        path,media=load(self.storage,self.client,self.doc,1,self.meta,'789',self.transport)
        self.assertEqual(path.read_bytes(),PNG);self.assertEqual(media,'image/png')
        self.assertNotIn('signature',path.with_suffix('.json').read_text())
        self.client.detail.reset_mock();load(self.storage,self.client,self.doc,1,self.meta,'789')
        self.client.detail.assert_not_called()
        other,_=load(self.storage,self.client,self.doc,2,self.meta,'789',self.transport)
        self.assertNotEqual(path,other)
    def test_reject_other_image_group_urls_and_nonimage(self):
        with self.assertRaises(SourceError):load(self.storage,self.client,self.doc,1,self.meta,'999',self.transport)
        self.client.detail.assert_not_called()
        self.topic['group']['group_id']='other'
        with self.assertRaises(SourceError):load(self.storage,self.client,self.doc,1,self.meta,'789',self.transport)
        for url in ['http://images.zsxq.com/a','https://images.zsxq.com.evil.test/a','https://localhost/a','https://images.zsxq.com:bad/a','https://user@images.zsxq.com/a']:
            with self.assertRaises(SourceError):safe_url(url)
        self.topic['group']['group_id']='456';_TOPICS.clear()
        with self.assertRaises(SourceError):load(self.storage,self.client,self.doc,1,self.meta,'789',httpx.MockTransport(lambda r:httpx.Response(200,content=b'<script>bad</script>')))
    def test_expired_url_can_refresh_on_next_request(self):
        with self.assertRaises(SourceError):load(self.storage,self.client,self.doc,1,self.meta,'789',httpx.MockTransport(lambda r:httpx.Response(403)))
        load(self.storage,self.client,self.doc,1,self.meta,'789',self.transport)
        self.assertEqual(self.client.detail.call_count,2)
    def test_local_route_returns_image_and_rejects_missing_revision(self):
        from fastapi.testclient import TestClient
        from app.web import app as web
        load(self.storage,self.client,self.doc,1,self.meta,'789',self.transport)
        archive='archive/test-image.md';atomic_write_text(self.storage.path(archive),'---\nsource:\n  platform: zsxq\n  item_id: "123"\n  space_id: "456"\nsource_attachments:\n- kind: image\n  image_id: "789"\n---\n「图片」')
        with patch.object(web,'storage',self.storage),patch.object(web,'sources',SimpleNamespace(client=self.client)),patch.object(web,'_conn',return_value=nullcontext(None)),patch.object(web.index,'get_document',return_value={'document_id':self.doc}),patch.object(web.index,'get_revisions',return_value=[{'revision':1,'archive_path':archive}]):
            client=TestClient(web.app);r=client.get(f'/documents/{self.doc}/images/789?revision=1')
            self.assertEqual(r.status_code,200);self.assertEqual(r.content,PNG);self.assertEqual(r.headers['content-type'],'image/png')
            self.assertEqual(r.headers['cross-origin-resource-policy'],'same-origin')
            self.assertEqual(client.get(f'/documents/{self.doc}/images/789?revision=2').status_code,404)
