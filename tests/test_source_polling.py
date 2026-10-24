from datetime import datetime,timedelta
from unittest.mock import patch
from app.utils import TZ
from app.storage import atomic_write_json,read_json
from test_sources import SourceTests,GROUP

class SourcePollingTests(SourceTests):
    def test_polling_without_model_key_interval_busy_and_backoff(self):
        atomic_write_json(self.storage.path('catalog/research-settings.json'),{'poll_enabled':True,'poll_minutes':5})
        now=datetime(2026,10,23,10,tzinfo=TZ)
        with patch.object(self.manager,'enqueue') as enqueue:
            self.manager.poll_once(now);enqueue.assert_called_once_with(GROUP,'live')
            self.manager.poll_once(now+timedelta(minutes=4));self.assertEqual(enqueue.call_count,1)
            self.manager.poll_once(now+timedelta(minutes=5));self.assertEqual(enqueue.call_count,2)
            source=read_json(self.manager.path(GROUP));source['status']='failed';atomic_write_json(self.manager.path(GROUP),source)
            self.manager.poll_once(now+timedelta(minutes=10));self.assertEqual(enqueue.call_count,2)
            self.manager.poll_once(now+timedelta(minutes=20));self.assertEqual(enqueue.call_count,3)
            source['status']='running';atomic_write_json(self.manager.path(GROUP),source)
            self.manager.poll_once(now+timedelta(hours=1));self.assertEqual(enqueue.call_count,3)
    def test_polling_disabled_and_live_collection_preserves_history_cursor(self):
        with patch.object(self.manager,'enqueue') as enqueue:
            self.manager.poll_once();enqueue.assert_not_called()
        source=read_json(self.manager.path(GROUP));source.update(history_cursor='keep-history',latest_pending_cursor='keep-latest')
        atomic_write_json(self.manager.path(GROUP),source)
        self.manager.sync(GROUP,mode='live')
        source=read_json(self.manager.path(GROUP))
        self.assertEqual(source['history_cursor'],'keep-history')
        self.assertEqual(source['latest_pending_cursor'],'keep-latest')
        self.assertTrue(source.get('live_latest_at'))

    def test_live_poll_skips_old_details_and_never_regresses_watermark(self):
        source=read_json(self.manager.path(GROUP));source['collected_through']='2026-10-22T00:00:00+08:00'
        atomic_write_json(self.manager.path(GROUP),source)
        with patch.object(self.client,'detail',wraps=self.client.detail) as detail:
            self.manager.sync(GROUP,mode='live')
            detail.assert_not_called()
        self.assertEqual(read_json(self.manager.path(GROUP))['live_latest_at'],source['collected_through'])
