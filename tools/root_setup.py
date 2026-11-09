"""First-use preparation and explicitly confirmed, model-bound Root workflow."""
from i18n import tr
import http.client
import ipaddress
import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
import zipfile

from desktop_paths import resource_root, private_root, download_root, frozen
from fetch_materials import fetch_entries, import_material, sha
from connection import resolve_connection, save_connection
from workflow import WorkflowError

ROOT = resource_root()
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class SetupError(RuntimeError):
    pass


def catalog():
    return json.loads((ROOT / 'materials/first-run-tools.json').read_text(encoding='utf-8'))


def firmware_entries():
    source = json.loads((ROOT / 'materials/sources.json').read_text(encoding='utf-8'))
    return [item for item in source['verified_inputs'] + source.get('additional_firmware', [])
            if item['id'].startswith('stock-')]


def firmware_variants():
    return [variant for item in firmware_entries() for variant in item['variants']]


def stock_firmware(variant=None):
    if not variant:
        raise SetupError('firmware_model_required')
    matches = [item for item in firmware_entries() if variant in item['variants']]
    if len(matches) != 1:
        raise SetupError('firmware_model_unsupported')
    return matches[0]


def selected_firmware_variant(selected, usb):
    """An attached device takes precedence; offline selection must be explicit."""
    count = usb.get('usb_count')
    detected = (usb.get('device') or {}).get('ModelName')
    if isinstance(count, int) and count > 1:
        raise SetupError('firmware_multiple_devices')
    if detected or count == 1 or usb.get('usb_present'):
        if count != 1 or not detected:
            raise SetupError('firmware_device_unverified')
        stock_firmware(detected)
        if selected and selected != detected:
            raise SetupError('firmware_model_mismatch')
        return detected
    stock_firmware(selected)
    return selected


def download_stock_firmware(variant, progress, proxy=None, cache_dir=None, offline=False):
    item = stock_firmware(variant)
    cache = fetch_entries([item], folder=cache_dir, progress=progress, proxy=proxy, verify_only=offline)
    return str(cache / item['file'])


def import_stock_firmware(path, progress, cache_dir=None, *, variant=None):
    return str(import_material(stock_firmware(variant), path, folder=cache_dir, progress=progress))


def powershell():
    return str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')


def discovery(peer='169.254.0.1', source=None, interface_index=None):
    # Anonymous metadata on the directly attached USB link only. Never send
    # credentials, follow a redirect or use an Internet proxy for this request.
    connection = None
    try:
        if sys.platform == 'darwin' and source:
            # The system client can reach the USB link in Mac execution
            # contexts where a relocated Python runtime returns EHOSTUNREACH.
            from macos_discovery import read
            body = read(peer, source)
        else:
            connection = http.client.HTTPConnection(peer, timeout=4)
            if source:
                connection.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                connection.sock.settimeout(4)
                if sys.platform == 'win32' and interface_index is not None:
                    connection.sock.setsockopt(socket.IPPROTO_IP, 31, struct.pack('!I', interface_index))
                connection.sock.bind((source, 0))
                connection.sock.connect((peer, 80))
            connection.request('GET', '/cgi-bin/discovery.cgi', headers={
                'User-Agent': 'QNXWebClient/1.0', 'Connection': 'close'})
            response = connection.getresponse()
            if response.status != 200:
                return {}
            body = response.read(131073)
        if len(body) > 131072:
            return {}
        document = ET.fromstring(body)
        allowed = {'OsType', 'ModelName', 'PlatformVersion', 'DeveloperModeEnabled', 'OobeCompleted'}
        return {node.tag.rsplit('}', 1)[-1]: node.text for node in document.iter()
                if node.tag.rsplit('}', 1)[-1] in allowed}
    except (OSError, ValueError, ET.ParseError, http.client.HTTPException, subprocess.TimeoutExpired):
        return {}
    finally:
        if connection is not None:
            connection.close()


