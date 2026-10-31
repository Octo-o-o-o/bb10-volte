"""Execute the real startup shell with isolated readiness and command stubs."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NameStartupTests(unittest.TestCase):
    def setUp(self):
        if os.name == 'nt':
            candidates = [Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Git/usr/bin/bash.exe']
            git = shutil.which('git')
            if git:
                candidates.append(Path(git).resolve().parent.parent / 'usr/bin/bash.exe')
            self.shell = next((str(p) for p in candidates if p.is_file()), None)
        else:
            self.shell = shutil.which('bash')
        if not self.shell: self.skipTest('Local POSIX shell unavailable')
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.base = self.folder / 'base'
        (self.base / 'state').mkdir(parents=True)
        (self.base / 'enabled').touch()
        (self.base / 'state/telecom-autostart-acceptance.json').write_text('{}')
        self.marker = self.folder / 'root.ready'
        self.entered = self.folder / 'entered'
        self.started = self.folder / 'started'
        self.trusted = self.folder / 'trusted'
        trust = self.script('trust-stub', "printf 'trust\\n' >> \"" + self.trusted.as_posix() + "\"\n")
        launch = self.script('launch-stub',
            'if test -f "' + self.marker.as_posix() + '"; then\n'
            '  printf ready > "' + self.started.as_posix() + '"\n'
            'else\n  printf premature > "' + self.started.as_posix() + '"\n  exit 42\nfi\n')
        source = (ROOT / 'device/operator-name-start.sh').read_text(encoding='utf-8')
        source = source.replace('BASE=/var/rootdata/q10_volte', 'BASE="' + self.base.as_posix() + '"')
        source = source.replace('test -f "$BASE/enabled"',
            'printf entered > "' + self.entered.as_posix() + '"\ntest -f "$BASE/enabled"')
        source = source.replace('/tmp/root.done', self.marker.as_posix())
        source = source.replace('/proc/boot/pathtrust', '"' + trust.as_posix() + '"')
        source = source.replace('/usr/bin/python3.2', '"' + launch.as_posix() + '"')
        self.entry = self.folder / 'entry.sh'
        self.entry.write_text(source, encoding='utf-8', newline='\n')

    def script(self, name, body):
        path = self.folder / name
        path.write_text('#!/bin/sh\n' + body, encoding='utf-8', newline='\n')
        path.chmod(0o700)
        return path

    def test_waits_before_trust_or_launch_then_starts_after_readiness(self):
        process = subprocess.Popen([self.shell, '--noprofile', '--norc', str(self.entry)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 3
            while not self.entered.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(self.entered.exists())
            time.sleep(0.2)
            self.assertIsNone(process.poll())
            self.assertFalse(self.trusted.exists())
            self.assertFalse(self.started.exists())
            self.marker.touch()
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr.decode(errors='replace'))
            self.assertEqual(self.started.read_text(), 'ready')
        finally:
            if process.poll() is None: process.kill(); process.communicate()

    def test_missing_root_completion_exits_without_trust_or_launch(self):
        sleeps = self.folder / 'sleeps'
        sleep = self.script('sleep-stub', "printf 'wait\\n' >> \"" + sleeps.as_posix() + "\"\n")
        source = self.entry.read_text(encoding='utf-8')
        self.entry.write_text(source.replace('sleep 2', '"' + sleep.as_posix() + '" 2'),
                              encoding='utf-8', newline='\n')
        result = subprocess.run([self.shell, '--noprofile', '--norc', str(self.entry)],
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 1, result.stderr.decode(errors='replace'))
        self.assertFalse(self.started.exists()); self.assertFalse(self.trusted.exists())
        self.assertGreaterEqual(len(sleeps.read_text().splitlines()), 1)
        self.assertLessEqual(len(sleeps.read_text().splitlines()), 60)


if __name__ == '__main__':
    unittest.main()
