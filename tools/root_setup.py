"""First-use preparation and explicitly confirmed Windows Q10 Root workflow."""
import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile

from desktop_paths import resource_root, private_root, download_root, frozen
from fetch_materials import fetch_entries, sha
from connection import resolve_connection, save_connection
from workflow import WorkflowError

ROOT = resource_root()
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class SetupError(RuntimeError):
    pass


def catalog():
    return json.loads((ROOT / 'materials/first-run-tools.json').read_text(encoding='utf-8'))


def powershell():
    return str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')


def discovery():
    # Anonymous metadata on the directly attached USB link only. Never send
    # credentials, follow a redirect or use an Internet proxy for this request.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    req = urllib.request.Request('http://169.254.0.1/cgi-bin/discovery.cgi', headers={'User-Agent': 'QNXWebClient/1.0'})
    try:
        with opener.open(req, timeout=4) as response:
            body = response.read(131072)
        document = ET.fromstring(body)
        allowed = {'OsType', 'ModelName', 'PlatformVersion', 'DeveloperModeEnabled'}
        return {node.tag.rsplit('}', 1)[-1]: node.text for node in document.iter()
                if node.tag.rsplit('}', 1)[-1] in allowed}
    except (OSError, ValueError, ET.ParseError):
        return {}


def local_usb_state():
    result = {'usb_present': None, 'usb_count': None, 'usb_network': None, 'driver_ready': None}
    if sys.platform == 'win32':
        script = r"""
$ErrorActionPreference='Stop'
$devices=@(Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match '^USB\\VID_0FCA&PID_[0-9A-F]{4}\\' })
$adapters=@(Get-NetAdapter -IncludeHidden | Where-Object { $_.InterfaceDescription -match 'BlackBerry' })
@{usb_present=($devices.Count -gt 0);usb_count=$devices.Count;driver_ready=(@($devices | Where-Object Status -eq 'OK').Count -eq $devices.Count -and $devices.Count -gt 0);usb_network=(@($adapters | Where-Object Status -eq 'Up').Count -gt 0)} | ConvertTo-Json -Compress
"""
        try:
            raw = subprocess.run([powershell(), '-NoProfile', '-Command', script], capture_output=True,
                                 text=True, timeout=18, creationflags=NO_WINDOW)
            if raw.returncode == 0:
                result.update(json.loads(raw.stdout))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    elif sys.platform == 'darwin':
        from macos_usb import read_state
        result.update(read_state())
    result['device'] = discovery()
    # Do not open and abandon QNX development sessions or raw SSH sockets.
    # SSH availability is established by the ordinary, authenticated client.
    result['ssh_port'] = None
    return result


def verify_root(host='bb10-root', config=''):
    client, choice = resolve_connection(host, config)
    try:
        # BB10 deliberately disables Python -c for EUID 0. A hash-checked,
        # individually trusted script respects that restriction.
        with client.stage(diagnostic='root') as path:
            result = client.execute(path + '/root-probe.py', timeout=15)
    except WorkflowError as error:
        if error.code in ('remote_operation_failed', 'invalid_device_response'):
            raise SetupError('root_probe_failed') from None
        raise
    if (not isinstance(result, dict) or type(result.get('schema')) is not int or result['schema'] != 1 or
            type(result.get('euid')) is not int or result['euid'] < 0):
        raise SetupError('root_probe_failed')
    # Outside the context: a completed non-root diagnostic is cleaned too.
    if result['euid'] != 0:
        raise SetupError('root_not_ready')
    save_connection(choice['host'], choice['config'])
    return choice


def verify_files(folder, files):
    for name, expected in files.items():
        path = Path(folder) / name
        if not path.is_file() or path.is_symlink() or sha(path) != expected:
            raise SetupError('tool_hash_mismatch')


def ensure_ssh(progress, proxy=None, cache_dir=None, offline=False):
    if sys.platform != 'win32':
        raise SetupError('windows_root_required')
    cache = Path(cache_dir) if cache_dir else download_root()
    ssh_spec = json.loads((ROOT / 'materials/windows-runtime.json').read_text(encoding='utf-8'))['openssh']
    bundled = ROOT / 'vendor/openssh'
    if frozen() and bundled.is_dir():
        verify_files(bundled, ssh_spec['files'])
        return bundled
    fetch_entries([ssh_spec], folder=cache, progress=progress, proxy=proxy, verify_only=offline)
    ssh = private_root() / 'first-run-tools/openssh'
    ssh.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(cache / ssh_spec['file']) as archive:
        for name, expected in ssh_spec['files'].items():
            data = archive.read(ssh_spec['prefix'] + name)
            if hashlib.sha256(data).hexdigest() != expected:
                raise SetupError('tool_hash_mismatch')
            (ssh / name).write_bytes(data)
    verify_files(ssh, ssh_spec['files'])
    return ssh


