import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from app.storage import Storage
from app.revision_cache import revision_content

class RevisionCacheTests(unittest.TestCase):
 def test_reuses_parse_without_sharing_mutable_metadata(self):
  with tempfile.TemporaryDirectory() as tmp:
   st=Storage(Path(tmp));st.ensure_layout();p=st.path('sample.md');p.write_text('---\ntitle: 合成\ntags: [原始]\n---\n完整正文')
   with patch.object(st,'read_revision_text',wraps=st.read_revision_text) as read:
    meta,body=revision_content(st,'sample.md');meta['tags'].append('污染')
    fresh,again=revision_content(st,'sample.md');self.assertEqual(read.call_count,1);self.assertEqual(fresh['tags'],['原始']);self.assertEqual(body,again)
 def test_same_size_atomic_replacement_and_deletion_invalidate_cache(self):
  with tempfile.TemporaryDirectory() as tmp:
   st=Storage(Path(tmp));st.ensure_layout();p=st.path('sample.md');p.write_text('原始正文');self.assertEqual(revision_content(st,'sample.md')[1],'原始正文')
   replacement=st.path('new.md');replacement.write_text('更新正文');replacement.replace(p)
   self.assertEqual(revision_content(st,'sample.md')[1],'更新正文');p.unlink()
   with self.assertRaises(FileNotFoundError):revision_content(st,'sample.md')
 def test_byte_budget_evicts_old_entries(self):
  import app.revision_cache as cache
  with tempfile.TemporaryDirectory() as tmp,patch.object(cache,'_LIMIT',30):
   st=Storage(Path(tmp));st.ensure_layout()
   for name in ['a.md','b.md']:st.path(name).write_text('四个汉字')
   with patch.object(st,'read_revision_text',wraps=st.read_revision_text) as read:
    for name in ['a.md','b.md','a.md']:revision_content(st,name)
    self.assertEqual(read.call_count,3)
