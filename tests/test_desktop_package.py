"""Frozen-resource isolation and SSH provenance; no network or phone access."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import desktop_paths as paths
import workflow as w
import build_windows
import profile_editor


class DesktopPackageTests(unittest.TestCase):
    def test_desktop_revision_is_distinct_from_phone_payload_version(self):
        project = {'version': '0.3.2', 'desktop_revision': 2}
        self.assertEqual(paths.desktop_release_version(project), '0.3.2-r2')
        self.assertEqual(project['version'], '0.3.2')
        self.assertEqual(paths.desktop_release_version({'version': '0.3.2'}), '0.3.2')
        for revision in (True, '2', 0, -1):
            with self.assertRaises(ValueError):
                paths.desktop_release_version({'version': '0.3.2', 'desktop_revision': revision})

    def test_source_paths_remain_in_checkout(self):
        with patch.object(paths.sys, 'frozen', False, create=True):
            self.assertEqual(paths.private_root(), paths.resource_root() / 'private')

    def test_windows_frozen_data_survives_bundle_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(paths.sys, 'frozen', True, create=True), \
                    patch.object(paths.sys, '_MEIPASS', str(root / 'extract'), create=True), \
                    patch.object(paths.sys, 'platform', 'win32'), \
                    patch.dict(paths.os.environ, {'LOCALAPPDATA': str(root / 'local')}):
                self.assertEqual(paths.resource_root(), root / 'extract')
                self.assertEqual(paths.private_root(), root / 'local/bb10-volte/private')
                self.assertFalse(paths.private_root().is_relative_to(paths.resource_root()))

    def test_mac_user_data_uses_application_support(self):
        with patch.object(paths.sys, 'frozen', True, create=True), patch.object(paths.sys, 'platform', 'darwin'):
            self.assertEqual(paths.private_root(), Path.home() / 'Library/Application Support/bb10-volte/private')

    def vendor(self, root):
        vendor = root / 'vendor/openssh'
        vendor.mkdir(parents=True)
        files = {}
        for name in ('ssh.exe', 'scp.exe', 'libcrypto.dll', 'LICENSE.txt', 'NOTICE.txt'):
            data = ('test fixture ' + name).encode()
            (vendor / name).write_bytes(data)
            files[name] = hashlib.sha256(data).hexdigest()
        (root / 'materials').mkdir()
        (root / 'materials/windows-runtime.json').write_text(json.dumps({'openssh': {'files': files}}))
        return vendor

    def test_frozen_ssh_never_falls_back_to_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            vendor = self.vendor(root)
            with patch.object(w, 'ROOT', root), patch.object(w, 'frozen', return_value=True), \
                    patch.object(w.sys, 'platform', 'win32'), patch.object(w.shutil, 'which', side_effect=AssertionError('PATH lookup')):
                client = w.Client()
                self.assertEqual(client.ssh, str(vendor / 'ssh.exe'))
                self.assertEqual(client.scp, str(vendor / 'scp.exe'))

    def test_tampered_or_missing_bundled_ssh_is_rejected(self):
        for missing in (False, True):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                vendor = self.vendor(root)
                if missing:
                    (vendor / 'libcrypto.dll').unlink()
                else:
                    (vendor / 'libcrypto.dll').write_bytes(b'tampered')
                with patch.object(w, 'ROOT', root), patch.object(w, 'frozen', return_value=True), \
                        patch.object(w.sys, 'platform', 'win32'):
                    with self.assertRaisesRegex(w.WorkflowError, 'bundled_ssh_mismatch'):
                        w.Client()

    def test_empty_ssh_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.vendor(root)
            (root / 'materials/windows-runtime.json').write_text('{"openssh":{"files":{}}}')
            with patch.object(w, 'ROOT', root), patch.object(w, 'frozen', return_value=True), \
                    patch.object(w.sys, 'platform', 'win32'):
                with self.assertRaisesRegex(w.WorkflowError, 'bundled_ssh_mismatch'):
                    w.Client()

    def test_packaged_app_cannot_regenerate_payload_hashes(self):
        with patch.object(w, 'frozen', return_value=True):
            with self.assertRaisesRegex(w.WorkflowError, 'package_readonly'):
                w.write_manifest()

    def test_scp_uses_the_resolved_ssh_even_with_spaces(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(w, 'frozen', return_value=False), \
                patch.object(w.shutil, 'which', side_effect=lambda name: '/test path/' + name), \
                patch.object(w, 'private_root', return_value=Path(folder)):
            client = w.Client()
            with patch.object(client, 'remote', return_value=''), patch.object(client, 'process', return_value='') as run, \
                    patch.object(client, 'execute', return_value={'stage_removed': True}):
                with client.stage():
                    pass
                self.assertEqual(run.call_count, 6)
                for call in run.call_args_list:
                    self.assertEqual(call.args[0][:5], ['/test path/scp', '-S', '/test path/ssh', '-O', '-q'])

    def test_bundle_data_does_not_include_root_preparation_or_private_materials(self):
        names = build_windows.runtime_data()
        self.assertIn('device/install.py', names)
        self.assertIn('materials/payload-manifest.json', names)
        self.assertFalse(any(name.startswith(('private/', 'downloads/')) for name in names))
        self.assertEqual({name for name in names if name.startswith('tools/')}, {'tools/stage_cleanup.py'})

    def test_legacy_device_transport_keeps_strict_host_verification(self):
        with patch.object(w, 'frozen', return_value=False), patch.object(w.shutil, 'which', side_effect=lambda n: n):
            options = w.Client().options
        self.assertIn('Ciphers=aes128-ctr,aes192-ctr,aes256-ctr', options)
        self.assertIn('HostKeyAlgorithms=+ssh-rsa', options)
        self.assertIn('PubkeyAcceptedAlgorithms=+ssh-rsa', options)
        self.assertIn('StrictHostKeyChecking=yes', options)
        self.assertIn('BatchMode=yes', options)

    def test_generic_default_and_legacy_explicit_ssh_alias(self):
        with patch.object(w, 'frozen', return_value=False), patch.object(w.shutil, 'which', side_effect=lambda n: n):
            self.assertEqual(w.Client().host, 'bb10-root')
            self.assertEqual(w.Client('q10-root').host, 'q10-root')

    def test_displayed_bb10_baseline_preserves_installed_profile_fingerprint(self):
        profile = w.profiles.default()
        visible = profile_editor.display_label(profile['label'])
        self.assertIn('BB10', visible)
        original = profile['label']
        profile['label'] = profile_editor.stored_label(visible, original)
        self.assertEqual(w.profiles.fingerprint(w.profiles.request(profile, False)),
                         w.profiles.fingerprint(w.profiles.request(w.profiles.default(), False)))
        self.assertEqual(profile_editor.stored_label('Custom BB10 carrier', original), 'Custom BB10 carrier')


if __name__ == '__main__':
    unittest.main()
