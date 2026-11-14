"""Exact Classic NA admission keeps known SMS failure separate from support."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'device')]
import carrier_policy as policy
import device_support
import profiles
import unified_install
import unified_migrate
import variant_trials

FACTS={'variant':'SQC100-4','board_type':'CLASSICNA','os_version':'10.3.3.3216'}
CARD={'state':'READY','kind':6,'mcc':'460','mnc':'11','imsi':'46011'+'12345'*2}

class ExactClassicNAScope(unittest.TestCase):
    def test_observed_telecom_USIM_CSIM_route_and_identity_guards(self):
        result=policy.select(FACTS,CARD)
        self.assertEqual(result['operator'],'telecom')
        self.assertEqual(result['request']['profile']['carrier']['mncs'],['11'])
        for change in ({'variant':'SQC100-3'},{'board_type':'CLASSICATT'},
                       {'board_type':None},{'os_version':'10.3.3.3057'}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                policy.select(dict(FACTS,**change),CARD)
        for change in ({'kind':22},{'kind':4},{'mcc':'001'},{'mnc':'03'},
                       {'mnc':'01'},{'mnc':'00'},{'mnc':'07'},
                       {'imsi':'46001'+'12345'*2},{'state':'ABSENT'}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                policy.select(FACTS,dict(CARD,**change))

    def test_no_legacy_adoption_by_family(self):
        with patch.object(unified_migrate.os.path,'lexists',return_value=False):
            self.assertIsNone(unified_migrate.inspect(FACTS))
        for directory in unified_migrate.BASES.values():
            with patch.object(unified_migrate.os.path,'lexists',side_effect=lambda p:p==directory):
                with self.assertRaisesRegex(AssertionError,'unvalidated_legacy_installation'):
                    unified_migrate.inspect(FACTS)

    def test_desktop_and_phone_routes_keep_unverified_carriers_closed(self):
        for operator in ('mobile','unicom','telecom'):
            self.assertEqual(variant_trials.plan('SQC100-4',operator)['route'],'automatic_supported')
        self.assertEqual(device_support.assess('SQC100-4')['evidence_status'],{'mobile':'failed','unicom':'failed','telecom':'issues'})
        page=(ROOT/'mobile/native/assets/main.qml').read_text(encoding='utf8')
        self.assertIn('volteController.compatibilityText',page)

    def test_owner_acceptance_does_not_relabel_SMS_as_passed(self):
        record=json.loads((ROOT/'materials/sqc100-4-intake-2026-11-06.json').read_text(encoding='utf8'))
        self.assertTrue(record['automatic_adaptation_admitted'])
        self.assertTrue(record['acceptance']['owner_explicitly_authorized'])
        self.assertFalse(record['acceptance']['SMS_functional_pass'])
        self.assertFalse(record['operator_cases']['telecom']['desktop']['sms_short_send_receive'])
        self.assertIsNone(record['operator_cases']['telecom']['desktop']['sms_long_and_duplicate'])
        self.assertFalse(record['hardware_acceptance_complete'])

    def test_closed_Unicom_route_rejects_old_and_generic_profiles_but_keeps_restore(self):
        import compatibility
        from test_variant_trials import facts_for
        facts=facts_for('SQC100-4','unicom')
        generic=profiles.default(); generic['runtime']['autostart']=False
        report=compatibility.evaluate(facts,generic,True)
        self.assertTrue(report['can_restore'])
        self.assertNotIn('operator_not_supported',[c['code'] for c in report['checks']])
        selected=policy.select(FACTS,dict(CARD,kind=2,mnc='01',imsi='46001'+'12345'*2))
        self.assertEqual(selected['operator'],'unicom')
        self.assertEqual(device_support.assess('SQC100-4','unicom')['evidence_status']['unicom'],'failed')

    def test_previous_public_payload_upgrade_uses_runtime_canonical_hash(self):
        before=json.loads((ROOT/'materials/unified-payload-r26.json').read_text())
        current=json.loads((ROOT/'materials/unified-payload.json').read_text())
        digest=hashlib.sha256(profiles.canonical(before['files'])).hexdigest()
        self.assertIn(digest,unified_install.PREVIOUS_PAYLOADS)
        changes={name for name in before['files'] if before['files'][name]!=current['files'][name]}
        self.assertLessEqual(changes,set(unified_install.UPDATE_FILES))
        self.assertIn('device/ims_image.py',changes)
        # r44 retained the reviewed r36 parent service; r45 updates only the MT signaling image/service selection.
        parent=json.loads((ROOT/'materials/unified-payload-r36.json').read_text())
        r44=json.loads((ROOT/'materials/unified-payload-r44.json').read_text())
        self.assertEqual(r44['files']['device/unified_service.py'],parent['files']['device/unified_service.py'])
        r45_changes={name for name in r44['files'] if r44['files'][name]!=current['files'][name]}
        self.assertEqual(r45_changes,{'device/ims_image.py','device/service.py','device/unified_install.py','device/unified_service.py'})

    def test_other_exact_model_carrier_admission_is_preserved(self):
        self.assertEqual(policy.VALIDATED_MNCS['SQW100-1'],('00','01','07','11'))
        for variant in ('SQN100-3','SQC100-2','SQW100-4'):
            self.assertEqual(policy.VALIDATED_MNCS[variant],('00','01','07','11'))

if __name__=='__main__':unittest.main()
