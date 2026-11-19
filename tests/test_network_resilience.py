"""Offline failure-injection for pre-native retries and explicit network selection."""
import contextlib
import copy
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'device'), str(ROOT / 'tools')]
import carrier_policy as policy
import compatibility
import connection
import native
import service
import unified_dca as d
import unified_service as u
import workflow


class BootRecoveryTests(unittest.TestCase):
    def test_root_readiness_and_no_current_native_attempt_gate_boot_retry(self):
        token = ['current']
        files = {u.ATTEMPT: {'owner': policy.OWNER, 'boot': ['previous'], 'stage': 'native_configured'}}
        state = {'phase': 'error', 'manager_alive': False, 'error': 'stock_ims_not_idle'}
        with patch.object(u.os.path, 'isfile', side_effect=lambda path: path in files), \
             patch.object(u.os.path, 'lexists', return_value=False), patch.object(u.s, 'load', side_effect=files.get), \
             patch.object(u.s, 'phone_idle', return_value=True), patch.object(u.n, 'active_vpn_sessions', return_value=[]), \
             patch.object(u.n, 'crypto_policy', return_value={'swcr_id': -1, 'crypto_support': 0}), \
             patch.object(u, 'card'), patch.object(u.device_info, 'read_identity'), patch.object(u.policy, 'select'):
            self.assertEqual(u.boot_start_state(token, state), 'waiting_for_root')
            files['/tmp/root.done'] = True
            self.assertEqual(u.boot_start_state(token, state), 'boot_start_available')
            self.assertIsNone(u.boot_start_state(token, dict(state, manager_alive=True)))
            files[u.ATTEMPT]['boot'] = token
            self.assertIsNone(u.boot_start_state(token, state))

    def test_transient_stock_probe_timeout_requires_two_fresh_proofs(self):
        with patch.object(u.n, 'ims_pids', side_effect=[[42], [42], [42], [42], [42], [], [], []]), \
             patch.object(u, 'idle_stock', side_effect=[RuntimeError('Command timed out'), None, None]) as idle, \
             patch.object(u.os.path, 'isfile', return_value=False), patch.object(u, 'boot_token', return_value=['current']), \
             patch.object(u, 'core_stopping', return_value=False), patch.object(u.time, 'sleep'), \
             patch.object(u.s, 'status'), patch.object(u, 'save') as save, patch.object(u.os, 'kill') as kill:
            u.handoff()
        self.assertEqual([call.args for call in idle.call_args_list], [(42,), (42,), (42,)])
        save.assert_called_once()
        kill.assert_called_once_with(42, u.signal.SIGTERM)


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.token = ['test', 'a' * 48]
        self.sim = 'b' * 64
        self.files = {
            u.ATTEMPT: {'owner': policy.OWNER, 'boot': self.token, 'stage': 'pre_native'},
            service.JOURNAL: {'owner': 'q10-unicom-volte-v1', 'boot': self.token,
                             'restore_completed': True, 'configuration_restored': True,
                             'managed_files': {}, 'native_pid': None,
                             'provider_retained_until_reboot': False},
        }
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        for item in (
            patch.object(u.os.path, 'isfile', side_effect=lambda p: p in self.files),
            patch.object(service, 'load', side_effect=lambda p: copy.deepcopy(self.files[p])),
            patch.object(native, 'crypto_policy', return_value={'swcr_id': -1, 'crypto_support': 0}),
            patch.object(native, 'ims_pids', return_value=[]),
            patch.object(native, 'active_vpn_sessions', return_value=[]),
        ):
            stack.enter_context(item)

    def test_restored_pre_native_same_sim_can_retry(self):
        self.assertTrue(u.pre_native_retryable(self.token, {'boot': self.token, 'sim_sha256': self.sim}, self.sim))

    def test_legacy_native_and_policy_attempts_require_reboot(self):
        for stage in (None, 'native_configured', 'policy_reboot', 'unknown'):
            with self.subTest(stage=stage):
                self.files[u.ATTEMPT]['stage'] = stage
                self.assertFalse(u.pre_native_retryable(self.token))

    def test_provider_native_or_vpn_prevents_retry(self):
        for name, value in (('crypto_policy', {'swcr_id': 4, 'crypto_support': 1}),
                            ('ims_pids', [42]), ('active_vpn_sessions', ['owned-by-someone'])):
            with self.subTest(resource=name), patch.object(native, name, return_value=value):
                self.assertFalse(u.pre_native_retryable(self.token))

    def test_hot_swap_and_incomplete_restore_prevent_retry(self):
        self.assertFalse(u.pre_native_retryable(self.token, {'boot': self.token, 'sim_sha256': 'other'}, self.sim))
        original = self.files[service.JOURNAL]
        for changed in ({'configuration_restored': False}, {'managed_files': {'/owned': 'hash'}},
                        {'provider_retained_until_reboot': True}, {'native_pid': 42},
                        {'owner': 'other'}, {'restore_completed': False}):
            self.files[service.JOURNAL] = dict(original, **changed)
            self.assertFalse(u.pre_native_retryable(self.token))

    def test_carrier_policy_reboot_and_unknown_storage_are_not_retryable(self):
        self.files[service.STATUS] = {'boot': self.token, 'phase': 'carrier_reboot_required'}
        self.assertFalse(u.pre_native_retryable(self.token))
        self.files.pop(service.STATUS)
        with patch.object(service, 'load', side_effect=IOError('unreadable')):
            self.assertFalse(u.pre_native_retryable(self.token))
        self.assertFalse(u.pre_native_retryable(None))


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.files, self.events = {}, []
        self.scan = 'AUTO'
        self.selected = {'operator': 'unicom', 'sim_sha256': 'b' * 64}
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for item in (
            patch.object(d.os.path, 'isfile', side_effect=lambda p: p in self.files),
            patch.object(d.s, 'load', side_effect=lambda p: json.loads(self.files[p])),
            patch.object(d.n, 'atomic', side_effect=lambda p, b: self.files.update({p: b})),
            patch.object(d.os, 'unlink', side_effect=lambda p: self.files.pop(p)),
            patch.object(d.s, 'phone_idle', return_value=True),
            patch.object(d.n, 'ims_pids', return_value=[]),
            patch.object(d.n, 'active_vpn_sessions', return_value=[]),
            patch.object(d.n, 'crypto_policy', return_value={'swcr_id': -1, 'crypto_support': 0}),
            patch.object(d, 'mobile_radio_state', return_value='ON'),
            patch.object(d, 'scan_mode_snapshot', side_effect=lambda: self.scan),
            patch.object(d, 'request_scan_mode', side_effect=self.set_scan),
            patch.object(d, 'request_network_select', side_effect=lambda *args: self.events.append(('select', args))),
            patch.object(d.s, 'boot_token', return_value=['boot']),
            patch.object(d, 'ensure_lte_mode', side_effect=lambda s: self.events.append(('lte',))),
            patch.object(d, 'serving_network_snapshot', return_value={}),
            patch.object(u, 'card', return_value={}),
            patch.object(u, 'ready_sim_hash', return_value=self.selected['sim_sha256']),
        ):
            self.stack.enter_context(item)

    def set_scan(self, mode):
        self.events.append(('scan', mode))
        self.scan = mode

    def test_explicit_lock_uses_primary_plmn_then_restores_auto(self):
        result = d.set_network_lock(self.selected)
        self.assertEqual(result['target_plmn'], '460-01')
        self.assertEqual(self.events[:2], [('scan', 'MANUAL'), ('select', ('460', '01', 16))])
        with patch.object(d, 'restore_lte_mode') as restore:
            result = d.clear_network_lock()
        self.assertTrue(result['restored'])
        self.assertEqual(self.scan, 'AUTO')
        self.assertNotIn(d.NETWORK_LOCK, self.files)
        restore.assert_called_once()

    def test_equivalent_home_serving_plmn_is_preferred_over_sim_hplmn(self):
        with patch.object(d, 'serving_network_snapshot', return_value={'mcc': '460', 'mnc': '09'}):
            self.assertEqual(d.set_network_lock(self.selected)['target_plmn'], '460-09')

    def test_existing_system_manual_selection_is_never_overwritten(self):
        self.scan = 'MANUAL'
        with self.assertRaisesRegex(AssertionError, 'system_manual_selection_preserved'):
            d.set_network_lock(self.selected)
        self.assertEqual(self.events, [])
        self.assertEqual(self.files, {})

    def test_unknown_scan_mode_and_active_call_native_vpn_provider_block_writes(self):
        for obj, name, value in ((d, 'scan_mode_snapshot', None), (d.s, 'phone_idle', False),
                                 (d.n, 'ims_pids', [42]), (d.n, 'active_vpn_sessions', ['vpn']),
                                 (d.n, 'crypto_policy', {'swcr_id': 1, 'crypto_support': 1})):
            with self.subTest(name=name), patch.object(obj, name, return_value=value), self.assertRaises(AssertionError):
                d.set_network_lock(self.selected)
            self.assertEqual(self.events, [])

    def test_network_select_failure_restores_auto_without_claiming_lock(self):
        with patch.object(d, 'request_network_select', side_effect=RuntimeError('rejected')):
            with self.assertRaisesRegex(RuntimeError, 'rejected'):
                d.set_network_lock(self.selected)
        self.assertEqual(self.scan, 'AUTO')
        self.assertNotIn(d.NETWORK_LOCK, self.files)
        self.assertTrue(json.loads(self.files[d.SELECTION_RECORD])['restored'])

    def test_failed_restore_retains_receipts_and_is_not_success(self):
        d.set_network_lock(self.selected)
        with patch.object(d, 'request_scan_mode', side_effect=RuntimeError('lost ack')):
            with self.assertRaisesRegex(RuntimeError, 'lost ack'):
                d.clear_network_lock()
        self.assertIn(d.NETWORK_LOCK, self.files)
        self.assertFalse(json.loads(self.files[d.SELECTION_RECORD])['restored'])

    def test_radio_off_restore_stays_pending_until_radio_returns(self):
        d.set_network_lock(self.selected)
        with patch.object(d, 'mobile_radio_state', return_value='OFF'):
            with self.assertRaisesRegex(AssertionError, 'mobile_network_off'):
                d.restore_network_selection()
        self.assertIn(d.NETWORK_LOCK, self.files)
        d.restore_network_selection()
        self.assertNotIn(d.NETWORK_LOCK, self.files)

    def test_sim_switch_clears_old_lock_and_current_sim_preserves_it(self):
        d.set_network_lock(self.selected)
        self.assertTrue(d.restore_network_selection(self.selected['sim_sha256'])['locked_for_current_sim'])
        self.assertTrue(d.restore_network_selection('new-sim')['restored'])
        self.assertEqual(self.scan, 'AUTO')
        self.assertNotIn(d.NETWORK_LOCK, self.files)

    def test_sim_change_between_scan_and_select_rolls_back(self):
        with patch.object(u, 'ready_sim_hash', side_effect=[self.selected['sim_sha256'], 'changed']):
            with self.assertRaisesRegex(AssertionError, 'sim_changed'):
                d.set_network_lock(self.selected)
        self.assertEqual(self.scan, 'AUTO')
        self.assertFalse(any(event[0] == 'select' for event in self.events))


