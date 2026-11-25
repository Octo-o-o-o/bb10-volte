"""Regression tests for v0.5.0-r55 / mobile 0.2.1.0 user feedback fixes."""
import base64
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for rel in ('tools', 'device', 'mobile/runtime'):
    path = str(ROOT / rel)
    if path not in sys.path:
        sys.path.insert(0, path)


def _fake_rsa_pub(seed=b'test-key-r55', comment=''):
    blob = b''
    for part in (b'ssh-rsa', b'\x01\x00\x01', b'\x00' + seed * 32):
        blob += struct.pack('>I', len(part)) + part
    key = 'ssh-rsa ' + base64.b64encode(blob).decode('ascii')
    return key + (' ' + comment if comment else '') + '\n'


class DeviceEngineR55Tests(unittest.TestCase):
    def test_previous_payloads_contains_r53_r54_canonical_hash(self):
        import unified_install
        self.assertIn(
            '1b1227074c90fc5794e19b5a2f0df06cb6d3307db5082679fc7e5914047b5c65',
            unified_install.PREVIOUS_PAYLOADS,
        )

    def test_probe_converts_unvalidated_legacy_installation_to_scope_error(self):
        import unified_install
        fake_facts = {
            'variant': 'SQC100-1',
            'board': 'CLASSICROW',
            'os_version': '10.3.3.3216',
        }
        with patch.object(unified_install.os, 'geteuid', return_value=0, create=True), \
                patch.object(unified_install.os, 'uname', return_value=('QNX',), create=True), \
                patch.object(unified_install.ctypes, 'sizeof', return_value=4), \
                patch.object(unified_install.device_info, 'read_identity', return_value=fake_facts), \
                patch.object(unified_install.policy, 'model', return_value='q20'), \
                patch.object(unified_install, 'identity', return_value=(fake_facts, 'q20')), \
                patch.object(unified_install, 'installed_management_schema', return_value=0), \
                patch.object(unified_install.s, 'phone_idle', return_value=True), \
                patch.object(unified_install, 'root_kind', return_value='autoroot_v4'), \
                patch.object(unified_install.migration, 'inspect', side_effect=AssertionError('unvalidated_legacy_installation')), \
                patch.object(unified_install.os.path, 'isfile', return_value=False):
            result = unified_install.probe()
        self.assertEqual(result['scope_error'], 'unvalidated_legacy_installation')
        self.assertFalse(result['can_install'])
        self.assertFalse(result['can_update'])

    def test_probe_converts_root_scheme_error_to_scope_error(self):
        import unified_install
        fake_facts = {
            'variant': 'SQC100-1',
            'board': 'CLASSICROW',
            'os_version': '10.3.3.3216',
        }
        with patch.object(unified_install.os, 'geteuid', return_value=0, create=True), \
                patch.object(unified_install.os, 'uname', return_value=('QNX',), create=True), \
                patch.object(unified_install.ctypes, 'sizeof', return_value=4), \
                patch.object(unified_install.device_info, 'read_identity', return_value=fake_facts), \
                patch.object(unified_install.policy, 'model', return_value='q20'), \
                patch.object(unified_install, 'identity', return_value=(fake_facts, 'q20')), \
                patch.object(unified_install, 'installed_management_schema', return_value=0), \
                patch.object(unified_install.s, 'phone_idle', return_value=True), \
                patch.object(unified_install, 'root_kind', side_effect=AssertionError('root_scheme_not_supported')), \
                patch.object(unified_install.os.path, 'isfile', return_value=False):
            result = unified_install.probe()
        self.assertEqual(result['scope_error'], 'root_scheme_not_supported')
        self.assertFalse(result['can_install'])

    def test_cleanup_stage_bypasses_management_lock(self):
        import unified_install
        op_id = 'a' * 32
        with patch.object(unified_install, 'management_lock', side_effect=AssertionError('management_busy')), \
                patch.object(unified_install, 'cleanup_stage', return_value={'cleaned': True}) as cleanup:
            result = unified_install.manage('cleanup-stage', stage='/var/tmp/bb10_volte_stage_abc', operation_id=op_id)
        cleanup.assert_called_once_with('/var/tmp/bb10_volte_stage_abc')
        self.assertTrue(result['cleaned'])
        self.assertEqual(result['operation_id'], op_id)

    def test_classify_status_error_is_allowlisted(self):
        import unified_service
        self.assertEqual(unified_service.classify_status_error('network_mode_rejected'), 'network_mode_rejected')
        self.assertEqual(unified_service.classify_status_error('Existing APN overlay'), 'existing_apn_overlay')
        self.assertEqual(unified_service.classify_status_error('Readiness timed out waiting for LTE'), 'network_readiness_timeout')
        self.assertEqual(unified_service.classify_status_error('SIM/carrier needs adaptation: 460-99'), 'sim_or_carrier_needs_adaptation')
        self.assertEqual(unified_service.classify_status_error('Original radio configuration changed'), 'radio_config_check_failed')
        self.assertEqual(unified_service.classify_status_error('Traceback /secret/path/12345'), 'internal_error')
        self.assertIsNone(unified_service.classify_status_error(''))

    def test_public_status_exports_error_code_only_on_current_boot_error(self):
        import unified_dca
        import unified_install
        import unified_service
        raw_error = {
            'phase': 'error',
            'error': 'network_mode_rejected',
            'status_from_current_boot': True,
        }
        with patch.object(unified_service, 'verify'), \
                patch.object(unified_service, 'boot_token', return_value='boot-1'), \
                patch.object(unified_service.s, 'read_status', return_value=dict(raw_error)), \
                patch.object(unified_service.device_info, 'read_identity', return_value={'variant': 'SQC100-2'}), \
                patch.object(unified_install, 'installed_management_schema', return_value=2), \
                patch.object(unified_dca, 'serving_network_snapshot', return_value={}), \
                patch.object(unified_service, 'card', side_effect=IOError('no sim')), \
                patch.object(unified_service.n, 'read', return_value=''), \
                patch.object(unified_service.os.path, 'isfile', return_value=False):
            out = unified_service.public_status()
        self.assertEqual(out['error_code'], 'network_mode_rejected')

        raw_stale = dict(raw_error, status_from_current_boot=False)
        with patch.object(unified_service, 'verify'), \
                patch.object(unified_service, 'boot_token', return_value='boot-1'), \
                patch.object(unified_service.s, 'read_status', return_value=raw_stale), \
                patch.object(unified_service.device_info, 'read_identity', return_value={'variant': 'SQC100-2'}), \
                patch.object(unified_install, 'installed_management_schema', return_value=2), \
                patch.object(unified_dca, 'serving_network_snapshot', return_value={}), \
                patch.object(unified_service, 'card', side_effect=IOError('no sim')), \
                patch.object(unified_service.n, 'read', return_value=''), \
                patch.object(unified_service.os.path, 'isfile', return_value=False):
            out_stale = unified_service.public_status()
        self.assertNotIn('error_code', out_stale)

    def test_locked_prepare_restores_lte_mode_on_pre_journal_failure(self):
        import contextlib
        import unified_dca
        import unified_install
        import unified_service

        @contextlib.contextmanager
        def dummy_lock(blocking=False):
            yield

        with patch.object(unified_service, 'prepare', side_effect=RuntimeError('network_mode_rejected')), \
                patch.object(unified_service.s, 'j', None), \
                patch.object(unified_service.s, 'shutdown', False), \
                patch.object(unified_service.os.path, 'isfile', return_value=False), \
                patch.object(unified_service.s, 'phone_idle', return_value=True), \
                patch.object(unified_service.n, 'ims_pids', return_value=[]), \
                patch.object(unified_service.n, 'active_vpn_sessions', return_value=[]), \
                patch.object(unified_service.n, 'crypto_policy', return_value={'swcr_id': -1, 'crypto_support': 0}), \
                patch.object(unified_install, 'management_lock', side_effect=dummy_lock), \
                patch.object(unified_service, 'verify'), \
                patch.object(unified_dca, 'restore_network_selection') as restore_sel, \
                patch.object(unified_dca, 'restore_lte_mode') as restore_lte:
            with self.assertRaises(RuntimeError):
                unified_service.locked_prepare()
        restore_sel.assert_called_once()
        restore_lte.assert_called_once()

    def test_workflow_and_feedback_keep_safe_error_code(self):
        import feedback
        import workflow
        status = workflow.public_status({
            'phase': 'error',
            'status_from_current_boot': True,
            'error_code': 'network_mode_rejected',
        })
        self.assertEqual(status['error_code'], 'network_mode_rejected')
        bad = workflow.public_status({
            'phase': 'error',
            'status_from_current_boot': True,
            'error_code': 'INVALID /path/leak',
        })
        self.assertNotIn('error_code', bad)
        projected = feedback.project({'error_code': 'network_mode_rejected', 'phase': 'error'})
        self.assertEqual(projected['error_code'], 'network_mode_rejected')


