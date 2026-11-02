"""Native daemons must traverse fresh runtime paths under a private umask."""
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'device'))
import unified_install as installer


@unittest.skipIf(os.name == 'nt', 'POSIX directory mode semantics required')
class NativeRuntimePermissionsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = os.path.realpath(temporary.name)
        old = os.umask(0o077)
        try:
            os.mkdir(self.base + '/runtime', 0o755)
            os.mkdir(self.base + '/runtime/carrier', 0o755)
            os.mkdir(self.base + '/backup', 0o700)
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(os.stat(self.base + '/runtime').st_mode), 0o700)
        self.real_lstat = os.lstat
        # Desktop tests run without Root; retain actual filesystem types/modes
        # and model only the target phone's root ownership.
        def owned(path, *args, **kwargs):
            value = self.real_lstat(path, *args, **kwargs)
            return types.SimpleNamespace(st_mode=value.st_mode, st_uid=0)
        self.owner = patch.object(installer.os, 'lstat', side_effect=owned)
        self.owner.start()
        self.addCleanup(self.owner.stop)
        self.base_patch = patch.object(installer, 'BASE', self.base)
        self.base_patch.start()
        self.addCleanup(self.base_patch.stop)

    def test_real_umask_created_tree_becomes_traversable_without_exposing_backup(self):
        installer.runtime_directory_permissions(self.base)
        for suffix in ('', '/runtime', '/runtime/carrier'):
            self.assertEqual(stat.S_IMODE(os.stat(self.base + suffix).st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(os.stat(self.base + '/backup').st_mode), 0o700)
        with patch.object(installer.os, 'chmod') as chmod:
            installer.runtime_directory_permissions(self.base)
        chmod.assert_not_called()

    def test_symlink_child_is_rejected_without_opening_other_directories(self):
        os.rmdir(self.base + '/runtime/carrier')
        os.symlink(self.base + '/backup', self.base + '/runtime/carrier')
        with patch.object(installer.os, 'chmod') as chmod:
            with self.assertRaisesRegex(AssertionError, 'runtime_directory_changed'):
                installer.runtime_directory_permissions(self.base)
        chmod.assert_not_called()

    def test_foreign_owner_is_rejected_before_any_permission_change(self):
        with patch.object(installer.os, 'lstat', return_value=types.SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=12345)), \
                patch.object(installer.os, 'chmod') as chmod:
            with self.assertRaisesRegex(AssertionError, 'runtime_directory_changed'):
                installer.runtime_directory_permissions(self.base)
        chmod.assert_not_called()

    def test_writable_child_is_rejected_before_root_or_parent_are_opened(self):
        os.chmod(self.base + '/runtime/carrier', 0o777)
        with patch.object(installer.os, 'chmod') as chmod:
            with self.assertRaisesRegex(AssertionError, 'runtime_directory_permissions_changed'):
                installer.runtime_directory_permissions(self.base)
        chmod.assert_not_called()


if __name__ == '__main__':
    unittest.main()
