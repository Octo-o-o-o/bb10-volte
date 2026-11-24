"""Native-console autoloader stage; passwords never pass through GUI arguments."""
import argparse
import contextlib
import ctypes
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
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


def status_prefix(pending):
    """Identify unterminated BlackBerry autoloader status prefixes for immediate logging."""
    match = re.search(rb'(?i)(connecting to bootrom\s*:|resetting device\s*:)', pending)
    return match.group(1).decode('ascii', errors='ignore') if match else None


def configure_windows_console(title):
    """Allocate/focus a Windows console and disable QuickEdit click-to-freeze mode."""
    from root_setup import SetupError
    kernel32 = ctypes.windll.kernel32
    if not kernel32.GetConsoleWindow():
        if not kernel32.AllocConsole():
            raise SetupError('native_console_unavailable')
    sys.stdin = open('CONIN$', 'r')
    # WindowsConsoleIO converts UTF-8 to wide console output, independently of
    # the user's separate regional code page.
    sys.stdout = open('CONOUT$', 'w', encoding='utf-8', errors='replace')
    sys.stderr = sys.stdout
    try:
        from ctypes import wintypes
        kernel32.SetConsoleTitleW(title)
        handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = wintypes.DWORD()
        if handle and handle != -1 and kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            # Clear ENABLE_QUICK_EDIT_MODE (0x0040) and set ENABLE_EXTENDED_FLAGS (0x0080)
            # so clicking the console to focus or type a password never freezes output.
            new_mode = (mode.value & ~0x0040) | 0x0080
            kernel32.SetConsoleMode(handle, new_mode)
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32 = ctypes.windll.user32
            user32.ShowWindow(hwnd, 5)  # SW_SHOW
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def _is_ansi_safe_path(path_str):
    if sys.platform != 'win32':
        return True
    return all(ord(ch) < 128 for ch in path_str) and len(path_str) <= 240


def _windows_short_path(path_str):
    if sys.platform != 'win32':
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        length = ctypes.windll.kernel32.GetShortPathNameW(path_str, buf, len(buf))
        if 0 < length < len(buf):
            return buf.value
    except Exception:
        pass
    return None


@contextlib.contextmanager
def ansi_safe_launch(image):
    """Ensure 32-bit ANSI-only BlackBerry autoloader binaries receive an ANSI-safe path and TEMP."""
    image = Path(image)
    raw = str(image)
    env = None
    temp_stage = None
    launch_path = raw
    if sys.platform == 'win32':
        if not _is_ansi_safe_path(raw):
            short = _windows_short_path(raw)
            if short and _is_ansi_safe_path(short):
                launch_path = short
            else:
                base = Path(os.environ.get('SystemDrive', 'C:') + '\\ProgramData\\bb10-volte\\flash-stage')
                temp_stage = base / uuid.uuid4().hex[:12]
                temp_stage.mkdir(parents=True, exist_ok=True)
                try:
                    from preparation_cache import restrict_windows_acl
                    restrict_windows_acl(temp_stage, directory=True)
                except Exception:
                    pass
                target = temp_stage / image.name
                try:
                    os.link(raw, str(target))
                except OSError:
                    shutil.copyfile(raw, str(target))
                launch_path = str(target)
        current_temp = os.environ.get('TEMP') or os.environ.get('TMP') or ''
        if current_temp and not _is_ansi_safe_path(current_temp):
            short_temp = _windows_short_path(current_temp)
            ascii_temp = short_temp if (short_temp and _is_ansi_safe_path(short_temp)) else None
            if not ascii_temp:
                if temp_stage is None:
                    base = Path(os.environ.get('SystemDrive', 'C:') + '\\ProgramData\\bb10-volte\\flash-stage')
                    temp_stage = base / uuid.uuid4().hex[:12]
                    temp_stage.mkdir(parents=True, exist_ok=True)
                    try:
                        from preparation_cache import restrict_windows_acl
                        restrict_windows_acl(temp_stage, directory=True)
                    except Exception:
                        pass
                ascii_tmp_dir = temp_stage / 'tmp'
                ascii_tmp_dir.mkdir(exist_ok=True)
                ascii_temp = str(ascii_tmp_dir)
            env = dict(os.environ)
            env['TEMP'] = ascii_temp
            env['TMP'] = ascii_temp
    try:
        yield launch_path, str(Path(launch_path).parent), env
    finally:
        if temp_stage is not None:
            shutil.rmtree(temp_stage, ignore_errors=True)