class MobileRuntimeR55Tests(unittest.TestCase):
    def test_scope_error_unvalidated_legacy_installation_has_actionable_copy(self):
        import worker
        resp = worker.inspection_response(
            {'language': 'zh'},
            {'scope_error': 'unvalidated_legacy_installation', 'installed': False},
            {'model': 'SQC100-1'},
        )
        self.assertEqual(resp['state'], 'unsupported')
        self.assertEqual(resp['details']['error_code'], 'unvalidated_legacy_installation')
        self.assertIn('/var/rootdata/q10_volte', resp['display_i18n']['zh']['message'])
        self.assertIn('自动接管', resp['display_i18n']['zh']['message'])
        self.assertIn('migrate automatically', resp['display_i18n']['en']['message'])

    def test_recovery_required_includes_error_code_and_network_restore_hint(self):
        import worker
        result = {
            'installed': True,
            'installed_stage': 'managed',
            'installed_management_schema': 2,
            'sim_supported': True,
            'status': {
                'enabled': True,
                'status_from_current_boot': True,
                'phase': 'error',
                'error_code': 'network_mode_rejected',
            },
        }
        resp = worker.inspection_response({'language': 'en'}, result, {'model': 'SQC100-2'})
        self.assertEqual(resp['state'], 'recovery_required')
        self.assertEqual(resp['details']['error_code'], 'network_mode_rejected')
        self.assertIn('network_mode_rejected', resp['display']['message'])
        self.assertIn('4G/3G/2G', resp['display']['message'])
        self.assertIn('network_mode_rejected', resp['display_i18n']['zh']['message'])


