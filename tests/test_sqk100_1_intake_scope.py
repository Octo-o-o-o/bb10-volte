"""P9983 trial admission preserves exact identity, native and recovery gates."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'device'),str(ROOT/'tools')]
import carrier_policy as policy
import device_info
import device_support
import unified_install as installer
import unified_migrate as migration
import unified_dca as dca
import variant_trials
import root_images

FACTS={'variant':'SQK100-1','board_type':'KHANE','os_version':'10.3.3.3216',
       'model':"P'9983",'full_model':"PORSCHE DESIGN P'9983 BlackBerry"}
def card(mnc):
    return {'state':'READY','kind':2,'mcc':'460','mnc':mnc,'imsi':'460'+mnc+'12345'*2}

class SQKIntakeTests(unittest.TestCase):
    def test_actual_identity_is_its_own_family_without_inherited_acceptance(self):
        value=device_info.identify(FACTS)
        self.assertTrue(value['recognized'])
        self.assertFalse(value['identity_conflict'])
        self.assertEqual(value['family'],'p9983')
        self.assertFalse(value['hardware_tested'])
        self.assertIn("P'9983",value['display_name'])
        self.assertTrue(device_info.identify(dict(FACTS,variant='SQN100-3'))['identity_conflict'])

    def test_three_carriers_admitted_as_trials_without_fabricating_acceptance(self):
        for mnc,operator in (('00','mobile'),('01','unicom'),('11','telecom')):
            selected=policy.select(FACTS,card(mnc))
            self.assertEqual(selected['operator'],operator)
            self.assertEqual(selected['family'],'p9983')
            scope=device_support.assess('SQK100-1',operator)
            self.assertTrue(scope['automatic_volte'])
            self.assertFalse(scope['owner_trial_pending_manual_acceptance'])
            self.assertEqual(variant_trials.plan('SQK100-1',operator)['hardware_acceptance'],'not_established_by_this_plan')

    def test_wrong_suffix_board_and_os_remain_blocked(self):
        for changed in ({'variant':'SQK100-99'},{'variant':'SQK100-3'},{'board_type':None},
                        {'board_type':'CLASSICATT'},{'os_version':'10.3.3.2163'}):
            with self.assertRaises(ValueError):policy.select(dict(FACTS,**changed),card('01'))

    def test_other_networks_and_bad_sim_identity_remain_blocked(self):
        for changed in (card('03'),dict(card('01'),kind=18),dict(card('01'),kind=True),
                        dict(card('01'),state='ABSENT'),dict(card('01'),imsi='unknown')):
            with self.assertRaises(ValueError):policy.select(FACTS,changed)

    def test_unknown_native_image_blocks_before_migration(self):
        phone=SimpleNamespace(geteuid=lambda:0,uname=lambda:('QNX',))
        with patch.object(installer,'os',phone),patch.object(installer.ctypes,'sizeof',return_value=4),\
             patch.object(installer.device_info,'read_identity',return_value=FACTS),\
             patch.object(installer,'identity',side_effect=AssertionError('unknown_native_image')),\
             patch.object(installer.migration,'inspect') as migrate:
            result=installer.probe()
        self.assertFalse(result['can_install'])
        self.assertEqual(result['scope_error'],'unknown_native_image')
        migrate.assert_not_called()

    def test_never_adopts_q10_or_other_suffix_legacy_backups(self):
        with patch.object(migration.os.path,'lexists',return_value=False):
            self.assertIsNone(migration.inspect(FACTS))
        for old in migration.BASES.values():
            with patch.object(migration.os.path,'lexists',side_effect=lambda p:p==old):
                with self.assertRaisesRegex(AssertionError,'unvalidated_legacy_installation'):
                    migration.inspect(FACTS)

    def test_trial_attach_policy_uses_the_existing_backup_transaction(self):
        for operator,desired in (('mobile',1),('unicom',0),('telecom',1)):
            selected={'family':'p9983','operator':operator}
            with patch.object(dca,'wait_policy_idle') as idle,\
                 patch.object(dca,'ensure_lte_mode') as lte,\
                 patch.object(dca,'set_usage',return_value={'policy_changed_boot':None}) as usage,\
                 patch.object(dca.n,'voice_policy',return_value=3):
                self.assertTrue(dca.prepare(selected))
            self.assertEqual(idle.call_count,2)
            lte.assert_called_once_with(selected)
            usage.assert_called_once_with(desired,selected)

    def test_exact_root_recipe_and_both_client_catalogs(self):
        stock,parts=root_images.recipe('SQK100-1')
        self.assertEqual(stock['id'],'stock-q10')
        self.assertEqual(parts['stock_sha256'],stock['extracted_sha256'])
        with self.assertRaises(Exception):root_images.recipe('SQK100-2')
        qml=(ROOT/'mobile/native/assets/main.qml').read_text(encoding='utf8')
        self.assertIn('volteController.compatibilityText',qml)
        row=json.loads((ROOT/'materials/device-support.json').read_text())['models']['SQK100-1']
        self.assertFalse(row['intake_20261108']['manual_tests_precompleted'])

if __name__=='__main__':unittest.main()
