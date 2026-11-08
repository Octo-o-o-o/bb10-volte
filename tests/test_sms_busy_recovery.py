"""Reject live SMS work, unknown images and changed identities before a PPS repair."""
import copy
import json
import os
from pathlib import Path
import sys
import types
import unittest
from contextlib import ExitStack
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'device'), str(ROOT / 'tools')]
import unified_service as u
import unified_install as installer
import carrier_policy as policy
import auto_carrier_view as view
import workflow


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.facts = {'variant': 'SQW100-4', 'board_type': 'WINDERMERE4ROW', 'os_version': '10.3.3.3216'}
        self.card = {'state': 'READY', 'kind': 2, 'mcc': '460', 'mnc': '00', 'imsi': '46000' + '12345' * 2}
        self.choice = policy.select(self.facts, self.card)
        self.previous = {'boot': ['old']}
        self.files, self.writes = {}, []
        self.raw = b'@status\nsmsServiceBusy:b:true\nreceivedMessages:n:7\n'
        self.idle = {'producer': {'pid': '10', 'values': {'busy': 0}},
                     'modem': {'pid': '11', 'values': {'rl_state': 0, 'stored_sms': 0}}}
        self.stack.enter_context(patch.object(u.os, 'geteuid', return_value=0, create=True))
        self.stack.enter_context(patch.object(u.os, 'stat', return_value=types.SimpleNamespace(st_ino=3, st_mtime=4)))
        self.stack.enter_context(patch.object(u.os.path, 'isfile', side_effect=lambda p: p in self.files))
        self.stack.enter_context(patch.object(u.os.path, 'lexists', return_value=False))
        self.stack.enter_context(patch.object(u.s, 'load', side_effect=lambda p: copy.deepcopy(self.files[p])))
        self.stack.enter_context(patch.object(u, 'save', side_effect=lambda p, v: self.files.__setitem__(p, copy.deepcopy(v))))
        self.stack.enter_context(patch.object(u, 'boot_token', return_value=['new']))
        self.current_card = self.stack.enter_context(patch.object(u, 'card', return_value=self.card))
        self.stop = self.stack.enter_context(patch.object(u, 'core_stopping', return_value=False))
        self.calls = self.stack.enter_context(patch.object(u.s, 'phone_idle', return_value=True))
        self.pids = self.stack.enter_context(patch.object(u.n, 'ims_pids', return_value=[]))
        self.crypto = self.stack.enter_context(patch.object(u.n, 'crypto_policy', return_value={'swcr_id': -1, 'crypto_support': 0}))
        self.stack.enter_context(patch.object(u.n, 'read', side_effect=lambda p: self.raw))
        self.stack.enter_context(patch.object(u.time, 'sleep'))
        self.snapshot = self.stack.enter_context(patch.object(u, 'sms_idle_snapshot', side_effect=lambda: copy.deepcopy(self.idle)))
        self.write = self.stack.enter_context(patch.object(u.n, 'update_pps', side_effect=self.change_pps))

    def change_pps(self, path, fields):
        self.writes.append((path, fields))
        self.raw = self.raw.replace(b'smsServiceBusy:b:true', b'smsServiceBusy:b:false')

    def run_recovery(self):
        return u.reconcile_stale_sms_busy(self.facts, self.choice, self.previous)

    def test_one_field_write_follows_durable_backup_and_three_idle_proofs(self):
        original = self.change_pps
        def checked_write(path, fields):
            self.assertEqual(self.snapshot.call_count, 3)
            backups = [v for p, v in self.files.items() if '/archive/' in p]
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0]['before_status'], self.raw.decode())
            self.assertEqual(self.files[u.BASE + '/state/sms-busy-recovery.json']['state'], 'write_intent')
            original(path, fields)
        self.write.side_effect = checked_write
        self.assertEqual(self.run_recovery(), 'reconciled')
        self.assertEqual(self.writes, [('/pps/services/cellular/sms/status', {'smsServiceBusy': 'b:false'})])
        self.assertIn(b'receivedMessages:n:7', self.raw)
        self.assertEqual(self.snapshot.call_count, 4)
        self.assertEqual(self.run_recovery(), 'already_checked')
        self.assertEqual(len(self.writes), 1)

    def test_false_or_missing_busy_does_not_read_native_memory(self):
        for raw in (b'@status\n', b'smsServiceBusy:b:false\n'):
            self.raw = raw
            self.assertEqual(self.run_recovery(), 'not_busy')
        self.snapshot.assert_not_called()
        self.write.assert_not_called()

    def test_unknown_model_board_os_or_telecom_is_untouched(self):
        for changes in ({'variant': 'SQC100-4'}, {'board_type': 'unexpected'}, {'os_version': 'unknown'}):
            old = self.facts
            self.facts = dict(old, **changes)
            self.assertEqual(self.run_recovery(), 'out_of_scope')
            self.facts = old
        self.choice['operator'] = 'telecom'
        self.assertEqual(self.run_recovery(), 'out_of_scope')
        self.snapshot.assert_not_called()
        self.write.assert_not_called()

    def test_first_install_and_same_boot_are_not_cold_boot_proof(self):
        for previous in (None, {'boot': ['new']}):
            self.previous = previous
            self.assertEqual(self.run_recovery(), 'normal_boot_not_proven')
        self.write.assert_not_called()

    def test_native_busy_unknown_code_or_read_error_never_writes(self):
        for error in (AssertionError('sms_native_busy'), AssertionError('sms_native_code_changed'), OSError()):
            self.files.clear()
            self.snapshot.side_effect = error
            self.assertEqual(self.run_recovery(), 'deferred')
        self.write.assert_not_called()

    def test_calls_native_ims_or_provider_prevent_reconciliation(self):
        for mock, value in ((self.calls, False), (self.pids, [42]),
                            (self.crypto, {'swcr_id': 0, 'crypto_support': 1}), (self.stop, True)):
            self.files.clear()
            old = mock.return_value
            mock.return_value = value
            self.assertEqual(self.run_recovery(), 'deferred')
            mock.return_value = old
        self.write.assert_not_called()

    def test_SIM_change_and_native_PID_change_prevent_write(self):
        self.current_card.return_value = dict(self.card, imsi='46000' + '54321' * 2)
        self.assertEqual(self.run_recovery(), 'deferred')
        self.files.clear()
        self.current_card.return_value = self.card
        changed = copy.deepcopy(self.idle)
        changed['producer']['pid'] = '99'
        self.snapshot.side_effect = [self.idle, changed]
        self.assertEqual(self.run_recovery(), 'deferred')
        self.write.assert_not_called()

    def test_last_instant_state_change_preserves_messages(self):
        self.snapshot.side_effect = [self.idle, self.idle, AssertionError('sms_native_busy')]
        self.assertEqual(self.run_recovery(), 'deferred')
        self.write.assert_not_called()

    def test_failed_backup_readback_prevents_write(self):
        with patch.object(u.s, 'load', return_value={}):
            self.assertEqual(self.run_recovery(), 'deferred')
        self.write.assert_not_called()

    def test_ambiguous_write_is_recorded_and_not_retried(self):
        self.write.side_effect = OSError('write outcome unknown')
        self.assertEqual(self.run_recovery(), 'unconfirmed')
        self.assertEqual(self.run_recovery(), 'already_checked')
        self.assertEqual(self.write.call_count, 1)

    def test_uninstall_retains_only_the_exact_recovery_diagnostic_names(self):
        payload = {'files': {}}
        self.assertTrue(installer.known_uninstall_member('state/sms-busy-recovery.json', payload))
        self.assertTrue(installer.known_uninstall_member('archive/sms-busy-' + 'a' * 32 + '.json', payload))
        for name in ('archive/sms-busy-' + 'a' * 32 + '.py', 'state/sms-busy-other.json',
                     'archive/sms-busy-../bad.json'):
            self.assertFalse(installer.known_uninstall_member(name, payload))


