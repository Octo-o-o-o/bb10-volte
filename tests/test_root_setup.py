"""First-use checks and destructive-operation gates; never flashes hardware."""
import hashlib
import contextlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import root_setup as r
import root_flash as rf
from workflow import WorkflowError
from root_flash import classify_output


class RootSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.kit = Path(self.temp.name)
        self.lock_patch = patch.object(r, 'root_lock_path', return_value=self.kit / 'root-flash.lock')
        self.lock_patch.start()
        self.addCleanup(self.lock_patch.stop)
        (self.kit / 'images').mkdir()
        self.state = self.kit / 'setup-state.json'
        self.state.write_text(json.dumps({'variant': 'SQN100-3', 'stage': 'prepared'}))
        images = []
        for name in ('Q10_os.exe', 'Q10_radio.exe'):
            data = ('non-executable fixture ' + name).encode()
            (self.kit / 'images' / name).write_bytes(data)
            images.append({'file': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        (self.kit / 'build-verification.json').write_text(json.dumps({'offline_build_verified': True, 'images': images}))
        self.usb = {'usb_count': 1, 'device': {'ModelName': 'SQN100-3'}}

    def test_phone_confirmation_is_required_before_any_flash_process(self):
        with patch.object(r.sys, 'platform', 'win32'), patch.object(r.subprocess, 'run') as run:
            with self.assertRaisesRegex(r.SetupError, 'flash_confirmation_required'):
                r.flash_root(self.kit, False, lambda _: None)
            run.assert_not_called()

    def test_tampered_image_and_unknown_prior_outcome_cannot_be_retried(self):
        (self.kit / 'images/Q10_os.exe').write_text('changed')
        with self.assertRaisesRegex(r.SetupError, 'image_not_verified'):
            r.prepared_images(self.kit)
        self.state.write_text(json.dumps({'variant': 'SQN100-3', 'stage': 'os_started'}))
        with self.assertRaisesRegex(r.SetupError, 'flash_state_unknown'):
            r.prepared_images(self.kit)

    def test_wrong_model_or_multiple_connected_devices_block_flashing(self):
        for usb in ({'usb_count': 2, 'device': {'ModelName': 'SQN100-3'}},
                    {'usb_count': 1, 'device': {'ModelName': 'SQC100-1'}}):
            with patch.object(r.sys, 'platform', 'win32'), patch.object(r, 'local_usb_state', return_value=usb), patch.object(r.subprocess, 'run') as run:
                with self.assertRaisesRegex(r.SetupError, 'device_model_not_verified'):
                    r.flash_root(self.kit, True, lambda _: None)
                run.assert_not_called()

    def test_existing_root_and_wrong_ssh_keys_are_not_repaired_by_flashing(self):
        for root_result, expected in [(None, 'already_rooted'),
                                      (WorkflowError('authentication_failed'), 'ssh_access_needs_repair')]:
            with patch.object(r.sys, 'platform', 'win32'), patch.object(r, 'local_usb_state', return_value=self.usb), patch.object(r.subprocess, 'run') as run, patch.object(r, 'verify_root', side_effect=root_result):
                with self.assertRaisesRegex(r.SetupError, expected):
                    r.flash_root(self.kit, True, lambda _: None)
                run.assert_not_called()

    def test_os_failure_stops_before_radio_and_preserves_uncertain_state(self):
        with patch.object(r.sys, 'platform', 'win32'), patch.object(r, 'local_usb_state', return_value=self.usb), patch.object(r, 'verify_root', side_effect=WorkflowError('connection_refused')), patch.object(r, 'run_flash_stage', side_effect=r.SetupError('flash_state_unknown')) as run:
            with self.assertRaisesRegex(r.SetupError, 'flash_state_unknown'):
                r.flash_root(self.kit, True, lambda _: None)
            self.assertEqual(run.call_count, 1)
        self.assertEqual(json.loads(self.state.read_text())['stage'], 'os_uncertain')
        self.assertTrue(r.root_lock_path().is_file())

    def test_verified_pair_runs_in_order_and_still_requires_postboot_root_check(self):
        with patch.object(r.sys, 'platform', 'win32'), patch.object(r, 'local_usb_state', return_value=self.usb), patch.object(r, 'verify_root', side_effect=WorkflowError('connection_refused')), patch.object(r, 'run_flash_stage', return_value={'completed': True}) as run:
            result = r.flash_root(self.kit, True, lambda _: None)
        self.assertEqual([call.args[1] for call in run.call_args_list], ['os', 'radio'])
        self.assertEqual(result['host'], 'bb10-root')
        self.assertEqual(json.loads(self.state.read_text())['stage'], 'flashed_waiting_for_root')
        self.assertFalse(r.root_lock_path().exists())

    def mac_kit(self):
        self.state.write_text(json.dumps({'variant': 'SQN100-3', 'platform': 'darwin', 'stage': 'prepared'}))
        images = []
        for name in ('Q10_os.unsigned', 'Q10_radio.signed'):
            data = ('non-executable Mac fixture ' + name).encode()
            (self.kit / 'images' / name).write_bytes(data)
            images.append({'file': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        (self.kit / 'build-verification.json').write_text(json.dumps({'offline_build_verified': True, 'images': images}))
        return dict(self.usb, usb_address_ready=True)

    def test_mac_preparation_dispatches_only_to_offline_native_builder(self):
        prepare = MagicMock(return_value='private/mac-kit')
        module = SimpleNamespace(prepare_root_kit_macos=prepare)
        with patch.object(r.sys, 'platform', 'darwin'), patch.dict(sys.modules, {'macos_root': module}), \
                patch.object(r, 'run_flash_stage') as flash:
            self.assertEqual(r.prepare_root_kit('SQN100-3', print, 'proxy', 'cache', True), 'private/mac-kit')
            prepare.assert_called_once_with('SQN100-3', print, 'proxy', 'cache', True)
            flash.assert_not_called()

    def test_mac_uses_hashed_native_payloads_and_cannot_flash_windows_kit(self):
        with patch.object(r.sys, 'platform', 'darwin'), patch.object(r, 'local_usb_state') as probe:
            with self.assertRaisesRegex(r.SetupError, 'root_platform_mismatch'):
                r.flash_root(self.kit, True, print)
            probe.assert_not_called()
        self.mac_kit()
        _, images = r.prepared_images(self.kit)
        self.assertEqual([image.name for image in images], ['Q10_os.unsigned', 'Q10_radio.signed'])
        (self.kit / 'images/Q10_os.unsigned').write_text('modified payload')
        with self.assertRaisesRegex(r.SetupError, 'image_not_verified'):
            r.prepared_images(self.kit)

    def test_mac_requires_confirmed_source_address_and_blocks_existing_root(self):
        usb = self.mac_kit()
        for ready in (None, False):
            with patch.object(r.sys, 'platform', 'darwin'), patch.object(r, 'local_usb_state', return_value=dict(usb, usb_address_ready=ready)), \
                    patch.object(r, 'run_flash_stage') as flash:
                with self.assertRaisesRegex(r.SetupError, 'usb_source_address_required'):
                    r.flash_root(self.kit, True, print)
                flash.assert_not_called()
        with patch.object(r.sys, 'platform', 'darwin'), patch.object(r, 'local_usb_state', return_value=usb), \
                patch.object(r, 'verify_root', return_value={}), patch.object(r, 'run_flash_stage') as flash:
            with self.assertRaisesRegex(r.SetupError, 'already_rooted'):
                r.flash_root(self.kit, True, print)
            flash.assert_not_called()

    def test_mac_os_failure_never_reaches_radio_or_retries(self):
        usb = self.mac_kit()
        with patch.object(r.sys, 'platform', 'darwin'), patch.object(r, 'local_usb_state', return_value=usb), \
                patch.object(r, 'verify_root', side_effect=WorkflowError('connection_refused')), \
                patch.object(r, 'run_flash_stage', side_effect=r.SetupError('flash_state_unknown')) as flash:
            with self.assertRaisesRegex(r.SetupError, 'flash_state_unknown'):
                r.flash_root(self.kit, True, print)
            flash.assert_called_once()
        self.assertEqual(json.loads(self.state.read_text())['stage'], 'os_uncertain')
        self.assertTrue(r.root_lock_path().is_file())

    def test_mac_complete_pair_still_requires_postboot_root_verification(self):
        usb = self.mac_kit()
        with patch.object(r.sys, 'platform', 'darwin'), patch.object(r, 'local_usb_state', return_value=usb), \
                patch.object(r, 'verify_root', side_effect=WorkflowError('connection_refused')), \
                patch.object(r, 'run_flash_stage', return_value={'completed': True}) as flash:
            r.flash_root(self.kit, True, lambda _: None)
        self.assertEqual([call.args[1] for call in flash.call_args_list], ['os', 'radio'])
        self.assertEqual(json.loads(self.state.read_text())['stage'], 'flashed_waiting_for_root')

    def test_mac_console_and_cli_dispatch_to_native_wrapper_without_executing_exe(self):
        launch, native = MagicMock(return_value={'completed': True}), MagicMock(return_value=0)
        module = SimpleNamespace(launch_stage=launch, run_stage=native)
        with patch.object(r.sys, 'platform', 'darwin'), patch.dict(sys.modules, {'macos_root_flash': module}), \
                patch.object(r.subprocess, 'run') as run:
            self.assertEqual(r.run_flash_stage(self.kit, 'os', 'token'), {'completed': True})
            launch.assert_called_once_with(self.kit, 'os', 'token')
            self.assertEqual(rf.run_stage(self.kit, 'radio', 'token'), 0)
            native.assert_called_once_with(self.kit, 'radio', 'token')
            run.assert_not_called()

    def test_local_probe_does_not_open_development_or_raw_ssh_sessions(self):
        with patch.object(r.sys, 'platform', 'darwin'), patch.object(r, 'discovery', return_value={'DeveloperModeEnabled': '0'}), patch('macos_usb.read_state', return_value={}), patch('socket.create_connection') as connect:
            state = r.local_usb_state()
        self.assertEqual(state['device']['DeveloperModeEnabled'], '0')
        self.assertIsNone(state['ssh_port'])
        connect.assert_not_called()

    def root_client(self, result):
        client = MagicMock()
        client.stage.return_value.__enter__.return_value = '/var/rootdata/q10_volte_stage_123456abcdef'
        client.execute.return_value = result
        return client

    def test_root_verification_uses_script_and_saves_only_after_valid_zero_euid(self):
        client = self.root_client({'schema': 1, 'euid': 0})
        choice = {'host': 'q10-root', 'config': 'personal/ssh_config'}
        with patch.object(r, 'resolve_connection', return_value=(client, choice)), patch.object(r, 'save_connection') as save:
            self.assertEqual(r.verify_root(), choice)
        client.stage.assert_called_once_with(diagnostic='root')
        client.execute.assert_called_once_with('/var/rootdata/q10_volte_stage_123456abcdef/root-probe.py', timeout=15)
        client.remote.assert_not_called()
        save.assert_called_once_with(choice['host'], choice['config'])

    def test_nonroot_and_malformed_result_are_cleaned_before_rejection_without_saving(self):
        values = [({'schema': 1, 'euid': 1000}, 'root_not_ready'),
                  ({'schema': 1, 'euid': False}, 'root_probe_failed'),
                  ({'schema': 1, 'euid': '0'}, 'root_probe_failed'),
                  ({'schema': True, 'euid': 0}, 'root_probe_failed'),
                  ({'schema': 1, 'euid': -1}, 'root_probe_failed'), ({}, 'root_probe_failed'),
                  ([], 'root_probe_failed')]
        for value, code in values:
            with self.subTest(value=value):
                events = []
                client = self.root_client(value)
                @contextlib.contextmanager
                def stage(**_):
                    yield '/owned-stage'
                    events.append('cleaned')
                client.stage = stage
                with patch.object(r, 'resolve_connection', return_value=(client, {})), patch.object(r, 'save_connection') as save:
                    with self.assertRaisesRegex(r.SetupError, code):
                        r.verify_root()
                self.assertEqual(events, ['cleaned'])
                save.assert_not_called()

    def test_transport_and_identity_errors_are_preserved_and_probe_rejection_is_distinct(self):
        for code in ('host_key_mismatch', 'authentication_failed', 'connection_refused',
                     'connection_failed', 'connection_timeout_state_unknown', 'remote_operation_failed',
                     'invalid_device_response'):
            with self.subTest(code=code):
                client = self.root_client(None)
                client.execute.side_effect = WorkflowError(code)
                expected = 'root_probe_failed' if code in ('remote_operation_failed', 'invalid_device_response') else code
                error_type = r.SetupError if expected == 'root_probe_failed' else WorkflowError
                with patch.object(r, 'resolve_connection', return_value=(client, {})), patch.object(r, 'save_connection') as save:
                    with self.assertRaisesRegex(error_type, expected):
                        r.verify_root()
                save.assert_not_called()

    def test_only_the_complete_recorded_v4_os_security_result_allows_radio_continuation(self):
        value = classify_output('os', 73, True, True, True, False)
        self.assertTrue(value['completed'])
        self.assertTrue(value['expected_v4_os_security_result'])
        for fields in [('os', 73, False, True, True, False), ('os', 1, True, True, True, False),
                       ('os', 0, False, False, False, False),
                       ('radio', 73, True, True, True, False), ('radio', 0, True, False, False, False)]:
            self.assertFalse(classify_output(*fields)['completed'])
