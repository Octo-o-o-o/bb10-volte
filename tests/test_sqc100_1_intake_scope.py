"""Owner-authorized SQC100-1 admission still enforces exact native/SIM boundaries."""
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'device'),str(ROOT/'tools')]
import carrier_policy as policy
import device_support
import unified_install as installer
import unified_migrate as migration
import variant_trials

FACTS={'variant':'SQC100-1','board_type':'CLASSICROW','os_version':'10.3.3.3216'}
def card(mnc):
    return {'state':'READY','kind':2,'mcc':'460','mnc':mnc,'imsi':'460'+mnc+'12345'*2}

class SQC1IntakeScopeTests(unittest.TestCase):
    def test_three_exact_operator_routes_without_marking_manual_tests_passed(self):
        for mnc,operator in (('00','mobile'),('01','unicom'),('11','telecom')):
            value=policy.select(FACTS,card(mnc))
            self.assertEqual(value['operator'],operator)
            self.assertEqual(value['request']['profile']['carrier']['mncs'],[mnc])
            scope=device_support.assess('SQC100-1',operator)
            self.assertTrue(scope['automatic_volte'])
            self.assertFalse(scope['owner_trial_pending_manual_acceptance'])
            self.assertEqual(variant_trials.plan('SQC100-1',operator)['hardware_acceptance'],'not_established_by_this_plan')

    def test_other_mncs_and_isim_or_unready_identity_stay_rejected(self):
        for changed in (card('03'),dict(card('01'),kind=18),dict(card('01'),state='PIN_REQUIRED'),
                        dict(card('01'),imsi='not-an-identity'),dict(card('01'),kind=True)):
            with self.assertRaises(ValueError):policy.select(FACTS,changed)

    def test_wrong_board_os_and_suffix_never_reuse_this_device_scope(self):
        for changed in ({'board_type':'CLASSICATT'},{'board_type':'CLASSICNA'},
                        {'os_version':'10.3.3.2163'},{'variant':'SQC100-99'}):
            with self.assertRaises(ValueError):policy.select(dict(FACTS,**changed),card('01'))

    def test_new_model_still_stops_before_migration_on_unknown_native_image(self):
        phone_os=SimpleNamespace(geteuid=lambda:0,uname=lambda:('QNX',))
        with patch.object(installer,'os',phone_os),patch.object(installer.ctypes,'sizeof',return_value=4),\
             patch.object(installer.device_info,'read_identity',return_value=FACTS),\
             patch.object(installer,'identity',side_effect=AssertionError('unknown_native_image')),\
             patch.object(installer.migration,'inspect') as migrate:
            result=installer.probe()
        self.assertEqual(result['scope_error'],'unknown_native_image')
        self.assertFalse(result['can_install']);migrate.assert_not_called()

    def test_other_model_admission_not_expanded(self):
        self.assertEqual(set(policy.MODELS),set(device_support.catalog()))
        for variant in policy.MODELS:
            self.assertEqual(policy.ADMITTED_MNCS[variant],('00','01','07','11'))

    def test_new_suffix_never_guesses_another_suffix_legacy_recovery(self):
        with patch.object(migration.os.path,'lexists',return_value=False),patch.object(migration.s,'load') as read:
            self.assertIsNone(migration.inspect(FACTS));read.assert_not_called()
        for path in migration.BASES.values():
            with patch.object(migration.os.path,'lexists',side_effect=lambda p:p==path),patch.object(migration.s,'load') as read:
                with self.assertRaisesRegex(AssertionError,'unvalidated_legacy_installation'):migration.inspect(FACTS)
                read.assert_not_called()

    def test_mobile_scope_is_visible_and_obsolete_manual_choices_removed(self):
        qml=(ROOT/'mobile/native/assets/main.qml').read_text(encoding='utf8')
        self.assertIn('volteController.compatibilityText',qml)
        experimental=(ROOT/'mobile/native/assets/Experimental.qml').read_text(encoding='utf8')
        self.assertNotIn('variant-trial-sqc100-1-',experimental)

if __name__=='__main__':unittest.main()
