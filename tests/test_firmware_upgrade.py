"""Version routing, stock upgrade journal and failure injection; no phone I/O."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import firmware_upgrade as u
import firmware_flash as flash
import firmware_policy as policy
import root_setup as r
from connection_flow import guidance


class FirmwarePolicyTests(unittest.TestCase):
    def test_exact_baseline_and_numeric_order(self):
        for version, state in [('10.3.3.3216', 'ready'), ('10.3.03.3216', 'ready'),
                               ('10.2.1.3442', 'upgrade'), ('10.3.2.9999', 'upgrade'),
                               ('10.3.3.2205', 'upgrade'), ('10.3.3.9999', 'newer'),
                               ('10.3.10.1', 'newer'), ('10.3.3', 'unknown'), ('10.3.3.3216\n', 'unknown'),
                               ('10.3.3.3216 other', 'unknown'), ('3216', 'unknown'), (None, 'unknown')]:
            with self.subTest(version=version):
                self.assertEqual(policy.assess_version(version).state, state)

    def test_versions_route_before_root_but_multiple_devices_never_upgrade(self):
        for model in ('SQN100-3', 'SQC100-2', 'SQW100-4'):
            usb = {'usb_count': 1, 'device': {'ModelName': model, 'PlatformVersion': '10.3.2.2876'}}
            for verified in (True, False):
                view = guidance(usb, 'connection_setup_required', verified)
                self.assertEqual(view.action, 'firmware')
                self.assertEqual(view.state, 'firmware_upgrade')
            usb['usb_count'] = 2
            for verified in (True, False):
                self.assertEqual(guidance(usb, verified=verified).state, 'multiple')

    def test_root_cannot_write_on_unknown_older_or_newer_os(self):
        for version, code in [(None, 'firmware_version_unknown'), ('10.3.3.2205', 'firmware_upgrade_required'),
                              ('10.3.3.9999', 'firmware_downgrade_blocked')]:
            with self.subTest(version=version), patch.object(r.sys, 'platform', 'win32'), \
                    patch.object(r, 'prepared_images', return_value=({'variant': 'SQN100-3'}, [])), \
                    patch.object(r, 'local_usb_state', return_value={'usb_count': 1, 'device': {'ModelName': 'SQN100-3', 'PlatformVersion': version}}), \
                    patch.object(r, 'verify_root') as probe, patch.object(r, 'run_flash_stage') as run:
                with self.assertRaisesRegex(r.SetupError, code):
                    r.flash_root('fixture', True, lambda _: None)
                probe.assert_not_called()
                run.assert_not_called()


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'root-kit-test'
        (self.folder / 'stock').mkdir(parents=True)
        self.original = self.folder / 'stock' / 'phone.exe'
        self.original.write_bytes(b'non executable verified fixture')
        digest = hashlib.sha256(self.original.read_bytes()).hexdigest()
        self.stock = {'id': 'stock-passport', 'family': 'passport', 'extracted_file': 'phone.exe',
                      'extracted_sha256': digest, 'sha256': digest, 'file': 'phone.exe'}
        self.state = {'schema': 1, 'stage': 'prepared', 'target': policy.TARGET_OS, 'variant': 'SQW100-4',
                      'platform': 'win32', 'firmware_id': self.stock['id'], 'stock_sha256': digest,
                      'images': [{'phase': 'stock', 'file': 'stock/phone.exe', 'bytes': self.original.stat().st_size,
                                  'sha256': digest}]}
        self.usb = {'usb_count': 1, 'device': {'ModelName': 'SQW100-4', 'PlatformVersion': '10.3.3.2205'}}
        self.lock = Path(self.temp.name) / 'shared.lock'
        for target, name, value in [(r, 'stock_firmware', lambda *_: self.stock),
                                    (r, 'local_usb_state', lambda: self.usb),
                                    (r, 'root_lock_path', lambda: self.lock),
                                    (u, 'private_root', lambda: Path(self.temp.name))]:
            item = patch.object(target, name, value)
            item.start()
            self.addCleanup(item.stop)
        platform = patch.object(u.sys, 'platform', 'win32')
        platform.start()
        self.addCleanup(platform.stop)
        self.save()

    def save(self):
        u.write_state(self.folder, self.state)

    def run_upgrade(self):
        return u.upgrade(self.folder, True, '10.3.3.2205', lambda _: None)

    def test_prepare_does_not_contact_or_flash_phone(self):
        (self.folder / u.JOURNAL).unlink()
        with patch.object(r, 'prepare_root_kit', return_value=str(self.folder)) as prepare, \
                patch.object(u.shutil, 'disk_usage', return_value=SimpleNamespace(free=32 * 1024 ** 3)), \
                patch.object(r, 'prepared_images', return_value=({'variant': 'SQW100-4'}, [])), \
                patch.object(r, 'local_usb_state') as probe, patch.object(flash, 'launch_stage') as run:
            result = u.prepare_upgrade('SQW100-4', print, 'proxy', 'cache', True)
        self.assertEqual(result, str(self.folder))
        prepare.assert_called_once_with('SQW100-4', print, 'proxy', 'cache', True)
        probe.assert_not_called()
        run.assert_not_called()
        self.assertEqual(u.read_state(self.folder)['stage'], 'prepared')

    def test_insufficient_disk_stops_before_preparation_or_phone_access(self):
        with patch.object(u.shutil, 'disk_usage', return_value=SimpleNamespace(free=24 * 1024 ** 3 - 1)), \
                patch.object(r, 'prepare_root_kit') as prepare, \
                patch.object(r, 'local_usb_state') as probe, patch.object(flash, 'launch_stage') as launch:
            with self.assertRaisesRegex(r.SetupError, 'upgrade_insufficient_disk'):
                u.prepare_upgrade('SQW100-4', lambda _: None, offline=True)
        prepare.assert_not_called()
        probe.assert_not_called()
        launch.assert_not_called()

    def test_unsupported_platform_never_downloads_or_prepares(self):
        with patch.object(u.sys, 'platform', 'linux'), patch.object(r, 'prepare_root_kit') as prepare:
            with self.assertRaisesRegex(r.SetupError, 'root_platform_mismatch'):
                u.prepare_upgrade('SQW100-4', print)
            prepare.assert_not_called()

    def test_boot_verification_rechecks_receipt_and_platform(self):
        self.state['stage'] = 'awaiting_reboot'
        self.state['platform'] = 'darwin'
        self.save()
        with patch.object(r, 'local_usb_state') as probe:
            with self.assertRaisesRegex(r.SetupError, 'root_platform_mismatch'):
                u.verify_boot(self.folder)
            probe.assert_not_called()

    def test_confirmation_model_version_and_single_device_are_rechecked(self):
        cases = [({'usb_count': 2, 'device': self.usb['device']}, 'device_model_not_verified'),
                 ({'usb_count': 1, 'device': {'ModelName': 'SQN100-3', 'PlatformVersion': '10.3.3.2205'}}, 'device_model_not_verified'),
                 ({'usb_count': 1, 'device': {'ModelName': 'SQW100-4'}}, 'firmware_version_unknown')]
        for version, error in [('10.3.3.3216', 'firmware_already_current'), ('10.3.3.9999', 'firmware_downgrade_blocked'),
                               ('10.3.2.2876', 'firmware_device_changed')]:
            cases.append(({'usb_count': 1, 'device': {'ModelName': 'SQW100-4', 'PlatformVersion': version}}, error))
        with patch.object(flash, 'launch_stage') as run:
            with self.assertRaisesRegex(r.SetupError, 'flash_confirmation_required'):
                u.upgrade(self.folder, False, '10.3.3.2205', print)
            for usb, error in cases:
                usb['usb_address_ready'] = True
                with self.subTest(error=error), patch.object(r, 'local_usb_state', return_value=usb):
                    with self.assertRaisesRegex(r.SetupError, error):
                        self.run_upgrade()
            run.assert_not_called()
        self.assertFalse(self.lock.exists())

    def test_source_or_receipt_tampering_blocks_before_hardware(self):
        mutations = [lambda value: value.update(target='10.3.3.2205'),
                     lambda value: value.update(stock_sha256='0' * 64),
                     lambda value: value['images'][0].update(file='../other.exe'),
                     lambda value: value['images'][0].update(sha256='0' * 64),
                     lambda value: value['images'][0].update(phase='stock_radio')]
        with patch.object(flash, 'launch_stage') as run:
            for mutation in mutations:
                value = copy.deepcopy(self.state)
                mutation(value)
                u.write_state(self.folder, value)
                with self.assertRaises(r.SetupError):
                    self.run_upgrade()
            self.save()
            self.original.write_bytes(b'changed')
            with self.assertRaisesRegex(r.SetupError, 'image_not_verified'):
                self.run_upgrade()
            run.assert_not_called()

    def test_loader_success_waits_for_boot_readback_and_never_starts_root(self):
        with patch.object(flash, 'launch_stage', return_value={'completed': True, 'stage': 'stock'}) as run, \
                patch.object(r, 'flash_root') as root_flash:
            self.run_upgrade()
            self.assertEqual(run.call_count, 1)
            root_flash.assert_not_called()
        self.assertEqual(u.read_state(self.folder)['stage'], 'awaiting_reboot')
        self.assertFalse(self.lock.exists())
        with self.assertRaisesRegex(r.SetupError, 'firmware_boot_not_verified'):
            u.verify_boot(self.folder)
        self.usb['device']['PlatformVersion'] = '10.3.3.3216'
        self.assertEqual(u.verify_boot(self.folder)['stage'], 'os_verified')
        with patch.object(flash, 'launch_stage') as run:
            with self.assertRaisesRegex(r.SetupError, 'flash_state_unknown'):
                self.run_upgrade()
            run.assert_not_called()

    def test_failure_preserves_lock_and_cannot_retry_or_skip_to_root(self):
        with patch.object(flash, 'launch_stage', side_effect=r.SetupError('flash_state_unknown')) as run:
            with self.assertRaises(r.SetupError):
                self.run_upgrade()
            self.assertEqual(u.read_state(self.folder)['stage'], 'uncertain')
            self.assertTrue(self.lock.exists())
            with self.assertRaises(r.SetupError):
                self.run_upgrade()
            with self.assertRaises(r.SetupError):
                u.verify_boot(self.folder)
            self.assertEqual(run.call_count, 1)

    def test_existing_shared_lock_blocks_without_overwrite(self):
        self.lock.write_text('other operation')
        with patch.object(flash, 'launch_stage') as run:
            with self.assertRaisesRegex(r.SetupError, 'flash_state_unknown'):
                self.run_upgrade()
            run.assert_not_called()
        self.assertEqual(self.lock.read_text(), 'other operation')
        self.assertEqual(u.read_state(self.folder)['stage'], 'prepared')

    def test_history_is_observation_only(self):
        with patch.object(flash, 'launch_stage') as run, patch.object(r, 'local_usb_state') as probe:
            history = u.pending_upgrades()
            self.assertEqual(history[0]['stage'], 'prepared')
            run.assert_not_called()
            probe.assert_not_called()


class StockEvidenceTests(unittest.TestCase):
    def test_original_firmware_never_accepts_unsigned_root_security_error(self):
        for code, lines, expected in [
                (0, ['Writing 100%', 'Done.'], True), (0, ['Done.'], False),
                (73, ['Writing 100%', 'Error: Failed to load images.', 'Error: Security Error.'], False),
                (0, ['Writing 100%', 'Error: Security Error.', 'Done.'], False),
                (0, ['Writing 100 bytes', 'Done.'], False),
                (0, ['Writing 100.0%', 'Done.'], True),
                (0, ['[                  Writing  0x0092C044 ] [############## 100 ##############]', 'Done.'], True),
                (0, ['[                  Writing  0x0092C044 ] [##############  99 ##############]', 'Done.'], False),
                (0, ['Writing 0x00000100', 'Done.'], False),
                (1, ['Writing 100%', 'Done.'], False)]:
            evidence = flash.StockFlashEvidence()
            for line in lines:
                evidence.line(line)
            self.assertEqual(evidence.result('stock', code)['completed'], expected)


class MacUpgradeTests(UpgradeTests):
    """Run the same failure matrix with two signed native stages."""
    def setUp(self):
        super().setUp()
        platform = patch.object(u.sys, 'platform', 'darwin')
        platform.start()
        self.addCleanup(platform.stop)
        self.usb['usb_address_ready'] = True
        output = self.folder / 'stock-upgrade'
        output.mkdir()
        self.signed = {}
        self.state.update(platform='darwin', images=[])
        for number, phase in enumerate(('stock_os', 'stock_radio')):
            path = output / ('phone.' + str(number) + '.signed')
            path.write_bytes((phase.encode() + b' signed fixture ') * 100)
            item = {'bytes': path.stat().st_size, 'sha256': u.sha(path)}
            self.signed[phase] = item
            self.state['images'].append(dict(item, phase=phase, file=path.relative_to(self.folder).as_posix()))
        spec = patch.object(u, 'stock_images', return_value=self.signed)
        spec.start()
        self.addCleanup(spec.stop)
        self.save()

    def test_prepare_does_not_contact_or_flash_phone(self):
        import macos_root
        output = self.folder / 'stock-upgrade'
        contents = {p.name: p.read_bytes() for p in output.iterdir()}
        for path in output.iterdir():
            path.unlink()
        output.rmdir()
        def split(command, **kwargs):
            self.assertEqual(command[1], 'split')
            self.assertNotIn('flash', command)
            for name, data in contents.items():
                (output / name).write_bytes(data)
            return SimpleNamespace(returncode=0)
        with patch.object(r, 'prepare_root_kit', return_value=str(self.folder)), \
                patch.object(u.shutil, 'disk_usage', return_value=SimpleNamespace(free=32 * 1024 ** 3)), \
                patch.object(r, 'prepared_images', return_value=({'variant': 'SQW100-4'}, [])), \
                patch.object(macos_root, 'verified_tools', return_value={'bb10mt': self.folder / 'bb10mt'}), \
                patch.object(macos_root, 'native_environment', return_value={}), \
                patch.object(u.subprocess, 'run', side_effect=split), \
                patch.object(r, 'local_usb_state') as probe, patch.object(flash, 'launch_stage') as run:
            u.prepare_upgrade('SQW100-4', lambda _: None, offline=True)
        probe.assert_not_called()
        run.assert_not_called()
        self.assertEqual([x[0] for x in u.verify_kit(self.folder)[1]], ['stock_os', 'stock_radio'])

    def test_loader_success_waits_for_boot_readback_and_never_starts_root(self):
        def result(folder, phase, token):
            return {'stage': phase, 'completed': True}
        with patch.object(flash, 'launch_stage', side_effect=result) as run, patch.object(r, 'flash_root') as root_flash:
            self.run_upgrade()
        self.assertEqual([call.args[1] for call in run.call_args_list], ['stock_os', 'stock_radio'])
        root_flash.assert_not_called()
        self.assertEqual(u.read_state(self.folder)['stage'], 'awaiting_reboot')
        with self.assertRaisesRegex(r.SetupError, 'firmware_boot_not_verified'):
            u.verify_boot(self.folder)
        self.usb['device']['PlatformVersion'] = policy.TARGET_OS
        self.assertEqual(u.verify_boot(self.folder)['stage'], 'os_verified')

    def test_boot_verification_rechecks_receipt_and_platform(self):
        self.state.update(stage='awaiting_reboot', platform='win32')
        self.save()
        with patch.object(r, 'local_usb_state') as probe:
            with self.assertRaisesRegex(r.SetupError, 'root_platform_mismatch'):
                u.verify_boot(self.folder)
            probe.assert_not_called()

    def test_modified_signed_os_and_receipt_cannot_bypass_pinned_stock_hash(self):
        path = self.folder / self.state['images'][0]['file']
        path.write_bytes(b'modified OS ' * 200)
        self.state['images'][0].update(bytes=path.stat().st_size, sha256=u.sha(path))
        self.save()
        with patch.object(flash, 'launch_stage') as run:
            with self.assertRaisesRegex(r.SetupError, 'image_not_verified'):
                self.run_upgrade()
            run.assert_not_called()

    def test_radio_failure_keeps_lock_after_os_success(self):
        with patch.object(flash, 'launch_stage', side_effect=[{'stage': 'stock_os', 'completed': True},
                                                            r.SetupError('flash_state_unknown')]):
            with self.assertRaises(r.SetupError):
                self.run_upgrade()
        self.assertEqual(u.read_state(self.folder)['stage'], 'uncertain')
        self.assertTrue(self.lock.exists())

    def test_unexpected_mac_completion_stops_stock_upgrade_before_radio(self):
        import macos_root_flash as native
        calls = []
        def terminal(command, **kwargs):
            calls.append(command)
            evidence = native.NativeFlashEvidence('phone.0.signed')
            for line in ('Flashing: phone.0.signed', '100%', 'Send signature',
                         'Complete returned unexpected response 0x1234',
                         'Done', 'Flash completed successfully!'):
                evidence.line(line)
            (self.folder / 'upgrade-stock_os.json').write_text(json.dumps(evidence.result('stock_os', 0)))
            return SimpleNamespace(returncode=0)
        with patch.object(flash.subprocess, 'run', side_effect=terminal):
            with self.assertRaisesRegex(r.SetupError, 'flash_state_unknown'):
                self.run_upgrade()
        self.assertEqual(len(calls), 1)
        self.assertEqual(u.read_state(self.folder)['stage'], 'uncertain')
        self.assertTrue(self.lock.exists())
        self.assertFalse((self.folder / 'upgrade-stock_radio.command').exists())

    def test_missing_usb_source_address_blocks_before_console(self):
        self.usb['usb_address_ready'] = False
        with patch.object(flash, 'launch_stage') as run:
            with self.assertRaisesRegex(r.SetupError, 'usb_source_address_required'):
                self.run_upgrade()
            run.assert_not_called()


class StageLaunchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def test_windows_timeout_keeps_child_alive_and_never_accepts_missing_result(self):
        with patch.object(flash.sys, 'platform', 'win32'), patch.object(flash.subprocess, 'Popen') as popen:
            child = popen.return_value
            child.wait.side_effect = flash.subprocess.TimeoutExpired('fixture', 1)
            with self.assertRaisesRegex(r.SetupError, 'flash_state_unknown'):
                flash.launch_stage(self.folder, 'stock', 'token', timeout=1)
            child.kill.assert_not_called()
            child.terminate.assert_not_called()

    def test_mac_console_pid_publish_is_atomic_and_reopening_never_relaunches(self):
        def launch(command, **kwargs):
            self.assertEqual(command[:3], ['/usr/bin/open', '-a', 'Terminal'])
            script = self.folder / 'upgrade-stock_os.command'
            text = script.read_text()
            self.assertIn('/bin/ln ', text)
            self.assertIn(' &&\nexec ', text)
            (self.folder / 'upgrade-stock_os.json').write_text(json.dumps({'stage': 'stock_os', 'completed': True}))
            return SimpleNamespace(returncode=0)
        with patch.object(flash.sys, 'platform', 'darwin'), patch.object(flash.subprocess, 'run', side_effect=launch) as run:
            flash.launch_stage(self.folder, 'stock_os', 'token')
            with self.assertRaisesRegex(r.SetupError, 'flash_state_unknown'):
                flash.launch_stage(self.folder, 'stock_os', 'token')
            self.assertEqual(run.call_count, 1)

    def test_child_rejects_wrong_token_and_replayed_stage_before_starting_loader(self):
        lock = self.folder / 'shared.lock'
        lock.write_text(json.dumps({'operation': 'stock-upgrade', 'kit': str(self.folder), 'token': 'valid'}))
        with patch.object(flash, 'root_lock_path', return_value=lock), \
                patch.object(u, 'verify_kit', return_value=({'confirmation_token': 'valid'}, [('stock', self.folder / 'phone.exe')])), \
                patch.object(flash.subprocess, 'Popen') as run:
            with self.assertRaisesRegex(r.SetupError, 'flash_confirmation_required'):
                flash.run_stage(self.folder, 'stock', 'wrong')
            (self.folder / 'upgrade-stock.claimed').write_text('valid')
            with self.assertRaises(FileExistsError):
                flash.run_stage(self.folder, 'stock', 'valid')
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
