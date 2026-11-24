"""Regression tests for v0.5.0-r56 / 0.2.2.0 root-cause fixes."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for rel in ('device', 'tools', 'mobile/runtime'):
    p = str(ROOT / rel)
    if p not in sys.path:
        sys.path.insert(0, p)


class DeviceEngineR56Tests(unittest.TestCase):
    def _make_legacy_q10_dir(self, root_dir):
        q10 = Path(root_dir) / 'q10_volte'
        q10.mkdir(parents=True)
        files = {}
        for name, body in (('manager.py', b'print("ok")\n'), ('service.py', b'x = 1\n')):
            target = q10 / name
            target.write_bytes(body)
            files[name] = hashlib.sha256(body).hexdigest()
        (q10 / 'installation.json').write_text(json.dumps({
            'owner': 'q10-unicom-volte-v1',
            'files': files,
        }), encoding='utf-8')
        return q10

    def test_verified_q10_volte_migrates_automatically_on_all_catalog_models(self):
        import unified_migrate as mig
        with tempfile.TemporaryDirectory() as tmp:
            q10 = self._make_legacy_q10_dir(tmp)
            root_done = Path(tmp) / 'root.done'
            root_done.write_text('ok', encoding='utf-8')
            fake_bases = {'SQN100-3': str(q10), 'SQC100-2': str(Path(tmp) / 'q20_volte'),
                          'SQW100-4': str(Path(tmp) / 'passport_volte_research')}
            real_isfile = os.path.isfile
            def fake_isfile(path):
                return True if path == '/tmp/root.done' else real_isfile(path)
            for variant in ('SQN100-3', 'SQC100-1', 'SQK100-1', 'SQW100-1', 'SQW100-4'):
                with patch.object(mig, 'STANDARD_BASE', str(q10)), \
                        patch.object(mig, 'BASES', fake_bases), \
                        patch.object(mig, 'legacy_boot', return_value=[1, 2]), \
                        patch.object(mig.n, 'read', side_effect=lambda p: Path(p).read_bytes()), \
                        patch.object(mig.os.path, 'isfile', side_effect=fake_isfile), \
                        patch.object(mig.s, 'alive', return_value=False):
                    info = mig.inspect({'variant': variant})
                self.assertEqual(info['base'], str(q10), variant)
                self.assertEqual(info['manifest'], 'installation.json', variant)
                self.assertEqual(info['boot'], [1, 2], variant)

    def test_legacy_migration_rejects_foreign_dirs_collisions_tx_trial_tamper_and_passport_lock(self):
        import unified_migrate as mig
        with tempfile.TemporaryDirectory() as tmp:
            q20 = Path(tmp) / 'q20_volte'
            q20.mkdir()
            fake_bases = {'SQN100-3': str(Path(tmp) / 'q10_volte'), 'SQC100-2': str(q20),
                          'SQW100-4': str(Path(tmp) / 'passport_volte_research')}
            real_isfile = os.path.isfile
            def fake_isfile(path):
                return True if path == '/tmp/root.done' else real_isfile(path)

            # Foreign q20_volte on SQC100-1 must fail closed.
            with patch.object(mig, 'STANDARD_BASE', str(Path(tmp) / 'q10_volte')), \
                    patch.object(mig, 'BASES', fake_bases), \
                    patch.object(mig, 'legacy_boot', return_value=[1, 2]), \
                    patch.object(mig.n, 'read', side_effect=lambda p: Path(p).read_bytes()), \
                    patch.object(mig.os.path, 'isfile', side_effect=fake_isfile):
                with self.assertRaisesRegex(AssertionError, 'unvalidated_legacy_installation'):
                    mig.inspect({'variant': 'SQC100-1'})

            # Multi-dir collision (both q10_volte and q20_volte present on SQC100-2) must fail closed.
            q10 = self._make_legacy_q10_dir(tmp)
            with patch.object(mig, 'STANDARD_BASE', str(q10)), \
                    patch.object(mig, 'BASES', fake_bases), \
                    patch.object(mig, 'legacy_boot', return_value=[1, 2]), \
                    patch.object(mig.n, 'read', side_effect=lambda p: Path(p).read_bytes()), \
                    patch.object(mig.os.path, 'isfile', side_effect=fake_isfile):
                with self.assertRaisesRegex(AssertionError, 'unvalidated_legacy_installation'):
                    mig.inspect({'variant': 'SQC100-2'})
            q20.rmdir()

            # Interrupted install transaction -> legacy_install_interrupted.
            (q10 / 'install-transaction.json').write_text('{}', encoding='utf-8')
            with patch.object(mig, 'STANDARD_BASE', str(q10)), \
                    patch.object(mig, 'BASES', fake_bases), \
                    patch.object(mig, 'legacy_boot', return_value=[1, 2]), \
                    patch.object(mig.n, 'read', side_effect=lambda p: Path(p).read_bytes()), \
                    patch.object(mig.os.path, 'isfile', side_effect=fake_isfile):
                with self.assertRaisesRegex(AssertionError, 'legacy_install_interrupted'):
                    mig.inspect({'variant': 'SQC100-1'})
            (q10 / 'install-transaction.json').unlink()

            # Unfinished nas_voice_trial -> unfinished_nas_trial.
            state_dir = q10 / 'state'
            state_dir.mkdir(exist_ok=True)
            (state_dir / 'journal.json').write_text(json.dumps({
                'owner': 'q10-unicom-volte-v1', 'original_voice_policy': 0, 'nas_voice_trial': True,
            }), encoding='utf-8')
            with patch.object(mig, 'STANDARD_BASE', str(q10)), \
                    patch.object(mig, 'BASES', fake_bases), \
                    patch.object(mig, 'legacy_boot', return_value=[1, 2]), \
                    patch.object(mig.n, 'read', side_effect=lambda p: Path(p).read_bytes()), \
                    patch.object(mig.os.path, 'isfile', side_effect=fake_isfile):
                with self.assertRaisesRegex(AssertionError, 'unfinished_nas_trial'):
                    mig.inspect({'variant': 'SQC100-1'})
            (state_dir / 'journal.json').unlink()

            # Live Passport lock.json -> unvalidated_legacy_installation (never quiesce live legacy on Passport).
            (state_dir / 'lock.json').write_text(json.dumps({'boot': [1, 2], 'pid': os.getpid()}), encoding='utf-8')
            with patch.object(mig, 'STANDARD_BASE', str(q10)), \
                    patch.object(mig, 'BASES', fake_bases), \
                    patch.object(mig, 'legacy_boot', return_value=[1, 2]), \
                    patch.object(mig.n, 'read', side_effect=lambda p: Path(p).read_bytes()), \
                    patch.object(mig.os.path, 'isfile', side_effect=fake_isfile), \
                    patch.object(mig.s, 'alive', return_value=True):
                with self.assertRaisesRegex(AssertionError, 'unvalidated_legacy_installation'):
                    mig.inspect({'variant': 'SQW100-1'})
            (state_dir / 'lock.json').unlink()

            # Tampered file -> legacy_payload_changed.
            (q10 / 'manager.py').write_bytes(b'corrupted')
            with patch.object(mig, 'STANDARD_BASE', str(q10)), \
                    patch.object(mig, 'BASES', fake_bases), \
                    patch.object(mig, 'legacy_boot', return_value=[1, 2]), \
                    patch.object(mig.n, 'read', side_effect=lambda p: Path(p).read_bytes()), \
                    patch.object(mig.os.path, 'isfile', side_effect=fake_isfile), \
                    patch.object(mig.s, 'alive', return_value=False):
                with self.assertRaisesRegex(AssertionError, 'legacy_payload_changed'):
                    mig.inspect({'variant': 'SQC100-1'})

    def test_unified_install_probe_catches_new_codes_and_cleanup_stage_guards(self):
        import unified_install as ui
        fake_facts = {'variant': 'SQC100-1', 'board': 'CLASSICROW', 'os_version': '10.3.3.3216'}
        for code in ('root_addon_directory_changed', 'legacy_install_interrupted'):
            with patch.object(ui.os, 'geteuid', return_value=0, create=True), \
                    patch.object(ui.os, 'uname', return_value=('QNX',), create=True), \
                    patch.object(ui.ctypes, 'sizeof', return_value=4), \
                    patch.object(ui.device_info, 'read_identity', return_value=fake_facts), \
                    patch.object(ui.policy, 'model', return_value='q20'), \
                    patch.object(ui, 'identity', return_value=(fake_facts, 'q20')), \
                    patch.object(ui, 'installed_management_schema', return_value=0), \
                    patch.object(ui.s, 'phone_idle', return_value=True), \
                    patch.object(ui, 'root_kind', return_value='autoroot_v4'), \
                    patch.object(ui.migration, 'inspect', side_effect=AssertionError(code)), \
                    patch.object(ui.os.path, 'isfile', return_value=False):
                res = ui.probe()
            self.assertEqual(res['scope_error'], code)
            self.assertFalse(res['can_install'])

        # cleanup_stage rejects non-string or unexpected directory structures.
        with self.assertRaises(AssertionError):
            ui.cleanup_stage(None)
        with self.assertRaises(AssertionError):
            ui.cleanup_stage('/tmp/other-dir')
        with patch.object(ui.os, 'geteuid', return_value=1000, create=True):
            with self.assertRaisesRegex(AssertionError, 'root_required'):
                ui.cleanup_stage('/var/bb10_auto_stage_1234567890ab')

    def test_dca_restore_original_and_network_lock_always_restore_lte_mode(self):
        import unified_dca as dca
        calls = []

        def fake_set_usage(val, sel):
            calls.append(('set_usage', val))
            raise RuntimeError('usage_failed')

        def fake_restore_sel(**kwargs):
            calls.append(('restore_sel', kwargs))
            raise RuntimeError('sel_failed')

        def fake_restore_lte():
            calls.append(('restore_lte',))

        with patch.object(dca, 'set_usage', side_effect=fake_set_usage), \
                patch.object(dca, 'restore_network_selection', side_effect=fake_restore_sel), \
                patch.object(dca, 'restore_lte_mode', side_effect=fake_restore_lte):
            with self.assertRaisesRegex(RuntimeError, 'usage_failed'):
                dca.restore_original()
        self.assertEqual([c[0] for c in calls], ['set_usage', 'restore_sel', 'restore_lte'])

    def test_service_restore_and_reconcile_never_strand_lte_only(self):
        import unified_service as svc
        import unified_dca as dca
        lte_restored = []
        sel_restored = []

        orig_j = svc.s.j
        orig_base = svc.s.BASE
        try:
            svc.s.BASE = svc.BASE
            svc.s.j = {
                'owner': 'q10-unicom-volte-v1',
                'original_voice_policy': 0,
                'boot': 'boot-1',
                'crypto_boot': 'boot-1',
                'provider': 0,
                'pps_before': {},
            }
            with patch.object(svc, 'boot_token', return_value='boot-1'), \
                    patch.object(svc.s, 'close_berry_indicator'), \
                    patch.object(svc.s, 'phone_idle', return_value=True), \
                    patch.object(svc.s, 'stop_native'), \
                    patch.object(svc.s, 'applied_updates', return_value={}), \
                    patch.object(svc.s, 'remove_owned'), \
                    patch.object(svc.s, 'remove_platform'), \
                    patch.object(svc.s, 'save_journal'), \
                    patch.object(svc.s, 'status'), \
                    patch.object(svc.n, 'crypto_policy', return_value={'swcr_id': 0, 'crypto_support': 1}), \
                    patch.object(svc.n, 'voice_policy', return_value=0), \
                    patch.object(svc.os.path, 'isfile', return_value=True), \
                    patch.object(svc.time, 'sleep'), \
                    patch.object(dca, 'restore_network_selection', side_effect=lambda: sel_restored.append(1)), \
                    patch.object(dca, 'restore_lte_mode', side_effect=lambda: lte_restored.append(1)):
                svc.restore(previous_boot=False)
            self.assertEqual(len(sel_restored), 1)
            self.assertEqual(len(lte_restored), 1)

            # Even if restore() aborts mid-way (e.g. remove_platform raises), finally rescues LTE + selection!
            lte_restored.clear()
            sel_restored.clear()
            svc.s.j = {
                'owner': 'q10-unicom-volte-v1',
                'original_voice_policy': 0,
                'boot': 'boot-1',
                'pps_before': {},
            }
            with patch.object(svc, 'boot_token', return_value='boot-1'), \
                    patch.object(svc.s, 'close_berry_indicator'), \
                    patch.object(svc.s, 'phone_idle', return_value=True), \
                    patch.object(svc.s, 'stop_native'), \
                    patch.object(svc.s, 'applied_updates', return_value={}), \
                    patch.object(svc.s, 'remove_owned'), \
                    patch.object(svc.s, 'remove_platform', side_effect=RuntimeError('platform_stuck')), \
                    patch.object(svc.n, 'ims_pids', return_value=[]), \
                    patch.object(svc.n, 'active_vpn_sessions', return_value=[]), \
                    patch.object(dca, 'restore_network_selection', side_effect=lambda: sel_restored.append(1)), \
                    patch.object(dca, 'restore_lte_mode', side_effect=lambda: lte_restored.append(1)):
                with self.assertRaisesRegex(RuntimeError, 'platform_stuck'):
                    svc.restore(previous_boot=False)
            self.assertEqual(len(sel_restored), 1)
            self.assertEqual(len(lte_restored), 1)

            # reconcile() always clears s.j in finally even if restore() fails.
            with patch.object(svc.os.path, 'isfile', return_value=True), \
                    patch.object(svc.s, 'load', return_value={'boot': 'boot-0', 'owner': 'q10-unicom-volte-v1'}), \
                    patch.object(svc, 'boot_token', return_value='boot-1'), \
                    patch.object(svc, 'restore', side_effect=RuntimeError('cleanup_boom')):
                with self.assertRaisesRegex(RuntimeError, 'cleanup_boom'):
                    svc.reconcile()
            self.assertIsNone(svc.s.j)
        finally:
            svc.s.j = orig_j
            svc.s.BASE = orig_base

    def test_classify_status_error_covers_scan_mode_and_new_codes(self):
        import unified_service as svc
        for raw, expected in (
            ('scan_mode_rejected', 'scan_mode_rejected'),
            ('network_mode_rejected', 'network_mode_rejected'),
            ('Timeout: dedicated IMS APN did not appear', 'ims_apn_timeout'),
            ('Initial modem policy is not the tested original00', 'voice_policy_failed'),
            ('usage_readback_failed', 'usage_readback_failed'),
            ('Existing software crypto provider', 'existing_crypto_provider'),
            ('Stop an existing VPN before starting', 'vpn_active'),
            ('Owned IMS APN file changed externally', 'owned_file_changed'),
            ('random unknown message', 'internal_error'),
            ('', None),
        ):
            self.assertEqual(svc.classify_status_error(raw), expected, raw)

    def test_mobile_worker_surfaces_cleanup_required_even_when_disabled(self):
        import worker
        result = {
            'installed': True,
            'installed_stage': 'managed',
            'installed_management_schema': 2,
            'sim_supported': True,
            'status': {
                'enabled': False,
                'status_from_current_boot': True,
                'phase': 'cleanup_required',
                'error_code': 'ims_apn_timeout',
            },
        }
        resp = worker.inspection_response({'language': 'zh'}, result, {'model': 'SQC100-2'})
        self.assertEqual(resp['state'], 'recovery_required')
        self.assertEqual(resp['details']['error_code'], 'ims_apn_timeout')


class WindowsFlashDriverR56Tests(unittest.TestCase):
    def test_install_usb_drivers_ps1_handles_pnputil_259_msi_1638_and_result_json(self):
        ps1 = (ROOT / 'tools/install_usb_drivers.ps1').read_text(encoding='utf-8')
        self.assertIn('259', ps1)
        self.assertIn('1638', ps1)
        self.assertIn('driver-install-result.json', ps1)
        self.assertIn('-Encoding UTF8', ps1)
        self.assertIn('/add-driver', ps1)

    def test_install_driver_kit_uac_cancel_and_blocked_process(self):
        import root_setup
        with tempfile.TemporaryDirectory() as tmp:
            kit = Path(tmp) / 'drivers'
            kit.mkdir()
            (kit / 'driver-install-result.json').write_text(json.dumps({
                'ok': False,
                'blocked_process': 'RimDeviceManager',
                'error_message': 'running process blocked',
            }), encoding='utf-8')
            with patch.object(root_setup, 'powershell', return_value='powershell.exe'), \
                    patch.object(root_setup.subprocess, 'run',
                                 return_value=subprocess.CompletedProcess(['ps'], 1, '', '')):
                with self.assertRaises(root_setup.SetupError) as ctx:
                    root_setup.install_driver_kit(kit)
            self.assertEqual(str(ctx.exception), 'driver_process_running')
            self.assertIn('blocked_process', getattr(ctx.exception, 'feedback_log', ''))

            # UAC cancelled -> exit 1223 -> driver_uac_cancelled.
            (kit / 'driver-install-result.json').unlink()
            with patch.object(root_setup, 'powershell', return_value='powershell.exe'), \
                    patch.object(root_setup.subprocess, 'run',
                                 return_value=subprocess.CompletedProcess(['ps'], 1223, '', '')):
                with self.assertRaises(root_setup.SetupError) as ctx2:
                    root_setup.install_driver_kit(kit)
            self.assertEqual(str(ctx2.exception), 'driver_uac_cancelled')

    def test_root_flash_ansi_check_status_prefix_and_launch_error_json(self):
        import root_flash as rf
        import firmware_flash as ff
        with patch.object(rf.sys, 'platform', 'win32'):
            self.assertTrue(rf._is_ansi_safe_path(r'C:\work\ascii-dir\bb10-volte'))
            self.assertFalse(rf._is_ansi_safe_path(r'C:\work\中文目录\bb10-volte'))
        self.assertEqual(rf.status_prefix(b'Connecting to Bootrom: '), 'Connecting to Bootrom:')
        self.assertEqual(rf.status_prefix(b'Resetting Device: '), 'Resetting Device:')
        self.assertTrue(rf.password_prompt(b'Please enter device password: '))
        self.assertIs(ff.run_windows_autoloader, rf.run_windows_autoloader)

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            image = folder / 'missing.exe'
            image.write_bytes(b'MZ')
            log_path = folder / 'flash.log'
            with log_path.open('w', encoding='utf-8') as log_file, \
                    patch.object(rf.subprocess, 'Popen', side_effect=PermissionError(13, 'Blocked by AV')):
                ev = rf.RootFlashEvidence()
                res = rf.run_windows_autoloader(image, folder, log_file, ev, lambda line: line, 'os')
            self.assertEqual(res['exit_code'], -1)
            self.assertFalse(res['completed'])
            self.assertTrue(res['error_seen'])
            self.assertTrue(res['launch_error'].startswith('os_error_'))
            self.assertIn('Autoloader launch failed', log_path.read_text(encoding='utf-8'))

    def test_feedback_scrub_preserves_safe_markers_and_redacts_secrets(self):
        import feedback
        sample = (
            '[Device password input requested in native console]\n'
            '[Bootrom device unlock prompt shown in console]\n'
            'Password: super-secret-value\n'
            'Connecting to Bootrom:\n'
        )
        scrubbed = feedback.scrub(sample)
        self.assertIn('[Device password input requested in native console]', scrubbed)
        self.assertIn('[Bootrom device unlock prompt shown in console]', scrubbed)
        self.assertNotIn('super-secret-value', scrubbed)
        self.assertIn('[credential removed]', scrubbed)

    def test_inspect_flash_lock_stage2_preserves_stage1_write_and_missing_receipt_is_unknown(self):
        import root_setup
        import preparation_cache
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp) / 'private'
            kit = private / 'root-kit'
            kit.mkdir(parents=True)
            lock = private / 'root-flash.lock'
            lock.write_text(json.dumps({
                'pid': 999999, 'pid_created_at': 12345, 'kit': str(kit), 'operation': 'root-flash',
            }), encoding='utf-8')
            # Stage 1 OS wrote to device, Stage 2 radio failed before writing -> overall writing_started MUST be True!
            (kit / 'flash-os.json').write_text(json.dumps({
                'phase': 'os', 'exit_code': 73, 'writing_started': True, 'completed': False,
            }), encoding='utf-8')
            (kit / 'flash-radio.json').write_text(json.dumps({
                'phase': 'radio', 'exit_code': 1, 'writing_started': False, 'completed': False,
            }), encoding='utf-8')
            (kit / 'flash-radio.log').write_text('Connecting to Bootrom:\nError: timed out\n', encoding='utf-8')
            with patch.object(root_setup, 'root_lock_path', return_value=lock), \
                    patch.object(root_setup, 'private_root', return_value=private), \
                    patch.object(preparation_cache, 'process_matches', return_value=False):
                info = root_setup.inspect_flash_lock()
            self.assertIsNotNone(info)
            self.assertTrue(info['writing_started'])
            self.assertEqual(info['failed_phase'], 'radio')

            # Missing JSON receipt + log with no write line -> writing_started MUST be None (unknown), NOT False!
            (kit / 'flash-os.json').unlink()
            (kit / 'flash-radio.json').unlink()
            with patch.object(root_setup, 'root_lock_path', return_value=lock), \
                    patch.object(root_setup, 'private_root', return_value=private), \
                    patch.object(preparation_cache, 'process_matches', return_value=False):
                info2 = root_setup.inspect_flash_lock()
            self.assertIsNone(info2['writing_started'])

            # Active child file with matching live PID reports process_running=True.
            (kit / 'flash-active.json').write_text(json.dumps({
                'pid': os.getpid(), 'created_at': preparation_cache.process_creation_time(os.getpid()), 'phase': 'os',
            }), encoding='utf-8')
            with patch.object(root_setup, 'root_lock_path', return_value=lock), \
                    patch.object(root_setup, 'private_root', return_value=private), \
                    patch.object(preparation_cache, 'process_matches', side_effect=lambda p, c=None: p == os.getpid()):
                info3 = root_setup.inspect_flash_lock()
            self.assertTrue(info3['process_running'])

            # Sibling non-root-kit path rejected by _lock_kit_dir.
            feedback_dir = private / 'feedback'
            feedback_dir.mkdir()
            with patch.object(root_setup, 'private_root', return_value=private):
                self.assertIsNone(root_setup._lock_kit_dir({'kit': str(feedback_dir)}))

    def test_restrict_windows_acl_uses_ascii_sid(self):
        import preparation_cache as pc
        captured = {}

        def fake_run(cmd, **kwargs):
            captured['cmd'] = cmd
            return subprocess.CompletedProcess(cmd, 0, '', '')

        with patch.object(pc.os, 'name', 'nt'), \
                patch.object(pc, 'windows_user_sid', return_value='S-1-5-21-100-200-300-1001'), \
                patch.object(pc.subprocess, 'run', side_effect=fake_run):
            pc.restrict_windows_acl(Path('C:/tmp/test'), directory=True)
        cmd = captured['cmd']
        self.assertIn('*S-1-5-21-100-200-300-1001:(OI)(CI)F', cmd)
        self.assertIn('*S-1-5-18:(OI)(CI)F', cmd)


class DesktopUxR56Tests(unittest.TestCase):
    def test_auto_carrier_view_shows_error_code_on_pre_native_retry(self):
        import auto_carrier_view as view
        res = view.status_view({
            'enabled': True,
            'status_from_current_boot': True,
            'phase': 'error_restored',
            'pre_native_retry_available': True,
            'error_code': 'scan_mode_rejected',
        })
        self.assertIn('scan_mode_rejected', res['guidance'])

    def test_gui_passport_open_cta_and_unified_error_disable_and_auto_carrier_error_preservation(self):
        import auto_carrier_gui
        import firmware_gui
        import feedback_gui
        import gui
        import mobile_app_gui
        import root_setup
        try:
            import tkinter as tk
            root = tk.Tk()
        except Exception as error:
            self.skipTest(str(error))
        root.withdraw()
        try:
            # 1. AutoCarrierWindow preserves error & error_code even when sim_not_ready scope_note fires.
            win = auto_carrier_gui.AutoCarrierWindow(root, 'bb10-root', '')
            try:
                win.events.put(('probe', {
                    'variant': 'SQC100-2',
                    'installed': True,
                    'sim_supported': False,
                    'sim_reason': 'sim_not_ready',
                    'status': {
                        'enabled': True,
                        'status_from_current_boot': True,
                        'phase': 'error',
                        'error_code': 'network_mode_rejected',
                    },
                }, None))
                win.window.after_cancel(win.poll_job)
                win.poll()
                details = win.details.get('1.0', 'end-1c')
                self.assertIn('network_mode_rejected', details)
                self.assertIn('停用自动适配', details)
                self.assertIn('SIM', details)
            finally:
                win.close()

            # 2. Main GUI uninstalled open-model Passport gets direct auto_carrier CTA.
            app = gui.App(root, auto_connect=False)
            try:
                passport_absent = {
                    'outcome': 'needs_adaptation',
                    'can_install': False, 'can_update': False, 'can_start': False, 'can_restore': False,
                    'device': {'display_name': 'BlackBerry Passport', 'variant': 'SQW100-1',
                               'os_version': '10.3.3.3216', 'recognized': True, 'hardware_tested': False},
                    'installation': {'state': 'absent'},
                    'checks': [
                        {'id': 'root', 'status': 'pass', 'code': 'root_qnx_arm32_required'},
                        {'id': 'provider_lifecycle', 'status': 'adapt', 'code': 'passport_provider_lifecycle_unvalidated'},
                    ],
                }
                app.render_report(passport_absent)
                self.assertEqual(app.primary_action, 'auto_carrier')
                self.assertIn('打开三网自动适配', app.primary_button.cget('text'))
                self.assertEqual(str(app.primary_button.cget('state')), 'normal')
                self.assertFalse(app.experiment_check.winfo_manager())

                # Unified error state exposes direct '停用自动适配' primary button without requiring ack.
                unified_err = {
                    'outcome': 'compatible',
                    'managed_adapter': 'unified_carriers',
                    'can_install': False, 'can_update': False, 'can_start': False, 'can_restore': True,
                    'device': {'display_name': 'BlackBerry Classic', 'variant': 'SQC100-2',
                               'os_version': '10.3.3.3216', 'recognized': True, 'hardware_tested': True},
                    'installation': {'state': 'busy', 'enabled': True},
                    'status': {'enabled': True, 'status_from_current_boot': True, 'phase': 'error',
                               'error_code': 'network_mode_rejected'},
                    'checks': [{'id': 'root', 'status': 'pass', 'code': 'root_qnx_arm32_required'}],
                }
                app.render_report(unified_err, unified_err['status'])
                self.assertEqual(app.primary_action, 'disable')
                self.assertIn('停用自动适配', app.primary_button.cget('text'))
                self.assertEqual(str(app.primary_button.cget('state')), 'normal')
                self.assertTrue(app.allowed_actions()['disable'])
            finally:
                app.close()

            # 3. MobileAppInstallWindow has help_row feedback button & FeedbackDialog reads tk.Text.
            root2 = tk.Tk()
            root2.withdraw()
            try:
                mwin = mobile_app_gui.MobileAppInstallWindow(root2, 'bb10-root', '')
                try:
                    def walk_texts(widget):
                        out = []
                        for child in widget.winfo_children():
                            try:
                                out.append(str(child.cget('text')))
                            except Exception:
                                pass
                            out.extend(walk_texts(child))
                        return out
                    self.assertTrue(any('反馈' in t or 'Feedback' in t for t in walk_texts(mwin.window)))
                finally:
                    mwin.close()

                # FeedbackDialog extracts tk.Text content safely.
                t = tk.Text(root2)
                t.insert('1.0', 'diagnostic-error-sample')
                root2._feedback_status_labels = [t]
                dlg = feedback_gui.FeedbackDialog(root2, 'install')
                try:
                    preview = dlg.content.get('1.0', 'end-1c')
                    self.assertIn('diagnostic-error-sample', preview)
                finally:
                    dlg.close()

                # FirmwareDialog exposes Windows driver button & Bootrom warning.
                with tempfile.TemporaryDirectory() as tmp:
                    lock = Path(tmp) / 'root-flash.lock'
                    lock.write_text(json.dumps({'pid': os.getpid(), 'kit': str(Path(tmp) / 'root-kit')}), encoding='utf-8')
                    usb_old = {'usb_present': True, 'usb_network': True, 'usb_count': 1,
                               'bootrom_driver_ready': False,
                               'device': {'ModelName': 'SQC100-1', 'PlatformVersion': '10.3.3.3057'}}
                    with patch.object(root_setup, 'root_lock_path', return_value=lock), \
                            patch.object(firmware_gui.upgrade, 'pending_upgrades', return_value=[]):
                        fdlg = firmware_gui.FirmwareDialog(root2, lambda *_: None, usb=usb_old)
                        try:
                            if sys.platform == 'win32':
                                self.assertIsNotNone(fdlg.install_drivers_lock_button)
                                self.assertIsNotNone(fdlg.drivers_button)
                                self.assertIn('RimUsb', fdlg.facts.cget('text'))
                        finally:
                            fdlg.close()
            finally:
                root2.destroy()
        finally:
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == '__main__':
    unittest.main()
