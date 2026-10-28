"""Desktop presentation and action gates; no transport or phone operations."""
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import gui
import connection


def report(ready=True, tested=True, installed=False):
    return {'device': {'display_name': 'BlackBerry Q10' if tested else 'BlackBerry Classic',
                       'variant': 'SQN100-3' if tested else 'SQC100-1', 'os_version': '10.3.3.3216',
                       'hardware_tested': tested, 'recognized': True},
            'checks': [{'id': 'model', 'status': 'pass', 'code': 'device_identified'},
                       {'id': 'native', 'status': 'pass', 'code': 'native_hashes_required'},
                       {'id': 'lte', 'status': 'pass' if ready else 'wait',
                        'code': 'lte_ready' if ready else 'lte_not_ready'}],
            'installation': {'state': 'stopped' if installed else 'absent'},
            'outcome': 'not_ready' if not ready else 'compatible' if tested else 'experimental',
            'can_install': ready and not installed, 'can_update': ready and installed,
            'can_start': ready and installed}


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.private = Path(self.temp.name)
        for module in (gui, connection):
            private_patch = patch.object(module, 'private_root', return_value=self.private)
            private_patch.start()
            self.addCleanup(private_patch.stop)
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest('Tk display unavailable: ' + str(error))
        self.root.withdraw()
        self.app = gui.App(self.root)

    def tearDown(self):
        if hasattr(self, 'app'):
            self.app.busy = False
            self.app.close()

    def test_check_device_selects_matching_kit_and_restores_it_on_restart(self):
        old = self.private / 'root-kit/ssh_config'
        current = self.private / 'root-kit-123abc/ssh_config'
        for config in (old, current):
            config.parent.mkdir(parents=True)
            config.write_text('Host bb10-root\n')
        self.app.close()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = gui.App(self.root)
        self.assertEqual(self.app.config.get(), '')
        choices = [{'host': 'bb10-root', 'config': str(path), 'saved': False}
                   for path in (old, current)]
        stale, matched = MagicMock(), MagicMock()
        for client in (stale, matched):
            client.process.return_value = 'hostname 169.254.0.1\nuser root\n'
        stale.remote.side_effect = gui.WorkflowError('host_key_mismatch')
        matched.remote.return_value = 'BB10_CONNECTION_READY\n'
        matched.preflight.return_value = report()
        with patch.object(connection, 'candidate_connections', return_value=choices), \
                patch.object(connection, 'Client', side_effect=[stale, matched]), \
                patch.object(gui.threading, 'Thread', side_effect=lambda target, **_: SimpleNamespace(start=target)):
            self.app.run('preflight')
            self.root.after_cancel(self.app._drain_job)
            self.app.drain()
        self.assertEqual(self.app.config.get(), str(current))
        self.assertEqual(self.app.report, report())
        self.assertEqual(connection.saved_connection(), {'host': 'bb10-root', 'config': str(current)})
        self.app.close()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = gui.App(self.root)
        self.assertEqual(self.app.config.get(), str(current))

    def test_first_launch_has_one_action_and_no_technical_rows(self):
        self.assertEqual(self.app.table.get_children(), ())
        self.assertFalse(self.app.primary_button.winfo_manager())
        self.assertFalse(self.app.host_entry.master.winfo_manager())
        self.assertFalse(self.app.experiment_check.winfo_manager())
        self.assertFalse(self.app.ack_check.winfo_manager())
        self.assertEqual(self.app.allowed_actions(), {'preflight': True, 'install': False,
                                                     'start': False, 'status': False, 'disable': False})

    def test_only_problems_are_prominent_and_full_report_is_retained(self):
        value = report(ready=False)
        self.app.render_report(value)
        self.assertEqual(self.app.table.get_children(), ('lte',))
        self.assertEqual(self.app.display_report, value)
        self.assertEqual(str(self.app.details_button.cget('state')), 'normal')
        self.assertFalse(self.app.allowed_actions()['install'])

    def test_ack_and_fresh_connection_still_gate_install(self):
        self.app.render_report(report())
        self.assertFalse(self.app.allowed_actions()['install'])
        self.app.ack.set(True)
        self.assertTrue(self.app.allowed_actions()['install'])
        self.app.host.set('another-device')
        self.assertFalse(self.app.allowed_actions()['install'])
        self.assertFalse(self.app.ack.get())
        self.assertIsNone(self.app.display_report)
        self.assertEqual(str(self.app.details_button.cget('state')), 'disabled')

    def test_experimental_device_is_visible_and_opt_in_requires_recheck(self):
        self.app.render_report(report(tested=False))
        self.assertTrue(self.app.experiment_check.winfo_manager())
        self.assertIn('未实测', self.app.device_label.cget('text'))
        self.app.experimental.set(True)
        self.assertTrue(self.app.experiment_check.winfo_manager())
        self.assertIsNone(self.app.report)
        self.assertFalse(self.app.allowed_actions()['install'])

    def test_stopped_installation_offers_start_and_retains_update_in_menu(self):
        self.app.render_report(report(installed=True))
        self.app.ack.set(True)
        self.assertEqual(self.app.primary_action, 'start')
        self.assertTrue(self.app.allowed_actions()['install'])
        self.assertTrue(self.app.allowed_actions()['disable'])
        self.assertEqual(self.app.menu.entrycget(self.app.menu_actions['install'], 'state'), 'normal')
        self.app.busy = True
        self.app.refresh_buttons()
        self.assertFalse(any(self.app.allowed_actions().values()))
        self.assertEqual(str(self.app.host_entry.cget('state')), 'disabled')

    def test_running_owned_service_does_not_display_expected_baseline_as_a_problem(self):
        value = report(installed=True)
        value.update(can_start=False, can_update=False)
        value['installation']['state'] = 'busy'
        value['checks'].append({'id': 'baseline', 'status': 'wait', 'code': 'baseline_not_clean'})
        self.app.render_report(value, {'manager_alive': True})
        self.assertNotIn('baseline', self.app.table.get_children())
        self.assertEqual(self.app.primary_action, 'status')
        self.assertTrue(self.app.allowed_actions()['status'])
        self.assertFalse(self.app.allowed_actions()['install'])
        self.assertEqual(value['checks'][-1]['status'], 'wait')

    def test_error_code_is_available_for_report_without_becoming_status_copy(self):
        self.root.after_cancel(self.app._drain_job)
        self.app.events.put(('error', ('untranslated_internal_code', None)))
        self.app.drain()
        self.assertNotIn('untranslated_internal_code', self.app.activity.cget('text'))
        self.assertEqual(self.app.last_result['error'], 'untranslated_internal_code')

    def test_actions_fit_when_connection_options_and_experiment_are_open(self):
        self.app.toggle_connection_options()
        self.app.render_report(report(tested=False))
        self.root.attributes('-alpha', 0.0)
        self.root.geometry('960x700')
        self.root.deiconify()
        self.root.update()
        for widget in [self.app.primary_button, self.app.check_button, self.app.ack_check, self.app.activity]:
            x = widget.winfo_rootx() - self.root.winfo_rootx()
            y = widget.winfo_rooty() - self.root.winfo_rooty()
            self.assertGreater(widget.winfo_width(), 1)
            self.assertGreater(widget.winfo_height(), 1)
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + widget.winfo_width(), self.root.winfo_width())
            self.assertLessEqual(y + widget.winfo_height(), self.root.winfo_height())


if __name__ == '__main__':
    unittest.main()