class NonAsciiSshAndDriversR55Tests(unittest.TestCase):
    def test_non_ascii_public_key_comment_handled_across_pairing_and_cache(self):
        import connection_recovery as cr
        import pairing_instructions as pi
        import preparation_cache as pc

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pub = tmp_path / 'identity.pub'
            raw_pub = _fake_rsa_pub(b'pc-key-01', comment='测试用户@中文主机')
            pub.write_text(raw_pub, encoding='utf-8')
            parsed = cr.read_public_key_file(pub)
            self.assertEqual(parsed, ' '.join(raw_pub.split()[:2]))
            # Also handles arbitrary non-UTF-8 (GBK) bytes in comment.
            gbk_bytes = parsed.encode('ascii') + b' ' + '测试用户'.encode('gbk') + b'\n'
            pub.write_bytes(gbk_bytes)
            self.assertEqual(cr.read_public_key_file(pub), parsed)

            # Full pairing prepare + export + pending_pairings + read_pairing_result round-trip.
            priv_root = tmp_path / 'private'
            priv_root.mkdir()
            captured_args = []

            def fake_keygen(args):
                captured_args.append(list(args))
                out = Path(args[args.index('-f') + 1])
                out.write_text('DUMMY-PRIVATE-MATERIAL\n', encoding='ascii')
                out.with_suffix('.pub').write_bytes(gbk_bytes)

            with patch.object(cr, 'private_root', return_value=priv_root), \
                    patch.object(cr, 'run_keygen', side_effect=fake_keygen):
                script = cr.prepare_pairing()
                self.assertIn('-C', captured_args[0])
                export_dir = tmp_path / 'export'
                export_dir.mkdir()
                pi.export_pairing_files(script, export_dir)
                self.assertEqual(len(list(export_dir.iterdir())), 3)
                pending = cr.pending_pairings()
                self.assertEqual(len(pending), 1)
                request_id = script.stem.removeprefix('bb10-pair-')
                host_pub = _fake_rsa_pub(b'phone-host', comment='root@bb10').strip()
                res_file = tmp_path / ('bb10-pair-' + request_id + '-result.json')
                res_file.write_text(json.dumps({
                    'schema': 1,
                    'root_verified_locally': True,
                    'request_id': request_id,
                    'computer_public_key': parsed,
                    'host_public_key': host_pub,
                }), encoding='utf-8')
                res_folder, res_host, _ = cr.read_pairing_result(res_file)
                self.assertEqual(res_folder.name, 'recovery-' + request_id)
                self.assertEqual(res_host, ' '.join(host_pub.split()[:2]))

            # Verify preparation_cache.legacy_record handles non-ASCII .pub comments & normalized authorized_keys2.
            src = (ROOT / 'tools/preparation_cache.py').read_text(encoding='utf-8')
            self.assertIn("encoding='utf-8', errors='replace'", src)
            self.assertIn('expected_keys', src)

    def test_powershell_bypass_and_driver_lock_decoupling(self):
        import prepare_usb_drivers
        import root_setup

        prep_src = (ROOT / 'tools/prepare_usb_drivers.py').read_text(encoding='utf-8')
        self.assertIn("'-ExecutionPolicy','Bypass'", prep_src)
        self.assertIn('_windows_powershell', prep_src)

        with tempfile.TemporaryDirectory() as tmp:
            fake_sys = Path(tmp)
            ps = fake_sys / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            ps.parent.mkdir(parents=True)
            ps.write_bytes(b'MZ')
            with patch.dict(os.environ, {'SystemRoot': str(fake_sys)}):
                self.assertEqual(prepare_usb_drivers._windows_powershell(), str(ps))

        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp) / 'private'
            private.mkdir()
            lock = private / 'root-flash.lock'
            lock.write_text(json.dumps({'pid': os.getpid(), 'kit': str(private / 'root-kit')}), encoding='utf-8')
            calls = []

            class DummyProc:
                returncode = 0

            def fake_run(cmd, **kwargs):
                calls.append(cmd)
                return DummyProc()

            with patch.object(root_setup, 'root_lock_path', return_value=lock), \
                    patch.object(root_setup, 'powershell', return_value='powershell.exe'), \
                    patch.object(root_setup.subprocess, 'run', side_effect=fake_run):
                result = root_setup.install_driver_kit(private / 'windows-usb')
            self.assertTrue(result['installed'])
            self.assertIn('-ExecutionPolicy', calls[0])
            self.assertIn('Bypass', calls[0])
            self.assertIn('-ExecutionPolicy Bypass', calls[0][-1])

            from preparation_cache import preparation_lock
            with patch.object(root_setup, 'root_lock_path', return_value=lock):
                with self.assertRaises(root_setup.SetupError) as ctx:
                    with preparation_lock(private, check_flash_lock=True):
                        pass
                self.assertEqual(str(ctx.exception), 'flash_state_unknown')
                with preparation_lock(private, check_flash_lock=False):
                    passed = True
                self.assertTrue(passed)


