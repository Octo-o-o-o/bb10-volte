"""The existing Q20 manager must dispatch the installed carrier safely."""
import hashlib
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import q20_managed
import q20_manage_probe as probe
import workflow


def phone(mnc='00'):
    profile = {'id': 'q20-sqc100-2-mobile-46000',
               'carrier': {'mcc': '460', 'mncs': ['00']}}
    return NS(
        status=lambda: {'manager_alive': False, 'enabled': False},
        s=NS(ACTIVE_REQUEST={'profile': profile}, ACTIVE_PROFILE=profile,
             CDSC='cdsc', APN='apn', phone_idle=lambda: True),
        profiles=NS(fingerprint=lambda value: 'profile-hash'),
        device_info=NS(read_identity=lambda: {'variant': 'SQC100-2'}, identify=lambda value: value),
        n=NS(digest=lambda value: probe.BOOT_HOOK_HASH, read=lambda path: b'hook',
             attrs=lambda value: {'cdsc_xml': ':'}, value=lambda obj, key: obj.get(key),
             voice_policy=lambda: 0, crypto_policy=lambda: {'swcr_id': -1, 'crypto_support': 0},
             ims_pids=lambda: [], active_vpn_sessions=lambda: []),
        c=NS(read_network=lambda profile: {'mcc': '460', 'mnc': mnc, 'sim_state': 'READY'},
             network_checks=lambda network, profile: [], configuration_diagnostics=lambda: {'clean': True},
             public_baseline=lambda value: value, public_network_diagnostics=lambda value: value,
             incoming_diagnostics=lambda: {}))


class MobileQ20ManagementTests(unittest.TestCase):
    def test_matching_mobile_card_is_manageable_and_other_carrier_is_blocked(self):
        with patch.object(probe.os.path, 'islink', return_value=False):
            good = probe.inspect(phone())
            wrong = probe.inspect(phone('11'))
        self.assertEqual(good['outcome'], 'compatible')
        self.assertTrue(good['can_start'])
        self.assertEqual(wrong['outcome'], 'needs_adaptation')
        self.assertFalse(wrong['can_start'])

    def test_mobile_prepare_uses_normal_precheck_without_a_telecom_dca_plan(self):
        q = phone()
        q.precheck = Mock()
        with patch.object(probe, 'inspect', return_value={'can_start': True}):
            plan = probe.perform(q, 'prepare')
        q.precheck.assert_called_once_with()
        self.assertEqual(plan, {'prepared': True, 'backup_required': False,
                                'profile_sha256': 'profile-hash'})

    def test_mobile_app_start_skips_telecom_backup_only_for_the_matching_precheck(self):
        client = NS(wait_registration=Mock(return_value={'registration': 'verified'}))
        adapter = q20_managed.Adapter(client)
        report = {'status': {'manager_alive': False}, 'can_start': True,
                  'profile_parameters': {'carrier': {'mncs': ['00']},
                                         'runtime': {'registration_wait_seconds': 180}},
                  'profile_sha256': 'profile-hash'}
        adapter.inspect = Mock(return_value=report)
        adapter.backup = Mock(side_effect=AssertionError('Telecom backup used for Mobile'))
        plan = {'prepared': True, 'backup_required': False, 'profile_sha256': 'profile-hash'}
        adapter.invoke = Mock(side_effect=[plan, {'started_manager_pid': 1}])
        self.assertEqual(adapter.action('start'), {'registration': 'verified'})
        self.assertEqual([call.args[0] for call in adapter.invoke.call_args_list], ['prepare', 'start'])
        adapter.backup.assert_not_called()
        adapter.invoke = Mock(return_value=dict(plan, profile_sha256='other-profile'))
        with self.assertRaisesRegex(workflow.WorkflowError, 'preflight_blocked'):
            adapter.action('start')
        self.assertEqual(adapter.invoke.call_count, 1)

    def test_unknown_phone_manifest_is_blocked_before_upload_or_pathtrust(self):
        spec = {'manifest_sha256': hashlib.sha256(b'accepted').hexdigest()}
        client = NS(remote=Mock(return_value='unknown'), process=Mock())
        with patch.object(q20_managed, 'bundle', return_value=(spec, Path('probe.py'))):
            with self.assertRaisesRegex(workflow.WorkflowError, 'package_mismatch'):
                q20_managed.Adapter(client).invoke('inspect')
        client.process.assert_not_called()
        self.assertEqual(client.remote.call_count, 1)
        self.assertIn('modelnumber::SQC100-2', client.remote.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
