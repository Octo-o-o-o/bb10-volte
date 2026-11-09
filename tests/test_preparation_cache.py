"""Disk growth and retry safety using tiny non-executable firmware fixtures."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import preparation_cache as cache
import root_setup as root
import firmware_upgrade as upgrade
import macos_root


def digest(data):
    return hashlib.sha256(data).hexdigest()


class PreparationCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.private = Path(self.temp.name) / 'private'
        self.private.mkdir()
        self.stock = dict(root.stock_firmware('SQN100-3'), extracted_sha256=digest(b'stock fixture'))
        self.messages = []
        for target, name, value in (
                (root, 'private_root', lambda: self.private),
                (upgrade, 'private_root', lambda: self.private),
                (macos_root, 'private_root', lambda: self.private),
                (root, 'root_lock_path', lambda: self.private / 'root-flash.lock'),
                (root, 'stock_firmware', lambda _: self.stock),
                (cache, 'recipe_id', lambda variant, platform: variant + '/' + platform + '/fixture')):
            mocked = patch.object(target, name, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        mocked = patch.object(root.sys, 'platform', 'win32')
        mocked.start()
        self.addCleanup(mocked.stop)
        mocked = patch.object(root.shutil, 'disk_usage', return_value=SimpleNamespace(free=40 * 1024**3))
        self.disk = mocked.start()
        self.addCleanup(mocked.stop)

    def builder(self, folder, variant, progress, proxy, cache_dir, offline, platform='win32'):
        folder.mkdir()
        cache.mark_started(folder, variant, platform)
        for name in cache.KEY_FILES:
            (folder / name).write_bytes(('non-secret fixture ' + name).encode())
        (folder / 'stock').mkdir()
        (folder / 'stock' / self.stock['extracted_file']).write_bytes(b'stock fixture')
        (folder / 'autoroot').mkdir()
        (folder / 'autoroot/tool').write_bytes(b'tool fixture')
        (folder / 'images').mkdir()
        stem = Path(self.stock['extracted_file']).stem
        outputs = []
        suffixes = ('_os.exe', '_radio.exe') if platform == 'win32' else ('_os.unsigned', '_radio.signed')
        for suffix in suffixes:
            path = folder / 'images' / (stem + suffix)
            path.write_bytes(b'image fixture' + suffix.encode())
            outputs.append({'file': path.name, 'bytes': path.stat().st_size, 'sha256': cache.sha(path)})
        for suffix in ('.0.4.ufs', '.0.signed', '.0.unsigned', '.1.signed'):
            (folder / 'images' / (stem + suffix)).write_bytes(b'disposable fixture')
        (folder / 'images/owner-notes.txt').write_text('keep unrelated file')
        (folder / 'root-build.log').write_text('build evidence')
        (folder / 'build-verification.json').write_text(json.dumps({
            'variant': variant, 'platform': platform, 'firmware_id': self.stock['id'],
            'stock_sha256': self.stock['extracted_sha256'], 'offline_build_verified': True,
            'images': outputs}))
        (folder / 'setup-state.json').write_text(json.dumps({'variant': variant, 'platform': platform, 'stage': 'prepared'}))

    def prepare(self):
        return Path(root.prepare_root_kit('SQN100-3', self.messages.append, offline=True))

    def test_repeated_prepare_reuses_same_images_keys_and_stock_even_with_no_free_space(self):
        with patch.object(root, '_prepare_root_kit_windows', side_effect=self.builder) as build:
            first = self.prepare()
            keys = cache.key_hashes(first)
            self.disk.return_value = SimpleNamespace(free=0)
            for _ in range(3):
                self.assertEqual(self.prepare(), first)
            build.assert_called_once()
        self.assertEqual(cache.key_hashes(first), keys)
        self.assertEqual(len(list(self.private.glob('root-kit-*'))), 1)
        self.assertEqual(len(list((first / 'images').iterdir())), 3)
        self.assertTrue((first / 'images/owner-notes.txt').is_file())
        root.prepared_images(first)

    def test_corrupt_image_key_stock_changed_recipe_and_wrong_model_are_never_reused(self):
        with patch.object(root, '_prepare_root_kit_windows', side_effect=self.builder):
            folder = self.prepare()
        stem = Path(self.stock['extracted_file']).stem
        for path in (folder / 'images' / (stem + '_os.exe'), folder / 'q10_root_rsa',
                     folder / 'stock' / self.stock['extracted_file']):
            original = path.read_bytes()
            path.write_bytes(b'damaged')
            self.assertIsNone(cache.reusable_root_kit(self.private, 'SQN100-3', 'win32', self.messages.append))
            self.assertTrue(path.exists())
            path.write_bytes(original)
        with patch.object(cache, 'recipe_id', return_value='different recipe'):
            self.assertIsNone(cache.reusable_root_kit(self.private, 'SQN100-3', 'win32', self.messages.append))
        self.assertIsNone(cache.reusable_root_kit(self.private, 'SQN100-1', 'win32', self.messages.append))
        self.assertIsNone(cache.reusable_root_kit(self.private, 'SQN100-3', 'darwin', self.messages.append))

    def test_prior_flash_or_upgrade_is_never_reset_or_cleaned(self):
        with patch.object(root, '_prepare_root_kit_windows', side_effect=self.builder):
            folder = self.prepare()
        for journal, state in (
                ('setup-state.json', {'variant': 'SQN100-3', 'stage': 'flashed_waiting_for_root'}),
                ('firmware-upgrade.json', {'stage': 'awaiting_reboot', 'phone_contacted': True})):
            path = folder / journal
            original = path.read_bytes() if path.exists() else None
            path.write_text(json.dumps(state))
            self.assertIsNone(cache.reusable_root_kit(self.private, 'SQN100-3', 'win32', self.messages.append))
            cache.clean_abandoned_roots(self.private, self.messages.append)
            self.assertTrue((folder / 'stock').is_dir())
            self.assertEqual(json.loads(path.read_text()), state)
            if original:
                path.write_bytes(original)
            else:
                path.unlink()
        (folder / 'flash-os.json').write_text('{}')
        self.assertIsNone(cache.reusable_root_kit(self.private, 'SQN100-3', 'win32', self.messages.append))

    def failed_builder(self, folder, variant, progress, *args):
        folder.mkdir()
        cache.mark_started(folder, variant, 'win32')
        for name in ('stock', 'images', 'autoroot'):
            (folder / name).mkdir()
            (folder / name / 'large-fixture').write_bytes(b'x' * 65536)
        (folder / 'q10_root_rsa').write_bytes(b'keep key fixture')
        (folder / 'root-build.log').write_text('failure evidence')
        raise RuntimeError('simulated offline failure')

    def test_repeated_failures_do_not_accumulate_large_output_and_keep_keys_logs(self):
        with patch.object(root, '_prepare_root_kit_windows', side_effect=self.failed_builder):
            for _ in range(4):
                with self.assertRaisesRegex(RuntimeError, 'simulated offline failure'):
                    self.prepare()
        for folder in self.private.glob('root-kit-*'):
            self.assertFalse((folder / 'stock').exists())
            self.assertFalse((folder / 'images').exists())
            self.assertFalse((folder / 'autoroot').exists())
            self.assertEqual((folder / 'root-build.log').read_text(), 'failure evidence')
            self.assertEqual((folder / 'q10_root_rsa').read_bytes(), b'keep key fixture')
        self.assertLess(sum(p.stat().st_size for p in self.private.rglob('*') if p.is_file()), 8192)

    def test_crashed_managed_build_is_cleaned_but_unmarked_and_outside_folders_are_not(self):
        abandoned = self.private / 'root-kit-abandoned'
        with self.assertRaises(RuntimeError):
            self.failed_builder(abandoned, 'SQN100-3', None)
        legacy = self.private / 'root-kit-legacy'
        (legacy / 'stock').mkdir(parents=True)
        (legacy / 'stock/keep').write_bytes(b'old evidence')
        with cache.preparation_lock(self.private):
            cache.clean_abandoned_roots(self.private, self.messages.append)
        self.assertFalse((abandoned / 'images').exists())
        self.assertEqual((legacy / 'stock/keep').read_bytes(), b'old evidence')
        outside = Path(self.temp.name) / 'outside'
        (outside / 'images').mkdir(parents=True)
        with self.assertRaises(ValueError):
            cache.remove_owned_tree(self.private, outside, 'images')
        self.assertTrue((outside / 'images').exists())

    def test_concurrent_prepare_and_uncertain_flash_are_blocked_before_build(self):
        with patch.object(root, '_prepare_root_kit_windows') as build:
            with cache.preparation_lock(self.private):
                with self.assertRaisesRegex(root.SetupError, 'preparation_busy'):
                    self.prepare()
            (self.private / 'root-flash.lock').write_text('preserve uncertain flash')
            with self.assertRaisesRegex(root.SetupError, 'flash_state_unknown'):
                self.prepare()
            build.assert_not_called()

    def test_upgrade_reuses_root_and_existing_upgrade_without_additional_disk_space(self):
        with patch.object(root, '_prepare_root_kit_windows', side_effect=self.builder) as build:
            folder = self.prepare()
            self.disk.return_value = SimpleNamespace(free=0)
            for _ in range(2):
                self.assertEqual(upgrade.prepare_upgrade('SQN100-3', self.messages.append, offline=True), str(folder))
            build.assert_called_once()
        self.assertEqual(upgrade.read_state(folder)['stage'], 'prepared')
        upgrade.verify_kit(folder)

    def test_mac_prepare_reuses_native_images_and_cleans_intermediates(self):
        def builder(*args):
            self.builder(*args, platform='darwin')
        with patch.object(root.sys, 'platform', 'darwin'), \
                patch.object(macos_root.platform, 'system', return_value='Darwin'), \
                patch.object(macos_root, 'architecture', return_value='arm64'), \
                patch.object(macos_root, '_prepare_root_kit_macos', side_effect=builder) as build:
            first = self.prepare()
            self.disk.return_value = SimpleNamespace(free=0)
            self.assertEqual(self.prepare(), first)
            build.assert_called_once()
        self.assertEqual(len(list((first / 'images').iterdir())), 3)

    def test_verified_driver_kit_is_reused_without_download_or_extraction(self):
        folder = self.private / 'windows-usb-fixture'
        (folder / 'package').mkdir(parents=True)
        (folder / 'rim-usb').mkdir()
        for name in ('package/BlackBerry-USBDrivers-5.0.0.2.exe', 'USBInstallerMSIx64.msi', 'rim-usb/rimusbnt.cat'):
            (folder / name).write_bytes(b'fixture')
        (folder / 'verification.json').write_text('{"prepared":true}')
        fixtures = Path(self.temp.name) / 'resources'
        (fixtures / 'materials').mkdir(parents=True)
        (fixtures / 'materials/usb-drivers.json').write_text(json.dumps({
            'bundle_sha256': digest(b'fixture'), 'msi_sha256': digest(b'fixture'),
            'driver_files': {'rimusbnt.cat': digest(b'fixture')}}))
        with patch.object(root, 'ROOT', fixtures), patch.object(root, 'ensure_tools') as tools:
            self.assertEqual(root.prepare_driver_kit(self.messages.append), str(folder))
            tools.assert_not_called()

    def test_complete_legacy_recipe_is_adopted_but_changed_patch_is_preserved(self):
        folder = self.private / 'root-kit-legacy'
        self.builder(folder, 'SQN100-3', None, None, None, True)
        (folder / cache.MARKER).unlink()
        source = json.loads((root.ROOT / 'materials/sources.json').read_text())
        bundle = next(item for item in source['verified_inputs'] if item['id'] == 'autoroot-v4')
        (folder / 'preparation.json').write_text(json.dumps({
            'variant': 'SQN100-3', 'platform': 'win32', 'firmware_id': self.stock['id'],
            'stock_sha256': self.stock['extracted_sha256'], 'root_bundle_sha256': bundle['sha256'],
            'offline_preparation_complete': True, 'shared_default_ssh_authorization_replaced': True}))
        (folder / 'autoroot/patch.txt').write_text('keep fixture\nremoveapp stock\n#sys.example\n')
        patch_file = folder / 'autoroot/patch-owner.txt'
        patch_file.write_text('changed patch\n')
        ssh = folder / 'autoroot/patchdata/var/etc/ssh'
        ssh.mkdir(parents=True)
        (ssh / 'sshd_config').write_text('PasswordAuthentication=no\n')
        public = (folder / 'q10_root_rsa.pub').read_text().strip()
        (ssh / 'authorized_keys2').write_text('from="169.254.0.2",no-agent-forwarding,no-port-forwarding,no-X11-forwarding ' + public + '\n')
        (ssh / 'ssh_host_rsa_key').write_bytes((folder / 'q10_host_rsa').read_bytes())
        with patch.object(root, '_prepare_root_kit_windows', side_effect=AssertionError('must reuse legacy kit')):
            self.assertIsNone(cache.reusable_root_kit(self.private, 'SQN100-3', 'win32', self.messages.append))
            self.assertFalse((folder / cache.MARKER).exists())
            patch_file.write_text('keep fixture\n')
            self.disk.return_value = SimpleNamespace(free=0)
            self.assertEqual(self.prepare(), folder)
        self.assertTrue(cache.read_json(folder / cache.MARKER)['adopted_legacy'])

    def test_linked_output_and_key_are_not_followed_or_removed(self):
        folder = self.private / 'root-kit-failed'
        with self.assertRaises(RuntimeError):
            self.failed_builder(folder, 'SQN100-3', None)
        real_linked = cache.linked
        with patch.object(cache, 'linked', side_effect=lambda path: path.name == 'large-fixture' or real_linked(path)):
            cache.clean_abandoned_roots(self.private, self.messages.append)
        self.assertTrue((folder / 'images/large-fixture').exists())
        self.assertTrue((folder / 'q10_root_rsa').exists())

    def test_orphan_worker_blocks_cleanup_and_a_second_copy_until_it_exits(self):
        folder = self.private / 'root-kit-orphan'
        with self.assertRaises(RuntimeError):
            self.failed_builder(folder, 'SQN100-3', None)
        record = cache.read_json(folder / cache.MARKER)
        record.update(owner_pid=None, worker_pid=12345)
        cache.write_record(folder, record)
        with patch.object(cache, 'process_alive', side_effect=lambda pid: pid == 12345):
            with self.assertRaisesRegex(root.SetupError, 'preparation_busy'):
                cache.clean_abandoned_roots(self.private, self.messages.append)
        self.assertTrue((folder / 'images/large-fixture').exists())
        with patch.object(cache, 'process_alive', return_value=False):
            cache.clean_abandoned_roots(self.private, self.messages.append)
        self.assertFalse((folder / 'images').exists())

    def test_offline_child_exit_and_timeout_release_worker_without_touching_phone(self):
        folder = self.private / 'root-kit-child'
        folder.mkdir()
        cache.mark_started(folder, 'SQN100-3', 'win32')
        self.assertTrue(cache.process_alive(os.getpid()))
        result = cache.run_preparation([sys.executable, '-c', 'print("fixture")'], folder,
                                       capture_output=True, timeout=5, check=True)
        self.assertEqual(result.stdout.strip(), b'fixture')
        self.assertIsNone(cache.read_json(folder / cache.MARKER)['worker_pid'])
        with self.assertRaises(subprocess.TimeoutExpired):
            cache.run_preparation([sys.executable, '-c', 'import time; time.sleep(10)'], folder,
                                  capture_output=True, timeout=0.05)
        self.assertIsNone(cache.read_json(folder / cache.MARKER)['worker_pid'])


if __name__ == '__main__':
    unittest.main()
