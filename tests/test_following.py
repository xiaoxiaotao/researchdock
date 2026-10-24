import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from app.storage import Storage
from app.following import preferences,save_preferences,subtopics,matched_notes

class FollowingTests(unittest.TestCase):
    def test_save_validates_ids_and_preserves_reviewed_versions(self):
        with tempfile.TemporaryDirectory() as d:
            s=Storage(Path(d)/'kb',allow_create=True)
            # Storage is initialized by its regular marker operation.
            s.path('catalog').mkdir(parents=True,exist_ok=True)
            save_preferences(s,{'stocks':['s1'],'industries':['半导体']},{'s1'})
            self.assertEqual(preferences(s)['stocks'],['s1'])
            with self.assertRaises(ValueError):save_preferences(s,{'stocks':['bogus'],'industries':[]},{'s1'})
    def test_subtopics_use_text_and_parent_industry(self):
        self.assertEqual(subtopics({'industries':['新能源'],'title':'锂电储能'},''),[('新能源','电池与储能')])
        self.assertEqual(subtopics({'industries':['医药生物'],'title':'光伏'},''),[])
    def test_watch_union_deduplicates_and_new_revision_is_new(self):
        p=SimpleNamespace(notes=[{'document_id':'a','revision':2,'industries':['半导体']}],stocks=lambda:[{'stock_id':'s1','document_ids':{'a'}}])
        result=matched_notes(p,{'stocks':['s1'],'industries':['半导体'],'seen':['a:1']})
        self.assertEqual(len(result),1)
        self.assertTrue(result[0]['is_new'])
        self.assertFalse(matched_notes(p,{'stocks':['s1'],'industries':[],'seen':['a:2']})[0]['is_new'])

class FollowingApiTests(unittest.TestCase):
    def test_preferences_and_manual_industry_routes(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        import threading
        from app.web import app as web
        from app.storage import read_json
        with tempfile.TemporaryDirectory() as d:
            s=Storage(Path(d)/'kb',allow_create=True)
            s.path('catalog').mkdir(parents=True,exist_ok=True)
            doc='doc_'+'A'*26
            fake=SimpleNamespace(lock=threading.RLock(),editorial=lambda:read_json(s.path('catalog/editorial.json')) or {})
            publication=SimpleNamespace(stocks=lambda:[{'stock_id':'known'}])
            with patch.object(web,'storage',s),patch.object(web,'research',fake),patch.object(web,'Publications',return_value=publication),patch.object(s,'read_manifest',return_value={'current_revision':1}):
                client=TestClient(web.app)
                self.assertEqual(client.post('/api/v1/following',json={'stocks':['unknown'],'industries':[]}).status_code,400)
                self.assertEqual(client.post('/api/v1/following',json={'stocks':['known'],'industries':['半导体']}).status_code,200)
                self.assertEqual(client.post('/api/v1/research/industries/'+doc,json={'industries':['半导体','通信']}).status_code,200)
                self.assertEqual(fake.editorial()[doc]['industries'],['半导体','通信'])
                self.assertEqual(client.post('/api/v1/research/industries/'+doc,json={'industries':None}).status_code,200)
                self.assertNotIn('industries',fake.editorial()[doc])
                self.assertEqual(client.post('/api/v1/following',headers={'Origin':'https://untrusted.example'},json={'stocks':[],'industries':[]}).status_code,403)
