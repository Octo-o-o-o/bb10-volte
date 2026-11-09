"""Reuse verified offline preparations and bound their disposable build output.

Never delete an old, unmarked kit or anything with evidence of a flash. Personal
keys, connection files and logs remain in place even after a failed preparation.
"""
from contextlib import contextmanager, ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from desktop_paths import resource_root
from fetch_materials import DownloadError, _download_lock, sha
from i18n import tr

MARKER = 'local-preparation.json'
RECIPE_VERSION = 1
KEY_FILES = ('q10_root_rsa', 'q10_root_rsa.pub', 'q10_host_rsa',
             'q10_host_rsa.pub', 'known_hosts', 'ssh_config')


def linked(path):
    return path.is_symlink() or path.is_junction()


def read_json(path):
    if linked(path) or path.stat().st_size > 65536:
        raise ValueError('Invalid preparation record')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Invalid preparation record')
    return value


def write_record(folder, record):
    target = Path(folder) / MARKER
    temporary = target.with_name(MARKER + '.tmp')
    if linked(target) or linked(temporary):
        raise ValueError('Linked preparation record')
    temporary.write_text(json.dumps(record, indent=2), encoding='utf-8')
    temporary.replace(target)


def process_alive(pid):
    if type(pid) is not int or pid < 1:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        api.OpenProcess.restype = wintypes.HANDLE
        api.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        api.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = api.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # Access denied is uncertain, not dead.
        try:
            code = wintypes.DWORD()
            return not api.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def active_build(record):
    owner = record.get('owner_pid')
    worker = record.get('worker_pid')
    return (owner != os.getpid() and process_alive(owner)) or worker == 'starting' or process_alive(worker)


def run_preparation(command, folder, **kwargs):
    """Record heavy child processes so a crashed GUI cannot erase live output."""
    folder = Path(folder)
    if not (folder / MARKER).exists():
        return subprocess.run(command, **kwargs)
    timeout, check = kwargs.pop('timeout', None), kwargs.pop('check', False)
    if kwargs.pop('capture_output', False):
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    def worker(pid):
        record = read_json(folder / MARKER)
        record['worker_pid'] = pid
        write_record(folder, record)
    worker('starting')
    process = None
    try:
        process = subprocess.Popen(command, **kwargs)
        worker(process.pid)
        stdout, stderr = process.communicate(timeout=timeout)
        result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        if check:
            result.check_returncode()
        return result
    except BaseException:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()
        raise
    finally:
        worker(None)


@contextmanager
def preparation_lock(private):
    """An OS lock is released after crashes, unlike a persistent busy flag."""
    from root_setup import SetupError, root_lock_path
    private = Path(private)
    if linked(private):
        raise SetupError('image_not_verified')
    private.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        try:
            stack.enter_context(_download_lock(private / 'local-preparation.lock'))
        except DownloadError as error:
            if error.code == 'download_busy':
                raise SetupError('preparation_busy') from None
            raise
        if root_lock_path().exists():
            raise SetupError('flash_state_unknown')
        yield


def recipe_id(variant, platform):
    from root_images import recipe
    stock, partitions = recipe(variant)
    source = read_json(resource_root() / 'materials/sources.json')
    def content_fields(item):
        return {key: value for key, value in item.items() if key not in ('url', 'mirrors', 'notes', 'browser_downloads')}
    # Bump recipe_version when the owner-key/patch recipe changes. Application
    # revisions alone must not invalidate gigabytes of identical local output.
    value = {'recipe_version': RECIPE_VERSION, 'variant': variant, 'platform': platform,
             'stock': content_fields(stock), 'partitions': partitions,
             'inputs': [content_fields(item) for item in source['verified_inputs'] if not item['id'].startswith('stock-')],
             'openssl': source['openssl']}
    if platform == 'darwin':
        from macos_root import architecture, specification, tool_hashes
        value.update(architecture=architecture(), native_tools=tool_hashes(specification(), architecture()))
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def mark_started(folder, variant, platform):
    record = {'schema': 1, 'status': 'building', 'variant': variant,
              'platform': platform, 'recipe': recipe_id(variant, platform), 'owner_pid': os.getpid()}
    write_record(folder, record)


