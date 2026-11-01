"""First addon installation on a freshly flashed AutoRoot v4 phone."""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'device'))
import unified_install as installer


class FreshRootInstallationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.base = self.root / 'payload'
        self.addon = self.root / 'addons' / 'bb10-unified-volte'
        self.base.mkdir()
        (self.base / 'device').mkdir()
        (self.base / 'backup').mkdir()
        self.script = b'#!/bin/sh\nexit 0\n'
        (self.base / 'device/unified_boot.sh').write_bytes(self.script)
        (self.base / 'install-pending.json').write_text(json.dumps({
            'owner': installer.policy.OWNER, 'phase': 'awaiting_desktop_backup',
            'variant': 'SQW100-4', 'root_kind': 'autoroot-v4'}))
        (self.base / 'backup/manifest.json').write_text('{}')
        original_isfile = installer.os.path.isfile
        stack = ExitStack()
        self.addCleanup(stack.close)
        for item in (patch.object(installer, 'BASE', str(self.base)),
                     patch.object(installer, 'ADDON', str(self.addon)),
                     patch.object(installer.os.path, 'isfile', side_effect=lambda name:
                         name == '/tmp/root.done' or original_isfile(name)),
                     patch.object(installer, 'identity', return_value=({'variant': 'SQW100-4'}, 'passport')),
                     patch.object(installer.s, 'phone_idle', return_value=True),
                     patch.object(installer.u, 'setup'), patch.object(installer.u, 'verify'),
                     patch.object(installer.u, 'boot_token', return_value=['fresh-boot']),
                     patch.object(installer.migration, 'quiesce', return_value=None),
                     patch.object(installer.n, 'read', side_effect=lambda name: Path(name).read_bytes()),
                     patch.object(installer.n, 'command', return_value=b'')):
            stack.enter_context(item)

    def test_fresh_root_probe_is_read_only_and_first_activation_installs_boot_hook(self):
        before = sorted(path.relative_to(self.root) for path in self.root.rglob('*'))
        self.assertEqual(installer.root_kind({'variant': 'SQW100-4'}), 'autoroot-v4')
        self.assertEqual(sorted(path.relative_to(self.root) for path in self.root.rglob('*')), before)
        result = installer.activate()
        self.assertTrue(result['installed'])
        self.assertTrue(result['reboot_required'])
        self.assertEqual((self.addon / 'init/start.sh').read_bytes(), self.script)
        self.assertTrue((self.base / 'enabled').is_file())
        self.assertFalse((self.base / 'install-pending.json').exists())

    def test_existing_addons_and_their_contents_are_preserved(self):
        self.addon.parent.mkdir()
        other = self.addon.parent / 'another-addon'
        other.write_bytes(b'owner content')
        self.assertTrue(installer.activate()['installed'])
        self.assertEqual(other.read_bytes(), b'owner content')

    def test_file_in_place_of_parent_blocks_probe_and_activation(self):
        self.addon.parent.write_bytes(b'owner content')
        for action in (lambda: installer.root_kind({'variant': 'SQW100-4'}), installer.activate):
            with self.assertRaisesRegex(AssertionError, 'root_addon_directory_changed'):
                action()
        self.assertEqual(self.addon.parent.read_bytes(), b'owner content')
        self.assertFalse((self.base / 'migration.json').exists())
        self.assertFalse((self.base / 'enabled').exists())

    def test_linked_parent_is_rejected_before_any_activation_write(self):
        self.addon.parent.mkdir()
        with patch.object(installer.os.path, 'islink', side_effect=lambda name: name == str(self.addon.parent)):
            with self.assertRaisesRegex(AssertionError, 'root_addon_directory_changed'):
                installer.activate()
        self.assertFalse((self.base / 'migration.json').exists())
        self.assertFalse(self.addon.exists())


if __name__ == '__main__':
    unittest.main()