def run_windows_autoloader(image, kit_dir, log_file, evidence, public_line, phase):
    """Run one Windows autoloader binary, recording live PID, prompts, status, and launch errors."""
    from preparation_cache import process_creation_time
    kit_dir = Path(kit_dir)
    active_file = kit_dir / 'flash-active.json'
    pending = bytearray()
    prompt_reported = False
    prefix_reported = None
    with ansi_safe_launch(image) as (launch_path, launch_cwd, launch_env):
        try:
            child = subprocess.Popen([launch_path], cwd=launch_cwd, env=launch_env,
                                     stdin=sys.stdin, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, bufsize=0)
        except OSError as error:
            code = getattr(error, 'winerror', None) or getattr(error, 'errno', None) or 1
            msg = 'Autoloader launch failed (OS error {})'.format(code)
            log_file.write('[' + msg + ']\n')
            log_file.flush()
            result = evidence.result(phase, -1)
            result['launch_error'] = 'os_error_' + str(code)
            result['error_seen'] = True
            result['completed'] = False
            return result
        if type(getattr(child, 'pid', None)) is int:
            try:
                active_file.write_text(json.dumps({
                    'pid': child.pid,
                    'created_at': process_creation_time(child.pid),
                    'phase': phase,
                }) + '\n', encoding='utf-8')
            except OSError:
                pass
        try:
            while True:
                char = child.stdout.read(1)
                if not char:
                    break
                sys.stdout.buffer.write(char)
                sys.stdout.buffer.flush()
                pending.extend(char)
                if not prompt_reported and password_prompt(pending):
                    log_file.write('[Device password input requested in native console]\n')
                    log_file.flush()
                    prompt_reported = True
                if prefix_reported is None:
                    seen_prefix = status_prefix(pending)
                    if seen_prefix:
                        log_file.write(seen_prefix + '\n')
                        log_file.flush()
                        prefix_reported = seen_prefix
                if char in (b'\r', b'\n'):
                    line = pending.decode('utf-8', 'replace')
                    evidence.line(line)
                    log_file.write(public_line(line))
                    log_file.flush()
                    pending.clear()
                    prompt_reported = False
                    prefix_reported = None
        finally:
            if pending:
                line = pending.decode('utf-8', 'replace')
                evidence.line(line)
                log_file.write(public_line(line))
                log_file.flush()
                pending.clear()
            exit_code = child.wait()
            try:
                active_file.unlink(missing_ok=True)
            except OSError:
                pass
    return evidence.result(phase, exit_code)


def pause_windows_console_on_failure(seconds=60):
    """Pause the failure console so owners can read output without hanging the GUI forever."""
    if (sys.platform != 'win32' or not isinstance(sys.stdin, io.TextIOBase) or
            not sys.stdin.isatty() or os.environ.get('BB10_FLASH_NO_PAUSE')):
        return
    print(tr('请先查看上方输出，按任意键关闭此窗口（{} 秒后自动返回应用）…').format(seconds), flush=True)
    try:
        import msvcrt
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                msvcrt.getwch()
                break
            time.sleep(0.1)
    except Exception:
        try:
            input(tr('请先查看上方输出，再按回车键关闭此窗口…'))
        except (EOFError, OSError):
            pass


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
    configure_windows_console(tr('bb10-volte：正在刷写 {} Root').format(phase.upper()))
    print(tr('bb10-volte：正在刷写 {} Root').format(phase.upper()), flush=True)
    print(tr('请保持 USB 连接；仅在黑莓工具提示时在此输入手机密码。'), flush=True)
    evidence = RootFlashEvidence()
    from macos_root_flash import public_line
    log = Path(folder) / ('flash-' + phase + '.log')
    # Claim the stage before launching the destructive child. Reopening the
    # same console must not execute the image before the existing-log check.
    with log.open('x', encoding='utf-8') as file:
        result = run_windows_autoloader(image, folder, file, evidence, public_line, phase)
    output = Path(folder) / ('flash-' + phase + '.json')
    temporary = output.with_suffix('.json.partial')
    with temporary.open('x', encoding='utf-8') as file:
        json.dump(result, file, indent=2)
    temporary.replace(output)
    print(tr('\n请返回 bb10-volte。状态未知或失败的阶段会保持暂停；不要重复运行。'), flush=True)
    if not result['completed']:
        print(tr('刷写工具退出码：{}（是否已进入写入：{}）').format(
            result['exit_code'], tr('是') if result.get('writing_started') else tr('否')), flush=True)
        if result.get('launch_error'):
            print(tr('未能启动刷写程序（{}）；请检查安全软件拦截或文件权限。').format(result['launch_error']), flush=True)
        elif not result.get('writing_started'):
            print(tr('未检测到进入写入阶段。常见原因：Windows 缺少 BlackBerry USB（Bootrom）驱动、未识别连接超时或密码提示中断。'), flush=True)
            print(tr('可在应用“Windows 驱动”页安装驱动，并通过“查看刷写日志并解除暂停”核对后重试。'), flush=True)
        pause_windows_console_on_failure()
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
