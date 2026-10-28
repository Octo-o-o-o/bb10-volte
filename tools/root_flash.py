"""Native-console autoloader stage; passwords never pass through GUI arguments."""
import argparse
import ctypes
import json
from pathlib import Path
import re
import subprocess
import sys


def classify_output(phase, exit_code, writing_complete, failed_to_load, security_error, done):
    expected = (phase == 'os' and exit_code == 73 and writing_complete and
                failed_to_load and security_error)
    return {'stage': phase, 'exit_code': exit_code, 'writing_complete': bool(writing_complete),
            'expected_v4_os_security_result': bool(expected),
            'completed': bool(expected or exit_code == 0 and
                              (phase == 'os' and writing_complete or phase == 'radio' and done))}


def run_stage(folder, phase, token):
    from root_setup import prepared_images, SetupError
    state, images = prepared_images(folder, allowed_stages=(phase + '_started',))
    if not token or state.get('confirmation_token') != token or phase not in ('os', 'radio'):
        raise SetupError('flash_confirmation_required')
    image = images[0 if phase == 'os' else 1]
    if not ctypes.windll.kernel32.GetConsoleWindow():
        if not ctypes.windll.kernel32.AllocConsole():
            raise SetupError('native_console_unavailable')
    sys.stdin = open('CONIN$', 'r')
    sys.stdout = open('CONOUT$', 'w')
    sys.stderr = sys.stdout
    print('bb10-volte: ' + phase.upper() + ' Root flashing', flush=True)
    print('Keep USB connected. Enter the phone password here only if the BlackBerry tool asks for it.', flush=True)
    child = subprocess.Popen([str(image)], cwd=image.parent, stdin=None,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
    pending = bytearray()
    flags = {'writing_complete': False, 'failed_to_load': False, 'security_error': False, 'done': False}
    log = Path(folder) / ('flash-' + phase + '.log')
    with log.open('xb', buffering=0) as file:
        while True:
            char = child.stdout.read(1)
            if not char:
                break
            sys.stdout.buffer.write(char)
            sys.stdout.buffer.flush()
            pending.extend(char)
            if char in (b'\r', b'\n'):
                line = bytes(pending).lower()
                if b'password' not in line:
                    file.write(pending)
                else:
                    file.write(b'[Native password prompt omitted]\n')
                flags['writing_complete'] |= b'writing' in line and re.search(rb'\b100\b', line) is not None
                flags['failed_to_load'] |= b'error: failed to load images.' in line
                flags['security_error'] |= b'error: security error.' in line
                flags['done'] |= line.strip() == b'done.'
                pending.clear()
    result = classify_output(phase, child.wait(), **flags)
    (Path(folder) / ('flash-' + phase + '.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('\nStage completed. Return to the bb10-volte window.', flush=True)
    return 0 if result['completed'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('os', 'radio'), required=True)
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--token', required=True)
    args = parser.parse_args(argv)
    return run_stage(args.kit, args.stage, args.token)


if __name__ == '__main__':
    raise SystemExit(main())
