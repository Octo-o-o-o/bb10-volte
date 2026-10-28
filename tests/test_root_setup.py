"""First-use checks and destructive-operation gates; never flashes hardware."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import root_setup as r
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

    def test_local_probe_does_not_open_development_or_raw_ssh_sessions(self):
        with patch.object(r.sys, 'platform', 'darwin'), patch.object(r, 'discovery', return_value={'DeveloperModeEnabled': '0'}), patch('socket.create_connection') as connect:
            state = r.local_usb_state()
        self.assertEqual(state['device']['DeveloperModeEnabled'], '0')
        self.assertIsNone(state['ssh_port'])
        connect.assert_not_called()

    def test_only_the_complete_recorded_v4_os_security_result_allows_radio_continuation(self):
        value = classify_output('os', 73, True, True, True, False)
        self.assertTrue(value['completed'])
        self.assertTrue(value['expected_v4_os_security_result'])
        for fields in [('os', 73, False, True, True, False), ('os', 1, True, True, True, False),
                       ('os', 0, False, False, False, False),
                       ('radio', 73, True, True, True, False), ('radio', 0, True, False, False, False)]:
            self.assertFalse(classify_output(*fields)['completed'])
