"""Persistent LTE selection must retain the original mode and preserve other edits."""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'device'))
import unified_dca as d


class LteModeTests(unittest.TestCase):
    def setUp(self):
        self.current = {'enabled_technologies': 3, 'preferred_technologies': -1}
        self.files, self.requests = {}, []
        self.fail = False
        self.selected = {'operator': 'telecom', 'sim_sha256': 'private-test-hash'}
        def request(value):
            record = json.loads(self.files[d.MODE_RECORD])
            self.assertIn(record['phase'], ('applying', 'restoring'))
            self.requests.append(dict(value))
            self.current = d.wire_mode(value)
            if self.fail:
                raise OSError('lost response after modem accepted the command')
        stack = ExitStack()
        self.addCleanup(stack.close)
        for item in (
            patch.object(d, 'mode_snapshot', side_effect=lambda: dict(self.current)),
            patch.object(d, 'request_mode', side_effect=request),
            patch.object(d.s, 'phone_idle', return_value=True),
            patch.object(d.n, 'ims_pids', return_value=[]),
            patch.object(d.n, 'active_vpn_sessions', return_value=[]),
            patch.object(d.n, 'crypto_policy', return_value={'swcr_id': -1, 'crypto_support': 0}),
            patch.object(d.s, 'boot_token', return_value=['test']),
            patch.object(d.os.path, 'isfile', side_effect=lambda path: path in self.files),
            patch.object(d.s, 'load', side_effect=lambda path: json.loads(self.files[path])),
            patch.object(d.n, 'atomic', side_effect=lambda path, blob: self.files.update({path: blob})),
        ):
            stack.enter_context(item)

    def test_lte_is_added_without_removing_other_technologies_and_disable_restores_original(self):
        d.ensure_lte_mode(self.selected)
        self.assertEqual(self.current, {'enabled_technologies': 19, 'preferred_technologies': 0})
        d.ensure_lte_mode(self.selected)
        self.assertEqual(len(self.requests), 1)
        d.restore_lte_mode()
        self.assertEqual(self.current, {'enabled_technologies': 3, 'preferred_technologies': 0})
        self.assertEqual(json.loads(self.files[d.MODE_RECORD])['before']['preferred_technologies'], -1)
        self.assertTrue(json.loads(self.files[d.MODE_RECORD])['restored'])

    def test_interrupted_ack_is_reconciled_by_readback_without_sending_again(self):
        self.fail = True
        with self.assertRaises(OSError):
            d.ensure_lte_mode(self.selected)
        self.assertEqual(json.loads(self.files[d.MODE_RECORD])['phase'], 'applying')
        self.fail = False
        d.ensure_lte_mode(self.selected)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(json.loads(self.files[d.MODE_RECORD])['phase'], 'ready')

    def test_an_independent_mode_change_is_not_overwritten_on_boot_or_disable(self):
        d.ensure_lte_mode(self.selected)
        self.current['enabled_technologies'] = 1
        with self.assertRaisesRegex(AssertionError, 'network_mode_changed'):
            d.ensure_lte_mode(self.selected)
        with self.assertRaisesRegex(AssertionError, 'network_mode_changed'):
            d.restore_lte_mode()
        self.assertEqual(len(self.requests), 1)

    def test_existing_lte_mode_needs_no_write_or_invented_backup(self):
        self.current['enabled_technologies'] = 19
        d.ensure_lte_mode(self.selected)
        self.assertFalse(self.files)
        self.assertFalse(self.requests)

    def test_call_or_existing_ims_prevents_selection_changes(self):
        with patch.object(d.s, 'phone_idle', return_value=False), self.assertRaises(AssertionError):
            d.ensure_lte_mode(self.selected)
        with patch.object(d.n, 'ims_pids', return_value=[123]), self.assertRaises(AssertionError):
            d.ensure_lte_mode(self.selected)
        self.assertFalse(self.files)
        self.assertFalse(self.requests)

    def test_reenable_can_reapply_only_the_recorded_original_mode(self):
        d.ensure_lte_mode(self.selected)
        d.restore_lte_mode()
        d.ensure_lte_mode(self.selected)
        self.assertEqual(self.current['enabled_technologies'], 19)
        self.assertEqual(json.loads(self.files[d.MODE_RECORD])['before']['enabled_technologies'], 3)

    def test_unset_preference_uses_zero_on_wire_but_is_retained_in_the_original(self):
        d.ensure_lte_mode(self.selected)
        self.assertEqual(self.requests[0]['preferred_technologies'], 0)
        self.assertTrue(d.same_mode({'enabled_technologies': 3, 'preferred_technologies': -1},
                                   {'enabled_technologies': 3, 'preferred_technologies': 0}))
        self.assertFalse(d.same_mode({'enabled_technologies': 3, 'preferred_technologies': 2},
                                    {'enabled_technologies': 3, 'preferred_technologies': 0}))