class PpsReplyTests(unittest.TestCase):
    def run_request(self, mode, readback, error=False, selected=False):
        sent = []
        def write(fd, blob):
            sent.append(blob)
            return len(blob)
        def read(fd, size):
            request = native.attrs(sent[-1])
            return ('@control\nid::' + native.value(request, 'id') + '\nres::' +
                    ('network_select' if selected else 'scan_mode') + '\n' +
                    ('err:n:22\n' if error else '')).encode('ascii')
        with contextlib.ExitStack() as stack:
            for item in (patch.object(d.os, 'O_NONBLOCK', 128, create=True),
                         patch.object(d.os, 'open', return_value=42), patch.object(d.os, 'close'),
                         patch.object(d.os, 'write', side_effect=write), patch.object(d.os, 'read', side_effect=read),
                         patch.object(d.n, 'read', return_value=b'fixture'), patch.object(d.n, 'digest', return_value=d.CELLULAR_HASH),
                         patch.object(d.select, 'select', return_value=([42], [], [])),
                         patch.object(d, 'scan_mode_snapshot', return_value=readback), patch.object(d.time, 'sleep')):
                stack.enter_context(item)
            if selected:
                d.request_network_select('460', '01', 16)
            else:
                d.request_scan_mode(mode)
        return native.value(native.attrs(sent[0]), 'dat')

    def test_ack_without_matching_readback_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'scan_mode_readback_failed'):
            self.run_request('MANUAL', 'AUTO')

    def test_partial_cdma_error_requires_successful_3gpp_readback(self):
        self.run_request('MANUAL', 'MANUAL', error=True)
        with self.assertRaisesRegex(RuntimeError, 'scan_mode_rejected'):
            self.run_request('MANUAL', None, error=True)

    def test_plmn_zero_padding_and_rat_types_are_preserved(self):
        self.assertEqual(self.run_request(None, None, selected=True), {'mcc': '460', 'mnc': '01', 'rat': 16})
        with self.assertRaisesRegex(AssertionError, 'network_select_rejected'):
            self.run_request(None, None, error=True, selected=True)


