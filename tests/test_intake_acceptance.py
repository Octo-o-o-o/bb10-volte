"""Acceptance cannot be inferred from registration or a mismatched receipt."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import intake_acceptance as intake


class IntakeEvidence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scope = {'variant':'SQW100-1','board':'WINDERMEREEMEA',
            'os_version':'10.3.3.3216','home_plmn':'460-00','SIM_type':'USIM_without_ISIM'}
        self.value = dict(self.scope, observed=True, unknown=None, failure=False, owner_allows_SMS=True)
        self.path = self.root / 'receipt.json'
        self.save_source()
        self.manifest = {'schema':1,'scope':self.scope,'sources':{'run':{
            'path':'receipt.json','sha256':hashlib.sha256(self.path.read_bytes()).hexdigest()}},
            'checks':{k:{'evidence':[{'source':'run','pointer':'/observed'}],
                'scope_note':'Fixture; no real hardware acceptance.'} for k in intake.CHECKS}}
        self.admission = {'runtime_scope_enabled':True,'explicit_product_exclusion':False}

    def save_source(self):
        self.path.write_text(json.dumps(self.value), encoding='utf8')
        if hasattr(self, 'manifest'):
            self.manifest['sources']['run']['sha256'] = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def evaluate(self):
        return intake.evaluate(self.manifest, self.root, self.admission)

    def test_complete_evidence_can_be_registered(self):
        self.assertEqual(self.evaluate()['status'], 'adapted')

    def test_registration_alone_does_not_mark_success(self):
        self.manifest['checks'] = {'normal_boot_registration':self.manifest['checks']['normal_boot_registration']}
        result = self.evaluate()
        self.assertEqual(result['status'], 'incomplete')
        self.assertIn('two_way_audio', result['missing_checks'])
        self.assertIn('normal_stop_restore', result['missing_checks'])

    def test_unknown_is_not_success(self):
        self.manifest['checks']['two_way_audio']['evidence'][0]['pointer'] = '/unknown'
        self.assertEqual(self.evaluate()['status'], 'incomplete')

    def test_failure_is_not_unknown(self):
        self.manifest['checks']['incoming_call']['evidence'][0]['pointer'] = '/failure'
        self.assertEqual(self.evaluate()['failed_checks'], ['incoming_call'])

    def test_hash_tampering_is_rejected(self):
        self.path.write_bytes(self.path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'evidence_hash_changed'): self.evaluate()

    def test_each_scope_dimension_is_bound(self):
        for key, value in (('variant','SQW100-4'),('board','WINDERMERE4ROW'),
                           ('os_version','10.3.3.2205'),('home_plmn','460-01'),('SIM_type','ISIM')):
            with self.subTest(key=key):
                old = self.value[key]; self.value[key] = value; self.save_source()
                with self.assertRaisesRegex(ValueError, 'evidence_.*mismatch'): self.evaluate()
                self.value[key] = old; self.save_source()

    def test_unknown_runtime_scope_requires_integration(self):
        self.admission['runtime_scope_enabled'] = False
        result = self.evaluate()
        self.assertEqual(result['status'], 'validated_pending_integration')
        self.assertFalse(result['runtime_admission_modified'])

    def test_explicit_product_exclusion_remains_blocked(self):
        self.admission['explicit_product_exclusion'] = True
        self.assertEqual(self.evaluate()['status'], 'blocked')

    def test_known_SMS_limitations_require_exact_evidence(self):
        self.manifest['checks']['short_SMS']['evidence'][0]['pointer'] = '/failure'
        self.manifest['known_SMS_limitations'] = [{'code':'known_sms_state_issue','checks':['short_SMS'],
            'owner_authorization':{'source':'run','pointer':'/owner_allows_SMS'}}]
        result = self.evaluate()
        self.assertEqual(result['status'], 'adapted_with_SMS_limitations')
        self.assertEqual(result['checks']['short_SMS']['result'], 'failed')
        self.value['owner_allows_SMS'] = False; self.save_source()
        with self.assertRaisesRegex(ValueError, 'missing_owner_authorization'): self.evaluate()

    def test_voice_and_identity_cannot_be_waived_as_SMS(self):
        for name in ('two_way_audio','identity_root_native','normal_stop_restore'):
            self.manifest['known_SMS_limitations'] = [{'code':'fake_issue','checks':[name],
                'owner_authorization':{'source':'run','pointer':'/owner_allows_SMS'}}]
            with self.assertRaisesRegex(ValueError, 'only_SMS_limitations'): self.evaluate()

    def test_paths_cannot_escape_evidence_root(self):
        for name in ('../receipt.json','/receipt.json','sub/../receipt.json',r'sub\receipt.json','x:receipt.json'):
            self.manifest['sources']['run']['path'] = name
            with self.assertRaisesRegex(ValueError, 'unsafe_evidence_path'): self.evaluate()

    def test_boolean_result_is_required(self):
        for value in ('true',1,[],{}):
            self.value['observed'] = value; self.save_source()
            with self.assertRaisesRegex(ValueError, 'evidence_value_not_boolean'): self.evaluate()

    def test_registry_keeps_earlier_verdicts_and_deduplicates(self):
        path = self.root / 'registry.json'; report = self.evaluate(); fingerprint = 'a' * 64
        self.assertTrue(intake.register(path, report, fingerprint))
        self.assertFalse(intake.register(path, report, fingerprint))
        changed = copy.deepcopy(report); changed['status'] = 'incomplete'
        self.assertTrue(intake.register(path, changed, fingerprint))
        values = json.loads(path.read_text())['records']
        self.assertEqual([x['verdict']['status'] for x in values], ['adapted','incomplete'])

    def test_registry_lock_prevents_concurrent_mutation(self):
        path = self.root / 'registry.json'; lock = self.root / 'registry.json.lock'
        lock.write_text('another collector')
        with self.assertRaises(FileExistsError): intake.register(path, self.evaluate(), 'a' * 64)
        self.assertTrue(lock.exists()); self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
