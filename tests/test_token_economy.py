import unittest
from app.token_economy import model_text,analysis_hash

class TokenEconomyTests(unittest.TestCase):
 def test_prose_complete_images_and_urls_removed(self):
  quote='2026年收入54.96亿元，同比增长22.50%。'
  body=quote+'\n\n![原图](https://note.youdao.com/a.png)\n来源：https://example.com/a\n\n风险：现金流波动。'
  result=model_text(body)
  self.assertIn(quote,result);self.assertIn('风险：现金流波动。',result)
  self.assertNotIn('https://',result);self.assertNotIn('![',result)
 def test_transport_changes_share_hash_but_prose_changes_do_not(self):
  self.assertEqual(analysis_hash('收入123亿元\nhttps://example.com/a'),analysis_hash('收入123亿元\nhttps://example.com/b'))
  self.assertNotEqual(analysis_hash('收入123亿元'),analysis_hash('收入124亿元'))
