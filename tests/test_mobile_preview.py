import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

class MobilePreviewTests(unittest.TestCase):
 def test_preview_does_not_require_or_access_private_library(self):
  from app.web import app as web
  with patch.object(web,'_conn',side_effect=AssertionError('No library access in mockup')):
   response=TestClient(web.app).get('/mobile-preview')
  self.assertEqual(response.status_code,200)
  self.assertEqual(response.headers['cache-control'],'no-store')
  self.assertIn('全部为合成示例',response.text)
  self.assertIn('原型的离线开关只改变展示状态',response.text)
  self.assertNotIn('api.deepseek.com',response.text)
  self.assertNotIn('fetch(',response.text)
