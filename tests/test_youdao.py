import json
import tempfile
import unittest
from pathlib import Path
import httpx
from app.youdao import links,extract,fetch,enrich
from app.storage import Storage
from app.sources import topic_record

KEY='0123456789abcdef0123456789abcdef'
URL='https://share.note.youdao.com/ynoteshare/index.html?id='+KEY

class YoudaoTests(unittest.TestCase):
 def test_real_href_not_shortened_title(self):
  r=topic_record({'topic_id':'123','content':'纪要 <e type="web" href="https%3A%2F%2Fshare.note.youdao.com%2Fynoteshare%2Findex.html%3Fid%3D'+KEY+'" title="https..." />'},'1','测试')
  self.assertEqual(links(r['content_text'])[0][0],KEY)
  self.assertEqual(links(URL.replace('share.note.youdao.com','share.note.youdao.com.evil.test')),[])
 def test_extract_runs_and_images_no_format_metadata(self):
  tree={'5':[{'5':[{'7':[{'8':'收入123亿元。'*8,'9':[{'0':'secret-font'}]},{'8':'利润45亿元。'}]}]},{'6':'im','4':{'u':'https://note.youdao.com/yws/public/resource/'+KEY+'/a.png'}}]}
  note=extract({'tl':'标题','content':json.dumps(tree)},KEY)
  self.assertIn('利润45亿元',note['body']);self.assertIn('![有道笔记原图]',note['body']);self.assertNotIn('secret-font',note['body'])
  with self.assertRaises(ValueError):extract({'error':'1014'},KEY)
 def test_cache_and_failure_keep_source(self):
  with tempfile.TemporaryDirectory() as tmp:
   storage=Storage(Path(tmp)/'kb');storage.ensure_layout()
   def handler(req):return httpx.Response(200,json={'tl':'标题','content':json.dumps({'5':[{'7':[{'8':'这是一份收入和利润的完整纪要。'*8}]}]})})
   a=fetch(storage,KEY,httpx.MockTransport(handler));b=fetch(storage,KEY,httpx.MockTransport(lambda r: self.fail('cache missed')))
   self.assertEqual(a,b)
   record=enrich(storage,{'content_text':'原帖 '+URL})
   self.assertIn('有道笔记正文',record['content_text']);self.assertTrue(record['content_text'].startswith('原帖'))