def usb_discovery_targets(state):
    """Use only the attached BlackBerry link, including stock DHCP /30 leases."""
    if state.get('usb_count') != 1:
        return []
    targets = []
    for interface in state.get('network_interfaces', []):
        if interface.get('active') is not True:
            continue
        for address in interface.get('ipv4', []):
            try:
                ip = ipaddress.IPv4Address(address)
                # Stock firmware assigns host .2 and phone .1 in a link-local
                # /30. Do not infer peers from Wi-Fi, /16 APIPA or arbitrary LANs.
                prefix = interface.get('prefixes', {}).get(address)
                if prefix != 30 or not ip.is_link_local or int(ip) % 4 != 2:
                    continue
                index = interface.get('index')
                if sys.platform == 'win32' and (type(index) is not int or index < 1):
                    continue
                target = (str(ip - 1), str(ip), index)
                if target not in targets:
                    targets.append(target)
            except (ValueError, TypeError):
                continue
    return targets


def local_usb_state():
    result = {'usb_present': None, 'usb_count': None, 'usb_network': None, 'driver_ready': None}
    if sys.platform == 'win32':
        script = r"""
$ErrorActionPreference='Stop'
$devices=@(Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match '^USB\\VID_0FCA&PID_[0-9A-F]{4}\\' })
$adapters=@(Get-NetAdapter -IncludeHidden | Where-Object { $_.InterfaceDescription -match 'BlackBerry' })
$links=@($adapters | Where-Object { $_.PnPDeviceID -match '^USB\\VID_0FCA&' } | ForEach-Object {
    $adapter=$_
    $addresses=@(Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object AddressState -eq 'Preferred')
    $prefixes=@{}; foreach ($address in $addresses) { $prefixes[$address.IPAddress]=$address.PrefixLength }
    @{index=[int]$adapter.ifIndex;active=($adapter.Status -eq 'Up');ipv4=@($addresses | Select-Object -ExpandProperty IPAddress);prefixes=$prefixes}
})
@{usb_present=($devices.Count -gt 0);usb_count=$devices.Count;driver_ready=(@($devices | Where-Object Status -eq 'OK').Count -eq $devices.Count -and $devices.Count -gt 0);usb_network=(@($links | Where-Object active).Count -gt 0);network_interfaces=$links} | ConvertTo-Json -Depth 5 -Compress
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
    result['device'] = {}
    targets = usb_discovery_targets(result)
    # A second active USB network is ambiguous; never choose by response order.
    if len(targets) == 1:
        peer, source, index = targets[0]
        result['device'] = discovery(peer, source, index)
        result['usb_peer'] = peer
        result['usb_source_address'] = source
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
    if sys.platform != 'win32':
        raise SetupError('windows_root_required')
    from preparation_cache import (preparation_lock, clean_abandoned_roots, reusable_root_kit,
                                   mark_ready, clean_failed_root, trim_intermediates)
    private = private_root()
    with preparation_lock(private):
        clean_abandoned_roots(private, progress)
        existing = reusable_root_kit(private, variant, 'win32', progress)
        if existing:
            return existing
        if shutil.disk_usage(private).free < 15 * 1024 ** 3:
            raise SetupError('insufficient_disk')
        folder = private / ('root-kit-' + uuid.uuid4().hex[:12])
        try:
            _prepare_root_kit_windows(folder, variant, progress, proxy, cache_dir, offline)
            mark_ready(folder)
        except BaseException:
            clean_failed_root(private, folder, progress)
            raise
        trim_intermediates(folder, variant, progress)
        return str(folder)


def _prepare_root_kit_windows(folder, variant, progress, proxy, cache_dir, offline):
    tools = ensure_tools(progress, proxy, cache_dir, offline)
    source = json.loads((ROOT / 'materials/sources.json').read_text(encoding='utf-8'))
    inputs = [item for item in source['verified_inputs'] if not item['id'].startswith('stock-')]
    fetch_entries(inputs + [stock_firmware(variant)], tools['cache'], progress, proxy, verify_only=offline)
    progress(tr('生成本设备使用的个人密钥与 Root 镜像'))
    import prepare_root
    prepare_root.main(['--variant', variant, '--seven-zip', str(tools['seven_zip']), '--output', str(folder),
                       '--cache', str(tools['cache']), '--openssl-dir', str(tools['openssl']),
                       '--ssh-keygen', str(tools['keygen'])])
    progress(tr('构建并校验系统与无线镜像；此步骤尚不刷写手机'))
    import build_root
    try:
        build_root.main(['--kit', str(folder)])
    except Exception as error:
        from feedback import build_failure_excerpt
        error.feedback_log = build_failure_excerpt(folder)
        raise
    (folder / 'setup-state.json').write_text(json.dumps({'variant': variant, 'stage': 'prepared'}, indent=2), encoding='utf-8')
    return str(folder)


def prepared_images(folder, allowed_stages=('prepared',)):
    from preparation_cache import linked
    folder = Path(folder)
    if linked(folder) or linked(folder / 'images'):
        raise SetupError('image_not_verified')
    folder = folder.resolve()
    state = json.loads((folder / 'setup-state.json').read_text(encoding='utf-8'))
    if state['variant'] not in catalog()['auto_root_variants'] or state['stage'] not in allowed_stages:
        raise SetupError('flash_state_unknown')
    build = json.loads((folder / 'build-verification.json').read_text(encoding='utf-8'))
    if build.get('offline_build_verified') is not True or len(build.get('images', [])) != 2:
        raise SetupError('image_not_verified')
    stock = stock_firmware(state['variant'])
    # Existing Q10 journals predate model-bound receipts. They are Q10-only.
    legacy = 'variant' not in build and stock['family'] == 'q10'
    if not legacy and (build.get('variant') != state['variant'] or build.get('firmware_id') != stock['id'] or
                       build.get('stock_sha256') != stock['extracted_sha256'] or
                       build.get('platform') != state.get('platform', 'win32')):
        raise SetupError('image_not_verified')
    images = []
    suffixes = ('_os.unsigned', '_radio.signed') if state.get('platform') == 'darwin' else ('_os.exe', '_radio.exe')
    for suffix in suffixes:
        items = [item for item in build['images'] if item['file'].endswith(suffix)]
        if len(items) != 1 or Path(items[0]['file']).name != items[0]['file']:
            raise SetupError('image_not_verified')
        item = items[0]
        expected_name = Path(stock['extracted_file']).stem + suffix
        if item['file'] != expected_name and not (legacy and item['file'] == 'Q10' + suffix):
            raise SetupError('image_not_verified')
        path = folder / 'images' / item['file']
        if path.is_symlink() or path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            raise SetupError('image_not_verified')
        images.append(path)
    return state, images


def prepared_kit_history():
    """Read bounded preparation journals; listing is never flash authorization."""
    result = []
    folders = [private_root() / 'root-kit'] + sorted(private_root().glob('root-kit-*'))
    for folder in folders:
        if folder.is_symlink() or folder.is_junction():
            continue
        try:
            journal = folder / 'setup-state.json'
            if journal.is_symlink() or journal.stat().st_size > 65536:
                continue
            state = json.loads(journal.read_text(encoding='utf-8'))
            if state.get('variant') not in catalog()['auto_root_variants'] or not isinstance(state.get('stage'), str):
                continue
            result.append({'folder': str(folder), 'variant': state['variant'], 'stage': state['stage'],
                           'platform': state.get('platform', 'win32')})
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return result


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
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/bb10-volte/private/root-flash.lock'
    local = os.environ.get('LOCALAPPDATA')
    return (Path(local) / 'bb10-volte/private' if local else private_root()) / 'root-flash.lock'


def flash_root(folder, confirmed, progress):
    if sys.platform not in ('win32', 'darwin') or confirmed is not True:
        raise SetupError('flash_confirmation_required')
    state, images = prepared_images(folder)
    if state.get('platform', 'win32') != sys.platform:
        raise SetupError('root_platform_mismatch')
    usb = local_usb_state()
    if usb.get('usb_count') != 1 or (usb.get('device') or {}).get('ModelName') != state['variant']:
        raise SetupError('device_model_not_verified')
    from firmware_policy import baseline_error
    version_error = baseline_error(usb['device'])
    if version_error:
        raise SetupError(version_error)
    if sys.platform == 'darwin' and usb.get('usb_address_ready') is not True:
        raise SetupError('usb_source_address_required')
    try:
        if usb.get('usb_peer') and usb.get('usb_source_address'):
            # A stock first boot uses DHCP, while AutoRoot uses 169.254.0.1.
            # Probe the actual phone with an ordinary strict SSH client; an
            # inaccessible old address (or absent saved profile) is not evidence
            # that this phone is unrooted. This also applies to the default link.
            from workflow import Client
            client = Client('bb10-root', str(Path(folder) / 'ssh_config'))
            client.options[:0] = ['-o', 'HostName=' + usb['usb_peer'],
                                 '-o', 'BindAddress=' + usb['usb_source_address'],
                                 '-o', 'ProxyCommand=none', '-o', 'ProxyJump=none',
                                 '-o', 'User=root', '-o', 'Port=22',
                                 '-o', 'HostKeyAlias=169.254.0.1']
            client.remote('echo BB10_CONNECTION_READY', timeout=12)
            raise SetupError('ssh_access_needs_repair')
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
        progress(tr('正在刷写') + (tr('系统') if name == 'os' else tr('无线固件')) + tr('。请保持 USB 连接，并按刷写窗口的密码提示操作。'))
        try:
            result = run_flash_stage(folder, name, state['confirmation_token'])
        except (SetupError, OSError, ValueError):
            state['stage'] = name + '_uncertain'
            journal.write_text(json.dumps(state, indent=2), encoding='utf-8')
            raise SetupError('flash_state_unknown') from None
        if result.get('expected_v4_os_security_result'):
            progress(tr('系统写入已完成，出现此 AutoRoot 配方的已知安全提示；继续无线固件步骤。'))
    state['stage'] = 'flashed_waiting_for_root'
    state.pop('confirmation_token', None)
    journal.write_text(json.dumps(state, indent=2), encoding='utf-8')
    lock.unlink()
    return {'host': 'bb10-root', 'config': str(folder / 'ssh_config')}


def prepare_driver_kit(progress, proxy=None):
    from preparation_cache import preparation_lock, linked, read_json, remove_owned_tree
    private = private_root()
    spec = json.loads((ROOT / 'materials/usb-drivers.json').read_text(encoding='utf-8'))
    files = {'package/BlackBerry-USBDrivers-5.0.0.2.exe': spec['bundle_sha256'],
             'USBInstallerMSIx64.msi': spec['msi_sha256'],
             **{'rim-usb/' + name: digest for name, digest in spec['driver_files'].items()}}
    with preparation_lock(private):
        for folder in [private / 'windows-usb'] + sorted(private.glob('windows-usb-*')):
            if linked(folder) or any(linked(folder / name) for name in ('package', 'rim-usb')):
                continue
            try:
                if read_json(folder / 'verification.json').get('prepared') is not True:
                    continue
                verify_files(folder, files)
            except (OSError, ValueError, SetupError):
                continue
            progress(tr('本地驱动文件校验通过，复用已有准备：') + str(folder))
            return str(folder)
        tools = ensure_tools(progress, proxy)
        fetch_entries(spec['parts'], tools['cache'], progress, proxy)
        folder = private / ('windows-usb-' + uuid.uuid4().hex[:12])
        import prepare_usb_drivers
        try:
            prepare_usb_drivers.main(['--seven-zip', str(tools['seven_zip']), '--output', str(folder), '--cache', str(tools['cache'])])
        except BaseException:
            # This directory belongs to this call and has never been installed.
            for name in ('package', 'bootstrapper', 'payload', 'extracted', 'rim-usb'):
                remove_owned_tree(private, folder, name)
            for name in ('payload.cab', 'USBInstallerMSIx64.msi'):
                (folder / name).unlink(missing_ok=True)
            raise
        for name in ('bootstrapper', 'payload', 'extracted'):
            remove_owned_tree(private, folder, name)
        (folder / 'payload.cab').unlink(missing_ok=True)
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
