"""Model guidance and early rejection: no network, firmware execution or phone I/O."""
import contextlib
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'device')]
import i18n
import device_support as support
import root_setup
import carrier_policy as policy
import unified_install as installer
from auto_carrier import AutoClient
from workflow import WorkflowError


class ModelSupportTests(unittest.TestCase):
    def test_support_guidance_works_from_only_the_declared_frozen_resources(self):
        import build_windows
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder)
            for name in build_windows.runtime_data():
                if name.startswith('materials/'):
                    target = bundle / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / name, target)
            support.catalog.cache_clear()
            try:
                with patch.object(support, 'resource_root', return_value=bundle):
                    self.assertTrue(support.assess('SQC100-2')['automatic_volte'])
                    self.assertEqual(support.assess('SQC100-3')['code'], 'supported')
                    self.assertEqual(support.assess('SQW100-2')['code'], 'supported')
            finally:
                support.catalog.cache_clear()

    def test_all_catalog_variants_have_an_explicit_outcome_without_granting_radio_candidates(self):
        self.assertEqual(set(support.catalog()) - set(root_setup.firmware_variants()), {'SQK100-2'})
        outcomes = [support.assess(v, op) for v in support.catalog() for op in ('mobile', 'unicom', 'telecom')]
        self.assertEqual(len(outcomes), 48)
        self.assertEqual(sum(x['automatic_volte'] for x in outcomes), 48)
        self.assertEqual(sum(x['code'] == 'radio_no_overlap' for x in outcomes), 0)
        self.assertEqual(sum(x['code'] == 'model_unconfirmed' for x in outcomes), 0)
        self.assertEqual(sum(x['code'] == 'adaptation_pending' for x in outcomes), 0)
        self.assertEqual({v for v in support.catalog() if support.assess(v)['automatic_volte']}, set(policy.MODELS))

    def test_q20_4_and_north_american_q10_are_not_three_carrier_candidates(self):
        for v in ('SQC100-4','SQN100-1','SQN100-2','SQN100-4','SQN100-5'):
            for op in ('mobile','unicom','telecom'):
                self.assertTrue(support.assess(v,op)['automatic_volte'])
        self.assertEqual(support.assess('SQC100-4')['evidence_status']['unicom'],'failed')

    def test_root_only_intent_does_not_invent_unknown_hardware(self):
        self.assertIsNone(support.preparation_blocker('SQC100-5'))
        self.assertIsNone(support.preparation_blocker('SQW100-2'))
        for v in ('SQW100-9','SQC100-99',''):
            self.assertIsNotNone(support.preparation_blocker(v,root_only=True))


class PhoneProbeTests(unittest.TestCase):
    def setUp(self):
        self.facts = {'variant': 'SQC100-2', 'board_type': 'CLASSICATT', 'os_version': policy.OS_VERSION}
        phone_os = SimpleNamespace(geteuid=lambda: 0, uname=lambda: ('QNX',), path=MagicMock())
        phone_os.path.isfile.return_value = False
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(installer, 'os', phone_os))
        self.stack.enter_context(patch.object(installer.ctypes, 'sizeof', return_value=4))
        self.stack.enter_context(patch.object(installer.device_info, 'read_identity', side_effect=lambda: self.facts))

    def test_unsupported_models_os_and_conflicting_boards_stop_before_native_or_legacy_operations(self):
        cases = [(dict(self.facts, variant='SQC100-99'), 'unsupported_model_or_os'),
                 (dict(self.facts, os_version='10.3.3.2205'), 'os_not_supported'),
                 (dict(self.facts, board_type='CLASSICVZW'), 'hardware_identity_conflict')]
        for facts, code in cases:
            self.facts = facts
            with patch.object(installer, 'identity') as identity, patch.object(installer.migration, 'inspect') as migration:
                result = installer.probe()
            self.assertEqual(result['scope_error'], code)
            self.assertFalse(result['can_install'])
            identity.assert_not_called()
            migration.assert_not_called()

    def test_sim_rejection_removes_install_permission_and_remains_read_only(self):
        for reason in ('carrier_not_validated', 'sim_route_unsupported', 'sim_not_ready', 'sim_identity_unavailable'):
            with patch.object(installer, 'identity', return_value=(self.facts, 'classic')), \
                    patch.object(installer.s, 'phone_idle', return_value=True), \
                    patch.object(installer, 'root_kind', return_value='autoroot-v4'), \
                    patch.object(installer.migration, 'inspect', return_value=None), \
                    patch.object(installer.u, 'card', return_value={}), \
                    patch.object(installer.policy, 'select', side_effect=ValueError(reason)), \
                    patch.object(installer.n, 'atomic') as write:
                result = installer.probe()
            self.assertFalse(result['can_install'])
            self.assertFalse(result['sim_supported'])
            self.assertEqual(result['sim_reason'], reason)
            write.assert_not_called()

    def test_unknown_native_image_is_a_support_result_not_a_connection_failure(self):
        with patch.object(installer, 'identity', side_effect=AssertionError('unknown_native_image')):
            self.assertEqual(installer.probe()['scope_error'], 'unknown_native_image')
        with patch.object(installer, 'identity', side_effect=AssertionError('unexpected_integrity_problem')):
            with self.assertRaisesRegex(AssertionError, 'unexpected_integrity_problem'):
                installer.probe()


class DesktopTransportTests(unittest.TestCase):
    def test_rejected_probe_never_enters_prepare_update_or_backup(self):
        for report in (
                {'variant': 'SQC100-99', 'scope_error': 'unsupported_model_or_os'},
                {'variant': 'SQC100-2', 'can_install': True, 'sim_supported': False, 'sim_reason': 'sim_route_unsupported'},
                {'variant': 'SQC100-2', 'can_install': False, 'sim_supported': True}):
            client = AutoClient(MagicMock())
            with patch.object(client, 'stage', return_value=contextlib.nullcontext('/var/test-stage')), \
                    patch.object(client, 'execute', return_value=report) as execute, \
                    patch.object(client, 'download') as download:
                with self.assertRaises(WorkflowError):
                    client.install()
            self.assertEqual(execute.call_args_list[0].args[2], ('probe',))
            self.assertEqual(execute.call_count, 1)
            download.assert_not_called()

    def test_unknown_model_probe_can_be_retried_after_switching_devices(self):
        client = AutoClient(MagicMock())
        reports = [{'variant': 'SQC100-99', 'scope_error': 'unsupported_model_or_os'}, {'variant': 'SQC100-2'}]
        with patch.object(client, 'stage', side_effect=lambda: contextlib.nullcontext('/var/test-stage')), \
                patch.object(client, 'execute', side_effect=reports):
            client.probe()
            self.assertIsNone(client.variant)
            client.probe()
            self.assertEqual(client.variant, 'SQC100-2')


if __name__ == '__main__':
    unittest.main()
