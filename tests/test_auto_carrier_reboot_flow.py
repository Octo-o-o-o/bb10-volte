"""Exercise the extra normal reboot through both desktop entry points."""
from pathlib import Path
import sys
import json
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import i18n
from auto_carrier_view import status_view
from auto_carrier_gui import AutoCarrierWindow
from auto_carrier_managed import Adapter
from workflow import public_status, registered


def state(phase='carrier_reboot_required', **changes):
    value = {'variant': 'SQW100-4', 'phase': phase, 'enabled': True,
             'automatic_carrier_selection': True, 'status_from_current_boot': True,
             'selected_this_boot': True, 'selected_operator': 'telecom',
             'manager_alive': phase == 'running', 'native_alive': phase == 'running',
             'current': {'ims': 'connected', 'register_status': '200 OK', 'ran': 'LTE', 'radio': ['lte']}}
    value.update(changes)
    return value


class RebootPresentationTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(i18n, 'LANGUAGE', 'zh')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_policy_reboot_is_incomplete_even_with_cached_200_and_lte(self):
        view = status_view(state())
        self.assertFalse(view['ready'])
        self.assertIn('还需一次', view['title'])
        self.assertNotIn('200 OK', view['details'])
        self.assertIn('飞行模式不能代替', view['guidance'])
        self.assertEqual(view['status_button'], '已重启，重新检查')

    def test_sequence_drops_previous_reboot_instruction_until_current_boot_is_ready(self):
        before = status_view(state())
        booting = status_view(state(status_from_current_boot=False, selected_this_boot=False, current=None))
        registering = status_view(state('registering', manager_alive=True))
        after = status_view(state('running'))
        self.assertTrue(all(not v['ready'] for v in (before, booting, registering)))
        self.assertNotIn('还需一次', booting['title'])
        self.assertNotIn('重启', registering['guidance'])
        self.assertTrue(after['ready'])
        self.assertNotIn('再正常重启', after['guidance'])
        self.assertEqual(after['status_button'], '刷新状态')

    def test_success_requires_current_boot_current_selection_and_enabled(self):
        for changes in ({'status_from_current_boot': False}, {'selected_this_boot': False},
                        {'enabled': False}, {'manager_alive': False}, {'native_alive': False},
                        {'current': None}):
            with self.subTest(changes=changes):
                self.assertFalse(status_view(state('running', **changes))['ready'])

    def test_disabled_restoring_and_cleanup_do_not_request_carrier_reboot(self):
        stopped = status_view(state(enabled=False))
        self.assertIn('已停用', stopped['title'])
        restoring = status_view(state(enabled=False, manager_alive=True))
        self.assertEqual(restoring['status_button'], '检查恢复进度')
        failed = status_view(state('cleanup_required', enabled=False))
        self.assertIn('恢复尚未完成', failed['title'])
        self.assertNotIn('已停用', failed['title'])

    def test_managed_preflight_has_an_explicit_reboot_check(self):
        adapter = Adapter(Mock())
        adapter.auto = Mock()
        adapter.auto.action.return_value = state()
        report = adapter.inspect()
        self.assertEqual(report['outcome'], 'not_ready')
        self.assertEqual(report['checks'][-1]['code'], 'unified_carrier_reboot_required')
        self.assertFalse(adapter.action('status')['registered'])
        adapter.auto.action.return_value = state('running')
        self.assertTrue(adapter.action('status')['registered'])

    def test_public_status_preserves_only_safe_carrier_selection_fields(self):
        result = public_status(dict(state('running'), private_number='not-for-export'))
        self.assertTrue(status_view(result)['ready'])
        self.assertNotIn('private_number', result)
        self.assertNotIn('selected_operator', public_status(state(selected_operator='untrusted')))
        self.assertFalse(registered({'current': None}))
        self.assertEqual(public_status({'current': None})['current']['ims'], None)

    def test_english_extra_restart_and_ready_states(self):
        with patch.object(i18n, 'LANGUAGE', 'en'):
            before, after = status_view(state()), status_view(state('running'))
        self.assertIn('One more normal restart', before['title'])
        self.assertIn('No reinstall', before['guidance'])
        self.assertEqual(before['status_button'], 'Restarted — check again')
        self.assertIn('verify calls', after['title'])

    def test_exported_preflight_uses_the_verified_boot_snapshot(self):
        import gui
        for phone in (state(), state('running', status_from_current_boot=False), state('running')):
            with self.subTest(phase=phone['phase'], current=phone['status_from_current_boot']), tempfile.TemporaryDirectory() as folder:
                adapter = Adapter(Mock())
                adapter.auto = Mock()
                adapter.auto.action.return_value = phone
                client = Mock()
                client.preflight.return_value = adapter.inspect()
                client.service.side_effect = AssertionError('Must keep the verified preflight snapshot')
                destination = Path(folder) / 'report.json'
                with patch.object(sys, 'argv', ['bb10-volte', '--preflight-report', str(destination)]), \
                        patch.object(gui, 'prepare_external_programs'), \
                        patch.object(gui, 'resolve_connection', return_value=(client, None)):
                    code = gui.main()
                report = json.loads(destination.read_text())
                self.assertEqual(report['registered'], status_view(phone)['ready'])
                self.assertEqual(code, 0 if report['registered'] else 2)
                client.service.assert_not_called()


class RebootWindowTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(i18n, 'LANGUAGE', 'zh')
        patcher.start()
        self.addCleanup(patcher.stop)
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.ui = AutoCarrierWindow(self.root, 'test-phone', '')
        self.ui.window.withdraw()
        self.addCleanup(self.ui.close)

    def deliver(self, action, result=None, error=None):
        self.ui.window.after_cancel(self.ui.poll_job)
        self.ui.events.put((action, result, error))
        self.ui.poll()

    def test_reopen_probe_resumes_extra_reboot_then_status_rechecks_readiness(self):
        self.deliver('probe', {'installed': True, 'variant': 'SQW100-4', 'status': state()})
        self.assertIn('还需一次', self.ui.status.cget('text'))
        self.assertEqual(self.ui.buttons['status'].cget('text'), '已重启，重新检查')
        self.deliver('status', state('registering', manager_alive=True))
        self.assertNotIn('注册成功', self.ui.status.cget('text'))
        self.deliver('status', state('running'))
        self.assertIn('本次开机注册成功', self.ui.status.cget('text'))
        self.assertEqual(self.ui.buttons['status'].cget('text'), '刷新状态')

    def test_usb_reboot_disconnect_invalidates_actions_and_reconnects_from_phone_state(self):
        self.ui.client = Mock()
        self.deliver('probe', {'installed': True, 'variant': 'SQW100-4', 'status': state()})
        self.deliver('status', error='connection_refused')
        self.assertIsNone(self.ui.client)
        self.assertIsNone(self.ui.report)
        self.assertEqual(self.ui.buttons['probe'].cget('text'), '重新检查连接')
        for name in ('install', 'enable', 'disable', 'status'):
            self.assertIn('disabled', self.ui.buttons[name].state())
        self.deliver('probe', {'installed': True, 'variant': 'SQW100-4', 'status': state('running')})
        self.assertIn('注册成功', self.ui.status.cget('text'))
        self.assertNotIn('disabled', self.ui.buttons['status'].state())

    def test_update_preserves_disabled_state_and_requires_enable_before_reboot(self):
        self.deliver('install', {'updated': True, 'desktop_backup': 'verified-backup',
                                'status': state(enabled=False)})
        self.assertIn('先启用', self.ui.status.cget('text'))
        self.assertNotIn('disabled', self.ui.buttons['enable'].state())
        self.deliver('enable', {'enabled': True, 'reboot_required': True})
        self.assertIn('请正常重启', self.ui.status.cget('text'))
        self.assertEqual(self.ui.buttons['status'].cget('text'), '已重启，重新检查')
        self.assertIn('Passport', self.ui.details.get('1.0', 'end'))

    def test_successful_install_with_failed_status_read_does_not_offer_reinstall(self):
        self.deliver('install', {'installed': True, 'desktop_backup': 'verified-backup', 'status': {}})
        self.assertIn('启用状态待检查', self.ui.status.cget('text'))
        self.assertIn('disabled', self.ui.buttons['install'].state())
        self.assertIn('disabled', self.ui.buttons['enable'].state())
        self.assertNotIn('disabled', self.ui.buttons['status'].state())


if __name__ == '__main__':
    unittest.main()
