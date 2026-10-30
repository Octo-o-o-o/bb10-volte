"""Explicit macOS Terminal flashing stages; never used by offline preparation."""
import contextlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from i18n import tr
import time


class NativeFlashEvidence:
    """The upstream flash command can report success after returning K < 0."""
    def __init__(self, image):
        self.image = image
        self.input_seen = False
        self.writing_complete = False
        self.signature_seen = False
        self.done = False
        self.success_seen = False
        self.error_seen = False

    def line(self, raw):
        text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', raw).strip()
        lower = text.lower()
        self.input_seen |= text == 'Flashing: ' + self.image
        self.writing_complete |= self.input_seen and re.search(r'\b100(?:\.0+)?\s*%', text) is not None
        self.signature_seen |= self.writing_complete and lower == 'send signature'
        self.done |= self.signature_seen and lower == 'done'
        self.success_seen |= self.done and lower == 'flash completed successfully!'
        self.error_seen |= (re.search(r'\b(?:error|failed|failure|exception|warning|aborted|cancelled|canceled)\b', lower) is not None or
                            re.search(r'\bk\s*=\s*-\d+', lower) is not None or 'wrong password' in lower)

    def result(self, phase, exit_code):
        completed = (exit_code == 0 and self.input_seen and self.writing_complete and
                     self.signature_seen and self.done and self.success_seen and not self.error_seen)
        return {'stage': phase, 'platform': 'darwin', 'exit_code': exit_code,
                'writing_complete': self.writing_complete, 'input_verified': self.input_seen,
                'signature_seen': self.signature_seen, 'done': self.done,
                'success_seen': self.success_seen, 'error_seen': self.error_seen,
                'expected_v4_os_security_result': False, 'completed': bool(completed)}


def public_line(raw):
    """No password prompts or full device identifiers in the private stage log."""
    if re.search(r'(?i)password|\bpin\b|\bbsn\b|\bserial\b', raw):
        return '[Device identity or password prompt omitted]\n'
    return raw


@contextlib.contextmanager
def hidden_terminal_input():
    import termios
    if not sys.stdin.isatty():
        raise RuntimeError('native_console_unavailable')
    descriptor = sys.stdin.fileno()
    previous = termios.tcgetattr(descriptor)
    hidden = list(previous)
    hidden[3] &= ~termios.ECHO
    termios.tcsetattr(descriptor, termios.TCSADRAIN, hidden)
    try:
        yield
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)


