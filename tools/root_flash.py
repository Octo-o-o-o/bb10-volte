"""Native-console autoloader stage; passwords never pass through GUI arguments."""
import argparse
import ctypes
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from i18n import tr


def writing_complete_line(text):
    """Accept the native bracketed progress bar as well as percent output."""
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text).strip().lower()
    return bool(re.fullmatch(r'\[\s*writing\s+0x[0-9a-f]+\s*\]\s*\[[# ]*100[# ]*\]', text) or
                re.search(r'\bwriting\b.*\b100(?:\.0+)?\s*%', text))


def writing_started_line(text):
    """Detect whether the autoloader actually began writing/erasing partitions."""
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text).strip().lower()
    return bool(writing_complete_line(text) or
                re.search(r'(?:\[\s*writing\b|\b(?:writing|erasing|flashing|formatting)\b)', text))


def classify_output(phase, exit_code, writing_complete, failed_to_load, security_error, done,
                    unexpected_error=False, writing_started=False):
    expected = (phase == 'os' and exit_code == 73 and writing_complete and
                failed_to_load and security_error and not unexpected_error)
    error_seen = failed_to_load or security_error or unexpected_error
    started = bool(writing_started or writing_complete)
    return {'stage': phase, 'exit_code': exit_code, 'writing_started': started,
            'writing_complete': bool(writing_complete),
            'done': bool(done), 'error_seen': bool(error_seen),
            'expected_v4_os_security_result': bool(expected),
            'completed': bool(expected or phase in ('os', 'radio') and exit_code == 0 and
                              writing_complete and done and not error_seen)}


class RootFlashEvidence:
    def __init__(self):
        self.flags = dict(writing_started=False, writing_complete=False, failed_to_load=False,
                          security_error=False, done=False, unexpected_error=False)

    def line(self, raw):
        lower = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', raw).strip().lower()
        self.flags['writing_started'] |= writing_started_line(lower)
        self.flags['writing_complete'] |= writing_complete_line(lower)
        self.flags['done'] |= self.flags['writing_complete'] and lower == 'done.'
        expected_errors = {'error: failed to load images.': 'failed_to_load',
                           'error: security error.': 'security_error'}
        if lower in expected_errors and self.flags['writing_complete']:
            self.flags[expected_errors[lower]] = True
        elif re.search(r'\b(?:error|failed|failure|exception|aborted|cancelled|canceled)\b', lower):
            self.flags['unexpected_error'] = True

    def result(self, phase, exit_code):
        return classify_output(phase, exit_code, **self.flags)


def password_prompt(pending):
    """Identify an unterminated console prompt without persisting its text."""
    return bool(re.search(rb'(?i)(?:enter|input|type|provide)[^\r\n]*password|password\s*[:?]', pending))


def run_stage(folder, phase, token):
    if sys.platform == 'darwin':
        from macos_root_flash import run_stage as run_macos_stage
        return run_macos_stage(folder, phase, token)
    from root_setup import prepared_images, SetupError
    state, images = prepared_images(folder, allowed_stages=(phase + '_started',))
    if (sys.platform != 'win32' or state.get('platform', 'win32') != 'win32' or
            not token or state.get('confirmation_token') != token or phase not in ('os', 'radio')):
        raise SetupError('flash_confirmation_required')
    image = images[0 if phase == 'os' else 1]
    if not ctypes.windll.kernel32.GetConsoleWindow():
        if not ctypes.windll.kernel32.AllocConsole():
            raise SetupError('native_console_unavailable')
    sys.stdin = open('CONIN$', 'r')
    # WindowsConsoleIO converts UTF-8 to wide console output, independently of
    # the user's separate regional code page.
    sys.stdout = open('CONOUT$', 'w', encoding='utf-8', errors='replace')
    sys.stderr = sys.stdout
    print(tr('bb10-volte：正在刷写 {} Root').format(phase.upper()), flush=True)
    print(tr('请保持 USB 连接；仅在黑莓工具提示时在此输入手机密码。'), flush=True)
    pending = bytearray()
    prompt_reported = False
    evidence = RootFlashEvidence()
    from macos_root_flash import public_line
    log = Path(folder) / ('flash-' + phase + '.log')
    # Claim the stage before launching the destructive child. Reopening the
    # same console must not execute the image before the existing-log check.
    with log.open('x', encoding='utf-8') as file:
        child = subprocess.Popen([str(image)], cwd=image.parent, stdin=sys.stdin,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
        while True:
            char = child.stdout.read(1)
            if not char:
                break
            sys.stdout.buffer.write(char)
            sys.stdout.buffer.flush()
            pending.extend(char)
            if not prompt_reported and password_prompt(pending):
                file.write('[Device password input requested in native console]\n')
                file.flush()
                prompt_reported = True
            if char in (b'\r', b'\n'):
                line = pending.decode('utf-8', 'replace')
                evidence.line(line)
                file.write(public_line(line))
                file.flush()
                pending.clear()
                prompt_reported = False
        if pending:
            line = pending.decode('utf-8', 'replace')
            evidence.line(line)
            file.write(public_line(line))
        result = evidence.result(phase, child.wait())
    output = Path(folder) / ('flash-' + phase + '.json')
    temporary = output.with_suffix('.json.partial')
    with temporary.open('x', encoding='utf-8') as file:
        json.dump(result, file, indent=2)
    temporary.replace(output)
    print(tr('\n请返回 bb10-volte。状态未知或失败的阶段会保持暂停；不要重复运行。'), flush=True)
    if not result['completed']:
        print(tr('刷写工具退出码：{}（是否已进入写入：{}）').format(
            result['exit_code'], tr('是') if result.get('writing_started') else tr('否')), flush=True)
        if not result.get('writing_started'):
            print(tr('未检测到进入写入阶段。常见原因：Windows 缺少 BlackBerry USB（Bootrom）驱动、未识别连接超时或密码提示中断。'), flush=True)
            print(tr('可在应用“Windows 驱动”页安装驱动，并通过“查看刷写日志并解除暂停”核对后重试。'), flush=True)
        if isinstance(sys.stdin, io.TextIOBase) and sys.stdin.isatty() and not os.environ.get('BB10_FLASH_NO_PAUSE'):
            try:
                input(tr('请先查看上方输出，再按回车键关闭此窗口…'))
            except (EOFError, OSError):
                pass
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