class StartupIdleTests(unittest.TestCase):
    def setUp(self):
        self.tick = 0
        self.states = [(True, [], [])]
        self.events = []
        self.stopped = False
        stack = ExitStack()
        self.addCleanup(stack.close)
        def state():
            return self.states[min(self.tick, len(self.states) - 1)]
        def sleep(unused):
            self.tick += 1
        def changed(name):
            self.assertEqual(state(), (True, [], []))
            self.events.append((name, self.tick))
            return {'policy_changed_boot': None}
        for item in (
            patch.object(d.s, 'stopping', side_effect=lambda: self.stopped),
            patch.object(d.s, 'phone_idle', side_effect=lambda: state()[0]),
            patch.object(d.n, 'ims_pids', side_effect=lambda: state()[1]),
            patch.object(d.n, 'active_vpn_sessions', side_effect=lambda: state()[2]),
            patch.object(d.s, 'status'), patch.object(d.time, 'sleep', side_effect=sleep),
            patch.object(d.s, 'boot_token', return_value=['boot']),
            patch.object(d, 'ensure_lte_mode', side_effect=lambda selected: changed('mode')),
            patch.object(d, 'set_usage', side_effect=lambda desired, selected: changed('usage')),
        ):
            stack.enter_context(item)

    def prepare(self):
        return d.prepare({'operator': 'unicom', 'family': 'passport'})

    def test_startup_call_state_can_settle_without_abandoning_this_boot(self):
        self.states = [(False, [], []), (False, [], []), (True, [], [])]
        self.assertTrue(self.prepare())
        self.assertEqual([name for name, tick in self.events], ['mode', 'usage'])
        self.assertTrue(all(tick >= 3 for name, tick in self.events))

    def test_stock_or_vpn_transition_is_only_observed_until_it_is_idle(self):
        self.states = [(True, [123], []), (True, [], [1]), (True, [], [])]
        with patch.object(d.os, 'kill') as kill:
            self.assertTrue(self.prepare())
            kill.assert_not_called()
        self.assertTrue(all(tick >= 3 for name, tick in self.events))

    def test_one_quiet_sample_does_not_allow_a_busy_transition_through(self):
        self.states = [(True, [], []), (False, [], []), (True, [], [])]
        self.assertTrue(self.prepare())
        self.assertTrue(all(tick >= 3 for name, tick in self.events))

    def test_busy_timeout_and_stop_do_not_change_network_policy(self):
        self.states = [(False, [], [])]
        wait = d.wait_policy_idle
        with patch.object(d, 'wait_policy_idle', side_effect=lambda: wait(timeout=3)), \
                self.assertRaisesRegex(RuntimeError, 'startup_resources_busy'):
            self.prepare()
        self.assertEqual(self.tick, 3)
        self.assertFalse(self.events)
        self.stopped = True
        with self.assertRaisesRegex(RuntimeError, 'stopped'):
            self.prepare()
        self.assertFalse(self.events)


class RadioReplyTests(unittest.TestCase):
    def run_reply(self, error=False):
        sent = []
        expected = {'enabled_technologies': 19, 'preferred_technologies': 0}
        def write(fd, blob):
            sent.append(blob)
            return len(blob)
        def read(fd, limit):
            identifier = d.n.value(d.n.attrs(sent[0]), 'id')
            return ('@control\nid::' + identifier + '\nres::configure_rats\n' +
                    ('err:n:22\n' if error else '')).encode('ascii')
        with patch.object(d.os, 'O_NONBLOCK', 0x80, create=True), \
                patch.object(d.os, 'open', return_value=42), patch.object(d.os, 'close') as close, \
                patch.object(d.os, 'write', side_effect=write), patch.object(d.os, 'read', side_effect=read), \
                patch.object(d.select, 'select', return_value=([42], [], [])), \
                patch.object(d, 'mode_snapshot', return_value=expected):
            try:
                d.request_mode(expected)
            finally:
                close.assert_called_once_with(42)
        self.assertEqual(len(sent), 1)
        self.assertEqual(d.n.value(d.n.attrs(sent[0]), 'dat'), expected)

    def test_correlated_ack_and_readback_are_required(self):
        self.run_reply()

    def test_daemon_error_is_not_reported_as_success(self):
        with self.assertRaisesRegex(AssertionError, 'network_mode_rejected'):
            self.run_reply(error=True)


if __name__ == '__main__':
    unittest.main()
