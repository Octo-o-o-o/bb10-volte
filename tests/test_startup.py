"""Regression cases from the Q10 startup timeout, with no hardware writes."""
import copy
import hashlib
import json
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'device'))
import service as s
import native as n


class ApnWaitTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.now = 0
        self.ready_at = 12
        self.network = {'sim_state': 'READY', 'sim_type': 2, 'mcc': '460', 'mnc': '01',
                        'identity_matches': True, 'radio_on': True, 'lte': True,
                        'apn_matches': True, 'data_connected': True}
        self.override = ':' + s.APN
        self.data = b'owned carrier file'
        profile = copy.deepcopy(s.ACTIVE_PROFILE)
        profile['runtime'].update(ims_apn_wait_seconds=10, poll_seconds=2)
        self.stack.enter_context(patch.object(s, 'ACTIVE_PROFILE', profile))
        self.stack.enter_context(patch.object(s, 'j', {'managed_files': {s.APN: hashlib.sha256(self.data).hexdigest()}}))
        self.stack.enter_context(patch.object(s.time, 'time', side_effect=lambda: self.now))
        self.stack.enter_context(patch.object(s.time, 'sleep', side_effect=self.sleep))
        self.stack.enter_context(patch.object(n, 'read', side_effect=self.read))
        self.stack.enter_context(patch.object(n, 'attrs', side_effect=lambda x: x))
        self.stack.enter_context(patch.object(s.compatibility, 'read_network', side_effect=lambda _: self.network))
        self.identity = self.stack.enter_context(patch.object(s, 'current_usim', return_value='test-sim'))
        self.stop = self.stack.enter_context(patch.object(s, 'stopping', return_value=False))
        self.status = self.stack.enter_context(patch.object(s, 'status'))
        self.write = self.stack.enter_context(patch.object(n, 'update_pps'))
        self.modem = self.stack.enter_context(patch.object(s, 'set_voice_preference'))

    def sleep(self, seconds):
        self.now += seconds

    def read(self, path):
        if path == s.APN:
            return self.data
        if path == s.CDSC:
            return {'cdsc_xml': self.override}
        if path == s.DATA:
            return {'ims': 'json:' + json.dumps({'apn': 'ims', 'connected': self.now >= self.ready_at})}
        raise AssertionError(path)

    def test_connection_can_recover_after_first_wait_window(self):
        s.wait_for_ims_apn('test-sim')
        self.assertEqual(self.now, 12)
        self.assertEqual({c.kwargs['details']['attempt'] for c in self.status.call_args_list}, {1, 2})
        self.write.assert_not_called()
        self.modem.assert_not_called()

    def test_failure_has_three_bounded_rounds_without_modem_reload(self):
        self.ready_at = 100
        with self.assertRaisesRegex(RuntimeError, 'after 3 bounded attempts'):
            s.wait_for_ims_apn('test-sim')
        self.assertEqual(self.now, 30)
        self.write.assert_not_called()
        self.modem.assert_not_called()

    def test_changed_sim_is_not_retried_or_exposed(self):
        self.identity.return_value = 'different-private-sim'
        with self.assertRaisesRegex(RuntimeError, '^SIM changed while') as result:
            s.wait_for_ims_apn('test-sim')
        self.assertNotIn('different-private', str(result.exception))
        self.assertEqual(self.now, 0)

    def test_changed_carrier_is_not_retried(self):
        self.network['mnc'] = '00'
        with self.assertRaisesRegex(RuntimeError, '^SIM/carrier changed'):
            s.wait_for_ims_apn('test-sim')
        self.identity.assert_not_called()

    def test_sim_initialization_can_finish_during_wait(self):
        self.network['sim_state'] = 'INITIALIZING'
        def sleep(seconds):
            self.now += seconds
            if self.now >= 4:
                self.network['sim_state'] = 'READY'
        with patch.object(s.time, 'sleep', side_effect=sleep):
            s.wait_for_ims_apn('test-sim')
        self.assertEqual(self.now, 12)

    def test_lte_loss_is_not_mistaken_for_a_connected_ims_bearer(self):
        self.ready_at = 0
        self.network['lte'] = False
        with self.assertRaisesRegex(RuntimeError, 'after 3 bounded attempts'):
            s.wait_for_ims_apn('test-sim')
        self.modem.assert_not_called()

    def test_external_override_is_preserved(self):
        self.override = ':/owner/other.xml'
        with self.assertRaisesRegex(AssertionError, 'override changed'):
            s.wait_for_ims_apn('test-sim')
        self.write.assert_not_called()

    def test_external_file_change_is_preserved(self):
        self.data = b'externally changed'
        with self.assertRaisesRegex(AssertionError, 'file changed'):
            s.wait_for_ims_apn('test-sim')
        self.write.assert_not_called()

    def test_owner_stop_interrupts_wait_without_delay(self):
        self.stop.return_value = True
        with self.assertRaisesRegex(RuntimeError, '^Stopped while'):
            s.wait_for_ims_apn('test-sim')
        self.assertEqual(self.now, 0)


