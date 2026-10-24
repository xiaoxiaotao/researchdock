import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from scripts import build_release
from app.research import Secrets
from app.storage import Storage

class ReleaseTests(unittest.TestCase):
 def test_whitelist_excludes_private_data_and_symlinks(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'app').mkdir();(root/'app/main.py').write_text('print("demo")')
   (root/'README.md').write_text('demo');(root/'kb-data').mkdir();(root/'kb-data/private.json').write_text('private')
   (root/'config.yaml').write_text('private config')
   with patch.object(build_release,'FILES',{'README.md'}),patch.object(build_release,'TREES',('app',)):
    self.assertEqual({str(p.relative_to(root)) for p in build_release.selected(root)},{'README.md','app/main.py'})
    (root/'app/link.py').symlink_to(root/'config.yaml')
    with self.assertRaises(ValueError):build_release.selected(root)
 def test_scan_reports_only_paths_and_rules(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);p=root/'sample.py';p.write_text('key='+'sk-'+'x'*24)
   issues=build_release.audit([p],root)
   self.assertEqual(issues,[('sample.py','api-key')])
   (root/'kb-data/catalog/sources').mkdir(parents=True)
   (root/'kb-data/catalog/sources/demo.json').write_text(json.dumps({'group_id':'12345678900000'}))
   p.write_text('group='+str(12345678900000));self.assertIn(('sample.py','local-source-identifier'),build_release.audit([p],root))
 def test_environment_key_has_priority_and_no_disk_write(self):
  with tempfile.TemporaryDirectory() as tmp:
   storage=Storage(Path(tmp)/'kb');storage.ensure_layout();backend=Mock()
   with patch('keyring.get_keyring',return_value=backend),patch.dict(os.environ,{'DEEPSEEK_API_KEY':'synthetic-test-key'}):
    secrets=Secrets(storage);self.assertEqual(secrets.get(),'synthetic-test-key');backend.get_password.assert_not_called()
   from keyring.errors import NoKeyringError
   backend.get_password.side_effect=NoKeyringError()
   with patch('keyring.get_keyring',return_value=backend),patch.dict(os.environ,{},clear=True):
    self.assertIsNone(Secrets(storage).get())
