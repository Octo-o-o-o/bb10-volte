"""Desktop presentation and action gates; no transport or phone operations."""
from pathlib import Path
import copy
import json
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
                       {'id': 'root', 'status': 'pass', 'code': 'root_qnx_arm32_required'},
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

    def test_passport_hold_keeps_status_but_disables_automatic_restore(self):
        value = report(tested=False, installed=True)
        value['device'].update(display_name='BlackBerry Passport', variant='SQW100-1')
        value.update(outcome='needs_adaptation', can_install=False, can_update=False,
                     can_start=False, can_restore=False)
        value['checks'].append({'id': 'provider_lifecycle', 'status': 'adapt',
                                'code': 'passport_provider_lifecycle_unvalidated'})
        value['incoming_diagnostics'] = {'allow_volte_provisioning': 1, 'use_preconditions': None}
        self.app.render_report(value)
        self.app.ack.set(True)
        self.assertIn('provider_lifecycle', self.app.table.get_children())
        self.assertIn('恢复策略待验证', self.app.device_label.cget('text'))
        self.assertTrue(self.app.allowed_actions()['status'])
        self.assertFalse(any(self.app.allowed_actions()[key] for key in ('install', 'start', 'disable')))
        self.app.show_checks()
        self.root.update_idletasks()

    def test_incoming_observations_share_snapshot_and_never_enable_actions_or_transport(self):
        value = report(ready=False, tested=False, installed=True)
        value.update(can_restore=False, incoming_diagnostics={
            'ims_state': 'connected', 'ims_ran': 'LTE', 'allow_volte_provisioning': 1,
            'engineering_voice_override': '5', 'dca_voice_preference': 3,
            'use_preconditions': True, 'extra': 'private-customer-data'})
        before = copy.deepcopy(value)
        self.app.render_report(value)
        self.app.ack.set(True)
        actions = self.app.allowed_actions()
        self.assertFalse(any(actions[key] for key in ('install', 'start', 'disable')))
        with patch.object(self.app, 'run') as action, patch.object(gui, 'Client') as client:
            self.app.show_checks()
            self.root.update_idletasks()
            def widgets(widget):
                return [widget] + [item for child in widget.winfo_children() for item in widgets(child)]
            popup = next(child for child in self.root.winfo_children() if isinstance(child, tk.Toplevel))
            all_widgets = widgets(popup)
            table = next(widget for widget in all_widgets if isinstance(widget, gui.ttk.Treeview))
            rows = [table.item(key, 'values') for key in table.get_children()]
            observations = {row[0]: row for row in rows if row[2].startswith('[I')}
            self.assertEqual(len(observations), 6)
            self.assertEqual(observations['IR92 preconditions'][1], '未知')
            self.assertIn('当前：未知', observations['IR92 preconditions'][2])
            self.assertIn('不同接口', observations['工程语音域'][2])
            self.assertNotIn('private-customer-data', str(rows))
            self.assertEqual(self.app.allowed_actions(), actions)
            copy_button = next(widget for widget in all_widgets if isinstance(widget, gui.ttk.Button)
                               and widget.cget('text') == '复制排查摘要')
            self.app.render_report(report())  # The open dialog retains the old observations.
            copy_button.invoke()
            summary = self.root.clipboard_get()
            self.assertIn('当前：connected', summary)
            self.assertNotIn('private-customer-data', summary)
            destination = self.private / 'incoming-report.json'
            export_button = next(widget for widget in all_widgets if isinstance(widget, gui.ttk.Button)
                                 and widget.cget('text') == '导出检查报告')
            with patch.object(gui.filedialog, 'asksaveasfilename', return_value=str(destination)):
                export_button.invoke()
            exported = json.loads(destination.read_text(encoding='utf-8'))
            self.assertEqual(exported['desktop_diagnostics']['summary'], summary)
            action.assert_not_called(); client.assert_not_called()
        self.assertEqual(value, before)

    def test_disconnected_ctlte_and_nondefault_configuration_are_visible_without_enabling_install(self):
        value = report(ready=False, tested=False)
        value['checks'] += [{'id': 'apn', 'status': 'wait', 'code': 'data_apn_disconnected'},
                            {'id': 'baseline', 'status': 'wait', 'code': 'baseline_not_clean'}]
        value['network_diagnostics'] = {'observed_data_apn': 'ctlte', 'apn_matches': True, 'data_connected': False}
        value['configuration_diagnostics'] = {'ims_override_absent': True, 'cdsc_selection_default': False}
        self.app.render_report(value)
        self.app.ack.set(True)
        self.assertIn('匹配', self.app.table.item('apn', 'values')[2])
        self.assertNotIn('服务运行时属正常', self.app.table.item('baseline', 'values')[2])
        self.assertFalse(self.app.allowed_actions()['install'])
        self.app.show_checks()
        def tables(widget):
            return ([widget] if isinstance(widget, gui.ttk.Treeview) else []) + [
                table for child in widget.winfo_children() for table in tables(child)]
        rows = [table.item(row, 'values') for table in tables(self.root) if table is not self.app.table
                for row in table.get_children()]
        self.assertIn(('手机报告的 APN', '只读快照', 'ctlte'), rows)
        self.assertIn(('数据连接状态', '只读快照', '否'), rows)
        self.assertTrue(any(row[:2] == ('数据配置选择为默认状态', '需核实') for row in rows))

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

    def test_baseline_reason_filter_copy_and_export_use_the_same_snapshot(self):
        value = report()
        value.update(can_install=False, baseline={'voice_policy': 3, 'crypto': {'swcr_id': -1, 'crypto_support': 0},
                     'ims_count': 1, 'vpn_count': 0, 'clean_configuration': False, 'native_read_error': False},
                     configuration_diagnostics={'cdsc_selection_default': False})
        value['checks'].append({'id': 'baseline', 'status': 'wait', 'code': 'baseline_not_clean'})
        self.app.render_report(value)
        self.assertEqual(self.app.summary.cget('text'), '安装前状态需处理')
        self.assertIn('语音策略：3', self.app.table.item('baseline', 'values')[2])
        # Native Tk selection events need a mapped window and a full event loop on macOS.
        self.root.attributes('-alpha', 0.0)
        self.root.deiconify()
        self.root.update()
        self.app.show_checks()
        self.root.update()
        def widgets(widget):
            return [widget] + [item for child in widget.winfo_children() for item in widgets(child)]
        popup = next(child for child in self.root.winfo_children() if isinstance(child, tk.Toplevel))
        all_widgets = widgets(popup)
        table = next(widget for widget in all_widgets if isinstance(widget, gui.ttk.Treeview))
        selected = next(widget for widget in all_widgets if isinstance(widget, tk.Text))
        voice = next(key for key in table.get_children() if table.item(key, 'values')[0] == '语音策略')
        table.selection_set(voice)
        self.root.update()
        self.assertIn('当前：3；安装前要求：0', selected.get('1.0', 'end'))
        toggle = next(widget for widget in all_widgets if isinstance(widget, gui.ttk.Checkbutton))
        before = len(table.get_children()); toggle.invoke()
        self.assertLess(len(table.get_children()), before)
        copy_button = next(widget for widget in all_widgets if isinstance(widget, gui.ttk.Button) and widget.cget('text') == '复制排查摘要')
        self.app.render_report(report())  # The open dialog must keep its original snapshot.
        copy_button.invoke()
        self.assertIn('当前：3；安装前要求：0', self.root.clipboard_get())
        destination = self.private / 'report.json'
        export_button = next(widget for widget in all_widgets if isinstance(widget, gui.ttk.Button) and widget.cget('text') == '导出检查报告')
        with patch.object(gui.filedialog, 'asksaveasfilename', return_value=str(destination)):
            export_button.invoke()
        exported = json.loads(destination.read_text(encoding='utf-8'))
        self.assertEqual(exported['baseline']['voice_policy'], 3)
        self.assertIn('[B01]', exported['desktop_diagnostics']['summary'])
        self.assertNotIn('desktop_diagnostics', value)

    def test_running_manager_does_not_hide_a_native_read_failure(self):
        value = report(installed=True)
        value.update(can_start=False, can_update=False, baseline={'native_read_error': True},
                     native_read_status={'voice_policy': 'failed'})
        value['installation']['state'] = 'busy'
        value['checks'].append({'id': 'baseline', 'status': 'wait', 'code': 'baseline_not_clean'})
        self.app.render_report(value, {'manager_alive': True})
        self.assertIn('baseline', self.app.table.get_children())
        self.assertFalse(self.app.running_baseline_expected)

    def test_passed_autostart_check_does_not_ask_user_to_disable_it_again(self):
        check = {'id': 'autostart_policy', 'status': 'pass', 'code': 'experimental_manual_start_required'}
        self.assertIn('已关闭', self.app.check_note(check, report(tested=False)))
        self.assertNotIn('请在', self.app.check_note(check, report(tested=False)))

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
