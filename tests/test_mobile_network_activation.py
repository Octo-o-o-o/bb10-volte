"""Explicit activation opens a confirmed-OFF radio once, with real readback."""
import contextlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'device'))
import unified_dca as network
import unified_install as installer


class MobileNetworkPowerTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.power = 'OFF'
        self.reply = 'ok'
        self.turn_on = True
        self.sent = []
        def read(path):
            if path == network.CELLULAR_IMAGE:
                return b'pinned native controller'
            return ('@status_public\npower_status::' + self.power + '\n').encode('ascii')
        def write(fd, blob):
            self.sent.append(blob)
            if self.turn_on:
                self.power = 'ON'
            return len(blob)
        def response(fd, size):
            identifier = network.n.value(network.n.attrs(self.sent[0]), 'id')
            if self.reply == 'foreign':
                identifier = 'unrelated-request'
            return ('@control\nid::' + identifier + '\nres::power\n' +
                    ('err:n:22\n' if self.reply == 'error' else '')).encode('ascii')
        for item in (
            patch.object(network.n, 'read', side_effect=read),
            patch.object(network.n, 'digest', return_value=network.CELLULAR_HASH),
            patch.object(network.s, 'phone_idle', return_value=True),
            patch.object(network.os, 'O_NONBLOCK', 0x80, create=True),
            patch.object(network.os, 'open', return_value=42),
            patch.object(network.os, 'close'),
            patch.object(network.os, 'write', side_effect=write),
            patch.object(network.os, 'read', side_effect=response),
            patch.object(network.select, 'select', return_value=([42], [], [])),
            patch.object(network.time, 'sleep'),
        ):
            self.stack.enter_context(item)

    def test_off_opens_once_and_a_second_attempt_is_a_read_only_noop(self):
        result = network.enable_mobile_network()
        self.assertEqual(result, {'before': 'OFF', 'after': 'ON', 'changed': True})
        self.assertFalse(network.enable_mobile_network()['changed'])
        self.assertEqual(len(self.sent), 1)
        request = network.n.attrs(self.sent[0])
        self.assertEqual(network.n.value(request, 'msg'), 'power')
        self.assertEqual(network.n.value(request, 'dat'), {'state': 'ON'})
        network.os.close.assert_called_once_with(42)

    def test_already_on_does_not_open_control_or_require_native_power_writes(self):
        self.power = 'ON'
        self.assertFalse(network.enable_mobile_network()['changed'])
        network.os.open.assert_not_called()

    def test_unknown_state_native_mismatch_and_call_never_write(self):
        for condition, code in (('unknown', 'mobile_network_state_unknown'),
                                ('native', 'unknown_radio_controller'), ('call', 'call_active')):
            with self.subTest(condition=condition):
                self.power = 'UNKNOWN' if condition == 'unknown' else 'OFF'
                with patch.object(network.n, 'digest', return_value='different' if condition == 'native' else network.CELLULAR_HASH), \
                     patch.object(network.s, 'phone_idle', return_value=condition != 'call'), \
                     self.assertRaisesRegex(AssertionError, code):
                    network.enable_mobile_network()
        network.os.open.assert_not_called()

    def test_rejected_or_foreign_ack_cannot_claim_success_even_if_on(self):
        for reply, code in (('error', 'mobile_network_rejected'), ('foreign', 'mobile_network_reply_timeout')):
            self.power, self.reply, self.sent = 'OFF', reply, []
            with self.subTest(reply=reply), self.assertRaisesRegex(AssertionError, code):
                network.enable_mobile_network()
            self.assertEqual(len(self.sent), 1)
            # A later explicit retry reconciles ON without sending again.
            self.assertFalse(network.enable_mobile_network()['changed'])
            self.assertEqual(len(self.sent), 1)

    def test_ack_without_on_readback_times_out_without_retry_or_off_command(self):
        self.turn_on = False
        with self.assertRaisesRegex(RuntimeError, 'mobile_network_enable_unconfirmed'):
            network.enable_mobile_network()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(network.time.sleep.call_count, 30)


class NetworkAdmissionTests(unittest.TestCase):
    def test_only_supported_or_transient_sim_gets_an_explicit_preparation_offer(self):
        for reason in (None, 'sim_not_ready', 'sim_identity_unavailable', 'sim_route_unsupported'):
            selection = {'operator': 'unicom', 'request': {'profile': {'carrier': {'mncs': ['01']}}}}
            with self.subTest(reason=reason), \
                 patch.object(installer.policy, 'select', return_value=selection, side_effect=ValueError(reason) if reason else None), \
                 patch.object(installer.u, 'card', return_value={}), \
                 patch.object(installer.profiles, 'carrier_template', return_value=('verified', None)), \
                 patch.object(network, 'mobile_radio_state', return_value='OFF'), \
                 patch.object(network, 'enable_mobile_network') as write:
                result = installer.with_sim_status({'can_install': True, 'installed': False}, {})
            self.assertEqual(result['can_prepare_mobile_network'], reason != 'sim_route_unsupported')
            self.assertEqual(result['can_install'], reason is None)
            self.assertEqual(result['sim_supported'], reason is None)
            write.assert_not_called()

    def test_off_does_not_admit_recovery_update_busy_or_unsupported_states(self):
        for changes in ({'call_idle': False}, {'update_available': True}, {'update_pending': True},
                        {'installation_pending': True}, {'status': {'enabled': False, 'manager_alive': True}},
                        {'status': {'enabled': False, 'phase': 'error_restored'}}):
            base = {'installed': True, 'call_idle': True, 'status': {'enabled': False, 'phase': 'disabled'}}
            base.update(changes)
            with self.subTest(changes=changes), \
                 patch.object(installer.policy, 'select', side_effect=ValueError('sim_not_ready')), \
                 patch.object(installer.u, 'card', return_value={}), \
                 patch.object(network, 'mobile_radio_state', return_value='OFF'):
                result = installer.with_sim_status(base, {})
            self.assertFalse(result['can_prepare_mobile_network'])

    def test_preparation_rechecks_sim_after_opening_and_retains_rejection(self):
        report = {'can_prepare_mobile_network': True, 'sim_supported': False, 'sim_reason': 'sim_not_ready'}
        with patch.object(installer, 'probe', return_value=report), \
             patch.object(installer, 'identity', return_value=({}, 'classic')), \
             patch.object(network, 'mobile_radio_state', return_value='OFF'), \
             patch.object(network, 'enable_mobile_network') as turn_on, \
             patch.object(installer.u, 'card', return_value={}), \
             patch.object(installer.policy, 'select', side_effect=ValueError('sim_route_unsupported')):
            with self.assertRaisesRegex(ValueError, 'sim_route_unsupported'):
                installer.prepare_mobile_network()
            turn_on.assert_called_once()

    def test_scope_block_and_unknown_state_do_not_open_mobile_network(self):
        for report in ({'scope_error': 'unknown_native_image'}, {'can_prepare_mobile_network': False}):
            with patch.object(installer, 'probe', return_value=report), \
                 patch.object(network, 'mobile_radio_state', return_value=None), \
                 patch.object(network, 'enable_mobile_network') as turn_on, self.assertRaises(AssertionError):
                installer.prepare_mobile_network()
            turn_on.assert_not_called()


if __name__ == '__main__':
    unittest.main()