class StartupGateTests(unittest.TestCase):
    def test_network_is_checked_again_after_stock_ims_exits(self):
        events = []
        with patch.object(n, 'verify_stock'), patch.object(n, 'ims_pids', return_value=[]), \
             patch.object(s, 'status'), patch.object(s, 'wait_for_network', side_effect=lambda: events.append('network') or True), \
             patch.object(s, 'wait_until', side_effect=lambda *a, **k: events.append('stock')), \
             patch.object(s, 'configure', side_effect=lambda: events.append('configure')):
            self.assertTrue(s.prepare_connection())
        self.assertEqual(events, ['network', 'stock', 'network', 'configure'])

    def test_stop_after_stock_wait_never_configures(self):
        with patch.object(n, 'verify_stock'), patch.object(s, 'wait_until'), \
             patch.object(s, 'wait_for_network', side_effect=[True, False]), patch.object(s, 'configure') as configure:
            self.assertFalse(s.prepare_connection())
            configure.assert_not_called()

    def test_new_foreign_ims_instance_blocks_launch(self):
        with patch.object(n, 'verify_stock'), patch.object(s, 'wait_until'), patch.object(s, 'status'), \
             patch.object(s, 'wait_for_network', return_value=True), patch.object(s, 'configure'), \
             patch.object(n, 'ims_pids', return_value=[123]):
            with self.assertRaisesRegex(AssertionError, 'new native IMS instance'):
                s.prepare_connection()


class BootStatusTests(unittest.TestCase):
    def snapshot(self, status, lock, boot):
        with patch.object(s.os.path, 'isfile', return_value=True), \
             patch.object(s, 'load', side_effect=lambda p: copy.deepcopy(status if p == s.STATUS else lock)), \
             patch.object(s, 'boot_token', return_value=boot), patch.object(s, 'alive', return_value=True), \
             patch.object(s, 'live', return_value={'register_status': '500 Server Internal Error'}), \
             patch.object(n, 'ims_pids', return_value=[321]):
            return s.read_status()

    def test_old_boot_error_and_reused_pid_are_not_current(self):
        value = self.snapshot({'boot': [1, 1], 'phase': 'error', 'error': 'old failure', 'native_pid': 321},
                              {'boot': [1, 1], 'pid': 123}, [2, 2])
        self.assertEqual(value['phase'], 'not_started_this_boot')
        self.assertIsNone(value['error'])
        self.assertFalse(value['manager_alive'])
        self.assertFalse(value['native_alive'])

    def test_live_legacy_status_uses_matching_lock_boot(self):
        value = self.snapshot({'phase': 'running', 'native_pid': 321}, {'boot': [2, 2], 'pid': 123}, [2, 2])
        self.assertTrue(value['status_from_current_boot'])
        self.assertTrue(value['native_alive'])


if __name__ == '__main__':
    unittest.main()