def ensure_tools(progress, proxy=None, cache_dir=None, offline=False):
    if sys.platform != 'win32':
        raise SetupError('windows_root_required')
    spec = catalog()
    cache = Path(cache_dir) if cache_dir else download_root()
    fetch_entries([spec['seven_zip_bootstrap'], spec['seven_zip_package'], spec['openssl_package']],
                  folder=cache, progress=progress, proxy=proxy, verify_only=offline)
    tools = private_root() / 'first-run-tools'
    tools.mkdir(parents=True, exist_ok=True)
    seven = tools / '7zip-26.05'
    seven.mkdir(exist_ok=True)
    if not all((seven / name).is_file() for name in spec['seven_zip_files']):
        subprocess.run([str(cache / spec['seven_zip_bootstrap']['file']), 'e',
                        str(cache / spec['seven_zip_package']['file'])] + list(spec['seven_zip_files']) +
                       ['-o' + str(seven), '-y'], check=True, capture_output=True, creationflags=NO_WINDOW)
    verify_files(seven, spec['seven_zip_files'])
    openssl = tools / 'openssl'
    openssl.mkdir(exist_ok=True)
    source = json.loads((ROOT / 'materials/sources.json').read_text(encoding='utf-8'))
    with zipfile.ZipFile(cache / spec['openssl_package']['file']) as archive:
        for name, expected in source['openssl']['files'].items():
            data = archive.read('mingw64/bin/' + name)
            if hashlib.sha256(data).hexdigest() != expected:
                raise SetupError('tool_hash_mismatch')
            (openssl / name).write_bytes(data)
        license_data = archive.read('mingw64/share/licenses/openssl/LICENSE')
        if hashlib.sha256(license_data).hexdigest() != spec['openssl_license_sha256']:
            raise SetupError('tool_hash_mismatch')
        (openssl / 'OPENSSL-LICENSE.txt').write_bytes(license_data)
    ssh = ensure_ssh(progress, proxy, cache, offline)
    return {'seven_zip': seven / '7z.exe', 'openssl': openssl, 'keygen': ssh / 'ssh-keygen.exe', 'cache': cache}


def prepare_root_kit(variant, progress, proxy=None, cache_dir=None, offline=False):
    if variant not in catalog()['auto_root_variants']:
        raise SetupError('root_model_unsupported')
    if sys.platform == 'darwin':
        from macos_root import prepare_root_kit_macos
        return prepare_root_kit_macos(variant, progress, proxy, cache_dir, offline)
    private_root().mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(private_root()).free < 15 * 1024 ** 3:
        raise SetupError('insufficient_disk')
    tools = ensure_tools(progress, proxy, cache_dir, offline)
    source = json.loads((ROOT / 'materials/sources.json').read_text(encoding='utf-8'))
    fetch_entries(source['verified_inputs'], tools['cache'], progress, proxy, verify_only=offline)
    folder = private_root() / ('root-kit-' + uuid.uuid4().hex[:12])
    progress('生成本设备使用的个人密钥与 Root 镜像')
    import prepare_root
    prepare_root.main(['--seven-zip', str(tools['seven_zip']), '--output', str(folder),
                       '--cache', str(tools['cache']), '--openssl-dir', str(tools['openssl']),
                       '--ssh-keygen', str(tools['keygen'])])
    progress('构建并校验系统与无线镜像；此步骤尚不刷写手机')
    import build_root
    build_root.main(['--kit', str(folder)])
    (folder / 'setup-state.json').write_text(json.dumps({'variant': variant, 'stage': 'prepared'}, indent=2), encoding='utf-8')
    return str(folder)


def prepared_images(folder, allowed_stages=('prepared',)):
    folder = Path(folder).resolve()
    state = json.loads((folder / 'setup-state.json').read_text(encoding='utf-8'))
    if state['variant'] not in catalog()['auto_root_variants'] or state['stage'] not in allowed_stages:
        raise SetupError('flash_state_unknown')
    build = json.loads((folder / 'build-verification.json').read_text(encoding='utf-8'))
    if build.get('offline_build_verified') is not True or len(build.get('images', [])) != 2:
        raise SetupError('image_not_verified')
    images = []
    suffixes = ('_os.unsigned', '_radio.signed') if state.get('platform') == 'darwin' else ('_os.exe', '_radio.exe')
    for suffix in suffixes:
        items = [item for item in build['images'] if item['file'].endswith(suffix)]
        if len(items) != 1 or Path(items[0]['file']).name != items[0]['file']:
            raise SetupError('image_not_verified')
        item = items[0]
        path = folder / 'images' / item['file']
        if path.is_symlink() or path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            raise SetupError('image_not_verified')
        images.append(path)
    return state, images


