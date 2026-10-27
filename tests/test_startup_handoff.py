"""Protect calls and unknown processes while shortening a proven idle boot wait."""
import copy
import json
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'device'))
import service as s
import native as n


class StockCandidateTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.exists = set()
        self.files = {s.BASE + '/enabled', s.JOURNAL}
        self.journal = {'owner': 'q10-unicom-volte-v1', 'boot': [1, 1]}
        self.arguments = 'Arguments\n/radio//bin/ims_rrm -U 453:31,80,387,427,521,1001\n'
        self.name = 'name\nradio/bin/ims_rrm\n'
        self.log = ('ims_rrm.123 main bb.cfgmgr:1455 imsProfiles= 0x00000000\n'
                    'ims_rrm.123 main bb.cfgmgr:1458 No IMS profiles provisioned .. waiting\n')
        self.config = b'@ims\n'
        self.stack.enter_context(patch.object(s.os.path, 'exists', side_effect=lambda p: p in self.exists))
        self.stack.enter_context(patch.object(s.os.path, 'isfile', side_effect=lambda p: p in self.files))
        self.stack.enter_context(patch.object(s, 'load', side_effect=lambda p: copy.deepcopy(self.journal if p == s.JOURNAL else {'boot': [2, 2]})))
        self.stack.enter_context(patch.object(s, 'boot_token', return_value=[2, 2]))
        self.stop = self.stack.enter_context(patch.object(s, 'stopping', return_value=False))
        self.stack.enter_context(patch.object(s.device_info, 'read_identity', return_value={
            'model': 'Q10', 'variant': 'SQN100-3', 'os_version': s.device_info.OS_VERSION}))
        self.baseline = self.stack.enter_context(patch.object(s.profiles, 'baseline_parameters', return_value=True))
        self.pids = self.stack.enter_context(patch.object(n, 'ims_pids', return_value=[123]))
        self.stack.enter_context(patch.object(n, 'command', side_effect=self.command))
        self.network = self.stack.enter_context(patch.object(s, 'ready', return_value=True))
        self.live = self.stack.enter_context(patch.object(s, 'live', return_value={'ims': 'disconnected', 'register_status': '200 OK'}))
        self.idle = self.stack.enter_context(patch.object(s, 'phone_idle', return_value=True))
        self.stack.enter_context(patch.object(n, 'read', side_effect=lambda p: self.config))
        self.vpn = self.stack.enter_context(patch.object(n, 'active_vpn_sessions', return_value=[]))

    def command(self, args, *unused):
        return (self.arguments if args[-1] == 'A' else self.name if args[-1] == '%80N' else self.log).encode('ascii')

    def rejected(self):
        self.assertIsNone(s.stock_exit_candidate()[0])

    def test_exact_idle_stock_is_eligible_despite_stale_global_200(self):
        self.assertEqual(s.stock_exit_candidate(), (123, 'verified_idle_stock'))

    def test_owned_replacement_is_never_a_stock_candidate(self):
        self.arguments = 'Arguments\n' + s.BIN + ' -U 453:31,80,387,427,521,1001\n'
        self.rejected()

    def test_matching_arguments_with_different_image_are_rejected(self):
        self.name = 'name\nvar/another/ims_rrm\n'
        self.rejected()

    def test_multiple_processes_are_preserved(self):
        self.pids.return_value = [123, 456]
        self.rejected()

    def test_connected_ims_or_active_call_are_preserved(self):
        self.live.return_value = {'ims': 'connected'}
        self.rejected()
        self.live.return_value = {'ims': 'disconnected'}
        self.idle.return_value = False
        self.rejected()

    def test_lost_lte_or_active_vpn_disable_fast_handoff(self):
        self.network.return_value = False
        self.rejected()
        self.network.return_value = True
        self.vpn.return_value = ['existing-session']
        self.rejected()

    def test_provisioned_profile_is_preserved(self):
        self.config = b'@ims\nIMS_profilesV2:json:["IR92"]\n'
        self.rejected()

    def test_later_profile_or_sip_activity_invalidates_old_idle_log(self):
        for extra in ('ims_rrm.123 main bb.cfgmgr:1455 imsProfiles= 0x00000001\n',
                      'ims_rrm.123 main CSeq: 1 REGISTER\n',
                      'ims_rrm.123 main CSeq: 5 INVITE\n',
                      'ims_rrm.123 main bb.rm:200 exit req but wait acl\n'):
            old = self.log
            self.log += extra
            self.rejected()
            self.log = old

    def test_unrelated_pid_log_is_not_evidence(self):
        self.log = self.log.replace('ims_rrm.123 ', 'ims_rrm.456 ')
        self.rejected()

    def test_current_boot_journal_is_not_a_reboot_handoff(self):
        self.journal['boot'] = [2, 2]
        self.rejected()

    def test_attempt_receipt_survives_manager_restart(self):
        self.exists.add(s.STATE + '/stock-handoff.json')
        self.rejected()

    def test_conservative_switch_and_experimental_profile_use_passive_wait(self):
        self.exists.add(s.BASE + '/conservative-start')
        self.rejected()
        self.exists.clear()
        self.baseline.return_value = False
        self.rejected()


class SignalRequestTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.candidate = self.stack.enter_context(patch.object(s, 'stock_exit_candidate', return_value=(123, 'verified_idle_stock')))
        self.sim = self.stack.enter_context(patch.object(s, 'current_usim', return_value='synthetic-identity'))
        self.stop = self.stack.enter_context(patch.object(s, 'stopping', return_value=False))
        self.stack.enter_context(patch.object(s.time, 'sleep'))
        self.stack.enter_context(patch.object(s, 'boot_token', return_value=[2, 2]))
        self.stack.enter_context(patch.object(n, 'ims_pids', return_value=[123]))
        self.idle = self.stack.enter_context(patch.object(s, 'phone_idle', return_value=True))
        self.write = self.stack.enter_context(patch.object(n, 'atomic'))
        self.kill = self.stack.enter_context(patch.object(s.os, 'kill'))

    def test_persist_before_one_sigterm_and_never_sigkill(self):
        events = []
        self.write.side_effect = lambda p, d: events.append(('receipt', json.loads(d)))
        self.kill.side_effect = lambda p, sig: events.append(('signal', p, sig))
        self.assertTrue(s.request_idle_stock_exit())
        self.assertEqual(events[0][0], 'receipt')
        self.assertEqual(events[0][1]['boot'], [2, 2])
        self.kill.assert_called_once_with(123, s.signal.SIGTERM)

    def test_pid_change_does_not_signal_replacement(self):
        self.candidate.side_effect = [(123, 'verified_idle_stock'), (456, 'verified_idle_stock')]
        self.assertFalse(s.request_idle_stock_exit())
        self.kill.assert_not_called()

    def test_sim_change_or_new_call_prevents_signal(self):
        self.sim.side_effect = ['first-sim', 'second-sim']
        self.assertFalse(s.request_idle_stock_exit())
        self.sim.side_effect = None
        self.idle.return_value = False
        self.assertFalse(s.request_idle_stock_exit())
        self.kill.assert_not_called()

    def test_stop_interrupts_confirmation(self):
        self.stop.return_value = True
        self.assertFalse(s.request_idle_stock_exit())
        self.kill.assert_not_called()

    def test_unavailable_evidence_keeps_passive_path(self):
        self.candidate.side_effect = OSError('unavailable observation')
        self.assertFalse(s.request_idle_stock_exit())
        self.kill.assert_not_called()

    def test_failed_receipt_prevents_signal(self):
        self.write.side_effect = OSError('disk write unavailable')
        self.assertFalse(s.request_idle_stock_exit())
        self.kill.assert_not_called()

    def test_post_signal_receipt_error_keeps_quiet_wait(self):
        self.write.side_effect = [None, OSError('disk write unavailable')]
        self.assertTrue(s.request_idle_stock_exit())
        self.kill.assert_called_once_with(123, s.signal.SIGTERM)


class CallNamespaceTests(unittest.TestCase):
    def test_missing_or_nonempty_namespace_is_not_idle(self):
        with patch.object(s.os.path, 'isdir', return_value=False):
            self.assertFalse(s.phone_idle())
        with patch.object(s.os.path, 'isdir', return_value=True), patch.object(s.os, 'listdir', side_effect=[[], ['call']]):
            self.assertFalse(s.phone_idle())


class PassiveFallbackTests(unittest.TestCase):
    def run_preparation(self, pids):
        self.now = 0
        def sleep(seconds):
            self.now += seconds
        profile = copy.deepcopy(s.ACTIVE_PROFILE)
        profile['runtime']['existing_ims_wait_seconds'] = 10
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(s, 'ACTIVE_PROFILE', profile))
        stack.enter_context(patch.object(s.time, 'time', side_effect=lambda: self.now))
        stack.enter_context(patch.object(s.time, 'sleep', side_effect=sleep))
        stack.enter_context(patch.object(s, 'stopping', return_value=False))
        stack.enter_context(patch.object(s, 'status'))
        stack.enter_context(patch.object(s, 'wait_for_network', return_value=True))
        stack.enter_context(patch.object(n, 'verify_stock'))
        stack.enter_context(patch.object(n, 'ims_pids', side_effect=lambda: pids(self.now)))
        self.request = stack.enter_context(patch.object(s, 'request_idle_stock_exit', return_value=True))
        self.configure = stack.enter_context(patch.object(s, 'configure'))

    def test_replacement_restarts_quiet_wait_without_another_signal(self):
        self.run_preparation(lambda t: [123] if t < 2 else [456] if 4 <= t < 6 else [])
        self.assertTrue(s.prepare_connection())
        self.assertEqual(self.now, 9)
        self.request.assert_called_once()
        self.configure.assert_called_once()

    def test_process_that_ignores_sigterm_keeps_original_bounded_wait(self):
        self.run_preparation(lambda t: [123])
        with self.assertRaisesRegex(RuntimeError, 'Timeout: pre-existing'):
            s.prepare_connection()
        self.assertEqual(self.now, 10)
        self.request.assert_called_once()
        self.configure.assert_not_called()


if __name__ == '__main__':
    unittest.main()
