"""First/return use, imported folders and interrupted onboarding; no phone access."""
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import connection
import connection_dialog as dialog_ui
import connection_flow as flow
import connection_materials as materials
import connection_recovery as recovery
import gui
import recovery_gui
import root_setup
import setup_wizard
from test_connection_recovery import rsa_public
from test_gui import report


class GuidanceTests(unittest.TestCase):
    def test_unknown_root_is_never_routed_to_flashing(self):
        cases = [({}, 'connection_setup_required', 'missing'),
                 ({'usb_present': False}, 'connection_setup_required', 'usb'),
                 ({'usb_present': True, 'usb_network': False}, 'connection_setup_required', 'network'),
                 ({}, 'connection_refused', 'service'), ({}, 'authentication_failed', 'authorization'),
                 ({}, 'host_key_mismatch', 'identity'), ({}, 'root_not_ready', 'root_pending'),
                 ({}, 'root_probe_failed', 'root_pending'), ({}, 'config_missing', 'missing'),
                 ({}, 'connection_timeout_state_unknown', 'offline'), ({'usb_count': 2}, None, 'multiple')]
        for usb, error, state in cases:
            with self.subTest(state=state):
                view = flow.guidance(usb, error)
                self.assertEqual(view.state, state)
                self.assertNotIn(view.action, ('root', 'flash'))
        self.assertEqual(flow.guidance({'usb_network': False}, 'authentication_failed').state, 'authorization')
        self.assertEqual(flow.guidance({'usb_network': False, 'device': {'ModelName': 'phone'}}, 'connection_setup_required').state, 'missing')


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def kit(self, folder=None, marker='a'):
        folder = folder or self.folder
        folder.mkdir(parents=True, exist_ok=True)
        # Not a key: import validation is independently tested with actual keygen.
        (folder / 'id_rsa4x').write_text('PRIVATE KEY fixture ' + marker)
        (folder / 'ssh_host_rsa_key.pub').write_text(rsa_public(2))

    def test_folder_import_ignores_foreign_absolute_config_paths_and_host_private_keys(self):
        self.kit()
        (self.folder / 'ssh_host_rsa_key').write_text('PRIVATE KEY host fixture')
        (self.folder / 'ssh_config').write_text('Host bb10-root\n IdentityFile /old-computer/id_rsa4x\n Match exec touch-marker\n')
        with patch('subprocess.run') as subprocess:
            found = materials.scan_materials(self.folder)
        self.assertEqual(found['state'], 'ready')
        self.assertEqual(found['identities'], [self.folder / 'id_rsa4x'])
        subprocess.assert_not_called()

    def test_duplicate_copies_are_ok_but_multiple_identities_require_narrower_folder(self):
        self.kit()
        self.kit(self.folder / 'backup')
        self.assertEqual(materials.scan_materials(self.folder)['state'], 'ready')
        self.kit(self.folder / 'another-phone', 'b')
        self.assertEqual(materials.scan_materials(self.folder)['state'], 'ambiguous')
        self.assertEqual(materials.scan_materials(self.folder / 'another-phone')['state'], 'ready')

    def test_missing_host_and_bounded_scan_do_not_select_incomplete_materials(self):
        self.kit()
        (self.folder / 'ssh_host_rsa_key.pub').unlink()
        self.assertEqual(materials.scan_materials(self.folder)['state'], 'host_missing')
        with patch.object(materials, 'MAX_ENTRIES', 0):
            self.assertEqual(materials.scan_materials(self.folder)['state'], 'limited')

    def test_multiple_phone_identities_are_not_chosen_by_file_date(self):
        self.kit()
        (self.folder / 'q10_host_rsa.pub').write_text(rsa_public(3))
        self.assertEqual(materials.scan_materials(self.folder)['state'], 'ambiguous')

    def test_linked_material_outside_selection_is_not_scanned(self):
        outside = self.folder / 'outside'
        self.kit(outside)
        selection = self.folder / 'selected'
        selection.mkdir()
        try:
            (selection / 'linked').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Creating symlinks is unavailable')
        self.assertEqual(materials.scan_materials(selection)['state'], 'empty')


class OnboardingGuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.private = Path(self.temp.name)
        for module in (connection, gui, recovery, root_setup):
            p = patch.object(module, 'private_root', return_value=self.private)
            p.start()
            self.addCleanup(p.stop)
        for module in (root_setup, setup_wizard):
            p = patch.object(module, 'root_lock_path', return_value=self.private / 'root-flash.lock')
            p.start()
            self.addCleanup(p.stop)
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def pending(self, request='abcdef123456', step=1):
        folder = self.private / ('recovery-' + request)
        folder.mkdir()
        (folder / 'identity').write_text('private fixture')
        (folder / 'identity.pub').write_text(rsa_public(1))
        script = folder / ('bb10-pair-' + request + '.py')
        script.write_text('# public pairing fixture')
        recovery.save_pairing_step(script, step)
        return script

    def test_first_launch_hides_config_and_opens_diagnostics_instead_of_file_picker(self):
        app = gui.App(self.root)
        self.assertFalse(app.config_entry.master.winfo_manager())
        self.assertEqual(app.check_button.cget('text'), '连接手机')
        with patch.object(app, 'setup') as setup, patch.object(app, 'run') as run:
            app.connect_phone()
        setup.assert_called_once_with()
        run.assert_not_called()
        self.root.after_cancel(app._drain_job)

    def test_saved_connection_reopens_with_one_read_only_check_and_no_install_permission(self):
        config = self.private / 'ssh_config'
        config.write_text('Host bb10-root\n')
        connection.save_connection('bb10-root', str(config))
        app = gui.App(self.root, auto_connect=True)
        self.root.after_cancel(app._startup_job)
        with patch.object(app, 'run') as run:
            app.resume_last_connection()
        run.assert_called_once_with('preflight')
        self.assertFalse(app.allowed_actions()['install'])
        self.assertIn('待重新验证', app.connection_status.cget('text'))
        self.root.after_cancel(app._drain_job)

    def test_moved_saved_config_is_retained_as_recoverable_history(self):
        config = self.private / 'moved-config'
        connection.save_connection('bb10-root', str(config))
        self.assertIsNone(connection.saved_connection())
        app = gui.App(self.root)
        self.assertEqual(app.config.get(), str(config))
        self.assertFalse(app.allowed_actions()['install'])
        self.root.after_cancel(app._drain_job)

    def test_non_root_report_does_not_replace_last_successful_connection(self):
        config = self.private / 'ssh_config'
        config.write_text('Host bb10-root\n')
        app = gui.App(self.root)
        app.config.set(str(config))
        value = report()
        value['checks'][1]['status'] = 'block'
        value.update(can_install=False)
        app.events.put(('result', ('preflight', {'preflight': value})))
        self.root.after_cancel(app._drain_job)
        app.drain()
        self.assertIsNone(connection.saved_connection())
        self.root.after_cancel(app._drain_job)

    def test_pending_authorization_survives_dialog_close_without_key_regeneration(self):
        script = self.pending(step=2)
        before = (script.parent / 'identity').read_bytes()
        with patch.object(recovery_gui, 'prepare_pairing') as generate:
            dialog = recovery_gui.RecoveryDialog(self.root, lambda *_: None)
            self.assertEqual(dialog.pair_script, script)
            self.assertEqual(dialog.pair_step, 2)
            dialog.set_step(3)
            dialog.close()
            again = recovery_gui.RecoveryDialog(self.root, lambda *_: None)
            self.assertEqual(again.pair_step, 3)
            again.close()
        generate.assert_not_called()
        self.assertEqual((script.parent / 'identity').read_bytes(), before)
        recovery.complete_pairing(script.parent / 'ssh_config')
        self.assertEqual(recovery.pending_pairings(), [])

    def test_multiple_pending_requests_require_explicit_selection(self):
        self.pending()
        self.pending('123456abcdef', step=3)
        dialog = recovery_gui.RecoveryDialog(self.root, lambda *_: None)
        try:
            self.assertIsNone(dialog.pair_script)
            self.assertEqual(dialog.resume_picker.current(), -1)
            self.assertEqual(str(dialog.step_next.cget('state')), 'disabled')
            dialog.resume_picker.current(1)
            dialog.resume_pairing()
            self.assertIsNotNone(dialog.pair_script)
        finally:
            dialog.close()

    def test_corrupt_progress_keeps_original_key_and_reopens_at_first_step(self):
        script = self.pending(step=2)
        (script.parent / 'pairing-progress.json').write_text('[]')
        self.assertEqual(recovery.pending_pairings(), [{'script': script, 'step': 1}])

    def test_saving_failure_is_visible_after_successful_preflight(self):
        app = gui.App(self.root)
        app.events.put(('result', ('preflight', {'preflight': report()})))
        self.root.after_cancel(app._drain_job)
        with patch.object(gui, 'save_connection', side_effect=OSError):
            app.drain()
        self.assertIn('未能保存', app.connection_status.cget('text'))
        self.root.after_cancel(app._drain_job)

    def test_multiple_usb_devices_prevent_any_authentication_attempt(self):
        dialog = dialog_ui.ConnectionDialog(self.root, lambda *_: None, auto_check=False)
        with patch.object(dialog_ui, 'local_usb_state', return_value={'usb_count': 2}), \
                patch.object(dialog_ui, 'verify_root') as verify, \
                patch.object(dialog_ui.threading, 'Thread', side_effect=lambda target, **_: SimpleNamespace(start=target)):
            dialog.detect()
            dialog.after_cancel(dialog._job)
            dialog.drain()
        verify.assert_not_called()
        self.assertIn('只连接一台', dialog.title_label.cget('text'))
        self.assertEqual(str(dialog.continue_button.cget('state')), 'disabled')
        dialog.close()

    def test_unknown_root_does_not_open_first_root_without_explicit_choice(self):
        dialog = dialog_ui.ConnectionDialog(self.root, lambda *_: None, auto_check=False)
        with patch.object(dialog, 'open_setup') as open_setup, patch.object(dialog_ui.messagebox, 'askokcancel', return_value=False):
            dialog.root_options()
            open_setup.assert_not_called()
            dialog.first_root()
            open_setup.assert_not_called()
        dialog.close()

    def test_root_history_resume_does_not_flash_and_uncertain_state_stays_blocked(self):
        folder = self.private / 'root-kit-example'
        folder.mkdir()
        journal = folder / 'setup-state.json'
        journal.write_text(json.dumps({'variant': 'SQN100-3', 'stage': 'os_uncertain'}))
        wizard = setup_wizard.SetupWizard(self.root, lambda *_: None, auto_check=False, initial_page='root')
        try:
            wizard.kit = 'an earlier selection'
            wizard.ack.set(True)
            with patch.object(wizard, 'start') as start, patch.object(setup_wizard, 'flash_root') as flash:
                wizard.resume_preparation()
            start.assert_not_called()
            flash.assert_not_called()
            self.assertIn('不要重复刷写', wizard.status.cget('text'))
            self.assertIsNone(wizard.kit)
        finally:
            wizard.close()

    def test_prepared_images_resume_requires_revalidation_and_fresh_confirmation(self):
        folder = self.private / 'root-kit-example'
        folder.mkdir()
        (folder / 'setup-state.json').write_text(json.dumps({'variant': 'SQN100-3', 'stage': 'prepared', 'platform': sys.platform}))
        wizard = setup_wizard.SetupWizard(self.root, lambda *_: None, auto_check=False, initial_page='root')
        try:
            wizard.ack.set(True)
            with patch.object(setup_wizard, 'prepared_images', return_value=({}, [])) as verify, \
                    patch.object(setup_wizard, 'flash_root') as flash, \
                    patch.object(setup_wizard.threading, 'Thread', side_effect=lambda target, **_: SimpleNamespace(start=target)):
                wizard.resume_preparation()
                wizard.after_cancel(wizard._job)
                wizard.drain()
            verify.assert_called_once_with(str(folder))
            flash.assert_not_called()
            self.assertEqual(wizard.kit, str(folder))
            self.assertFalse(wizard.ack.get())
            self.assertEqual(str(wizard.flash_button.cget('state')), 'disabled')
        finally:
            wizard.close()

    def test_pairing_step_controls_fit_both_platform_layouts(self):
        self.pending(step=2)
        for platform in ('win32', 'darwin'):
            with self.subTest(platform=platform), patch.object(sys, 'platform', platform):
                dialog = recovery_gui.RecoveryDialog(self.root, lambda *_: None)
                try:
                    dialog.attributes('-alpha', 0.0)
                    dialog.geometry('820x690')
                    self.root.attributes('-alpha', 0.0)
                    self.root.deiconify()
                    dialog.deiconify()
                    self.root.update()
                    for widget in (dialog.step_next, dialog.result_button, dialog.continue_button, dialog.status):
                        self.assertGreater(widget.winfo_width(), 1)
                        self.assertLessEqual(widget.winfo_rootx() - dialog.winfo_rootx() + widget.winfo_width(), dialog.winfo_width())
                        self.assertLessEqual(widget.winfo_rooty() - dialog.winfo_rooty() + widget.winfo_height(), dialog.winfo_height())
                finally:
                    dialog.close()

    def test_connection_choices_and_footer_fit_minimum_window(self):
        dialog = dialog_ui.ConnectionDialog(self.root, lambda *_: None, auto_check=False)
        dialog.attributes('-alpha', 0.0)
        self.root.attributes('-alpha', 0.0)
        dialog.geometry('700x580')
        self.root.deiconify()
        dialog.deiconify()
        self.root.update()
        for widget in (dialog.close_button, dialog.continue_button, dialog.retry_button, dialog.back_button):
            self.assertLessEqual(widget.winfo_rooty() - dialog.winfo_rooty() + widget.winfo_height(), dialog.winfo_height())
            self.assertGreater(widget.winfo_width(), 1)
        dialog.close()


if __name__ == '__main__':
    unittest.main()
