"""Replay native progress and failing consoles without launching a loader."""
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import root_flash as f

WRITTEN = '[                  Writing  0x0092C044 ] [############## 100 ##############]'
EXPECTED = [WRITTEN, 'Error: Failed to load images.', 'Error: Security error.']


class WindowsRootFlashTests(unittest.TestCase):
    def test_only_complete_success_or_exact_root_exception_can_continue(self):
        for phase, code, lines, accepted in [
                ('os', 73, EXPECTED, True), ('radio', 73, EXPECTED, False),
                ('os', 0, EXPECTED, False),
                ('os', 73, EXPECTED + ['Error: USB disconnected.'], False),
                ('os', 73, EXPECTED[1:] + [WRITTEN], False),
                ('os', 0, [WRITTEN], False), ('radio', 0, ['Done.'], False),
                ('radio', 0, [WRITTEN, 'Done.'], True),
                ('os', 0, [WRITTEN, 'Done.'], True),
                ('os', 0, ['Writing 100 bytes', 'Done.'], False),
                ('radio', 0, [WRITTEN, 'Error: USB disconnected.', 'Done.'], False)]:
            with self.subTest(phase=phase, code=code, lines=lines):
                evidence = f.RootFlashEvidence()
                for line in lines:
                    evidence.line(line)
                self.assertEqual(evidence.result(phase, code)['completed'], accepted)

    def run_console(self, root, transcript, code, preexisting=False, before_eof=None):
        image = root / 'images/Q10_radio.exe'
        console_in = MagicMock()
        console_out = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
        class Output(io.BytesIO):
            def read(self, count=-1):
                value = super().read(count)
                if not value and before_eof:
                    before_eof()
                return value
        child = MagicMock(stdout=Output(transcript.encode()))
        child.wait.return_value = code
        if preexisting:
            (root / 'flash-radio.log').write_text('prior stage must be preserved')
        with patch.object(f.sys, 'platform', 'win32'), \
                patch.object(f.sys, 'stdin', console_in), patch.object(f.sys, 'stdout', console_out), \
                patch.object(f.sys, 'stderr', console_out), \
                patch.object(f.ctypes, 'windll', SimpleNamespace(kernel32=MagicMock()), create=True), \
                patch('builtins.open', side_effect=[console_in, console_out]), \
                patch('root_setup.prepared_images', return_value=({'confirmation_token': 'token'}, [image, image])), \
                patch.object(f.subprocess, 'Popen', return_value=child) as spawn:
            if preexisting:
                with self.assertRaises(FileExistsError):
                    f.run_stage(root, 'radio', 'token')
                spawn.assert_not_called()
            else:
                result = f.run_stage(root, 'radio', 'token')
                self.assertIs(spawn.call_args.kwargs['stdin'], console_in)
                return result, json.loads((root / 'flash-radio.json').read_text())

    def test_unterminated_final_error_cannot_be_lost(self):
        with tempfile.TemporaryDirectory() as folder:
            code, report = self.run_console(Path(folder), WRITTEN + '\rDone.\rError: USB disconnected.', 0)
            self.assertEqual(code, 1)
            self.assertFalse(report['completed'])
            self.assertTrue(report['error_seen'])

    def test_unterminated_success_and_explicit_console_input(self):
        with tempfile.TemporaryDirectory() as folder:
            code, report = self.run_console(Path(folder), WRITTEN + '\rDone.', 0)
            self.assertEqual(code, 0)
            self.assertTrue(report['completed'])

    def test_reopening_console_does_not_launch_another_destructive_child(self):
        with tempfile.TemporaryDirectory() as folder:
            self.run_console(Path(folder), '', 0, preexisting=True)

    def test_unterminated_password_prompt_is_visible_before_process_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def still_waiting():
                text = (root / 'flash-radio.log').read_text()
                self.assertEqual(text.count('[Device password input requested in native console]'), 1)
                self.assertNotIn('Please enter password', text)
                self.assertFalse((root / 'flash-radio.json').exists())
            unused, report = self.run_console(root, 'Resetting Device:\rPlease enter password: ', 1,
                                               before_eof=still_waiting)
            self.assertFalse(report['completed'])


if __name__ == '__main__':
    unittest.main()
