"""Shared desktop/mobile trial boundaries and migration source contracts."""
import importlib.util
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'device'), str(ROOT / 'tools')]
import package_mobile
import profiles
import unified_install
import variant_trials
import compatibility
from test_mobile_runtime import WORKER
legacy_spec = importlib.util.spec_from_file_location('mobile_legacy_trial_test', ROOT / 'mobile/runtime/legacy_entry.py')
LEGACY = importlib.util.module_from_spec(legacy_spec)
with patch.dict(sys.modules, {'entry': WORKER.e}):
    legacy_spec.loader.exec_module(LEGACY)


class MobileTrialIntegration(unittest.TestCase):
    def setUp(self):
        self.blobs = package_mobile.trial_inputs()
        self.catalog = json.loads(self.blobs['materials/variant-trials.json'])

    def profile(self, item):
        return json.loads(self.blobs['profiles/' + item['profile_id'] + '.json'])

    def test_phone_choices_match_the_exact_desktop_catalog(self):
        cases = self.catalog['cases']
        self.assertEqual(len(cases), 19)
        self.assertEqual(sum(c['route'] == 'manual_candidate' for c in cases), 13)
        page = (ROOT / 'mobile/native/assets/Experimental.qml').read_text(encoding='utf-8')
        options = re.findall(r'value: "(variant-trial-[^"]+)"', page)
        self.assertEqual(set(options), {c['profile_id'] for c in cases})
        self.assertEqual(len(options), len(cases))
        for item in cases:
            profile = self.profile(item)
            self.assertEqual(profile, variant_trials.profile(item['variant'], item['operator']))
            self.assertFalse(profile['runtime']['autostart'])
            self.assertNotIn('lte_attach', profile)

    def test_generic_profiles_cannot_bypass_trial_hash_and_variant_gates(self):
        profile = profiles.default()
        for variant in ('SQC100-3', 'SQW100-1', 'SQN100-1', 'SQN100-9', None):
            for action in ('legacy-inspect', 'legacy-install', 'legacy-start'):
                with self.subTest(variant=variant, action=action):
                    with self.assertRaisesRegex(WORKER.e.MobileError, 'trial_exact_profile_required'):
                        WORKER.validate_legacy_target(profile, {'variant': variant}, action, '/snapshot')
        for variant in ('SQN100-3', 'SQC100-2', 'SQW100-4'):
            WORKER.validate_legacy_target(profile, {'variant': variant}, 'legacy-inspect', '/snapshot')

    def test_exact_trial_target_and_read_only_passport_are_server_side(self):
        with patch.object(WORKER, 'load', return_value=self.catalog):
            for item in self.catalog['cases']:
                profile = self.profile(item)
                facts = {'variant': item['variant']}
                WORKER.validate_legacy_target(profile, facts, 'legacy-inspect', '/snapshot')
                with self.assertRaisesRegex(WORKER.e.MobileError, 'trial_exact_variant_required'):
                    WORKER.validate_legacy_target(profile, {'variant': 'SQC100-99'}, 'legacy-inspect', '/snapshot')
                for action in ('legacy-install', 'legacy-start', 'legacy-stop'):
                    if item['route'] == 'manual_candidate':
                        WORKER.validate_legacy_target(profile, facts, action, '/snapshot')
                    else:
                        with self.assertRaisesRegex(WORKER.e.MobileError, 'trial_read_only_lifecycle_pending'):
                            WORKER.validate_legacy_target(profile, facts, action, '/snapshot')

    def test_profile_selection_cannot_import_unlisted_shared_file(self):
        with patch.object(WORKER, 'load', return_value=self.catalog) as read:
            with self.assertRaisesRegex(WORKER.e.MobileError, 'invalid_profile'):
                WORKER.profile_for({'experimental': True, 'profile_id': '../untrusted'}, '/snapshot')
            self.assertEqual(read.call_count, 1)

    def test_previous_releases_can_replace_only_reviewed_files(self):
        origins = json.loads((ROOT / 'materials/mobile-upgrade-origins.json').read_text())['origins']
        current = json.loads((ROOT / 'materials/unified-payload.json').read_text())['files']
        self.assertEqual({o['label'] for o in origins}, {'desktop-r14', 'desktop-r15', 'mobile-v5'})
        for origin in origins:
            fingerprint = unified_install.n.digest(profiles.canonical(origin['files']))
            self.assertEqual(fingerprint, origin['fingerprint'])
            self.assertIn(fingerprint, unified_install.PREVIOUS_PAYLOADS)
            self.assertEqual(set(origin['files']), set(current))
            changed = {name for name in current if current[name] != origin['files'][name]}
            self.assertTrue(changed)
            self.assertLessEqual(changed, set(unified_install.UPDATE_FILES))
            self.assertFalse(any(name.endswith('.so') for name in changed))

    def test_start_rechecks_actual_preflight_and_installed_profile(self):
        profile = self.profile(self.catalog['cases'][0])
        with patch.object(profiles, 'installed_request', return_value=profiles.request(profile, True)), \
                patch.object(compatibility, 'require', side_effect=RuntimeError('native changed')) as check:
            with self.assertRaisesRegex(RuntimeError, 'native changed'):
                LEGACY.require_start(profile)
            check.assert_called_once_with('start', profile, True)
        with patch.object(profiles, 'installed_request', return_value=profiles.request()), \
                patch.object(compatibility, 'require') as check:
            with self.assertRaisesRegex(WORKER.e.MobileError, 'legacy_profile_changed'):
                LEGACY.require_start(profile)
            check.assert_not_called()

    def test_failed_restoration_can_retry_stop_without_enabling_other_writes(self):
        report = {'can_restore': True, 'installation': {'state': 'recovery_required', 'payload_verified': True}}
        self.assertEqual(LEGACY.management_actions(report), {'can_stop': True, 'can_uninstall': False})
        for state in ('conflict', 'interrupted', 'absent'):
            report['installation']['state'] = state
            self.assertFalse(any(LEGACY.management_actions(report).values()))
        report['installation']['state'] = 'recovery_required'
        for key, target in (('can_restore', report), ('payload_verified', report['installation'])):
            target[key] = False
            self.assertFalse(any(LEGACY.management_actions(report).values()))
            target[key] = True


if __name__ == '__main__':
    unittest.main()
