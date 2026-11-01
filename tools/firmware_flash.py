"""Native console for one confirmed stock stage; never accepts Root-only errors."""
import ctypes
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

from desktop_paths import frozen, resource_root
from i18n import tr
from root_setup import SetupError, root_lock_path
from root_flash import writing_complete_line


class StockFlashEvidence:
    def __init__(self):
        self.writing_complete = False
        self.done = False
        self.error_seen = False

    def line(self, raw):
        lower = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', raw).strip().lower()
        self.writing_complete |= writing_complete_line(lower)
        self.done |= self.writing_complete and lower == 'done.'
        self.error_seen |= re.search(r'\b(?:error|failed|failure|exception|aborted|cancelled|canceled)\b', lower) is not None

    def result(self, phase, code):
        return {'stage': phase, 'exit_code': code, 'writing_complete': self.writing_complete,
                'done': self.done, 'error_seen': self.error_seen,
                'completed': code == 0 and self.writing_complete and self.done and not self.error_seen}


def launch_stage(folder, phase, token, timeout=3600):
    folder = Path(folder)
    result_path = folder / ('upgrade-' + phase + '.json')
    if result_path.exists():
        raise SetupError('flash_state_unknown')
    command = ([sys.executable, '--firmware-stage', phase, '--root-kit', str(folder), '--flash-token', token]
               if frozen() else [sys.executable, str(resource_root() / 'tools/firmware_flash.py'),
                                  '--stage', phase, '--kit', str(folder), '--token', token])
    if sys.platform == 'win32':
        child = subprocess.Popen(command, creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0))
        try:
            code = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Never kill a loader that could still be writing to the phone.
            raise SetupError('flash_state_unknown') from None
        if code:
            raise SetupError('flash_state_unknown')
    elif sys.platform == 'darwin':
        script = folder / ('upgrade-' + phase + '.command')
        pidfile = folder / ('upgrade-' + phase + '.pid')
        pending_pid = pidfile.with_suffix('.pid.pending')
        if any(path.exists() or path.is_symlink() for path in (script, pidfile, pending_pid)):
            raise SetupError('flash_state_unknown')
        with script.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write('#!/bin/sh\numask 077\n(set -C; printf "%s\\n" "$$" > ' +
                         shlex.quote(str(pending_pid)) + ') &&\n/bin/ln ' +
                         shlex.quote(str(pending_pid)) + ' ' + shlex.quote(str(pidfile)) +
                         ' &&\n/bin/rm ' + shlex.quote(str(pending_pid)) + ' &&\nexec ' + shlex.join(command) + '\n')
        script.chmod(0o700)
        if subprocess.run(['/usr/bin/open', '-a', 'Terminal', str(script)], capture_output=True).returncode:
            raise SetupError('native_console_unavailable')
        deadline, startup = time.monotonic() + timeout, time.monotonic() + 30
        while not result_path.is_file():
            if time.monotonic() >= deadline:
                raise SetupError('flash_state_unknown')
            if pidfile.is_file():
                try:
                    pid = int(pidfile.read_text().strip())
                    if pid <= 1:
                        raise ValueError('Invalid PID')
                    os.kill(pid, 0)
                except (ProcessLookupError, ValueError):
                    raise SetupError('flash_state_unknown') from None
            elif time.monotonic() >= startup:
                raise SetupError('flash_state_unknown')
            time.sleep(0.5)
    else:
        raise SetupError('root_platform_mismatch')
    if not result_path.is_file() or result_path.is_symlink() or result_path.stat().st_size > 65536:
        raise SetupError('flash_state_unknown')
    value = json.loads(result_path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('stage') != phase or value.get('completed') is not True:
        raise SetupError('flash_state_unknown')
    return value


def run_stage(folder, phase, token):
    from firmware_upgrade import verify_kit
    from macos_root_flash import NativeFlashEvidence, hidden_terminal_input, public_line
    import contextlib
    folder = Path(folder).resolve()
    state, images = verify_kit(folder, allowed=(phase + '_started',))
    lock = json.loads(root_lock_path().read_text(encoding='utf-8'))
    if (not token or token != state.get('confirmation_token') or token != lock.get('token')
            or lock.get('operation') != 'stock-upgrade' or Path(lock.get('kit', '')).resolve() != folder):
        raise SetupError('flash_confirmation_required')
    selected = [image for name, image in images if name == phase]
    if len(selected) != 1:
        raise SetupError('image_not_verified')
    image = selected[0]
    # Claim before starting a process. Replaying the same token never flashes twice.
    with (folder / ('upgrade-' + phase + '.claimed')).open('x', encoding='ascii') as stream:
        stream.write(token)
    if sys.platform == 'win32':
        if not ctypes.windll.kernel32.GetConsoleWindow() and not ctypes.windll.kernel32.AllocConsole():
            raise SetupError('native_console_unavailable')
        sys.stdin = open('CONIN$', 'r')
        sys.stdout = open('CONOUT$', 'w', encoding='utf-8', errors='replace')
        command, environment = [str(image)], None
        evidence, input_context = StockFlashEvidence(), contextlib.nullcontext()
    elif sys.platform == 'darwin':
        from macos_root import verified_tools, native_environment
        tools = verified_tools(folder / 'autoroot')
        if any(char in str(image) for char in ('=', '\r', '\n')):
            raise SetupError('path_unsupported')
        listing = folder / ('upgrade-' + phase + '-input.txt')
        with listing.open('x', encoding='utf-8') as stream:
            stream.write(str(image) + '\n')
        listing.chmod(0o600)
        command = [str(tools['bb10mt']), 'flash', '-l', str(listing), '-r', str(tools['loaders'])]
        environment = native_environment(tools)
        sys.stdin, sys.stdout = open('/dev/tty', 'r'), open('/dev/tty', 'w', buffering=1)
        evidence, input_context = NativeFlashEvidence(image.name), hidden_terminal_input()
    else:
        raise SetupError('root_platform_mismatch')
    sys.stderr = sys.stdout
    print(tr('正在写入对应机型的原版系统；请保持连接，仅在工具提示时输入手机密码。'), flush=True)
    pending = bytearray()
    with input_context, (folder / ('upgrade-' + phase + '.log')).open('x', encoding='utf-8') as log:
        child = subprocess.Popen(command, cwd=image.parent, env=environment, stdin=sys.stdin,
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
    output = folder / ('upgrade-' + phase + '.json')
    temporary = output.with_suffix('.json.partial')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    temporary.replace(output)
    print(tr('请返回应用。必须重新检测开机后的系统版本，才能继续 Root。'), flush=True)
    return 0 if result['completed'] else 1


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('stock', 'stock_os', 'stock_radio'), required=True)
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--token', required=True)
    args = parser.parse_args()
    return run_stage(args.kit, args.stage, args.token)


if __name__ == '__main__':
    raise SystemExit(main())
