"""Run the exported guard in a local shell with mocked phone commands."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from pairing_instructions import phone_commands, export_pairing_files
from connection_recovery import RecoveryError


class PairingInstructionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.script = self.folder / 'bb10-pair-abcdef123456.py'
        self.script.write_text('# public fixture only')
        self.export = self.folder / 'export'
        self.export.mkdir()

    def test_export_keeps_request_and_never_exports_private_key(self):
        (self.folder / 'identity').write_text('private fixture')
        export_pairing_files(self.script, self.export)
        self.assertEqual({p.name for p in self.export.iterdir()},
                         {self.script.name, self.script.stem + '-instructions.txt'})
        self.assertEqual((self.export / self.script.name).read_bytes(), self.script.read_bytes())
        instruction = (self.export / (self.script.stem + '-instructions.txt')).read_text(encoding='utf-8')
        self.assertIn(phone_commands(self.script.name), instruction)
        self.assertNotIn('private fixture', instruction)
        export_pairing_files(self.script, self.export)

    def test_conflicting_instructions_are_preserved_before_partial_export(self):
        existing = self.export / (self.script.stem + '-instructions.txt')
        existing.write_text('owner content')
        with self.assertRaisesRegex(RecoveryError, 'pairing_export_conflict'):
            export_pairing_files(self.script, self.export)
        self.assertEqual(existing.read_text(), 'owner content')
        self.assertFalse((self.export / self.script.name).exists())

    def test_unsafe_or_wrong_request_names_are_rejected(self):
        for name in ('pair.py', '../bb10-pair-abcdef123456.py', 'bb10-pair-abcdef123456.py;echo bad'):
            with self.assertRaises(ValueError):
                phone_commands(name)

    def test_shell_stops_before_trust_and_python_on_wrong_uid_missing_file_and_trust_error(self):
        shell = shutil.which('sh')
        if os.name == 'nt':
            git = shutil.which('git')
            candidate = Path(git).parents[1] / 'bin/bash.exe' if git else Path('missing')
            shell = str(candidate) if candidate.is_file() else None
        if not shell:
            self.skipTest('POSIX shell unavailable')
        for uid, exists, trust, expected in [('1000', True, 0, ['ROOT_REQUIRED']),
                                             ('', True, 0, ['ROOT_REQUIRED']),
                                             ('0', False, 0, ['PAIR_FILE_NOT_FOUND']),
                                             ('0', True, 1, ['TRUST']),
                                             ('0', True, 0, ['TRUST', 'PYTHON'])]:
            with self.subTest(uid=uid, exists=exists, trust=trust):
                path = self.script if exists else self.folder / 'missing.py'
                # Substitute only absolute phone endpoints; all behavior is the
                # same shell block exported to the owner, including && ordering.
                block = phone_commands(self.script.name)
                block = block.replace('/accounts/1000/shared/downloads/' + self.script.name,
                                      "'" + path.as_posix() + "'")
                block = block.replace('/proc/boot/pathtrust', 'test_trust').replace('/usr/bin/python3.2', 'test_python')
                setup = ('id() { printf "%s\\n" "' + uid + '"; };\n'
                         'test_trust() { echo TRUST; return ' + str(trust) + '; };\n'
                         'test_python() { echo PYTHON; };\n')
                result = subprocess.run([shell, '-s'], input=setup + block, capture_output=True, text=True, timeout=10)
                observed = [line.split(':', 1)[0] for line in result.stdout.splitlines()]
                self.assertEqual(observed, expected, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
