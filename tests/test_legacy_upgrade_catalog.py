"""Real r21/r29 manifests must be recognized using the runtime serialization."""
from contextlib import ExitStack
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'device'))
import unified_install as installer
import profiles


class LegacyUpgradeCatalogTests(unittest.TestCase):
    def probe(self, current, active=False):
        candidate = json.loads((ROOT / 'materials/unified-payload.json').read_text())
        facts = {'variant': 'SQW100-4', 'board_type': 'WINDERMERE4ROW', 'os_version': '10.3.3.3216'}
        with ExitStack() as stack:
            patches = [patch.object(installer.os, 'geteuid', return_value=0, create=True),
                patch.object(installer.os, 'uname', return_value=('QNX',), create=True),
                patch.object(installer.ctypes, 'sizeof', return_value=4),
                patch.object(installer.device_info, 'read_identity', return_value=facts),
                patch.object(installer, 'identity', return_value=(facts, 'passport')),
                patch.object(installer, 'installed_management_schema', return_value=2),
                patch.object(installer.os.path, 'isfile', side_effect=lambda p: p == installer.BASE + '/payload.json'),
                patch.object(installer.s, 'phone_idle', return_value=True),
                patch.object(installer.u, 'setup'),
                patch.object(installer.s, 'load', side_effect=lambda p: current if p == installer.BASE + '/payload.json' else candidate),
                patch.object(installer.u, 'public_status', return_value={'manager_alive': active}),
                patch.object(installer.n, 'crypto_policy', return_value={'swcr_id': -1, 'crypto_support': 0}),
                patch.object(installer, 'with_sim_status', side_effect=lambda report, facts: report)]
            for item in patches:
                stack.enter_context(item)
            return installer.probe()

    def test_verified_releases_are_upgradable_only_after_stop(self):
        expected = {'r44': 'ef9208d0f19624f07d33512394c8337ec55c1072ad52310361e53539183bcd7d',
                    'r43': 'eedd9fe6e19b675219040231eb0298d1a8b7da750cfa7153a825843de43b1aff',
                    'r40': '3064c5836cac88a3cf3769e6ca882cd53b40b39a89fd62b30604af70e8bd8128',
                    'r37': '31e49226ef388bb1ba4d0070e78c3a270bdb67428c1f1d688b2a34eb6637deff',
                    'r36': '35303db01a8d71f3f8056102cc40bf2a972008420c11d9c33c604ff84d38ad62',
                    'r21': '14f12228c4306df69e797e1d26839bec7ac560e05b3fed690cf12d70957b7715',
                    'r29': 'a54ac20b79a9b5f9b923ac8ff8d26708d5cb738a5437ee7141994d7621163751',
                    'r32': 'a2ee5acadb44d651a7fef080961ce842faed9e02db10a674ed6ae88e06410942',
                    'r34': '2b0a38e9d0789328b02c165491be2542255e9df1e0e6742819dd522dd942abd3',
                    'r35': 'be1add90c8d89da2146bb3baac47aad435e03dcb28bf83bac7b3a09523ab067f'}
        candidate = json.loads((ROOT / 'materials/unified-payload.json').read_text())
        for release, digest in expected.items():
            previous = json.loads((ROOT / ('materials/unified-payload-' + release + '.json')).read_text())
            with self.subTest(release=release):
                self.assertEqual(hashlib.sha256(profiles.canonical(previous['files'])).hexdigest(), digest)
                self.assertIn(digest, installer.PREVIOUS_PAYLOADS)
                self.assertEqual(set(previous['files']), set(candidate['files']))
                changed = {name for name in previous['files'] if previous['files'][name] != candidate['files'][name]}
                self.assertLessEqual(changed, set(installer.UPDATE_FILES))
                self.assertTrue(self.probe(previous)['can_update'])
                running = self.probe(previous, active=True)
                self.assertTrue(running['update_available'])
                self.assertFalse(running['can_update'])

    def test_unknown_edited_map_is_not_admitted(self):
        previous = json.loads((ROOT / 'materials/unified-payload-r21.json').read_text())
        edited = copy.deepcopy(previous)
        edited['files']['device/unified_install.py'] = 'a' * 64
        result = self.probe(edited)
        self.assertFalse(result['update_available'])
        self.assertFalse(result['can_update'])


if __name__ == '__main__':
    unittest.main()
