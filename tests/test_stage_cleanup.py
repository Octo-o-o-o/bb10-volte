"""Real temporary trees verify that cleanup never recurses into unknown files."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import stage_cleanup as c


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name) / 'q10_volte_stage_123456abcdef'
        for p in (self.base / 'device', self.base / 'driver'):
            p.mkdir(parents=True)
        self.names = ['stage-cleanup.py', 'profile-request.json', 'device/native.py']
        for name in self.names:
            (self.base / name).write_text('generated file')
        self.parent = patch.object(c, 'ROOT_PARENT', str(Path(self.tmp.name)))
        self.parent.start()
        self.addCleanup(self.parent.stop)

    def test_exact_generated_tree_is_removed(self):
        self.assertTrue(c.cleanup(str(self.base), self.names)['stage_removed'])
        self.assertFalse(self.base.exists())

    def test_unknown_file_preserves_every_file(self):
        (self.base / 'device/owner.txt').write_text('keep')
        with self.assertRaises(AssertionError):
            c.cleanup(str(self.base), self.names)
        self.assertTrue(all((self.base / n).exists() for n in self.names))
        self.assertTrue((self.base / 'device/owner.txt').exists())

    def test_unknown_subdirectory_is_never_traversed(self):
        (self.base / 'device/__pycache__').mkdir()
        with self.assertRaises(AssertionError):
            c.cleanup(str(self.base), self.names)
        self.assertTrue(all((self.base / n).exists() for n in self.names))

    def test_paths_cannot_escape_the_owned_stage(self):
        with self.assertRaises(AssertionError):
            c.cleanup(str(self.base), self.names + ['../owner.txt'])
        self.assertTrue(all((self.base / n).exists() for n in self.names))

    def test_foreign_root_is_rejected(self):
        with patch.object(c, 'ROOT_PARENT', str(self.base)):
            with self.assertRaises(AssertionError):
                c.cleanup(str(self.base), self.names)
        self.assertTrue(self.base.exists())


if __name__ == '__main__':
    unittest.main()