def key_hashes(folder):
    result = {}
    for name in KEY_FILES:
        path = folder / name
        if linked(path) or not path.is_file() or not 0 < path.stat().st_size <= 65536:
            raise ValueError('Missing or changed personal credentials')
        result[name] = sha(path)
    return result


def mark_ready(folder):
    folder = Path(folder)
    record = read_json(folder / MARKER)
    record.update(status='ready', keys=key_hashes(folder))
    write_record(folder, record)


def untouched(folder):
    """A preparation may be reused, but a prior flash must never be reset."""
    if any(folder.glob('flash-*')) or any(folder.glob('upgrade-*')):
        return False
    journal = folder / 'firmware-upgrade.json'
    if journal.exists():
        state = read_json(journal)
        if state.get('stage') != 'prepared' or state.get('phone_contacted') is not False:
            return False
    return True


def kit_folders(private):
    return [Path(private) / 'root-kit'] + sorted(Path(private).glob('root-kit-*'))


def legacy_record(folder, variant, platform):
    """Adopt r42's unchanged recipe only with its complete local evidence.

    Older or incomplete records remain available through the existing history
    flow; they are neither guessed compatible nor automatically removed.
    """
    from root_setup import stock_firmware
    if RECIPE_VERSION != 1:
        raise ValueError('Legacy recipe is no longer current')
    stock = stock_firmware(variant)
    preparation = read_json(folder / 'preparation.json')
    state = read_json(folder / 'setup-state.json')
    build = read_json(folder / 'build-verification.json')
    source = read_json(resource_root() / 'materials/sources.json')
    bundle = next(item for item in source['verified_inputs'] if item['id'] == 'autoroot-v4')
    expected = {'variant': variant, 'platform': platform, 'firmware_id': stock['id'],
                'stock_sha256': stock['extracted_sha256'], 'root_bundle_sha256': bundle['sha256'],
                'offline_preparation_complete': True, 'shared_default_ssh_authorization_replaced': True}
    if (any(preparation.get(key) != value for key, value in expected.items())
            or state.get('stage') != 'prepared' or state.get('variant') != variant
            or build.get('variant') != variant or build.get('platform') != platform):
        raise ValueError('Legacy recipe does not match')
    work = folder / 'autoroot'
    if linked(work) or any(linked(path) for path in work.rglob('*')):
        raise ValueError('Linked legacy recipe')
    original = (work / 'patch.txt').read_text()
    patch = '\n'.join(line for line in original.splitlines()
                      if not line.startswith('removeapp ') and not line.startswith('#sys.')) + '\n'
    if (work / 'patch-owner.txt').read_text() != patch:
        raise ValueError('Changed legacy patch recipe')
    ssh = work / 'patchdata/var/etc/ssh'
    public = (folder / 'q10_root_rsa.pub').read_text().strip()
    expected_key = 'from="169.254.0.2",no-agent-forwarding,no-port-forwarding,no-X11-forwarding ' + public + '\n'
    config = (ssh / 'sshd_config').read_text()
    if ((ssh / 'authorized_keys2').read_text() != expected_key
            or sha(ssh / 'ssh_host_rsa_key') != sha(folder / 'q10_host_rsa')
            or 'PasswordAuthentication=no' not in config
            or platform == 'win32' and variant == 'SQC100-4' and 'UseDNS=no' not in config):
        raise ValueError('Changed legacy SSH recipe')
    if platform == 'darwin':
        from macos_root import architecture, specification, tool_hashes, verified_tools
        if (preparation.get('architecture') != architecture()
                or preparation.get('tool_hashes') != tool_hashes(specification(), architecture())):
            raise ValueError('Different native Mac recipe')
        verified_tools(work)
    return {'schema': 1, 'status': 'ready', 'variant': variant, 'platform': platform,
            'recipe': recipe_id(variant, platform), 'keys': key_hashes(folder), 'adopted_legacy': True}


