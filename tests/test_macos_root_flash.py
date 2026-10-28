"""Native flash classification and launch gates; no USB command is executed."""
import contextlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import macos_root_flash as m
from root_setup import SetupError


TRANSCRIPT = ['Flashing: Q10_os.unsigned', '[================] 100%', 'Send signature',
              'Done', 'Rebooting phone...', 'Flash completed successfully!']


class NativeFlashTests(unittest.TestCase):
    def evidence(self, lines, code=0):
        value = m.NativeFlashEvidence('Q10_os.unsigned')
        for line in lines:
            value.line(line)
        return value.result('os', code)

    def test_complete_native_evidence_requires_every_stage_and_clean_exit(self):
        result = self.evidence(TRANSCRIPT)
        self.assertTrue(result['completed'])
        self.assertFalse(result['expected_v4_os_security_result'])
        for code in (1, 73, -1):
            self.assertFalse(self.evidence(TRANSCRIPT, code)['completed'])
        for index in range(len(TRANSCRIPT)):
            if TRANSCRIPT[index] == 'Rebooting phone...':
                continue
            with self.subTest(omitted=TRANSCRIPT[index]):
                self.assertFalse(self.evidence(TRANSCRIPT[:index] + TRANSCRIPT[index + 1:])['completed'])

    def test_upstream_false_success_is_rejected_even_with_zero_exit_and_done(self):
        failures = ['Error flashing file: Q10_os.unsigned', 'Flash error', 'Signature send error',
                    'Error reading file data', 'K=-3', 'Loader failed', 'Exception: unknown result',
                    'Warning: Could not read complete signature', 'Wrong password!']
        for failure in failures:
            with self.subTest(failure=failure):
                self.assertFalse(self.evidence(TRANSCRIPT + [failure])['completed'])

    def test_unrelated_file_or_loader_progress_never_counts_as_payload_completion(self):
        self.assertFalse(self.evidence(['100%'] + [line for line in TRANSCRIPT if '100%' not in line])['completed'])
        self.assertFalse(self.evidence([line.replace('Q10_os.unsigned', 'other.unsigned') for line in TRANSCRIPT])['completed'])

    def test_private_prompts_and_device_identifiers_do_not_enter_log(self):
        for line in ('Enter password (1/10):', 'PIN: private-value', 'BSN: private-value', 'Serial: private-value'):
            self.assertNotIn('private-value', m.public_line(line))
            self.assertIn('omitted', m.public_line(line))

    def test_terminal_launch_quotes_local_paths_and_waits_for_atomic_stage_result(self):
        with tempfile.TemporaryDirectory(prefix='native stage ') as folder:
            root = Path(folder)
            def terminal(args, **_):
                self.assertEqual(args[:3], ['/usr/bin/open', '-a', 'Terminal'])
                script = Path(args[3])
                self.assertEqual(stat.S_IMODE(script.stat().st_mode), 0o700)
                self.assertIn('--token confirmation-token', script.read_text())
                (root / 'flash-os.json').write_text(json.dumps({'stage': 'os', 'platform': 'darwin', 'completed': True}))
                return SimpleNamespace(returncode=0)
            with patch.object(m.subprocess, 'run', side_effect=terminal):
                self.assertTrue(m.launch_stage(root, 'os', 'confirmation-token', timeout=1)['completed'])

    def test_frozen_terminal_command_reenters_app_without_source_python(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def terminal(args, **_):
                text = Path(args[3]).read_text()
                self.assertIn('--flash-stage os', text)
                self.assertIn('--flash-token confirmation-token', text)
                self.assertNotIn('root_flash.py', text)
                (root / 'flash-os.json').write_text(json.dumps({'stage': 'os', 'platform': 'darwin', 'completed': True}))
                return SimpleNamespace(returncode=0)
            with patch('desktop_paths.frozen', return_value=True), patch.object(m.subprocess, 'run', side_effect=terminal):
                self.assertTrue(m.launch_stage(root, 'os', 'confirmation-token', timeout=1)['completed'])

    def test_false_result_and_dead_console_pause_without_retry(self):
        for mode in ('false_result', 'dead_console'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                def terminal(*_, **__):
                    if mode == 'false_result':
                        (root / 'flash-os.json').write_text(json.dumps({'stage': 'os', 'platform': 'darwin', 'completed': False}))
                    else:
                        (root / 'flash-os.pid').write_text('987654')
                    return SimpleNamespace(returncode=0)
                with patch.object(m.subprocess, 'run', side_effect=terminal) as run, \
                        patch.object(m.os, 'kill', side_effect=ProcessLookupError):
                    with self.assertRaisesRegex(SetupError, 'flash_state_unknown'):
                        m.launch_stage(root, 'os', 'confirmation-token', timeout=1)
                    self.assertEqual(run.call_count, 1)

    def test_existing_console_or_result_cannot_be_relaunched(self):
        for name in ('flash-os.command', 'flash-os.json'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                (Path(folder) / name).write_text('preserve prior outcome')
                with patch.object(m.subprocess, 'run') as run:
                    with self.assertRaisesRegex(SetupError, 'flash_state_unknown'):
                        m.launch_stage(folder, 'os', 'token')
                    run.assert_not_called()

    def test_native_child_receives_opened_terminal_input_even_with_frozen_stdio(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / 'images/Q10_os.unsigned'
            tools = {'bb10mt': root / 'autoroot/bb10mt', 'loaders': root / 'autoroot/loaders'}
            console_in = MagicMock()
            console_out = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
            child = MagicMock(stdout=io.BytesIO(('\n'.join(TRANSCRIPT) + '\n').encode()))
            child.wait.return_value = 0
            state = {'platform': 'darwin', 'confirmation_token': 'token'}
            with patch.object(m.sys, 'platform', 'darwin'), \
                    patch.object(m.sys, 'stdin', console_in), patch.object(m.sys, 'stdout', console_out), \
                    patch.object(m.sys, 'stderr', console_out), \
                    patch('builtins.open', side_effect=[console_in, console_out]), \
                    patch('root_setup.prepared_images', return_value=(state, [image, root / 'images/Q10_radio.signed'])), \
                    patch('macos_root.verified_tools', return_value=tools), patch('macos_root.native_environment', return_value={}), \
                    patch.object(m, 'hidden_terminal_input', return_value=contextlib.nullcontext()), \
                    patch.object(m.subprocess, 'Popen', return_value=child) as spawn:
                self.assertEqual(m.run_stage(root, 'os', 'token'), 0)
                self.assertIs(spawn.call_args.kwargs['stdin'], console_in)
            self.assertTrue(json.loads((root / 'flash-os.json').read_text())['completed'])


if __name__ == '__main__':
    unittest.main()
