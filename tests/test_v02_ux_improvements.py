"""Regression tests for v0.2 UX improvements (direct pairing, netdisk import, mobile UI)."""
import base64
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

import connection_recovery as cr
import fetch_materials as fm
import phone_pairing as pp


def fake_rsa_public(seed: bytes) -> str:
    modulus = b'\x00' + hashlib.sha256(seed).digest() * 4
    blob = (struct.pack('>I', 7) + b'ssh-rsa' +
            struct.pack('>I', 3) + b'\x01\x00\x01' +
            struct.pack('>I', len(modulus)) + modulus)
    return 'ssh-rsa ' + base64.b64encode(blob).decode('ascii')


class V02UxImprovementTests(unittest.TestCase):
    def test_direct_pairing_short_code_and_pinning_guards(self):
        host_a = fake_rsa_public(b'host-a')
        host_b = fake_rsa_public(b'host-b')
        fp = cr.fingerprint(host_a)
        code = cr.short_code(host_a)
        self.assertEqual(len(code), 9)
        self.assertEqual(code[4], '-')
        self.assertEqual(code.replace('-', ''), fp.removeprefix('SHA256:')[:8])

        with tempfile.TemporaryDirectory() as tmp:
            priv = Path(tmp)
            folder = priv / 'recovery-abcdef123456'
            folder.mkdir()
            script = folder / 'bb10-pair-abcdef123456.py'
            script.write_text('# pair\n', encoding='utf-8')
            (folder / 'identity').write_text('dummy-identity-placeholder\n', encoding='utf-8')
            (folder / 'identity.pub').write_text(fake_rsa_public(b'pc-key') + '\n', encoding='ascii')

            with patch.object(cr, 'private_root', return_value=priv):
                with self.assertRaisesRegex(cr.RecoveryError, 'host_confirmation_required'):
                    cr.finish_pairing_direct(script, host_a, confirmed=False)
                choice = cr.finish_pairing_direct(script, host_a, confirmed=True)
                self.assertEqual(choice['host'], 'bb10-root')
                config = Path(choice['config']).read_text(encoding='utf-8')
                self.assertIn('StrictHostKeyChecking yes', config)
                self.assertIn('GlobalKnownHostsFile none', config)
                self.assertEqual(cr.read_host_key(folder / 'known_hosts'), host_a)
                with self.assertRaisesRegex(cr.RecoveryError, 'host_key_changed'):
                    cr.finish_pairing_direct(script, host_b, confirmed=True)

    def test_result_cannot_change_the_confirmed_key_or_request(self):
        folder = Path('pending')
        original_key = fake_rsa_public(b'previewed')
        for changed in ((Path('other-request'), original_key), (folder, fake_rsa_public(b'changed-key'))):
            with self.subTest(changed_folder=changed[0]), \
                    patch.object(cr, 'read_pairing_result', return_value=(*changed, False)), \
                    patch.object(cr, 'write_config') as write:
                with self.assertRaisesRegex(cr.RecoveryError, 'pairing_result_changed'):
                    cr.finish_pairing('result.json', confirmed=True, expected=(folder, original_key))
                write.assert_not_called()

    def test_probe_usb_host_key_blocks_multiple_usb_devices(self):
        import root_setup
        with patch.object(root_setup, 'local_usb_state', return_value={'usb_count': 2}):
            with self.assertRaisesRegex(cr.RecoveryError, 'multiple_usb_devices'):
                cr.probe_usb_host_key()

    def test_probe_requires_a_single_identified_usb_link(self):
        import root_setup
        for state in ({}, {'usb_count': 0}, {'usb_count': 1}, {'usb_count': None}):
            with self.subTest(state=state), patch.object(root_setup, 'local_usb_state', return_value=state), \
                    patch.object(cr, '_probe_peer_host_key') as probe:
                with self.assertRaisesRegex(cr.RecoveryError, 'direct_usb_not_ready'):
                    cr.probe_usb_host_key()
                probe.assert_not_called()

    def test_probe_observes_a_key_while_strict_ssh_rejects_the_host(self):
        key = fake_rsa_public(b'host-usb')
        offered = 'BB10-HOST HOSTNAME ' + key + '\n'
        client = SimpleNamespace(ssh='ssh')
        with patch.object(cr.subprocess, 'run') as run:
            run.return_value = SimpleNamespace(returncode=255, stderr=offered + 'Host key verification failed.\n')
            self.assertEqual(cr._probe_peer_host_key(client, '169.254.88.1', '169.254.88.2'), (key, None))
            cmd = run.call_args.args[0]
            for option in ('StrictHostKeyChecking=yes', 'BindAddress=169.254.88.2',
                           'IdentityFile=none', 'IdentityAgent=none', 'UserKnownHostsFile=none'):
                self.assertIn(option, cmd)
            run.return_value = SimpleNamespace(returncode=0, stderr=offered)
            self.assertEqual(cr._probe_peer_host_key(client, '169.254.88.1'), (None, 'connection_failed'))

    def test_probe_usb_host_key_prefers_detected_usb_subnet_and_accepts_known_hosts_alias(self):
        import root_setup
        host_a = fake_rsa_public(b'host-usb')
        calls = []
        with patch.object(root_setup, 'local_usb_state', return_value={
                'usb_count': 1, 'usb_peer': '169.254.88.1', 'usb_source_address': '169.254.88.2'}) as usb_probe, \
                patch.object(cr, '_probe_peer_host_key', side_effect=lambda _c, peer, source=None: (
                    calls.append((peer, source)) or (host_a, None))):
            self.assertEqual(cr.probe_usb_host_key(), host_a)
        usb_probe.assert_called_once_with()
        self.assertEqual(calls, [('169.254.88.1', '169.254.88.2')])

        with tempfile.TemporaryDirectory() as tmp:
            known = Path(tmp) / 'known_hosts'
            known.write_text('bb10-root,169.254.0.1 ' + host_a + '\n', encoding='ascii')
            self.assertEqual(cr.read_host_key(known), host_a)
            known.write_text('example.com ' + host_a + '\n', encoding='ascii')
            with self.assertRaisesRegex(cr.RecoveryError, 'host_key_invalid'):
                cr.read_host_key(known)

    def test_find_local_firmware_candidates_and_fast_size_precheck(self):
        data = b'0123456789' * 20
        item = {
            'file': 'Passport_10.3.03.3216.7z',
            'extracted_file': 'Passport_10.3.03.3216_SQW100-1-2-3-4.exe',
            'size': len(data),
            'sha256': hashlib.sha256(data).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as tmp:
            downloads = Path(tmp) / 'Downloads'
            cache = Path(tmp) / 'cache'
            downloads.mkdir()
            # Browser-renamed archive + partial files + same-size unrelated files.
            exact = downloads / 'Passport_10.3.03.3216 (1).7z'
            exact.write_bytes(data)
            (downloads / 'Passport_10.3.03.3216.7z.crdownload').write_bytes(data)
            (downloads / 'Passport_10.3.03.3216.7z.td').write_bytes(data)
            (downloads / 'unrelated-video.mp4').write_bytes(data)
            (downloads / 'unrelated.7z').write_bytes(data)
            partial = downloads / 'Passport_10.3.03.3216.7z'
            partial.write_bytes(data[:50])
            extracted = downloads / 'Passport_10.3.03.3216_SQW100-1-2-3-4.exe'
            extracted.write_bytes(data + b'extra')

            candidates = fm.find_local_firmware_candidates(item, search_dirs=[downloads])
            self.assertEqual(candidates, [exact])

            # When only the mistakenly extracted .exe is present, scan surfaces it so import explains not to extract
            exact.unlink()
            partial.unlink()
            self.assertEqual(fm.find_local_firmware_candidates(item, search_dirs=[downloads]), [extracted])
            exact.write_bytes(data)
            partial.write_bytes(data[:50])

            # Fast size pre-check for extracted .exe
            with self.assertRaises(fm.MaterialImportError) as ctx_exe:
                fm.import_material(item, extracted, folder=cache)
            self.assertEqual(str(ctx_exe.exception), 'import_hash_mismatch')
            self.assertIn('.exe', ctx_exe.exception.user_message)

            # Fast size pre-check for incomplete file
            with self.assertRaises(fm.MaterialImportError) as ctx_small:
                fm.import_material(item, partial, folder=cache)
            self.assertEqual(str(ctx_small.exception), 'import_hash_mismatch')
            self.assertIn('Passport_10.3.03.3216.7z', ctx_small.exception.user_message)

            with self.assertRaises(fm.MaterialImportError):
                fm.import_material(item, downloads / 'Passport_10.3.03.3216.7z.td', folder=cache)
            corrupted = downloads / 'Passport_10.3.03.3216 (2).7z'
            corrupted.write_bytes(b'X' * len(data))
            with self.assertRaisesRegex(fm.MaterialImportError, 'import_hash_mismatch'):
                fm.import_material(item, corrupted, folder=cache)

            # Exact file succeeds and marks cached
            imported = fm.import_material(item, exact, folder=cache, progress=lambda _: None)
            self.assertTrue(imported.is_file())
            self.assertTrue(fm.firmware_cached(item, folder=cache))

    def test_mobile_pair_returns_host_fingerprint_from_authorization(self):
        pc_key = fake_rsa_public(b'pc-pub')
        host_key = fake_rsa_public(b'phone-host')
        req = pp.pairing_request(pc_key, 'abcdef123456')
        encoded = base64.b64encode(json.dumps(req).encode('utf-8')).decode('ascii')
        with tempfile.TemporaryDirectory() as tmp:
            res_path = Path(tmp) / 'bb10-pair-abcdef123456-result.json'
            res_path.write_text(json.dumps({'host_public_key': fake_rsa_public(b'other-host')}), encoding='ascii')
            host_fingerprint = pp.key_fingerprint(host_key)
            with patch.object(pp.os, 'geteuid', return_value=0, create=True), \
                    patch.object(pp.os, 'uname', return_value=('QNX',), create=True), \
                    patch.object(pp, 'authorize', return_value=(str(res_path), host_fingerprint)) as authorize, \
                    patch.object(pp, 'usb_ssh_available', return_value=True):
                out = pp.mobile_pair(encoded)
            authorize.assert_called_once_with(pc_key, 'abcdef123456', include_host_fingerprint=True)
            self.assertEqual(out['host_fingerprint'], host_fingerprint)

    def test_v02_version_and_mobile_ui_cleanup_contracts(self):
        proj = json.loads((ROOT / 'project.json').read_text(encoding='utf-8'))
        self.assertEqual(proj['mobile_version'], '0.2.0.0')
        self.assertEqual(proj['desktop_revision'], 54)
        bar_xml = (ROOT / 'mobile/native/bar-descriptor.xml').read_text(encoding='utf-8')
        self.assertIn('<versionNumber>0.2.0</versionNumber>', bar_xml)
        self.assertIn('<buildId>0</buildId>', bar_xml)
        main_qml = (ROOT / 'mobile/native/assets/main.qml').read_text(encoding='utf-8')
        self.assertNotIn('navigation.t("confirm-calls")', main_qml)
        self.assertNotIn('navigation.t("tagline")', main_qml)
        manage_qml = (ROOT / 'mobile/native/assets/Manage.qml').read_text(encoding='utf-8')
        self.assertIn('property bool advancedOpen: false', manage_qml)
        self.assertIn('ActionItem', manage_qml)
        self.assertIn('source: "CallCheck.qml"', manage_qml)
        self.assertIn('visible: page.allows("confirm-calls")', manage_qml)
        self.assertIn('var model = volteController.model; return volteController.allowed(action);', manage_qml)
        self.assertIn('volteController.exportPath', manage_qml)
        self.assertIn('volteController.hasPackage && page.allows("update")', manage_qml)
        pairing_qml = (ROOT / 'mobile/native/assets/Pairing.qml').read_text(encoding='utf-8')
        self.assertIn('onCreationCompleted:', pairing_qml)
        self.assertIn('pairingController.hasRequest && !pairingController.done', pairing_qml)
        cpp = (ROOT / 'mobile/native/src/pairingcontroller.cpp').read_text(encoding='utf-8')
        self.assertIn('bb10-pair-*-request*.json', cpp)
        self.assertIn('m_hostShortCode', cpp)
        self.assertIn('seenRequests', cpp)
        self.assertIn('unpaired', cpp)

    def test_recovery_dialog_request_hint_and_bilingual_layout_fit(self):
        import i18n
        import recovery_gui
        try:
            import tkinter as tk
            root = tk.Tk()
        except Exception as error:
            self.skipTest(str(error))
        root.withdraw()
        self.addCleanup(root.destroy)
        with tempfile.TemporaryDirectory() as tmp:
            priv = Path(tmp) / 'priv'
            folder = priv / 'recovery-abcdef123456'
            folder.mkdir(parents=True)
            script = folder / 'bb10-pair-abcdef123456.py'
            script.write_text('# pair\n', encoding='utf-8')
            (folder / 'identity').write_text('dummy\n', encoding='utf-8')
            (folder / 'identity.pub').write_text(fake_rsa_public(b'pc') + '\n', encoding='ascii')
            with patch.object(cr, 'private_root', return_value=priv):
                for lang in ('zh', 'en'):
                    cr.save_pairing_step(script, 2)
                    with self.subTest(lang=lang), patch.object(i18n, 'LANGUAGE', lang):
                        dialog = recovery_gui.RecoveryDialog(root, lambda *_: None)
                        try:
                            dialog.attributes('-alpha', 0.0)
                            root.attributes('-alpha', 0.0)
                            dialog.geometry('820x690')
                            root.deiconify()
                            dialog.deiconify()
                            root.update()
                            for widget in (dialog.direct_button, dialog.result_button, dialog.step_back, dialog.step_next):
                                self.assertGreater(widget.winfo_width(), 1)
                                self.assertLessEqual(
                                    widget.winfo_rootx() - dialog.winfo_rootx() + widget.winfo_width(),
                                    dialog.winfo_width())
                            dialog.events.put(('script', script))
                            dialog.after_cancel(dialog._job)
                            dialog.drain()
                            self.assertIn('bb10-pair-abcdef123456-request.json', dialog.status.cget('text'))
                            self.assertNotIn('.py', dialog.status.cget('text'))
                        finally:
                            dialog.close()

    def test_recovery_direct_decline_and_result_retry_use_same_pinned_identity(self):
        import recovery_gui
        import tkinter as tk
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        root.withdraw()
        self.addCleanup(root.destroy)
        with tempfile.TemporaryDirectory() as tmp, patch.object(cr, 'private_root', return_value=Path(tmp)):
            folder = Path(tmp) / 'recovery-abcdef123456'
            folder.mkdir()
            script = folder / 'bb10-pair-abcdef123456.py'
            script.write_text('# fixture\n')
            (folder / 'identity').write_text('private fixture')
            pc_key, phone_key = fake_rsa_public(b'pc'), fake_rsa_public(b'phone')
            (folder / 'identity.pub').write_text(pc_key, encoding='ascii')
            cr.save_pairing_step(script, 2)
            receipt = Path(tmp) / 'bb10-pair-abcdef123456-result.json'
            receipt.write_text(json.dumps({'schema': 1, 'request_id': 'abcdef123456',
                                           'computer_public_key': pc_key, 'host_public_key': phone_key,
                                           'root_verified_locally': True}), encoding='ascii')
            ready = []
            dialog = recovery_gui.RecoveryDialog(root, lambda *args: ready.append(args))
            def deliver(action, work):
                try:
                    dialog.events.put((action, work()))
                except recovery_gui.WorkflowError as error:
                    dialog.events.put(('error', error.code))
            def drain():
                dialog.after_cancel(dialog._job)
                dialog.drain()
            config = folder / 'ssh_config'
            try:
                with patch.object(dialog, 'start', side_effect=deliver), \
                        patch.object(recovery_gui, 'probe_usb_host_key', return_value=phone_key), \
                        patch.object(recovery_gui.messagebox, 'askokcancel', side_effect=[False, True]) as confirm, \
                        patch.object(recovery_gui.filedialog, 'askopenfilename', return_value=str(receipt)), \
                        patch.object(recovery_gui, 'local_usb_state', return_value={'usb_count': 1}), \
                        patch.object(recovery_gui, 'verify_root', side_effect=[
                            recovery_gui.WorkflowError('connection_refused'),
                            {'host': 'bb10-root', 'config': str(config)}]) as verify:
                    dialog.direct_button.invoke()
                    drain()
                    self.assertIn(cr.short_code(phone_key), confirm.call_args.args[1])
                    self.assertIn(cr.fingerprint(phone_key), confirm.call_args.args[1])
                    self.assertFalse(config.exists())
                    verify.assert_not_called()
                    dialog.result_button.invoke()
                    drain()
                    self.assertFalse(dialog.verified)
                    self.assertEqual(cr.read_host_key(folder / 'known_hosts'), phone_key)
                    self.assertEqual(str(dialog.verify_button.cget('state')), 'normal')
                    dialog.verify_button.invoke()
                    drain()
                    self.assertTrue(dialog.verified)
                    self.assertEqual(verify.call_args_list[0], verify.call_args_list[1])
                    dialog.continue_button.invoke()
                    self.assertEqual(ready, [('bb10-root', str(config))])
            finally:
                if dialog.winfo_exists():
                    dialog.close()

    def test_mobile_app_window_can_export_verified_bundled_bar(self):
        import mobile_app_gui
        try:
            import tkinter as tk
            root = tk.Tk()
        except Exception as error:
            self.skipTest(str(error))
        root.withdraw()
        self.addCleanup(root.destroy)
        win = mobile_app_gui.MobileAppInstallWindow(root, 'bb10-root', '')
        self.addCleanup(win.close)
        with tempfile.TemporaryDirectory() as tmp:
            out_bar = Path(tmp) / 'exported.bar'
            with patch.object(mobile_app_gui.filedialog, 'asksaveasfilename', return_value=str(out_bar)):
                win.export_bar()
            self.assertEqual(out_bar.read_bytes(), mobile_app_gui.bundled_bar(win.pin).read_bytes())


if __name__ == '__main__':
    unittest.main()
