"""Regress the expired manual lease and missing accepted Telecom boot path."""
import hashlib
import ast
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from unittest.mock import patch
from types import SimpleNamespace
from test_passport_autostart import namespace, telecom_stub, marker, journal, TOKEN, SHA


def receipt():
    return {'owner': 'passport-call-acceptance-v1', 'variant': 'SQW100-4',
            'profile_id': 'passport-telecom-manual-research', 'profile_sha256': SHA,
            'sim_fingerprint': hashlib.sha256(b'usim').hexdigest(),
            'incoming': True, 'outgoing': True, 'audio_both_directions': True,
            'lte': True, 'sip_dialogs_verified': True}


class TelecomRecoveryTests(unittest.TestCase):
    def test_real_shared_prepare_calls_passport_fast_path_before_stock_handoff(self):
        class ChildExit(Exception):
            pass
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            plan, *_ = telecom_stub(base, g, data_centric=True, ue_usage=1)
            marker(base, plan, [10, 1000.0])
            journal(base)
            (base / 'enabled').touch()
            g['acceptance_receipt'] = receipt
            g['EARLY_SDP0_PROFILES'] = ()
            g['s'].ACTIVE_PROFILE['runtime'] = {'existing_ims_wait_seconds': 330}
            g['s'].save_journal = Mock()
            g['os'].fork = Mock(return_value=0)
            g['os']._exit = Mock(side_effect=ChildExit)
            order = []
            g['n'].verify_stock = lambda: None
            g['s'].telecom_dca_plan = plan
            def fast_path():
                order.append('cold_boot_fast_path')
            g['telecom_ensure_lte'] = fast_path
            def original_configure():
                order.append('original_configure')
                g['s'].j = {}
            g['s'].configure = original_configure
            module = SimpleNamespace(ensure_lte=Mock(side_effect=AssertionError('Q10 runtime bootstrap was called')))
            g['telecom'] = lambda: module
            service_source = Path(__file__).resolve().parents[2] / 'device/service.py'
            node = next(item for item in ast.parse(service_source.read_text()).body
                        if isinstance(item, ast.FunctionDef) and item.name == 'prepare_connection')
            engine = {'__name__': 'fake_passport_service', 'sys': sys, 'n': g['n'], 'time': g['time'],
                      'ACTIVE_PROFILE': g['s'].ACTIVE_PROFILE, 'startup_timing': g['s'].startup_timing,
                      'wait_for_network': lambda: True,
                      'request_idle_stock_exit': lambda: (order.append('stock_handoff') or False),
                      'wait_until': lambda predicate, *args, **kwargs: self.assertTrue(predicate()),
                      'status': lambda *args: None,
                      'configure': lambda: g['s'].configure()}
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(service_source), 'exec'), engine)
            g['s'].serve = engine['prepare_connection']
            with patch.dict(sys.modules, {'telecom_attach': module, 'fake_passport_service': g['s']}):
                with self.assertRaises(ChildExit):
                    g['boot']()
            self.assertEqual(order, ['cold_boot_fast_path', 'stock_handoff',
                                     'cold_boot_fast_path', 'original_configure'])
            self.assertEqual(g['s'].j['telecom_dca_plan'], plan)

    def test_telecom_acceptance_requires_real_call_flags_and_a_sim_fingerprint(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            telecom_stub(base, g)
            self.assertTrue(g['acceptance_valid'](receipt(), SHA))
            wrong = receipt()
            wrong.pop('sim_fingerprint')
            self.assertFalse(g['acceptance_valid'](wrong, SHA))
            self.assertFalse(g['acceptance_valid'](dict(receipt(), lte='true'), SHA))

    def test_persisted_plan_and_acceptance_must_bind_the_current_sim(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            plan, *_ = telecom_stub(base, g, data_centric=True, ue_usage=1)
            marker(base, plan, [10, 1000.0])
            self.assertEqual(g['telecom_acceptance_sim'](receipt()), receipt()['sim_fingerprint'])
            g['s'].current_usim = lambda: 'another-usim-on-the-same-plmn'
            with self.assertRaisesRegex(AssertionError, 'SIM changed'):
                g['telecom_acceptance_sim'](receipt())
            with self.assertRaisesRegex(AssertionError, 'SIM changed'):
                g['telecom_ensure_lte']()

    def test_boot_rejects_a_same_operator_sim_swap_before_start_or_stock_signal(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            plan, *_ = telecom_stub(base, g, data_centric=True, ue_usage=1)
            marker(base, plan, [10, 1000.0])
            (base / 'enabled').touch()
            g['acceptance_receipt'] = receipt
            g['s'].current_usim = lambda: 'another-usim'
            with self.assertRaisesRegex(AssertionError, 'SIM changed'):
                g['boot']()
            self.assertEqual(g['os'].forks, 0)
            self.assertEqual(g['os'].kills, [])

    def test_autostart_uses_the_same_cold_boot_fast_path_then_journals_its_restore_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            plan, _, writes, restores, _ = telecom_stub(base, g, data_centric=True, ue_usage=1)
            marker(base, plan, [10, 1000.0])
            g['acceptance_receipt'] = receipt
            g['EARLY_SDP0_PROFILES'] = ()
            g['s'].save_journal = Mock()
            order = []
            original_fast_path = g['telecom_ensure_lte']
            def fast_path():
                order.append('cold_boot_fast_path')
                original_fast_path()
            def configure():
                order.append('configure_ims')
                g['s'].j = {}
            g['telecom_ensure_lte'] = fast_path
            g['autostart_configure'](configure)()
            self.assertEqual(order, ['cold_boot_fast_path', 'configure_ims'])
            self.assertEqual(g['s'].j['telecom_dca_plan'], plan)
            self.assertEqual(g['s'].j['configured_sim_fingerprint'], receipt()['sim_fingerprint'])
            self.assertFalse(g['s'].j['manual_only'])
            self.assertEqual(writes, [])
            self.assertEqual(restores, [])

    def test_automatic_manager_has_no_manual_deadline_or_watchdog_after_old_lease_expires(self):
        class ChildExit(Exception):
            pass
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            plan, *_ = telecom_stub(base, g, data_centric=True, ue_usage=1)
            marker(base, plan, [10, 1000.0])
            journal(base)
            (base / 'enabled').touch()
            (base / 'state/lease.json').write_text(json.dumps({'boot': [10, 1000.0], 'deadline_unix': 1}))
            g['acceptance_receipt'] = receipt
            g['EARLY_SDP0_PROFILES'] = ()
            g['os'].fork = Mock(return_value=0)
            g['os']._exit = Mock(side_effect=ChildExit)
            g['s'].configure = Mock()
            observed = []
            def serve():
                observed.append(g['s'].stopping())
                self.assertFalse((base / 'state/lease.json').exists())
                self.assertFalse((base / 'state/stop-request').exists())
            g['s'].serve = serve
            with self.assertRaises(ChildExit):
                g['boot']()
            self.assertEqual(observed, [False])
            g['os'].fork.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