class NativeReaderTests(unittest.TestCase):
    def test_hash_pin_is_checked_before_process_access(self):
        with patch.object(u.n, 'read', return_value=b'unknown'), patch.object(u.n, 'command') as command:
            with self.assertRaisesRegex(AssertionError, 'sms_native_image_unknown'):
                u.sms_native_state('test', '/image', '0' * 64, (), {})
            command.assert_not_called()

    def test_native_memory_is_read_only_and_code_mismatch_closes_descriptor(self):
        raw = b'\x7fELF' + b'\0' * 60
        position = [0]
        def seek(fd, offset, mode):position[0] = offset - 0x1000
        def read(fd, size):
            return raw[position[0]:position[0] + size]
        with ExitStack() as stack:
            stack.enter_context(patch.object(u.n, 'read', return_value=raw))
            stack.enter_context(patch.object(u.n, 'command', side_effect=[b'123\n', b' test @ 00001000\n']))
            opened = stack.enter_context(patch.object(u.os, 'open', return_value=17))
            closed = stack.enter_context(patch.object(u.os, 'close'))
            stack.enter_context(patch.object(u.os, 'lseek', side_effect=seek))
            stack.enter_context(patch.object(u.os, 'read', side_effect=read))
            result = u.sms_native_state('test', '/image', u.n.digest(raw), ((4, 4),), {'busy': (8, 1)})
            self.assertEqual(result['values'], {'busy': 0})
            opened.assert_called_once_with('/proc/123/as', os.O_RDONLY)
            closed.assert_called_once_with(17)

    def test_each_native_busy_field_blocks_snapshot(self):
        for field in ('busy', 'rl_state', 'stored_sms'):
            first = {'values': {'busy': int(field == 'busy')}}
            second = {'values': {'rl_state': int(field == 'rl_state'), 'stored_sms': int(field == 'stored_sms')}}
            with patch.object(u, 'sms_native_state', side_effect=[first, second]):
                with self.assertRaisesRegex(AssertionError, 'sms_native_busy'):
                    u.sms_idle_snapshot()


class PresentationTests(unittest.TestCase):
    def test_busy_only_changes_waiting_state_and_safe_boolean_is_exported(self):
        state = {'phase': 'registering', 'enabled': True, 'status_from_current_boot': True,
                 'selected_this_boot': True, 'current_sim_matches': True, 'management_schema': 2,
                 'manager_alive': True, 'native_alive': True, 'sms_service_busy': True,
                 'current': {'ims': 'idle', 'register_status': None, 'radio': ['lte']}}
        self.assertEqual(view.status_view(state)['check_code'], 'unified_waiting_sms')
        self.assertIs(workflow.public_status(state)['sms_service_busy'], True)
        self.assertIsNone(workflow.public_status(dict(state, sms_service_busy='private text'))['sms_service_busy'])
        state.update(phase='running', current={'ims': 'connected', 'register_status': '200 OK', 'ran': 'LTE', 'radio': ['lte']})
        self.assertEqual(view.status_view(state)['check_code'], 'unified_running')


if __name__ == '__main__':
    unittest.main()