def launch_stage(folder, phase, token, timeout=3600):
    """Open a visible Terminal. A missing result remains an uncertain stage."""
    from desktop_paths import frozen, resource_root
    from root_setup import SetupError
    folder = Path(folder).resolve()
    result = folder / ('flash-' + phase + '.json')
    script = folder / ('flash-' + phase + '.command')
    pidfile = script.with_suffix('.pid')
    pending_pid = script.with_suffix('.pid.pending')
    if phase not in ('os', 'radio') or any(path.exists() for path in (result, script, pidfile, pending_pid)):
        raise SetupError('flash_state_unknown')
    command = ([sys.executable, '--flash-stage', phase, '--root-kit', str(folder), '--flash-token', token]
               if frozen() else [sys.executable, str(resource_root() / 'tools/root_flash.py'),
                                  '--stage', phase, '--kit', str(folder), '--token', token])
    with script.open('x', encoding='utf-8', newline='\n') as stream:
        # Publish a complete PID atomically, without replacing an existing
        # stage. Reopening this .command cannot hide the original live child.
        stream.write('#!/bin/sh\numask 077\n'
                     '(set -C; printf "%s\\n" "$$" > ' + shlex.quote(str(pending_pid)) + ') &&\n'
                     '/bin/ln ' + shlex.quote(str(pending_pid)) + ' ' + shlex.quote(str(pidfile)) + ' &&\n'
                     '/bin/rm ' + shlex.quote(str(pending_pid)) + ' &&\nexec ' + shlex.join(command) + '\n')
    script.chmod(0o700)
    launched = subprocess.run(['/usr/bin/open', '-a', 'Terminal', str(script)], capture_output=True)
    if launched.returncode:
        raise SetupError('native_console_unavailable')
    deadline = time.monotonic() + timeout
    startup = time.monotonic() + 30
    while time.monotonic() < deadline:
        if result.is_file():
            try:
                value = json.loads(result.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                raise SetupError('flash_state_unknown') from None
            if (not isinstance(value, dict) or value.get('stage') != phase or
                    value.get('platform') != 'darwin' or value.get('completed') is not True):
                raise SetupError('flash_state_unknown')
            return value
        if pidfile.is_file():
            try:
                pid = int(pidfile.read_text(encoding='ascii').strip())
                if pid <= 1:
                    raise ValueError('Invalid stage process')
                os.kill(pid, 0)
            except (ProcessLookupError, ValueError):
                raise SetupError('flash_state_unknown') from None
        elif time.monotonic() >= startup:
            raise SetupError('flash_state_unknown')
        time.sleep(0.5)
    # Do not kill a possibly writing child or retry an uncertain operation.
    raise SetupError('flash_state_unknown')


def run_stage(folder, phase, token):
    from macos_root import verified_tools, native_environment
    from root_setup import prepared_images, SetupError
    folder = Path(folder).resolve()
    state, images = prepared_images(folder, allowed_stages=(phase + '_started',))
    if (sys.platform != 'darwin' or state.get('platform') != 'darwin' or not token or
            state.get('confirmation_token') != token or phase not in ('os', 'radio')):
        raise SetupError('flash_confirmation_required')
    tools = verified_tools(folder / 'autoroot')
    image = images[0 if phase == 'os' else 1]
    # The Pascal -i parser splits commas; its -l form accepts a full path per
    # line, but '=' is a filename/type delimiter and must never be ambiguous.
    if any(character in str(image) for character in ('=', '\r', '\n')):
        raise SetupError('path_unsupported')
    listing = folder / ('flash-' + phase + '-input.txt')
    with listing.open('x', encoding='utf-8') as stream:
        stream.write(str(image) + '\n')
    listing.chmod(0o600)
    evidence = NativeFlashEvidence(image.name)
    try:
        sys.stdin = open('/dev/tty', 'r')
        sys.stdout = open('/dev/tty', 'w', buffering=1)
        sys.stderr = sys.stdout
    except OSError:
        raise SetupError('native_console_unavailable') from None
    print(tr('bb10-volte：正在通过 Mac 原生工具刷写 {} Root').format(phase.upper()), flush=True)
    print(tr('请保持 USB 连接；仅在原生工具提示时输入设备密码，输入内容不会显示。'), flush=True)
    pending = bytearray()
    with hidden_terminal_input(), (folder / ('flash-' + phase + '.log')).open('x', encoding='utf-8') as log:
        child = subprocess.Popen([str(tools['bb10mt']), 'flash', '-l', str(listing), '-r', str(tools['loaders'])],
                                 cwd=tools['bb10mt'].parent, env=native_environment(tools), stdin=sys.stdin,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
        while True:
            char = child.stdout.read(1)
            if not char:
                break
            sys.stdout.buffer.write(char)
            sys.stdout.buffer.flush()
            pending.extend(char)
            if char in (b'\r', b'\n'):
                line = pending.decode('utf-8', 'replace')
                evidence.line(line)
                log.write(public_line(line))
                log.flush()
                pending.clear()
        if pending:
            line = pending.decode('utf-8', 'replace')
            evidence.line(line)
            log.write(public_line(line))
        result = evidence.result(phase, child.wait())
    output = folder / ('flash-' + phase + '.json')
    temporary = folder / ('flash-' + phase + '.json.partial')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    temporary.chmod(0o600)
    temporary.replace(output)
    print(tr('\n请返回 bb10-volte。状态未知或失败的阶段会保持暂停；不要重复运行。'), flush=True)
    return 0 if result['completed'] else 1
