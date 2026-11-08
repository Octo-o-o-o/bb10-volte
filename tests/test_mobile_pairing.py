"""Public request parsing and native pairing keep code and private keys local."""
import base64
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch, mock_open

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import phone_pairing as p
import connection_recovery as recovery
import recovery_gui


def public_key(marker=1):
    parts = [b'ssh-rsa', b'\x01\x00\x01', b'\x00' + bytes([marker]) * 256]
    raw = b''.join(struct.pack('>I', len(part)) + part for part in parts)
    return 'ssh-rsa ' + base64.b64encode(raw).decode('ascii')


class MobilePairingTests(unittest.TestCase):
    def setUp(self):
        self.key = public_key()
        self.request = p.pairing_request(self.key, 'abcdef123456')
        self.raw = json.dumps(self.request).encode('ascii')
        self.encoded = base64.b64encode(self.raw).decode('ascii')

    def test_request_is_public_only_and_fingerprint_matches_desktop(self):
        self.assertEqual(p.parse_pairing_request(self.raw), self.request)
        self.assertEqual(set(self.request), {'schema', 'kind', 'request_id', 'computer_public_key'})
        self.assertEqual(p.key_fingerprint(self.key), recovery.fingerprint(self.key))

    def test_ambiguous_malformed_and_executable_request_fields_are_rejected(self):
        bad = [b'', b'null', b'[]', b'x' * 16385,
               self.raw[:-1] + b',"schema":1}', self.raw.replace(b'"schema": 1', b'"schema": true')]
        for change in ({'request_id': '../file'}, {'computer_public_key': 'ssh-rsa invalid'},
                       {'kind': 'python-code'}, {'script': 'os.system("danger")'},
                       {'request_id': 123}, {'computer_public_key': None}):
            value = dict(self.request); value.update(change); bad.append(json.dumps(value).encode('ascii'))
        for blob in bad:
            with self.subTest(blob=blob[:70]), self.assertRaises((ValueError, TypeError)):
                p.parse_pairing_request(blob)

    def test_mobile_authorizes_exact_previewed_key_without_touching_running_ssh(self):
        result_path = '/accounts/1000/shared/downloads/bb10-pair-abcdef123456-result.json'
        with patch.object(p.os, 'geteuid', return_value=0, create=True), \
                patch.object(p.os, 'uname', return_value=('QNX',), create=True), \
                patch.object(p, 'authorize', return_value=result_path) as authorize, \
                patch.object(p, 'usb_ssh_available', return_value=True), \
                patch.object(p.subprocess, 'call') as start:
            result = p.mobile_pair(self.encoded)
        authorize.assert_called_once_with(self.key, 'abcdef123456')
        start.assert_not_called()
        self.assertEqual(result['result_path'], result_path)
        self.assertTrue(result['desktop_verification_required'])
        self.assertTrue(result['usb_ssh_available'])

    def test_mobile_rejects_nonroot_before_authorization(self):
        with patch.object(p.os, 'geteuid', return_value=1000, create=True), \
                patch.object(p, 'authorize') as authorize:
            with self.assertRaisesRegex(ValueError, 'ROOT_REQUIRED'):
                p.mobile_pair(self.encoded)
            authorize.assert_not_called()

    def test_invalid_encoded_request_cannot_reach_authorization(self):
        with patch.object(p.os, 'geteuid', return_value=0, create=True), \
                patch.object(p.os, 'uname', return_value=('QNX',), create=True), \
                patch.object(p, 'authorize') as authorize:
            for value in (';touch /tmp/test', self.encoded + '\n', 'A' * 21849, '!!!!'):
                with self.assertRaises(ValueError):
                    p.mobile_pair(value)
            authorize.assert_not_called()

    def test_missing_ssh_starts_existing_service_only_on_usb(self):
        with patch.object(p.os, 'geteuid', return_value=0, create=True), \
                patch.object(p.os, 'uname', return_value=('QNX',), create=True), \
                patch.object(p, 'authorize', return_value='/downloads/result.json'), \
                patch.object(p, 'usb_ssh_available', side_effect=[False, True]), \
                patch.object(p, 'usb_ssh_safe_to_start', return_value=True), \
                patch.object(p, 'open', mock_open(), create=True), \
                patch.object(p.subprocess, 'call', return_value=0) as start:
            result = p.mobile_pair(self.encoded)
        self.assertEqual(start.call_args.args[0], ['/usr/sbin/sshd', '-f', '/etc/ssh/sshd_config',
                                                '-o', 'ListenAddress=169.254.0.1'])
        self.assertTrue(result['usb_ssh_available'])

    def test_existing_non_usb_listener_is_not_started_or_rewritten(self):
        for settings in ({'listenaddress':['0.0.0.0']}, {'listenaddress':['::']},
                         {'port':['2222']}, {'listenaddress':['169.254.0.1','192.0.2.1']}):
            with self.subTest(settings=settings), patch.object(p, 'settings', return_value=settings):
                self.assertFalse(p.usb_ssh_safe_to_start())
        with patch.object(p, 'settings', return_value={}):
            self.assertTrue(p.usb_ssh_safe_to_start())
        with patch.object(p.os, 'geteuid', return_value=0, create=True), \
                patch.object(p.os, 'uname', return_value=('QNX',), create=True), \
                patch.object(p, 'authorize', return_value='/downloads/result.json'), \
                patch.object(p, 'usb_ssh_available', return_value=False), \
                patch.object(p, 'usb_ssh_safe_to_start', return_value=False), \
                patch.object(p.subprocess, 'call') as start:
            result = p.mobile_pair(self.encoded)
            self.assertFalse(result['usb_ssh_available'])
            self.assertEqual(result['state'], 'paired')
            start.assert_not_called()

    def test_authorization_failure_never_starts_ssh(self):
        with patch.object(p.os, 'geteuid', return_value=0, create=True), \
                patch.object(p.os, 'uname', return_value=('QNX',), create=True), \
                patch.object(p, 'authorize', side_effect=ValueError('layout mismatch')), \
                patch.object(p, 'usb_ssh_available') as service:
            with self.assertRaises(ValueError):
                p.mobile_pair(self.encoded)
            service.assert_not_called()


class DesktopNativePairingFlowTests(unittest.TestCase):
    def test_native_instructions_are_default_and_terminal_is_optional(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        root.withdraw()
        try:
            with tempfile.TemporaryDirectory() as directory, patch.object(recovery, 'private_root', return_value=Path(directory)):
                folder = Path(directory) / 'recovery-abcdef123456'; folder.mkdir()
                (folder/'identity').write_text('private fixture')
                (folder/'identity.pub').write_text(public_key())
                script=folder/'bb10-pair-abcdef123456.py';script.write_text('# fixture')
                recovery.save_pairing_step(script, 2)
                dialog = recovery_gui.RecoveryDialog(root, lambda *_: None)
                try:
                    self.assertEqual(dialog.pair_step, 2)
                    self.assertEqual(dialog.commands.winfo_manager(), '')
                    self.assertIn('-request.json', dialog.pair_hint.cget('text'))
                    self.assertIn(p.key_fingerprint(public_key()), dialog.pair_hint.cget('text'))
                    dialog.show_terminal_steps()
                    self.assertEqual(dialog.commands.winfo_manager(), 'pack')
                    dialog.show_terminal_steps()
                    self.assertEqual(dialog.commands.winfo_manager(), '')
                finally:
                    dialog.close()
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