def reusable_root_kit(private, variant, platform, progress):
    from root_setup import SetupError, prepared_images, stock_firmware
    fingerprint = None
    for folder in kit_folders(private):
        if linked(folder) or linked(folder / MARKER) or not folder.is_dir():
            continue
        try:
            adopt = not (folder / MARKER).exists()
            record = legacy_record(folder, variant, platform) if adopt else read_json(folder / MARKER)
            if (record.get('schema') != 1 or record.get('status') != 'ready'
                    or record.get('variant') != variant or record.get('platform') != platform
                    or not untouched(folder)):
                continue
            if fingerprint is None:
                fingerprint = recipe_id(variant, platform)
            if record.get('recipe') != fingerprint:
                continue
            state, _ = prepared_images(folder)
            if state['variant'] != variant or state.get('platform', 'win32') != platform:
                continue
            if record.get('keys') != key_hashes(folder):
                continue
            stock = stock_firmware(variant)
            original = folder / 'stock' / stock['extracted_file']
            if linked(original.parent) or linked(original) or sha(original) != stock['extracted_sha256']:
                continue
        except (OSError, ValueError, KeyError, TypeError, SetupError):
            continue
        if adopt:
            write_record(folder, record)
        progress(tr('本地镜像、原版固件和个人密钥校验通过，复用已有准备：') + str(folder))
        trim_intermediates(folder, variant, progress)
        return str(folder)
    return None


def remove_owned_tree(private, folder, name):
    """Validate the whole tree and resolved boundary before recursive removal."""
    private, folder = Path(private), Path(folder)
    target = folder / name
    if not target.exists() and not linked(target):
        return
    if (linked(private) or linked(folder) or linked(target)
            or folder.resolve().parent != private.resolve()
            or target.resolve().parent != folder.resolve() or not target.is_dir()):
        raise ValueError('Unsafe preparation directory')
    if any(linked(path) for path in target.rglob('*')):
        raise ValueError('Linked preparation output')
    shutil.rmtree(target)


def clean_failed_root(private, folder, progress):
    folder = Path(folder)
    try:
        if linked(folder) or not (folder / MARKER).exists():
            return
        record = read_json(folder / MARKER)
        if (record.get('schema') != 1 or record.get('status') not in ('building', 'failed') or active_build(record)
                or (folder / 'setup-state.json').exists() or (folder / 'build-verification.json').exists()
                or not untouched(folder)):
            return
        for name in ('images', 'stock', 'autoroot'):
            remove_owned_tree(private, folder, name)
        record['status'] = 'failed'
        write_record(folder, record)
    except (OSError, ValueError, TypeError):
        progress(tr('部分构建临时文件未能清理，请退出程序后按磁盘清理说明处理：') + str(folder))


def clean_abandoned_roots(private, progress):
    # Called only while holding the preparation lock. Old releases have no
    # marker and are intentionally left for explicit manual cleanup.
    for folder in kit_folders(private):
        if (folder / MARKER).is_file():
            try:
                record = read_json(folder / MARKER)
            except (OSError, ValueError):
                continue
            worker = record.get('worker_pid')
            if (record.get('status') == 'building' and active_build(record)
                    or worker == 'starting' or process_alive(worker)):
                from root_setup import SetupError
                raise SetupError('preparation_busy')
            clean_failed_root(private, folder, progress)


def trim_intermediates(folder, variant, progress):
    """Only known bb10mt intermediates; keep both verified flash images/stock."""
    from root_setup import stock_firmware
    output = Path(folder) / 'images'
    if linked(Path(folder)) or linked(output):
        return
    stem = Path(stock_firmware(variant)['extracted_file']).stem
    suffixes = ('.0.0.ifs', '.0.1.rcfs', '.0.2.sig2', '.0.3.mbr', '.0.4.ufs',
                '.0.lst', '.0.signed', '.0.unsigned', '.1.signed')
    try:
        for suffix in suffixes:
            path = output / (stem + suffix)
            if path.is_file() and not linked(path):
                path.unlink()
    except OSError:
        progress(tr('部分构建临时文件未能清理，请退出程序后按磁盘清理说明处理：') + str(folder))
