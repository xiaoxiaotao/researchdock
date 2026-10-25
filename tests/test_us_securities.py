import tempfile,unittest
from pathlib import Path
from app.storage import Storage
from app.securities import Securities,code_hint
from app.us_securities import parse,ingest,matches
class USDirectoryTests(unittest.TestCase):
 def test_parser_excludes_etfs_test_and_derivatives(self):
  text='Symbol|Security Name|Listing Exchange|ETF|Test Issue\nNVDA|NVIDIA Corporation - Common Stock|Q|N|N\nABC|Synthetic ETF|N|Y|N\nTEST|Synthetic|Q|N|Y\nAB.W|Synthetic Warrants|N|N|N\nBRK.B|Berkshire Hathaway Class B Common Stock|N|N|N\nFile Creation Time:20261025||||\n'
  rows=parse(text);self.assertEqual([r['code'] for r in rows],['NVDA','BRK.B']);self.assertEqual(rows[0]['name'],'NVIDIA Corporation')
 def test_alias_share_classes_and_market_isolation(self):
  with tempfile.TemporaryDirectory() as tmp:
   catalog=Securities(Storage(Path(tmp)));catalog.ingest([{'code':'600001','zwjc':'合成沪股','category':'A股'}]);catalog.ingest_hk([{'code':'00123','name':'合成港股'}])
   rows=[{'code':'NVDA','name':'NVIDIA Corporation'},{'code':'GOOG','name':'Alphabet Inc.'},{'code':'GOOGL','name':'Alphabet Inc.'},{'code':'AI','name':'C3.ai Inc.'}]
   ingest(catalog,rows);found=matches(catalog,['英伟达','谷歌','AI','NVDA.US']);self.assertEqual(found['英伟达'][0]['code'],'NVDA');self.assertEqual(len(found['谷歌']),2);self.assertNotIn('AI',found);self.assertEqual(found['NVDA.US'][0]['security_id'],'usNVDA')
   catalog.ingest([{'code':'600001','zwjc':'合成沪股','category':'A股'}]);self.assertEqual(catalog.stats()['us_count'],4);self.assertEqual(catalog.stats()['hk_count'],1)
   self.assertEqual(code_hint('BRK.B.US'),('BRK.B','us'))
   with self.assertRaises(ValueError):ingest(catalog,[{'code':'NVDA','name':'NVIDIA Corporation'}])
   self.assertEqual(catalog.stats()['us_count'],4)
 def test_recycled_ticker_does_not_keep_old_chinese_aliases(self):
  with tempfile.TemporaryDirectory() as tmp:
   catalog=Securities(Storage(Path(tmp)));ingest(catalog,[{'code':'NVDA','name':'NVIDIA Corporation'}]);self.assertIn('英伟达',matches(catalog,['英伟达']))
   ingest(catalog,[{'code':'NVDA','name':'Different Issuer'}]);self.assertNotIn('英伟达',matches(catalog,['英伟达']))
