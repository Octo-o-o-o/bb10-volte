"""Desktop routing must not reactivate the migrated legacy installation."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import workflow as w
import auto_carrier as a
import auto_carrier_managed as managed


class UnifiedDesktopTests(unittest.TestCase):
    def test_unified_directory_takes_priority_and_blocks_legacy_install(self):
        client = object.__new__(w.Client)
        client.detect_managed = True
        client.remote = Mock(return_value='UNIFIED_CARRIERS\n')
        client.stage = Mock(side_effect=AssertionError('legacy staging used'))
        with patch.object(managed, 'Adapter') as adapter:
            adapter.return_value.inspect.return_value = {'managed_adapter': 'unified_carriers'}
            self.assertEqual(client.preflight()['managed_adapter'], 'unified_carriers')
            with self.assertRaisesRegex(w.WorkflowError, 'unified_already_installed'):
                client.install()
        command = client.remote.call_args[0][0]
        self.assertLess(command.index('/var/bb10_volte'), command.index('/var/q20_volte'))
        client.stage.assert_not_called()

    def test_changed_payload_is_rejected_before_pathtrust_or_execution(self):
        expected = a.verify_package()
        changed = copy.deepcopy(expected)
        changed['files']['device/unified_service.py'] = '0' * 64
        for value in (changed, [], None):
            with self.subTest(value=type(value).__name__):
                transport = Mock()
                transport.remote.return_value = json.dumps(value)
                auto = a.AutoClient(transport)
                auto.execute = Mock(side_effect=AssertionError('unverified code executed'))
                with self.assertRaisesRegex(w.WorkflowError, 'unified_package_mismatch'):
                    auto.action('disable')
                auto.execute.assert_not_called()

    def test_desktop_revision_does_not_require_phone_reinstall(self):
        installed = a.verify_package()
        installed['desktop_revision'] = 1
        transport = Mock()
        transport.remote.return_value = json.dumps(installed)
        auto = a.AutoClient(transport)
        auto.execute = Mock(return_value={'phase': 'running'})
        self.assertEqual(auto.action('status'), {'phase': 'running'})

    def test_enable_waits_until_old_manager_finishes_restoring(self):
        transport = Mock()
        transport.remote.return_value = json.dumps(a.verify_package())
        auto = a.AutoClient(transport)
        auto.execute = Mock(return_value={'manager_alive': True, 'enabled': False})
        with self.assertRaisesRegex(w.WorkflowError, 'restore_pending'):
            auto.action('enable')
        self.assertEqual(auto.execute.call_count, 1)
        self.assertEqual(auto.execute.call_args[0][2], ('status',))

    def test_known_previous_candidate_remains_manageable_for_upgrade(self):
        old = json.loads((a.ROOT / 'materials/unified-previous-payload.json').read_text())
        transport = Mock()
        transport.remote.return_value = json.dumps(old)
        auto = a.AutoClient(transport)
        auto.execute = Mock(return_value={'enabled': True})
        self.assertEqual(auto.action('status'), {'enabled': True})

    def test_cached_register_success_is_not_presented_as_a_live_registration(self):
        from auto_carrier_gui import status_text
        stale = {'phase': 'error_restored', 'manager_alive': False, 'native_alive': False,
                 'status_from_current_boot': True, 'current': {'register_status': '200 OK', 'radio': ['gsm']}}
        title, details = status_text(stale)
        self.assertNotIn('200 OK', details)
        self.assertIn('gsm', details)
        stale['phase'] = 'running'
        stopped_title, unused = status_text(stale)
        live = dict(stale, manager_alive=True, native_alive=True, enabled=True, selected_this_boot=True,
                    current={'ims': 'connected', 'register_status': '200 OK', 'ran': 'LTE', 'radio': ['lte']})
        live_title, live_details = status_text(live)
        self.assertNotEqual(stopped_title, live_title)
        self.assertIn('200 OK', live_details)

    def test_all_models_manage_unified_service_without_claiming_call_acceptance(self):
        for variant in a.policy.MODELS:
            adapter = managed.Adapter(Mock())
            adapter.auto = Mock()
            state = {'variant': variant, 'phase': 'running', 'manager_alive': True,
                     'native_alive': True, 'status_from_current_boot': True, 'selected_this_boot': True, 'enabled': True,
                     'current': {'ims': 'connected', 'register_status': '200 OK', 'ran': 'LTE', 'radio': ['lte']}}
            adapter.auto.action.return_value = state
            report = adapter.inspect()
            self.assertEqual(report['managed_adapter'], 'unified_carriers')
            self.assertEqual(report['device']['variant'], variant)
            self.assertFalse(report['device']['hardware_tested'])
            self.assertEqual(report['outcome'], 'compatible')
            for operation in ('can_start', 'can_install', 'can_update', 'can_enable'):
                self.assertFalse(report[operation])
            state.update(enabled=False, manager_alive=False, phase='reboot_required')
            self.assertTrue(adapter.inspect()['can_enable'])
            state.update(enabled=True, phase='unsupported_sim')
            self.assertEqual(adapter.inspect()['outcome'], 'not_ready')
            adapter.action('disable')
            adapter.auto.action.assert_called_with('disable')


if __name__ == '__main__':
    unittest.main()
