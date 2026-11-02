"""Whole-BAR trust, app identity and interrupted native provisioning boundaries."""
import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import mobile_app_device as device
import mobile_app_install as host
from workflow import WorkflowError


def fixture(folder, version='0.1.0.12', author='gYAOctoLabBB10VoLTE20261102'):
    identity = {'Package-Name': 'com.octolab.bb10volte', 'Package-Id': 'testDev_b_bb10volte7b237e48',
                'Package-Author-Id': author, 'Package-Architecture': 'armle-v7',
                'Package-Version': version, 'Application-Id': 'testDev_b_bb10volte7b237e48',
                'Application-Version': version}
    manifest = ''.join(k + ': ' + v + '\n' for k, v in identity.items()).encode()
    files = {'META-INF/MANIFEST.MF': manifest, 'native/bb10volte': b'reviewed ELF',
             'native/assets/main.qml': b'reviewed QML', 'native/assets/manifest.sig.json': b'unchanged inner signature'}
    bar = folder / ('app-' + version + '.bar')
    with zipfile.ZipFile(bar, 'w') as archive:
        for name, blob in files.items():
            archive.writestr(name, blob)
    pin = {'schema': 1, 'version': version, 'identity': identity,
           'helper_sha256': hashlib.sha256((host.ROOT / host.HELPER).read_bytes()).hexdigest(),
           'bar_size': bar.stat().st_size, 'bar_sha256': hashlib.sha256(bar.read_bytes()).hexdigest(),
           'platform_manifest_sha256': hashlib.sha256(manifest).hexdigest(),
           'installed_files': {name: {'size': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()} for name, blob in files.items()}}
    return bar, pin, files


