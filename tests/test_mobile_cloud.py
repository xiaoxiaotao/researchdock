import tempfile,unittest
from fastapi.testclient import TestClient
from app.mobile_cloud import create_app

P='p'*40;R='r'*40
DOC={'document_id':'doc_'+'A'*26,'revision':1,'title':'合成测试','body':'收入123亿元','industries':['半导体'],'companies':['示例公司']}
class MobileCloudTests(unittest.TestCase):
 def test_auth_idempotency_version_and_atomic_batch(self):
  with tempfile.TemporaryDirectory() as tmp:
   client=TestClient(create_app(tmp,P,R));read={'Authorization':'Bearer '+R};push={'Authorization':'Bearer '+P}
   self.assertEqual(client.get('/v1/documents').status_code,401)
   self.assertEqual(client.post('/v1/sync',headers=read,json={'library_id':'demo','documents':[DOC]}).status_code,401)
   response=client.post('/v1/sync',headers=push,json={'library_id':'demo','documents':[DOC]});self.assertEqual(response.status_code,200)
   self.assertEqual(client.post('/v1/sync',headers=push,json={'library_id':'demo','documents':[DOC]}).json()['changed'],0)
   rows=client.get('/v1/documents',headers=read).json();self.assertEqual(len(rows['documents']),1);self.assertNotIn('body',rows['documents'][0])
   self.assertEqual(client.get('/v1/documents/'+DOC['document_id'],headers=read).json()['body'],DOC['body'])
   altered={**DOC,'body':'改写同一修订'}
   extra={**DOC,'document_id':'doc_'+'B'*26}
   self.assertEqual(client.post('/v1/sync',headers=push,json={'library_id':'demo','documents':[extra,altered]}).status_code,409)
   self.assertEqual(len(client.get('/v1/documents',headers=read).json()['documents']),1)
   self.assertEqual(client.post('/v1/sync',headers=push,json={'library_id':'other','documents':[]}).status_code,409)
   bad={**DOC,'api_key':'private'}
   self.assertEqual(client.post('/v1/sync',headers=push,json={'library_id':'demo','documents':[bad]}).status_code,422)
 def test_assets_require_auth_and_document_reference(self):
  import hashlib
  with tempfile.TemporaryDirectory() as tmp:
   client=TestClient(create_app(tmp,P,R));read={'Authorization':'Bearer '+R};push={'Authorization':'Bearer '+P}
   data=b'%PDF-1.7 synthetic';digest=hashlib.sha256(data).hexdigest()
   self.assertEqual(client.post('/v1/assets/'+digest,content=data).status_code,401)
   self.assertEqual(client.post('/v1/assets/'+digest,content=b'wrong',headers=push).status_code,422)
   self.assertEqual(client.post('/v1/assets/'+digest,content=data,headers=push).status_code,200)
   self.assertEqual(client.get('/v1/assets/'+digest,headers=read).status_code,404)
   doc={**DOC,'assets':[{'id':digest,'name':'合成.pdf','type':'pdf'}]}
   client.post('/v1/sync',headers=push,json={'library_id':'demo','documents':[doc]})
   self.assertEqual(client.get('/v1/assets/'+digest,headers=read).content,data)
   self.assertEqual(client.post('/v1/sync',headers=push,json={'library_id':'demo','documents':[],'deleted_ids':[DOC['document_id']]}).json()['deleted'],1)
   self.assertEqual(client.get('/v1/assets/'+digest,headers=read).status_code,404)

 def test_missing_or_shared_tokens_fail_closed(self):
  with tempfile.TemporaryDirectory() as tmp:
   for p,r in [('',''),(P,P)]:self.assertEqual(TestClient(create_app(tmp,p,r)).get('/v1/documents').status_code,503)

 def test_company_codes_roundtrip_and_reject_conflicting_identity(self):
  with tempfile.TemporaryDirectory() as tmp:
   client=TestClient(create_app(tmp,P,R));push={'Authorization':'Bearer '+P};read={'Authorization':'Bearer '+R}
   ref={'name':'示例公司','canonical_name':'示例公司','security_id':'hk00700','code':'00700','exchange':'hk'}
   doc={**DOC,'company_securities':[ref]}
   self.assertEqual(client.post('/v1/sync',headers=push,json={'library_id':'demo','documents':[doc]}).status_code,200)
   self.assertEqual(client.get('/v1/documents',headers=read).json()['documents'][0]['company_securities'],[ref])
   self.assertEqual(client.get('/v1/documents/'+DOC['document_id'],headers=read).json()['company_securities'],[ref])
   for bad in [{**ref,'code':'700'},{**ref,'security_id':'sz000001'},{**ref,'name':'未关联公司'}]:
    self.assertEqual(client.post('/v1/sync',headers=push,json={'library_id':'demo','documents':[{**DOC,'company_securities':[bad]}]}).status_code,422)