class ManagedWaitingTests(unittest.TestCase):
    def test_timeout_continues_event_wait_without_auto_manual_selection_or_management_lock(self):
        selected = {'sim_sha256': 'b' * 64}
        in_lock = []
        @contextlib.contextmanager
        def phase_lock(unused):
            in_lock.append(True)
            try:
                yield
            finally:
                in_lock.pop()
        waiter = MagicMock()
        waiter.wait.side_effect = lambda seconds: self.assertFalse(in_lock)
        with contextlib.ExitStack() as stack:
            for item in (patch.object(u, '_phase_lock', side_effect=phase_lock),
                         patch.object(u, 'core_stopping', return_value=False),
                         patch.object(u, 'card', return_value={}),
                         patch.object(u, 'ready_sim_hash', return_value=selected['sim_sha256']),
                         patch.object(u.policy, 'select', return_value=selected),
                         patch.object(d, 'deferred_lte_lock', False),
                         patch.object(u.os.path, 'isfile', return_value=True),
                         patch.object(service, 'wait_for_network', side_effect=RuntimeError('Readiness timed out after 45 seconds')),
                         patch.object(service, 'MonitorWaiter', return_value=waiter),
                         patch.object(service, 'status'),
                         patch.object(compatibility, 'read_network', return_value={}),
                         patch.object(compatibility, 'network_state', side_effect=['waiting', 'ready'])):
                stack.enter_context(item)
            select_network = stack.enter_context(patch.object(d, 'apply_network_selection'))
            self.assertTrue(u.wait_for_managed_network({}, selected))
        waiter.wait.assert_called_once_with(30)
        waiter.close.assert_called_once()
        select_network.assert_not_called()

    def test_event_wait_is_valid_before_native_child_exists(self):
        waiter = service.MonitorWaiter.__new__(service.MonitorWaiter)
        waiter.streams = {42: (('status',), (':old',))}
        with patch.object(service, 'child', None), patch.object(service, 'stopping', return_value=False), \
                patch.object(service.select, 'select', return_value=([42], [], [])) as select, \
                patch.object(waiter, 'snapshot', return_value=(':new',)), patch.object(service.time, 'sleep') as sleep:
            waiter.wait(30)
        select.assert_called_once()
        sleep.assert_called_once_with(service.ACTIVE_PROFILE['runtime']['poll_seconds'])
        self.assertTrue(waiter.streams)

    def test_stop_before_native_restores_configuration_but_shutdown_does_not(self):
        for shutdown in (False, True):
            with self.subTest(shutdown=shutdown), tempfile.TemporaryDirectory() as directory:
                folder = pathlib.Path(directory)
                stop = folder / 'stop'
                stop.touch()
                with patch.object(service, 'LOCK', str(folder / 'lock.json')), patch.object(service, 'STOP', str(stop)), \
                        patch.object(service, 'boot_token', return_value=['boot']), patch.object(service.signal, 'signal'), \
                        patch.object(service.signal, 'SIGHUP', 1, create=True), \
                        patch.object(service, 'load', side_effect=lambda p: json.loads(pathlib.Path(p).read_text())), \
                        patch.object(service, 'status'), patch.object(service, 'j', {}), \
                        patch.object(service, 'shutdown', shutdown), patch.object(service, 'close_berry_indicator'), \
                        patch.object(service, 'prepare_connection', return_value=False), patch.object(service, 'restore') as restore:
                    service.serve()
                self.assertEqual(restore.call_count, 0 if shutdown else 1)