class AppArtifactTests(unittest.TestCase):
    def test_pinned_release_matches_the_current_packaged_helper(self):
        pin = host.release()
        self.assertEqual(hashlib.sha256((host.ROOT / host.HELPER).read_bytes()).hexdigest(), pin['helper_sha256'])

    def test_pps_reads_one_snapshot_and_closes_even_when_too_large(self):
        for data, error in ((b'@job\nresult::success\n', None), (b'x' * 131073, 'pps_response_too_large')):
            with patch.object(device.os.path, 'realpath', side_effect=lambda value: value), \
                 patch.object(device.os.path, 'islink', return_value=False), \
                 patch.object(device.os, 'open', return_value=47), \
                 patch.object(device.os, 'read', return_value=data) as read, \
                 patch.object(device.os, 'close') as close:
                if error:
                    with self.assertRaisesRegex(device.InstallError, error):
                        device.read_pps('/pps/owned-job')
                else:
                    self.assertEqual(device.read_pps('/pps/owned-job'), data.decode())
                read.assert_called_once_with(47, 131073)
                close.assert_called_once_with(47)

    def test_pps_wait_queries_are_rejected_before_open(self):
        with patch.object(device.os, 'open') as opened:
            with self.assertRaisesRegex(device.InstallError, 'unsafe_pps_path'):
                device.read_pps('/pps/owned-job?wait')
        opened.assert_not_called()

    def test_changed_executable_is_rejected_even_with_unchanged_inner_signature(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            bar, pin, files = fixture(folder)
            self.assertEqual(host.verify_bar(bar, pin), bar.read_bytes())
            files['native/bb10volte'] = b'modified ELF'
            with zipfile.ZipFile(bar, 'w') as archive:
                for name, blob in files.items():
                    archive.writestr(name, blob)
            with self.assertRaisesRegex(WorkflowError, 'mobile_app_bar_mismatch'):
                host.verify_bar(bar, pin)

    def test_untrusted_input_is_rejected_before_any_phone_transfer(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            bar, pin, unused = fixture(folder)
            bar.write_bytes(b'not the selected release')
            client = Mock()
            with patch.object(host, 'release', return_value=pin):
                manager = host.MobileAppInstaller(client)
                with self.assertRaisesRegex(WorkflowError, 'mobile_app_bar_mismatch'):
                    manager.install(bar, 'a' * 32)
            client.remote.assert_not_called()
            client.process.assert_not_called()

    def test_pin_generation_rejects_a_different_publisher_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            bar, unused, files = fixture(folder, author='untrusted-publisher')
            with self.assertRaisesRegex(ValueError, 'Unexpected native application identity'):
                host.make_release_pin(bar, folder / 'pin.json')
            self.assertFalse((folder / 'pin.json').exists())

    def test_pending_submission_is_not_reissued_by_inspection(self):
        job = {'id': 'a' * 32, 'state': 'submitted', 'bar_sha256': 'b' * 64, 'sud_job': '/pps/owned-job'}
        with patch.object(device, 'pps', return_value={}), patch.object(device, 'save') as save, \
             patch.object(device, 'installed') as inspect:
            self.assertEqual(device.reconcile(copy.deepcopy(job), {'bar_sha256': 'b' * 64}), job)
        save.assert_not_called()
        inspect.assert_not_called()

    def test_sud_success_for_an_old_version_is_not_install_success(self):
        job = {'id': 'a' * 32, 'state': 'submitted', 'bar_sha256': 'b' * 64, 'sud_job': '/pps/owned-job'}
        pin = {'bar_sha256': 'b' * 64, 'version': '0.1.0.12',
               'identity': {'Package-Name': 'com.octolab.bb10volte', 'Package-Id': 'app-id', 'Package-Author-Id': 'author'}}
        result = {'result': 'success', 'actual_name': 'com.octolab.bb10volte', 'actual_id': 'app-id',
                  'actual_author_id': 'author', 'actual_version': '0.1.0.11'}
        with patch.object(device, 'pps', return_value=result), patch.object(device, 'save'), \
             patch.object(device, 'installed') as inspect:
            self.assertEqual(device.reconcile(job, pin)['state'], 'conflict')
        inspect.assert_not_called()

    def test_matching_sud_result_requires_all_actual_installed_files(self):
        pin = {'bar_sha256': 'b' * 64, 'version': '0.1.0.12',
               'identity': {'Package-Name': 'com.octolab.bb10volte', 'Package-Id': 'app-id', 'Package-Author-Id': 'author'}}
        result = {'result': 'success', 'actual_name': 'com.octolab.bb10volte', 'actual_id': 'app-id',
                  'actual_author_id': 'author', 'actual_version': '0.1.0.12'}
        for actual, expected in (({'state': 'installed', 'all_files_verified': True}, 'completed'),
                                 ({'state': 'upgrade_available', 'all_files_verified': False}, 'conflict')):
            job = {'id': 'a' * 32, 'state': 'submitted', 'bar_sha256': 'b' * 64, 'sud_job': '/pps/owned-job'}
            with patch.object(device, 'pps', return_value=result), patch.object(device, 'save'), \
                 patch.object(device, 'installed', return_value=actual):
                self.assertEqual(device.reconcile(job, pin)['state'], expected)

    def test_changed_phone_cannot_start_a_job_using_stale_inspection(self):
        with patch.object(device, 'locked', contextlib.nullcontext), \
             patch.object(device, 'load', return_value={'id': 'b' * 32}), \
             patch.object(device, 'current_job') as current, patch.object(device.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(device.InstallError, 'device_changed'):
                device.provision({}, '/unused', 'c' * 32, 'a' * 32)
        current.assert_not_called()
        start.assert_not_called()

    def test_second_submit_is_blocked_even_if_the_ssh_invocation_was_lost(self):
        pending = {'state': 'submitted'}
        with patch.object(device, 'locked', contextlib.nullcontext), \
             patch.object(device, 'load', return_value={'id': 'a' * 32}), \
             patch.object(device, 'current_job', return_value=pending), \
             patch.object(device, 'reconcile', return_value=pending), \
             patch.object(device, 'installed') as inspect, patch.object(device.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(device.InstallError, 'app_install_unresolved'):
                device.provision({}, '/unused', 'c' * 32, 'a' * 32)
        inspect.assert_not_called()
        start.assert_not_called()

    def test_complete_installed_match_does_not_launch_the_installer_again(self):
        with patch.object(device, 'locked', contextlib.nullcontext), \
             patch.object(device, 'load', return_value={'id': 'a' * 32}), \
             patch.object(device, 'current_job', return_value=None), \
             patch.object(device, 'reconcile', return_value=None), \
             patch.object(device, 'installed', return_value={'state': 'installed', 'can_install': False}), \
             patch.object(device, 'summary', return_value={'state': 'installed'}), \
             patch.object(device.subprocess, 'Popen') as start:
            self.assertEqual(device.provision({}, '/unused', 'c' * 32, 'a' * 32)['state'], 'installed')
        start.assert_not_called()


@unittest.skipIf(os.name == 'nt', 'Real POSIX ownership/path checks run on the Linux builder and macOS')
class InstalledAppFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name).resolve()
        self.bar, self.pin, self.files = fixture(self.folder)
        self.apps = self.folder / 'apps'
        self.apps.mkdir()
        self.app = self.apps / ('com.octolab.bb10volte.' + self.pin['identity']['Package-Id'])
        self.patch = patch.object(device, 'APP_ROOT', str(self.apps)); self.patch.start()

    def tearDown(self):
        self.patch.stop(); self.temp.cleanup()

    def write_files(self, files=None):
        for name, blob in (files or self.files).items():
            path = self.app / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)

    def test_absent_and_unchanged_installed_app(self):
        self.assertTrue(device.installed(self.pin)['can_install'])
        self.write_files()
        self.assertEqual(device.installed(self.pin)['state'], 'installed')
        self.assertFalse(device.installed(self.pin)['can_install'])

    def test_modified_native_executable_blocks_same_version_reinstall(self):
        self.write_files()
        (self.app / 'native/bb10volte').write_bytes(b'unreviewed')
        with self.assertRaisesRegex(device.InstallError, 'same_version_conflict'):
            device.installed(self.pin)

    def test_newer_version_is_compared_numerically_and_never_downgraded(self):
        unused, pin, files = fixture(self.folder, version='0.1.0.20')
        self.write_files(files)
        value = device.installed(self.pin)
        self.assertEqual(value['state'], 'newer_installed')
        self.assertFalse(value['can_install'])

    def test_same_package_name_with_wrong_author_is_not_adopted(self):
        unused, pin, files = fixture(self.folder, version='0.1.0.9', author='different')
        self.write_files(files)
        with self.assertRaisesRegex(device.InstallError, 'app_identity_conflict'):
            device.installed(self.pin)

    def test_symlinked_installed_native_file_is_rejected(self):
        self.write_files()
        path = self.app / 'native/bb10volte'
        original = path.read_bytes(); path.unlink()
        elsewhere = self.folder / 'elsewhere'; elsewhere.write_bytes(original)
        path.symlink_to(elsewhere)
        with self.assertRaisesRegex(device.InstallError, 'unsafe_file'):
            device.installed(self.pin)

    def test_existing_job_lock_cannot_be_redirected(self):
        base = self.folder / 'manager'; base.mkdir(mode=0o700)
        elsewhere = self.folder / 'elsewhere'; elsewhere.write_text('untouched')
        (base / 'lock').symlink_to(elsewhere)
        with patch.object(device, 'BASE', str(base)):
            with self.assertRaisesRegex(device.InstallError, 'unsafe_file'):
                with device.locked():
                    self.fail('linked lock acquired')
        self.assertEqual(elsewhere.read_text(), 'untouched')

    def test_second_process_cannot_acquire_the_same_device_install_lock(self):
        base = self.folder / 'manager'; base.mkdir(mode=0o700)
        code = ('import sys; sys.path.insert(0, sys.argv[1]); import mobile_app_device as d; '
                'd.BASE=sys.argv[2]\ntry:\n with d.locked(): pass\n'
                'except d.InstallError as e:\n sys.exit(22 if str(e)=="app_install_busy" else 23)\n')
        with patch.object(device, 'BASE', str(base)), device.locked():
            result = subprocess.run([sys.executable, '-c', code, str(ROOT / 'tools'), str(base)],
                                    capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 22, result.stderr.decode())

    def test_installer_executes_private_verified_bytes_even_if_original_changes(self):
        base = self.folder / 'manager'; base.mkdir(mode=0o700)
        (base / 'jobs').mkdir(mode=0o700)
        device_file = base / 'device.json'; device_file.write_text(json.dumps({'id': 'a' * 32})); device_file.chmod(0o600)
        stage = self.folder / 'stage'; stage.mkdir(mode=0o700)
        staged = stage / 'application.bar'; staged.write_bytes(self.bar.read_bytes()); staged.chmod(0o600)
        original = self.folder / 'shared-installer'; original.write_bytes(b'verified native installer')
        self.pin['installer_sha256'] = hashlib.sha256(original.read_bytes()).hexdigest()
        called = []
        def start(argv, **kwargs):
            original.write_bytes(b'changed shared path')
            self.assertNotEqual(argv[0], str(original))
            self.assertEqual(Path(argv[0]).read_bytes(), b'verified native installer')
            self.assertEqual(Path(argv[0]).stat().st_mode & 0o777, 0o700)
            self.assertNotIn('LD_PRELOAD', kwargs['env'])
            with zipfile.ZipFile(argv[1]) as archive:
                self.assertEqual(set(archive.namelist()), {'MANIFEST', 'pkg.bar'})
                self.assertEqual(archive.read('pkg.bar'), self.bar.read_bytes())
            self.write_files()
            called.append(argv)
            return Mock(pid=123, returncode=0, poll=Mock(return_value=0))
        identity = self.pin['identity']
        result = {'result': 'success', 'actual_name': identity['Package-Name'], 'actual_id': identity['Package-Id'],
                  'actual_author_id': identity['Package-Author-Id'], 'actual_version': self.pin['version']}
        with patch.object(device, 'BASE', str(base)), patch.object(device, 'INSTALLER', str(original)), \
             patch.object(device, 'PPS', str(self.folder / 'pps')), \
             patch.object(device.subprocess, 'call', return_value=0) as trust, \
             patch.object(device.subprocess, 'Popen', side_effect=start), \
             patch.object(device, 'pps', return_value=result), \
             patch.object(device, 'read_pps', return_value='@device\nmodelnumber::SQC100-2\n'):
            observed = device.provision(self.pin, str(stage), 'c' * 32, 'a' * 32)
        self.assertEqual(observed['state'], 'installed')
        self.assertEqual(observed['job']['state'], 'completed')
        self.assertEqual(len(called), 1)
        self.assertEqual(trust.call_args[0][0], ['/proc/boot/pathtrust', '!' + called[0][0]])

    def test_hung_installer_releases_lock_and_reconciles_without_resubmission(self):
        real_popen = subprocess.Popen
        base = self.folder / 'manager'; base.mkdir(mode=0o700)
        (base / 'jobs').mkdir(mode=0o700)
        stage = self.folder / 'stage'; stage.mkdir(mode=0o700)
        staged = stage / 'application.bar'; staged.write_bytes(self.bar.read_bytes()); staged.chmod(0o600)
        original = self.folder / 'installer'; original.write_bytes(b'verified native installer')
        self.pin['installer_sha256'] = hashlib.sha256(original.read_bytes()).hexdigest()
        child = Mock(pid=123, poll=Mock(return_value=None))
        identity = self.pin['identity']
        success = {'result': 'success', 'actual_name': identity['Package-Name'], 'actual_id': identity['Package-Id'],
                   'actual_author_id': identity['Package-Author-Id'], 'actual_version': self.pin['version']}
        with patch.object(device, 'BASE', str(base)), patch.object(device, 'INSTALLER', str(original)), \
             patch.object(device, 'PPS', str(self.folder / 'pps')), \
             patch.object(device.subprocess, 'call', return_value=0), \
             patch.object(device.subprocess, 'Popen', return_value=child) as start, \
             patch.object(device, 'pps', return_value={}) as read, \
             patch.object(device.time, 'sleep') as sleep, \
             patch.object(device, 'read_pps', return_value='@device\nmodelnumber::SQC100-2\n'):
            device.save(str(base / 'device.json'), {'id': 'a' * 32})
            observed = device.provision(self.pin, str(stage), 'c' * 32, 'a' * 32)
            self.assertEqual(observed['state'], 'pending')
            self.assertLessEqual(sleep.call_count, 30)
            child.wait.assert_not_called()
            child.kill.assert_not_called()
            child.terminate.assert_not_called()
            with self.assertRaisesRegex(device.InstallError, 'app_install_unresolved'):
                device.provision(self.pin, str(stage), 'd' * 32, 'a' * 32)
            # The lock is available to a different process while the child
            # remains alive; the same SUD result can now complete the job.
            code = ('import sys; sys.path.insert(0, sys.argv[1]); import mobile_app_device as d; '
                    'd.BASE=sys.argv[2]\nwith d.locked(): pass\n')
            with patch.object(device.subprocess, 'Popen', real_popen):
                acquired = subprocess.run([sys.executable, '-c', code, str(ROOT / 'tools'), str(base)],
                                          capture_output=True, timeout=10)
            self.assertEqual(acquired.returncode, 0, acquired.stderr.decode())
            self.write_files()
            read.return_value = success
            with device.locked():
                job = device.reconcile(device.current_job(), self.pin)
            self.assertEqual(job['state'], 'completed')
            self.assertEqual(job['id'], 'c' * 32)
            self.assertEqual(start.call_count, 1)

    def test_missing_active_pointer_retains_unresolved_job_and_blocks_resubmit(self):
        base = self.folder / 'manager'; base.mkdir(mode=0o700)
        (base / 'jobs').mkdir(mode=0o700)
        with patch.object(device, 'BASE', str(base)), patch.object(device, 'pps', return_value={}), \
             patch.object(device.subprocess, 'Popen') as start:
            device.save(str(base / 'device.json'), {'id': 'a' * 32})
            for identifier in ('c' * 32, 'd' * 32):
                directory = Path(device.job_path(identifier)); directory.mkdir(mode=0o700)
                job = {'id': identifier, 'owner': 'bb10-volte-app-installer-v1', 'device_id': 'a' * 32,
                       'bar_sha256': self.pin['bar_sha256'], 'sud_job': device.PPS + '/job.bb10-volte-app-' + identifier,
                       'state': 'submitted'}
                device.save(str(directory / 'record.json'), job)
                if identifier == 'c' * 32:
                    self.assertEqual(device.current_job()['id'], identifier)
                    with self.assertRaisesRegex(device.InstallError, 'app_install_unresolved'):
                        device.provision(self.pin, '/unused', 'e' * 32, 'a' * 32)
                else:
                    with self.assertRaisesRegex(device.InstallError, 'orphaned_install_records'):
                        device.current_job()
            start.assert_not_called()

    def test_final_task_pointer_is_synced_after_rename(self):
        path = self.folder / 'active.json'
        committed = []
        sync = device.os.fsync
        def snapshot(descriptor):
            sync(descriptor)
            committed.append(json.loads(path.read_text()) if path.exists() else None)
        with patch.object(device.os, 'fsync', side_effect=snapshot), \
             patch.object(device.os, 'open', wraps=device.os.open) as opened:
            device.save(str(path), {'id': 'a' * 32})
        self.assertEqual(committed, [None, {'id': 'a' * 32}])
        # Linux accepts read-only fsync descriptors; QNX rejects those.
        self.assertEqual(opened.call_args.args, (str(path), os.O_WRONLY))


if __name__ == '__main__':
    unittest.main()