class FlashVisibilityAndLockRecoveryR55Tests(unittest.TestCase):
    def test_writing_started_detection_and_scrub_and_excerpt(self):
        import feedback
        import firmware_flash
        import root_flash

        ev_none = root_flash.RootFlashEvidence()
        ev_none.line('Connecting to bootrom:')
        ev_none.line('Timed out waiting for device')
        res_none = ev_none.result('os', 1)
        self.assertFalse(res_none['writing_started'])
        self.assertFalse(res_none['completed'])

        ev_started = root_flash.RootFlashEvidence()
        ev_started.line('Connecting to bootrom:')
        ev_started.line('Writing signed image: 12%')
        res_started = ev_started.result('os', 1)
        self.assertTrue(res_started['writing_started'])
        self.assertFalse(res_started['completed'])

        sev = firmware_flash.StockFlashEvidence()
        sev.line('[                  Writing  0x0092C044 ] [## 12 ##]')
        self.assertTrue(sev.result('stock', 1)['writing_started'])

        # Scrub keeps safe Chinese progress lines while stripping credential assignments.
        safe_line = '正在刷写系统。请保持 USB 连接，并按刷写窗口的密码提示操作。'
        self.assertEqual(feedback.scrub(safe_line), safe_line)
        self.assertEqual(feedback.scrub('密码：MySecret123'), '[credential removed]')
        self.assertEqual(feedback.scrub('密钥=abcdef'), '[credential removed]')
        self.assertEqual(feedback.scrub('password=mysecret'), '[credential removed]')

        with tempfile.TemporaryDirectory() as tmp:
            kit = Path(tmp)
            (kit / 'flash-os.json').write_text(json.dumps({
                'stage': 'os', 'exit_code': 1, 'writing_started': False,
                'writing_complete': False, 'done': False, 'error_seen': True, 'completed': False,
            }), encoding='utf-8')
            (kit / 'flash-os.log').write_text('Connecting to bootrom:\nError: timed out\n', encoding='utf-8')
            excerpt = feedback.flash_failure_excerpt(kit, prefix='flash', phase='os')
            self.assertIn('flash-os.json:', excerpt)
            self.assertIn('"writing_started": false', excerpt)
            self.assertIn('Connecting to bootrom:', excerpt)

    def test_inspect_and_clear_flash_lock_safety_and_audit(self):
        import root_setup

        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp) / 'private'
            kit = private / 'root-kit-abcdefabcdef'
            kit.mkdir(parents=True)
            lock = private / 'root-flash.lock'
            (kit / 'flash-os.log').write_text('Connecting to bootrom:\nError: failed\n', encoding='utf-8')
            # Legacy lock without flash-os.json (infers writing_started=False from log).
            lock.write_text(json.dumps({'pid': os.getpid(), 'kit': str(kit), 'token': 'tok1'}), encoding='utf-8')

            with patch.object(root_setup, 'private_root', return_value=private), \
                    patch.object(root_setup, 'root_lock_path', return_value=lock):
                info = root_setup.inspect_flash_lock()
                self.assertIsNotNone(info)
                self.assertFalse(info['process_running'])
                self.assertFalse(info['writing_started'])
                self.assertEqual(info['operation'], 'root-flash')
                self.assertIn('Connecting to bootrom:', info['excerpt'])

                with self.assertRaises(root_setup.SetupError) as ctx:
                    root_setup.clear_flash_lock(confirmed=False)
                self.assertEqual(str(ctx.exception), 'flash_confirmation_required')
                self.assertTrue(lock.exists())

                cleared = root_setup.clear_flash_lock(confirmed=True)
                self.assertTrue(cleared['cleared'])
                self.assertFalse(lock.exists())
                audit = json.loads((kit / 'flash-lock-cleared.json').read_text(encoding='utf-8'))
                self.assertTrue(audit['cleared_by_owner'])
                self.assertFalse(audit['writing_started'])
                self.assertTrue((kit / 'flash-os.log').is_file())

            # Refuses to clear if another live PID owns the lock.
            lock.write_text(json.dumps({'pid': os.getpid() + 9999, 'kit': str(kit), 'token': 'tok2'}), encoding='utf-8')
            with patch.object(root_setup, 'private_root', return_value=private), \
                    patch.object(root_setup, 'root_lock_path', return_value=lock), \
                    patch('preparation_cache.process_alive', return_value=True):
                info2 = root_setup.inspect_flash_lock()
                self.assertTrue(info2['process_running'])
                with self.assertRaises(root_setup.SetupError) as ctx:
                    root_setup.clear_flash_lock(confirmed=True)
                self.assertEqual(str(ctx.exception), 'flash_process_running')
                self.assertTrue(lock.exists())