class PreparationBoundaryTests(unittest.TestCase):
    def test_disable_during_handoff_restores_selection_before_first_journal(self):
        import unified_install
        with patch.object(u, 'prepare', side_effect=RuntimeError('stopped')), \
                patch.object(u, 'verify'), patch.object(service, 'j', None), \
                patch.object(service, 'shutdown', False), \
                patch.object(u.os.path, 'isfile', side_effect=lambda p: p == service.STOP), \
                patch.object(unified_install, 'management_lock', return_value=contextlib.nullcontext()), \
                patch.object(d, 'restore_network_selection') as selection, \
                patch.object(d, 'restore_lte_mode') as mode:
            with self.assertRaisesRegex(RuntimeError, 'stopped'):
                u.locked_prepare()
        selection.assert_called_once()
        mode.assert_called_once()

    def test_handoff_stop_does_not_restore_on_shutdown_or_without_explicit_disable(self):
        import unified_install
        for shutdown, enabled, stop, journal in ((True, False, True, None),
                (False, True, True, None), (False, False, False, None),
                (False, False, True, {})):
            with self.subTest(shutdown=shutdown, enabled=enabled, stop=stop, journal=journal), \
                    patch.object(u, 'prepare', return_value=False), patch.object(u, 'verify'), \
                    patch.object(service, 'j', journal), patch.object(service, 'shutdown', shutdown), \
                    patch.object(u.os.path, 'isfile', side_effect=lambda p: (
                        stop if p == service.STOP else enabled if p == u.BASE + '/enabled' else False)), \
                    patch.object(unified_install, 'management_lock', return_value=contextlib.nullcontext()), \
                    patch.object(d, 'restore_network_selection') as selection, \
                    patch.object(d, 'restore_lte_mode') as mode:
                self.assertFalse(u.locked_prepare())
                selection.assert_not_called()
                mode.assert_not_called()

    def test_handoff_restore_failure_is_reported(self):
        import unified_install
        with patch.object(u, 'prepare', return_value=False), patch.object(u, 'verify'), \
                patch.object(service, 'j', None), patch.object(service, 'shutdown', False), \
                patch.object(u.os.path, 'isfile', side_effect=lambda p: p == service.STOP), \
                patch.object(unified_install, 'management_lock', return_value=contextlib.nullcontext()), \
                patch.object(d, 'restore_network_selection', side_effect=RuntimeError('restore_unconfirmed')):
            with self.assertRaisesRegex(RuntimeError, 'restore_unconfirmed'):
                u.locked_prepare()

    def test_disable_releases_explicit_lock_without_an_ims_journal(self):
        with patch.object(u, 'setup'), patch.object(u, 'verify'), \
                patch.object(service, 'phone_idle', return_value=True), \
                patch.object(u.os.path, 'isfile', return_value=False), \
                patch.object(u, 'boot_token', return_value=['boot']), patch.object(native, 'atomic'), \
                patch.object(d, 'restore_network_selection') as selection, patch.object(d, 'restore_lte_mode') as mode:
            result = u.service_action('disable')
        self.assertTrue(result['disabled'])
        selection.assert_called_once()
        mode.assert_called_once()

    def test_enable_uses_guarded_retry_instead_of_requiring_reboot(self):
        with patch.object(u, 'setup'), patch.object(u, 'verify'), \
                patch.object(service, 'phone_idle', return_value=True), \
                patch.object(service, 'read_status', return_value={'manager_alive': False}), \
                patch.object(u.os.path, 'isfile', return_value=True), \
                patch.object(u, 'public_status', return_value={'pre_native_retry_available': True}), \
                patch.object(u, 'launch', return_value={'started_manager_pid': 42}) as launch, \
                patch.object(native, 'atomic') as write:
            result = u.service_action('enable')
        self.assertFalse(result['reboot_required'])
        launch.assert_called_once()
        write.assert_not_called()

    def run_prepare(self, network_error=None, dca_ready=True):
        from test_auto_carrier import facts, card
        import unified_migrate
        events = []
        def save(path, value):
            if path == u.ATTEMPT:
                events.append(value['stage'])
        def network(*args):
            self.assertEqual(events, ['pre_native'])
            if network_error:
                raise RuntimeError(network_error)
            events.append('network_ready')
            return True
        def configure():
            self.assertEqual(events, ['pre_native', 'network_ready', 'native_configured'])
            events.append('configure')
        with contextlib.ExitStack() as stack:
            for item in (patch.object(u, 'verify', return_value=facts()),
                         patch.object(u, 'boot_token', return_value=['boot']),
                         patch.object(u.os.path, 'isfile', return_value=False),
                         patch.object(native, 'crypto_policy', return_value={'swcr_id': -1, 'crypto_support': 0}),
                         patch.object(native, 'ims_pids', return_value=[]), patch.object(u, 'handoff'),
                         patch.object(unified_migrate, 'finish_previous_boot'), patch.object(u, 'reconcile'),
                         patch.object(u, 'core_stopping', return_value=False), patch.object(u, 'card', return_value=card()),
                         patch.object(u.profiles, 'carrier_template', return_value=({'path': '/etc/carrier/config/36.xml', 'sha256': 'a' * 64}, b'')),
                         patch.object(u, 'save', side_effect=save), patch.object(u, 'notify_sim_change'),
                         patch.object(service, 'j', None), patch.object(u, 'selected', None),
                         patch.object(service, 'ACTIVE_PROFILE', copy.deepcopy(service.ACTIVE_PROFILE)),
                         patch.object(service, 'ACTIVE_REQUEST', copy.deepcopy(service.ACTIVE_REQUEST)),
                         patch.object(service, 'UPDATES', copy.deepcopy(service.UPDATES)),
                         patch.object(service, 'init_journal', side_effect=lambda: setattr(service, 'j', {})),
                         patch.object(service, 'save_journal'), patch.object(service, 'status'),
                         patch.object(d, 'prepare', return_value=dca_ready),
                         patch.object(service, 'wait_for_network', side_effect=network),
                         patch.object(u, 'reconcile_stale_sms_busy'), patch.object(service, 'configure', side_effect=configure)):
                stack.enter_context(item)
            if network_error:
                with self.assertRaisesRegex(RuntimeError, network_error):
                    u.prepare()
            else:
                self.assertEqual(u.prepare(), dca_ready)
        return events

    def test_native_attempt_is_committed_only_after_network_readiness(self):
        self.assertEqual(self.run_prepare(), ['pre_native', 'network_ready', 'native_configured', 'configure'])

    def test_network_failure_never_consumes_native_attempt(self):
        self.assertEqual(self.run_prepare('Readiness timed out'), ['pre_native'])

    def test_passport_policy_reboot_is_persisted_before_return(self):
        self.assertEqual(self.run_prepare(dca_ready=False), ['pre_native', 'policy_reboot'])


