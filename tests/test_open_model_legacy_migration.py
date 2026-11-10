"""Open model admission must not guess cross-device legacy recovery paths."""
from pathlib import Path
import hashlib
import json
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'device'))
import carrier_policy as policy
import profiles
import unified_install as installer
import unified_migrate as migration


class OpenModelLegacyMigrationTests(unittest.TestCase):
    def test_every_admitted_model_can_check_a_fresh_phone(self):
        with patch.object(migration.os.path, 'lexists', return_value=False), \
             patch.object(migration.os.path, 'exists', return_value=False):
            for variant in policy.MODELS:
                with self.subTest(variant=variant):
                    self.assertIsNone(migration.inspect({'variant': variant}))

    def test_unrecognized_legacy_files_block_each_unmapped_model(self):
        for variant in set(policy.MODELS) - set(migration.BASES):
            for legacy_path in migration.BASES.values():
                with self.subTest(variant=variant, legacy_path=legacy_path), \
                     patch.object(migration.os.path, 'lexists', side_effect=lambda path: path == legacy_path), \
                     patch.object(migration.s, 'load') as load:
                    with self.assertRaisesRegex(AssertionError, 'unvalidated_legacy_installation'):
                        migration.inspect({'variant': variant})
                    load.assert_not_called()

    def test_unknown_model_is_not_admitted_as_a_fresh_phone(self):
        with patch.object(migration.os.path, 'lexists', return_value=False):
            with self.assertRaisesRegex(ValueError, 'unsupported_model_or_os'):
                migration.inspect({'variant': 'SQC100-99'})

    def test_released_r43_service_remains_eligible_for_safe_update(self):
        prior = json.loads((ROOT / 'materials/unified-payload-r43.json').read_text(encoding='ascii'))
        digest = hashlib.sha256(profiles.canonical(prior['files'])).hexdigest()
        self.assertIn(digest, installer.PREVIOUS_PAYLOADS)
        changed = {name for name, expected in prior['files'].items()
                   if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected}
        self.assertTrue(changed)
        self.assertTrue(changed <= set(installer.UPDATE_FILES))


if __name__ == '__main__':
    unittest.main()
