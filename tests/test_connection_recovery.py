"""Owner pairing, identity pinning, and desktop recovery without phone access."""
import base64
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import connection_recovery as r
import phone_pairing as p
import recovery_gui as ui


def rsa_public(marker):
    fields = [b'ssh-rsa', b'\x01\x00\x01', b'\x00' + bytes([marker]) * 256]
    blob = b''.join(struct.pack('>I', len(field)) + field for field in fields)
    return 'ssh-rsa ' + base64.b64encode(blob).decode('ascii')


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.private = self.root / 'private'
        self.key, self.host = rsa_public(1), rsa_public(2)
        self.private_patch = patch.object(r, 'private_root', return_value=self.private)
        self.private_patch.start()
        self.addCleanup(self.private_patch.stop)

    def pending(self, request='abcdef123456'):
        folder = self.private / ('recovery-' + request)
        folder.mkdir(parents=True)
        (folder / 'identity').write_text('fixture, not a private key')
        (folder / 'identity.pub').write_text(self.key)
        result = self.root / 'result.json'
        result.write_text(json.dumps({'schema': 1, 'request_id': request, 'root_verified_locally': True,
                                      'computer_public_key': self.key, 'host_public_key': self.host}))
        return folder, result

    def test_result_requires_owner_confirmation_and_matches_the_same_computer_key(self):
        folder, result = self.pending()
        with self.assertRaisesRegex(r.RecoveryError, 'host_confirmation_required'):
            r.finish_pairing(result)
        self.assertFalse((folder / 'ssh_config').exists())
        value = json.loads(result.read_text())
        value['computer_public_key'] = rsa_public(3)
        result.write_text(json.dumps(value))
        with self.assertRaisesRegex(r.RecoveryError, 'pairing_result_invalid'):
            r.finish_pairing(result, True)
        self.assertFalse((folder / 'ssh_config').exists())

    def test_import_survives_restart_and_preserves_pinned_host_on_mismatch(self):
        folder, result = self.pending()
        choice = r.finish_pairing(result, True)
        self.assertEqual(choice['config'], str(folder / 'ssh_config'))
        content = (folder / 'ssh_config').read_text()
        self.assertIn('StrictHostKeyChecking yes', content)
        self.assertIn('BatchMode yes', content)
        before = (folder / 'known_hosts').read_bytes()
        value = json.loads(result.read_text())
        value['host_public_key'] = rsa_public(3)
        result.write_text(json.dumps(value))
        with self.assertRaisesRegex(r.RecoveryError, 'host_key_changed'):
            r.finish_pairing(result, True)
        self.assertEqual((folder / 'known_hosts').read_bytes(), before)

    def test_result_cannot_escape_private_directory(self):
        _, result = self.pending()
        value = json.loads(result.read_text())
        value['request_id'] = '../outside'
        result.write_text(json.dumps(value))
        with self.assertRaisesRegex(r.RecoveryError, 'pairing_result_invalid'):
            r.read_pairing_result(result)

    def test_host_key_input_rejects_ambiguous_or_invalid_material(self):
        path = self.root / 'host.pub'
        for content in ('not a key', self.key + '\n' + self.host,
                        'example.com ' + self.host, 'ssh-rsa ' + base64.b64encode(b'bad').decode()):
            path.write_text(content)
            with self.assertRaisesRegex(r.RecoveryError, 'host_key_invalid'):
                r.read_host_key(path)
        path.write_text('169.254.0.1 ' + self.host)
        self.assertEqual(r.read_host_key(path), self.host)

    def test_real_key_generation_exports_no_private_key_and_keeps_pending_identity(self):
        script = r.prepare_pairing()
        folder = script.parent
        self.assertTrue((folder / 'identity').is_file())
        self.assertFalse((folder / 'ssh_config').exists())
        text = script.read_text(encoding='utf-8')
        self.assertNotIn('PRIVATE KEY', text)
        self.assertIn((folder / 'identity.pub').read_text().split()[1], text)
        self.assertNotIn(str(folder), text)
        compile(text, str(script), 'exec')
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((folder / 'identity').stat().st_mode), 0o600)

    def test_importing_real_owner_key_preserves_original_and_builds_strict_config(self):
        script = r.prepare_pairing()
        source = script.parent / 'identity'
        before = source.read_bytes()
        choice = r.import_identity(source, self.host, confirmed=True)
        folder = Path(choice['config']).parent
        self.assertNotEqual(folder, source.parent)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual((folder / 'identity').read_bytes(), before)
        self.assertEqual(r.read_host_key(folder / 'known_hosts'), self.host)

    def test_host_private_key_and_putty_key_are_not_used_as_login_identity(self):
        host = self.root / 'ssh_host_rsa_key'
        host.write_text('fixture')
        with self.assertRaisesRegex(r.RecoveryError, 'login_key_required'):
            r.import_identity(host, self.host, True)
        putty = self.root / 'identity.ppk'
        putty.write_text('PuTTY-User-Key-File-3: ssh-rsa')
        with self.assertRaisesRegex(r.RecoveryError, 'putty_conversion_required'):
            r.import_identity(putty, self.host, True)


class PhonePairingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.ssh, self.root, self.out = [self.base / name for name in ('ssh', 'root', 'downloads')]
        for folder in (self.ssh, self.root, self.out):
            folder.mkdir()
        self.target = self.ssh / 'authorized_keys2'
        self.old = b'# original owner keys\noriginal-key fixture\n'
        self.target.write_bytes(self.old)
        self.host, self.key = rsa_public(5), rsa_public(6)
        (self.ssh / 'ssh_host_rsa_key.pub').write_text(self.host)
        self.config = self.ssh / 'sshd_config'
        self.config.write_text('AuthorizedKeysFile=' + str(self.target) + '\nHostKey=' + str(self.ssh / 'ssh_host_rsa_key') + '\n')
        uid = patch.object(p.os, 'geteuid', return_value=0, create=True)
        uid.start()
        self.addCleanup(uid.stop)
        real_stat = os.stat
        def file_stat(path, *args, **kwargs):
            value = real_stat(path, *args, **kwargs)
            if os.path.realpath(path) == os.path.realpath(str(self.target)):
                return SimpleNamespace(st_uid=0, st_mode=stat.S_IFREG | 0o600, st_size=value.st_size)
            return value
        permissions = patch.object(p.os, 'stat', side_effect=file_stat)
        permissions.start()
        self.addCleanup(permissions.stop)

    def pair(self):
        return p.authorize(self.key, 'abcdef123456', str(self.ssh), str(self.root), str(self.out))

    def test_existing_authorization_is_backed_up_preserved_and_not_duplicated(self):
        result = self.pair()
        self.assertTrue(self.target.read_bytes().startswith(self.old))
        self.assertEqual((self.ssh / 'authorized_keys2.bb10-backup-abcdef123456').read_bytes(), self.old)
        self.pair()
        self.assertEqual(self.target.read_text().count(self.key), 1)
        data = json.loads(Path(result).read_text())
        self.assertEqual(data['host_public_key'], self.host)
        self.assertEqual(data['computer_public_key'], self.key)
        self.assertFalse(data['ssh_startup_configured'])
        self.assertFalse((self.root / 'use.sshd').exists())

    def test_no_root_or_unknown_ssh_layout_performs_no_authorization_write(self):
        with patch.object(p.os, 'geteuid', return_value=1000):
            with self.assertRaisesRegex(ValueError, 'ROOT_REQUIRED'):
                self.pair()
        self.assertEqual(self.target.read_bytes(), self.old)
        self.config.write_text('AuthorizedKeysFile=/some/other/file\n')
        with self.assertRaisesRegex(ValueError, 'UNSUPPORTED_SSH_LAYOUT'):
            self.pair()
        self.assertEqual(self.target.read_bytes(), self.old)

    def test_conflicting_result_or_lock_is_preserved_without_writing_keys(self):
        output = self.out / 'bb10-pair-abcdef123456-result.json'
        output.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.pair()
        self.assertEqual(self.target.read_bytes(), self.old)
        output.unlink()
        lock = self.ssh / 'authorized_keys2.bb10-pair.lock'
        lock.write_text('another operation')
        with self.assertRaises(OSError):
            self.pair()
        self.assertEqual(lock.read_text(), 'another operation')
        self.assertEqual(self.target.read_bytes(), self.old)


class RecoveryGuiTests(unittest.TestCase):
    def test_recovery_is_available_and_cannot_continue_before_verification(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        root.withdraw()
        dialog = ui.RecoveryDialog(root, lambda *_: self.fail('unverified continuation'))
        try:
            for platform in ('win32', 'darwin'):
                with self.subTest(platform=platform), patch.object(sys, 'platform', platform):
                    self.assertEqual(len(dialog.tabs.tabs()), 2)
                    self.assertEqual(str(dialog.continue_button.cget('state')), 'disabled')
                    dialog.finish()
            dialog.attributes('-alpha', 0.0)
            root.attributes('-alpha', 0.0)
            root.deiconify()
            dialog.deiconify()
            dialog.geometry('820x690')
            for index in (0, 1):
                dialog.tabs.select(index)
                root.update()
                for widget in (dialog.continue_button, dialog.verify_button, dialog.status):
                    self.assertGreater(widget.winfo_height(), 1)
                    self.assertLessEqual(widget.winfo_rooty() - dialog.winfo_rooty() + widget.winfo_height(), dialog.winfo_height())
        finally:
            dialog.close()
            root.destroy()