class MobileGuidanceTests(unittest.TestCase):
    def test_update_text_keeps_existing_reboot_protocol_and_poll_action(self):
        from test_mobile_runtime import WORKER
        for state, expected in (('running', 'working'), ('waiting_reboot', 'reboot_required')):
            job = {'id': 'a' * 32, 'action': 'update', 'state': state,
                   'phase': 'updating', 'commit_outcome_unknown': False}
            result = WORKER.job_response(job, {'language': 'en'})
            self.assertEqual(result['state'], expected)
            self.assertEqual(result['primary_action'], 'poll')
            self.assertIn('service', result['display']['title'].lower())

    def test_retry_is_offered_only_for_verified_pre_native_restore(self):
        from test_mobile_runtime import WORKER
        report = {'installed': True, 'sim_supported': True, 'status': {
                  'enabled': True, 'phase': 'error_restored', 'pre_native_retry_available': True}}
        with patch.object(WORKER, 'engine') as manager, patch.object(WORKER.os.path, 'isfile', return_value=False):
            manager.return_value.BASE = '/synthetic'
            result = WORKER.inspection_response({'language': 'en'}, report, {})
            self.assertEqual(result['state'], 'retry_ready')
            self.assertEqual(result['primary_action'], 'enable')
            report['status']['pre_native_retry_available'] = False
            self.assertEqual(WORKER.inspection_response({}, report, {})['state'], 'recovery_required')