def run_flash_stage(folder, stage, token):
    if sys.platform == 'darwin':
        from macos_root_flash import launch_stage
        return launch_stage(folder, stage, token)
    args = ['--stage', stage, '--kit', str(folder), '--token', token]
    command = ([sys.executable, '--flash-stage', stage, '--root-kit', str(folder), '--flash-token', token]
               if frozen() else [sys.executable, str(ROOT / 'tools/root_flash.py')] + args)
    result = subprocess.run(command, creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0))
    report = Path(folder) / ('flash-' + stage + '.json')
    if result.returncode != 0 or not report.is_file():
        raise SetupError('flash_state_unknown')
    value = json.loads(report.read_text(encoding='utf-8'))
    if value.get('stage') != stage or value.get('completed') is not True:
        raise SetupError('flash_state_unknown')
    return value


def root_lock_path():
    local = os.environ.get('LOCALAPPDATA')
    return (Path(local) / 'bb10-volte/private' if local else private_root()) / 'root-flash.lock'


def flash_root(folder, confirmed, progress):
    if sys.platform not in ('win32', 'darwin') or confirmed is not True:
        raise SetupError('flash_confirmation_required')
    state, images = prepared_images(folder)
    if state.get('platform', 'win32') != sys.platform:
        raise SetupError('root_platform_mismatch')
    usb = local_usb_state()
    if usb.get('usb_count') != 1 or usb['device'].get('ModelName') != state['variant']:
        raise SetupError('device_model_not_verified')
    if sys.platform == 'darwin' and usb.get('usb_address_ready') is not True:
        raise SetupError('usb_source_address_required')
    try:
        verify_root()
    except WorkflowError as error:
        if error.code not in ('connection_setup_required', 'connection_refused'):
            raise SetupError('ssh_access_needs_repair') from None
    except SetupError:
        raise SetupError('ssh_access_needs_repair') from None
    else:
        raise SetupError('already_rooted')
    folder = Path(folder)
    journal = folder / 'setup-state.json'
    state['confirmation_token'] = uuid.uuid4().hex
    lock = root_lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        with lock.open('x', encoding='utf-8') as file:
            json.dump({'pid': os.getpid(), 'kit': str(folder), 'token': state['confirmation_token']}, file)
    except FileExistsError:
        raise SetupError('flash_state_unknown') from None
    for name, image in zip(('os', 'radio'), images):
        state['stage'] = name + '_started'
        journal.write_text(json.dumps(state, indent=2), encoding='utf-8')
        progress('正在刷写' + ('系统' if name == 'os' else '无线固件') + '。请保持 USB 连接，并按刷写窗口的密码提示操作。')
        try:
            result = run_flash_stage(folder, name, state['confirmation_token'])
        except (SetupError, OSError, ValueError):
            state['stage'] = name + '_uncertain'
            journal.write_text(json.dumps(state, indent=2), encoding='utf-8')
            raise SetupError('flash_state_unknown') from None
        if result.get('expected_v4_os_security_result'):
            progress('系统写入已完成，出现此 AutoRoot 配方的已知安全提示；继续无线固件步骤。')
    state['stage'] = 'flashed_waiting_for_root'
    state.pop('confirmation_token', None)
    journal.write_text(json.dumps(state, indent=2), encoding='utf-8')
    lock.unlink()
    return {'host': 'bb10-root', 'config': str(folder / 'ssh_config')}


def prepare_driver_kit(progress, proxy=None):
    tools = ensure_tools(progress, proxy)
    spec = json.loads((ROOT / 'materials/usb-drivers.json').read_text(encoding='utf-8'))
    fetch_entries(spec['parts'], tools['cache'], progress, proxy)
    folder = private_root() / ('windows-usb-' + uuid.uuid4().hex[:12])
    import prepare_usb_drivers
    prepare_usb_drivers.main(['--seven-zip', str(tools['seven_zip']), '--output', str(folder), '--cache', str(tools['cache'])])
    return str(folder)


def install_driver_kit(folder):
    # Use standard Windows UAC on the recipient's machine, with explicit paths.
    # The assistant's personal administrator bridge is not a product dependency.
    if root_lock_path().exists():
        raise SetupError('flash_state_unknown')
    script = ROOT / 'tools/install_usb_drivers.ps1'
    spec = ROOT / 'materials/usb-drivers.json'
    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"
    args = '-NoProfile -File "' + str(script) + '" -PreparedKit "' + str(folder) + '" -SpecPath "' + str(spec) + '"'
    command = ("$ErrorActionPreference='Stop'; try { $p=Start-Process -FilePath " + quote(powershell()) +
               ' -ArgumentList ' + quote(args) + ' -Verb RunAs -WindowStyle Hidden -Wait -PassThru; exit $p.ExitCode } catch { exit 1 }')
    result = subprocess.run([powershell(), '-NoProfile', '-Command', command], creationflags=NO_WINDOW)
    if result.returncode not in (0, 3010):
        raise SetupError('driver_install_incomplete')
    return {'installed': True, 'reboot_required': result.returncode == 3010}
