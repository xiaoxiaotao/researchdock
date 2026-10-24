import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.config import load_config
from app.storage import Storage
from app.doctor import checks

class DoctorTests(unittest.TestCase):
 def test_no_credentials_network_or_directory_creation(self):
  with tempfile.TemporaryDirectory() as tmp:
   cfg=replace(load_config(),data_dir=Path(tmp)/'new-library')
   with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'synthetic-secret-for-test'}),patch('httpx.Client',side_effect=AssertionError('network prohibited')),patch('keyring.get_password',side_effect=AssertionError('keyring prohibited')):
    report=checks(cfg)
   self.assertTrue(report['ok']);self.assertFalse(report['network_accessed']);self.assertEqual(report['paid_requests'],0)
   self.assertNotIn('synthetic-secret-for-test',json.dumps(report));self.assertFalse(cfg.data_dir.exists())
 def test_missing_optional_dependency_does_not_block(self):
  with tempfile.TemporaryDirectory() as tmp:
   cfg=replace(load_config(),data_dir=Path(tmp)/'kb')
   with patch('app.doctor.shutil.which',return_value=None):report=checks(cfg)
   self.assertTrue(report['ok']);self.assertEqual(next(r for r in report['checks'] if r['key']=='poppler')['status'],'optional')
   with patch('app.doctor.sqlite3.connect',side_effect=sqlite3.OperationalError('no fts')):report=checks(cfg)
   self.assertFalse(report['ok'])
 def test_setup_available_without_initializing_library(self):
  from app.web import app as web
  with tempfile.TemporaryDirectory() as tmp:
   cfg=replace(load_config(),data_dir=Path(tmp)/'kb');storage=Storage(cfg.data_dir)
   with patch.multiple(web,cfg=cfg,storage=storage),patch.dict(os.environ,{'DEEPSEEK_API_KEY':'synthetic-setup-key'}):
    response=TestClient(web.app).get('/setup')
   self.assertEqual(response.status_code,200);self.assertIn('导入第一份资料',response.text);self.assertIn('安装检查',response.text);self.assertNotIn('synthetic-setup-key',response.text)
   self.assertFalse(cfg.data_dir.exists())
