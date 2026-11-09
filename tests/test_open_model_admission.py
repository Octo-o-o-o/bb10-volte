"""Every advertised entry reaches selection regardless of its evidence category."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'device'),str(ROOT/'tools')]
import carrier_policy as policy
import device_support
import package_mobile

class OpenAdmissionTests(unittest.TestCase):
    def test_all_catalog_models_and_home_networks_select_without_fabricating_evidence(self):
        matrix=json.loads((ROOT/'materials/compatibility-matrix.json').read_text(encoding='utf8'))
        self.assertEqual(len(matrix['models']),16)
        self.assertEqual(set(matrix['models']),set(policy.MODELS))
        for variant,(family,board) in policy.MODELS.items():
            facts=dict(variant=variant,board_type=board,os_version=policy.OS_VERSION)
            for mnc,carrier in policy.CARRIERS.items():
                card=dict(state='READY',kind=6 if mnc=='11' else 2,mcc='460',mnc=mnc,imsi='460'+mnc+'12345'*2)
                with self.subTest(variant=variant,mnc=mnc):
                    selected=policy.select(facts,card)
                    self.assertEqual(selected['operator'],carrier[0])
                    self.assertEqual(selected['family'],family)
                    self.assertEqual(selected['request']['profile']['carrier']['mncs'],[mnc])
                    self.assertTrue(device_support.assess(variant,carrier[0])['automatic_volte'])
                    self.assertFalse(matrix['models'][variant]['new_release_hardware_acceptance'])
        self.assertEqual(matrix['models']['SQC100-4']['status']['mobile'],'failed')
        self.assertEqual(matrix['models']['SQK100-2']['status']['unicom'],'untested')
        self.assertEqual(matrix['models']['SQK100-1']['status']['unicom'],'passed')
        self.assertFalse(device_support.assess('SQK100-2')['root_recipe_eligible'])
        self.assertTrue(device_support.assess('SQK100-2')['automatic_volte'])

    def test_frontends_use_same_evidence_and_signed_mobile_bundle(self):
        matrix=json.loads((ROOT/'materials/compatibility-matrix.json').read_text(encoding='utf8'))
        website=json.loads((ROOT/'website/src/compatibility.json').read_text(encoding='utf8'))
        for row in website['models']:
            self.assertEqual(row['evidence_status'],matrix['models'][row['variant']]['status'])
            self.assertEqual(row['evidence_summary'],matrix['models'][row['variant']]['summary'])
        import build_windows
        self.assertIn('materials/compatibility-matrix.json',build_windows.runtime_data())
        import zipfile
        with zipfile.ZipFile(ROOT/'assets/mobile/bb10-volte.bar') as bar:
            member=next(n for n in bar.namelist() if n.endswith('/materials/compatibility-matrix.json'))
            self.assertEqual(json.loads(bar.read(member)),matrix)

if __name__=='__main__':unittest.main()
