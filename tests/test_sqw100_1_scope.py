"""Exact SQW100-1 admission, including non-expansion of other devices/MNCs."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'device')]
import carrier_policy as policy
import device_info
import device_support
import profiles
import unified_migrate
import variant_trials

FACTS = {'variant': 'SQW100-1', 'board_type': 'WINDERMEREEMEA', 'os_version': '10.3.3.3216'}
CARD = {'state': 'READY', 'kind': 2, 'mcc': '460', 'mnc': '07', 'imsi': '460' + '07' + '12345' * 2}

class ExactPassportScope(unittest.TestCase):
    def test_only_observed_variant_board_and_sim_route_are_admitted(self):
        result = policy.select(FACTS, CARD)
        self.assertEqual(result['operator'], 'mobile')
        self.assertEqual(result['request']['profile']['carrier']['mncs'], ['07'])
        for field, value in (('board_type', 'WINDERMERE4ROW'), ('variant', 'SQW100-99'),
                             ('os_version', '10.3.3.2205')):
            with self.subTest(field=field), self.assertRaises(ValueError):
                policy.select(dict(FACTS, **{field: value}), CARD)
        for mnc in ('02', '08', '000', '001', '007'):
            with self.subTest(mnc=mnc), self.assertRaisesRegex(ValueError, 'carrier_not_validated'):
                policy.select(FACTS, dict(CARD, mnc=mnc, imsi='460' + mnc + '1234512345'))
        with self.assertRaisesRegex(ValueError, 'sim_route_unsupported'):
            policy.select(FACTS, dict(CARD, kind=18))

    def test_unicom_requires_exact_home_identity_board_and_USIM(self):
        card = dict(CARD, mnc='01', imsi='46001' + '12345' * 2)
        selected = policy.select(FACTS, card)
        self.assertEqual(selected['operator'], 'unicom')
        self.assertEqual(selected['request']['profile']['carrier']['mncs'], ['01'])
        for changes in ({'kind': 18}, {'kind': 1}, {'imsi': CARD['imsi']}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                policy.select(FACTS, dict(card, **changes))
        with self.assertRaises(ValueError):
            policy.select(dict(FACTS, board_type='WINDERMERE4ROW'), card)

    def test_telecom_voice_data_admission_keeps_identity_and_SMS_limits(self):
        card = dict(CARD, kind=6, mnc='11', imsi='46011' + '12345' * 2)
        result = policy.select(FACTS, card)
        self.assertEqual(result['operator'], 'telecom')
        self.assertEqual(result['request']['profile']['carrier']['mncs'], ['11'])
        self.assertCountEqual(result['request']['profile']['carrier']['data_apns'], ['ctnet', 'ctlte'])
        for change in ({'kind': 22}, {'imsi': CARD['imsi']}, {'mnc': '03'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                policy.select(FACTS, dict(card, **change))
        with self.assertRaises(ValueError):
            policy.select(dict(FACTS, board_type='WINDERMERE4ROW'), card)
        intake = device_support.catalog()['SQW100-1']['intake']
        self.assertFalse(intake['telecom_SMS_acceptance_complete'])
        self.assertTrue(intake['telecom_SMS_does_not_block_activation'])
        self.assertEqual(len(intake['telecom_known_issues']), 2)

    def test_mobile00_requires_exact_identity_and_keeps_other_models_closed(self):
        card = dict(CARD, mnc='00', imsi='46000' + '12345' * 2)
        selected = policy.select(FACTS, card)
        self.assertEqual(selected['operator'], 'mobile')
        self.assertEqual(selected['request']['profile']['carrier']['mncs'], ['00'])
        for changes in ({'kind':18}, {'kind':1}, {'imsi':CARD['imsi']}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                policy.select(FACTS, dict(card, **changes))
        for changes in ({'board_type':'WINDERMERE4ROW'}, {'os_version':'10.3.3.2205'},
                        {'variant':'SQW100-99'}, {'variant':'SQC100-4','board_type':'WINDERMEREEMEA'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                policy.select(dict(FACTS, **changes), card)
        self.assertIn('460-00', device_support.assess('SQW100-1','mobile')['admitted_home_plmns'])
        self.assertEqual(device_support.assess('SQW100-1')['evidence_status']['mobile'],'passed')

    def test_number_portability_does_not_override_the_current_sim_identity(self):
        ported = dict(CARD, previous_operator='unicom', displayed_operator='unicom')
        self.assertEqual(policy.select(FACTS, ported), policy.select(FACTS, CARD))
        with self.assertRaisesRegex(ValueError, 'sim_identity_unavailable'):
            policy.select(FACTS, dict(ported, imsi='460' + '01' + '12345' * 2))

    def test_46007_is_not_implicitly_enabled_on_previous_models(self):
        for variant in policy.MODELS:
            facts = dict(FACTS, variant=variant, board_type=policy.MODELS[variant][1])
            self.assertEqual(policy.ADMITTED_MNCS[variant], ('00','01','07','11'))
            self.assertEqual(policy.select(facts, CARD)['operator'],'mobile')

    def test_unknown_legacy_installation_is_never_adopted_as_sqw100_4(self):
        with patch.object(unified_migrate.os.path, 'lexists', return_value=False):
            self.assertIsNone(unified_migrate.inspect(FACTS))
        for directory in unified_migrate.BASES.values():
            with patch.object(unified_migrate.os.path, 'lexists', side_effect=lambda p: p == directory):
                with self.assertRaisesRegex(AssertionError, 'unvalidated_legacy_installation'):
                    unified_migrate.inspect(FACTS)

    def test_old_standalone_passport_provider_gate_remains_closed(self):
        identity = device_info.identify(FACTS)
        self.assertEqual(identity['family'], 'passport')
        self.assertFalse(device_info.provider_lifecycle_supported(identity))

    def test_desktop_and_phone_catalog_admit_observed_carriers_with_SMS_limits(self):
        mobile = device_support.assess('SQW100-1', 'mobile')
        self.assertTrue(mobile['automatic_volte'])
        self.assertEqual(mobile['validated_home_plmns'], ['460-00', '460-01', '460-07', '460-11'])
        self.assertIn('460-07', device_support.describe(mobile))
        self.assertTrue(device_support.assess('SQW100-1', 'telecom')['automatic_volte'])
        self.assertEqual(variant_trials.plan('SQW100-1', 'telecom')['route'], 'automatic_supported')
        self.assertEqual(mobile['evidence_status']['telecom'],'issues')
        self.assertEqual(variant_trials.plan('SQW100-1', 'mobile')['validated_home_plmns'], ['460-00', '460-01', '460-07', '460-11'])
        self.assertTrue(device_support.assess('SQW100-1', 'unicom')['automatic_volte'])
        self.assertEqual(variant_trials.plan('SQW100-1', 'unicom')['route'], 'automatic_supported')

    def test_home_page_shows_exact_scope(self):
        page = (ROOT/'mobile/native/assets/main.qml').read_text(encoding='utf8')
        self.assertIn('volteController.compatibilityText',page)
        matrix=json.loads((ROOT/'materials/compatibility-matrix.json').read_text(encoding='utf8'))
        self.assertIn('460-07',matrix['models']['SQW100-1']['summary']['zh'])

    def test_actual_previous_BAR_payloads_are_admitted_with_runtime_canonical_format(self):
        import unified_install
        for label in ('r23', 'r24', 'r25', 'r26', 'r27', 'r28', 'sqw100-1-mobile00-trial'):
            previous = json.loads((ROOT / ('materials/unified-payload-' + label + '.json')).read_text())
            current = json.loads((ROOT / 'materials/unified-payload.json').read_text())
            runtime_digest = hashlib.sha256(profiles.canonical(previous['files'])).hexdigest()
            wrong_digest = hashlib.sha256(profiles.canonical(previous['files']).rstrip(b'\n')).hexdigest()
            self.assertIn(runtime_digest, unified_install.PREVIOUS_PAYLOADS)
            self.assertNotIn(wrong_digest, unified_install.PREVIOUS_PAYLOADS)
            self.assertEqual(set(previous['files']), set(current['files']))
            changed = {name for name in previous['files'] if previous['files'][name] != current['files'][name]}
            self.assertLessEqual(changed, set(unified_install.UPDATE_FILES))

    def test_backend_release_label_matches_the_actual_product_revision(self):
        project = json.loads((ROOT / 'project.json').read_text(encoding='utf8'))
        payload = json.loads((ROOT / 'materials/unified-payload.json').read_text(encoding='utf8'))
        self.assertEqual(payload['desktop_revision'], project['desktop_revision'])
        self.assertEqual(payload['version'], project['version'])

if __name__ == '__main__':
    unittest.main()