class UsbAndDiagnosticTests(unittest.TestCase):
    def test_explicit_cli_network_actions_use_the_verified_transport(self):
        import ai_skill
        auto = MagicMock()
        auto.action.return_value = {'network_locked': True, 'target_plmn': '460-01', 'private_identity': 'secret'}
        for action in ('lock-network', 'unlock-network'):
            with patch.object(ai_skill.root_setup, 'verify_root', return_value={'host': 'bb10-root', 'config': ''}), \
                    patch.object(connection, 'resolve_connection', return_value=(MagicMock(), {})), \
                    patch.object(ai_skill, 'AutoClient', return_value=auto):
                rc, result = ai_skill.run(['volte', action])
            self.assertEqual(rc, 0)
            auto.action.assert_called_with(action)
            self.assertNotIn('secret', json.dumps(result))

    def test_only_one_verified_link_local_30_peer_is_selected(self):
        import root_setup
        good = {'usb_count': 1, 'usb_peer': '169.254.54.61', 'usb_source_address': '169.254.54.62'}
        for overrides, expected in (({}, ('169.254.54.61', '169.254.54.62')),
                                    ({'usb_count': 2}, None), ({'usb_peer': '169.254.54.65'}, None),
                                    ({'usb_peer': '192.168.1.1'}, None), ({'usb_source_address': 'garbage'}, None)):
            with patch.object(root_setup, 'local_usb_state', return_value=dict(good, **overrides)):
                self.assertEqual(connection.dynamic_usb_link(), expected)

    def test_dynamic_peer_keeps_key_pin_and_does_not_override_proxy_or_remote(self):
        for suffix, applies in (('', True), ('hostkeyalias dedicated-phone\n', True),
                                ('proxyjump owner-proxy\n', False)):
            client = MagicMock(options=['-o', 'StrictHostKeyChecking=yes'])
            client.process.return_value = 'hostname 169.254.0.1\nuser root\n' + suffix
            connection._apply_dynamic_usb_peer(client, ('169.254.54.61', '169.254.54.62'))
            self.assertEqual('HostName=169.254.54.61' in client.options, applies)
            self.assertIn('StrictHostKeyChecking=yes', client.options)
            if applies:
                self.assertIn('HostKeyAlias=' + ('dedicated-phone' if suffix else '169.254.0.1'), client.options)
        client.process.return_value = 'hostname remote.example\nuser root\n'
        client.options = []
        connection._apply_dynamic_usb_peer(client, ('169.254.54.61', '169.254.54.62'))
        self.assertEqual(client.options, [])

    def test_diagnostics_decode_bands_without_exporting_identifiers(self):
        for mask, bands in ((4108, [3, 4, 13]), (True, []), (-1, []), (1 << 64, []), ('secret', [])):
            self.assertEqual(compatibility.decode_lte_bands(mask), bands)
        result = compatibility.public_network_diagnostics({'scan_mode': 'MANUAL', 'roaming': True,
                    'data_roaming_mode': 'OFF', 'lte_band_capability_mask': 4108, 'cell_id': 'secret'})
        self.assertEqual(result['lte_capability_bands'], [3, 4, 13])
        self.assertNotIn('secret', json.dumps(result))
        self.assertIsNone(compatibility.public_network_diagnostics({'scan_mode': 'secret'})['scan_mode'])


if __name__ == '__main__':
    unittest.main()