class UiAndMiscR55Tests(unittest.TestCase):
    def test_auto_carrier_view_error_lte_wait_and_incall_caution(self):
        import auto_carrier_view
        view_err = auto_carrier_view.status_view({
            'enabled': True, 'phase': 'error', 'error_code': 'network_mode_rejected',
            'status_from_current_boot': True,
        })
        self.assertIn('network_mode_rejected', view_err['guidance'])
        self.assertIn('停用自动适配', view_err['guidance'])

        view_wait = auto_carrier_view.status_view({
            'enabled': True, 'phase': 'waiting_for_lte_and_usim',
            'status_from_current_boot': True, 'manager_alive': True,
        })
        self.assertIn('并非 IMS 失败', view_wait['guidance'])

        view_ok = auto_carrier_view.status_view({
            'enabled': True, 'phase': 'running', 'management_schema': 2,
            'current': {'ims': 'connected', 'register_status': '200 OK', 'ran': 'LTE', 'radio': ['lte']},
            'status_from_current_boot': True, 'manager_alive': True, 'native_alive': True,
            'selected_this_boot': True, 'current_sim_matches': True,
        })
        self.assertIn('移动网络', view_ok['guidance'])

    def test_device_support_legacy_error_message_and_kt_host_and_sha_retry(self):
        import device_support
        import i18n
        import kt_isim_trial
        import root_images

        self.assertIn('/var/rootdata/q10_volte', device_support.error_message('unvalidated_legacy_installation'))
        with patch.object(i18n, 'LANGUAGE', 'en'):
            self.assertIn('legacy VoLTE', device_support.error_message('unvalidated_legacy_installation'))

        src_kt = (ROOT / 'tools/kt_isim_trial.py').read_text(encoding='utf-8')
        self.assertIn("default='bb10-root'", src_kt)

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'sample.bin'
            p.write_bytes(b'hello-bb10')
            expected = hashlib.sha256(b'hello-bb10').hexdigest()
            attempts = {'n': 0}
            real_sha = root_images.sha

            def flaky_sha(path):
                attempts['n'] += 1
                if attempts['n'] < 3:
                    raise PermissionError('Defender lock')
                return real_sha(path)

            with patch.object(root_images, 'sha', side_effect=flaky_sha), \
                    patch.object(root_images.time, 'sleep'):
                self.assertEqual(root_images._sha_retry(p), expected)
            self.assertEqual(attempts['n'], 3)

    def test_gui_passport_note_points_to_auto_carriers(self):
        import gui
        self.assertIn('三网自动适配', gui.NOTES['passport_provider_lifecycle_unvalidated'])

    def test_setup_wizard_driver_enabled_and_flash_lock_bar_and_firmware_unlock(self):
        import firmware_gui
        import root_setup
        import setup_wizard
        try:
            import tkinter as tk
            root = tk.Tk()
        except Exception as error:
            self.skipTest(str(error))
        root.withdraw()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                private = Path(tmp) / 'private'
                private.mkdir()
                lock = private / 'root-flash.lock'
                lock.write_text(json.dumps({'pid': os.getpid(), 'kit': str(private / 'root-kit')}), encoding='utf-8')
                usb_online = {'usb_present': True, 'usb_network': True, 'usb_count': 1,
                              'device': {'ModelName': 'SQN100-3', 'PlatformVersion': '10.3.3.3216'}}
                with patch.object(setup_wizard, 'root_lock_path', return_value=lock), \
                        patch.object(root_setup, 'root_lock_path', return_value=lock), \
                        patch.object(setup_wizard, 'prepared_kit_history', return_value=[]), \
                        patch.object(root_setup, 'private_root', return_value=private):
                    wizard = setup_wizard.SetupWizard(root, lambda *_: None, auto_check=False, initial_usb=usb_online)
                    try:
                        wizard.refresh()
                        if sys.platform == 'win32':
                            self.assertEqual(str(wizard.driver_button['state']), 'normal')
                        self.assertTrue(bool(wizard.flash_lock_bar.winfo_manager()))
                        self.assertEqual(str(wizard.prepare_button['state']), 'disabled')
                        lock.unlink()
                        wizard.refresh()
                        self.assertFalse(bool(wizard.flash_lock_bar.winfo_manager()))
                    finally:
                        wizard.close()

                    lock.write_text(json.dumps({'pid': os.getpid(), 'kit': str(private / 'root-kit'),
                                                'operation': 'stock-upgrade'}), encoding='utf-8')
                    usb_old = {'usb_present': True, 'usb_network': True, 'usb_count': 1,
                               'device': {'ModelName': 'SQC100-1', 'PlatformVersion': '10.3.3.3057'}}
                    with patch.object(firmware_gui.upgrade, 'pending_upgrades', return_value=[]):
                        dlg = firmware_gui.FirmwareDialog(root, lambda *_: None, usb=usb_old)
                        try:
                            dlg.kit = str(private / 'root-kit')
                            dlg.stage = 'uncertain'
                            dlg.refresh()
                            self.assertTrue(bool(dlg.flash_lock_bar.winfo_manager()))
                            self.assertEqual(str(dlg.prepare_button['state']), 'disabled')
                            with patch.object(setup_wizard, 'review_flash_lock', side_effect=lambda *_: (lock.unlink(), True)[1]):
                                dlg.review_flash_lock()
                            self.assertIsNone(dlg.kit)
                            self.assertIsNone(dlg.stage)
                            self.assertFalse(bool(dlg.flash_lock_bar.winfo_manager()))
                            if sys.platform in ('win32', 'darwin'):
                                self.assertEqual(str(dlg.prepare_button['state']), 'normal')
                        finally:
                            dlg.close()
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
