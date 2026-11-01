"""Owner-confirmed stock upgrade followed by observed boot and separate Root.

Preparation is offline-capable and never contacts a phone. A completed loader
does not establish a completed upgrade: discovery must read the target OS back.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

from desktop_paths import private_root, resource_root
from fetch_materials import sha
from firmware_policy import TARGET_OS, assess_version
from i18n import tr
import root_setup as root

JOURNAL = 'firmware-upgrade.json'
STAGES = ('prepared', 'stock_started', 'stock_os_started', 'stock_radio_started',
          'uncertain', 'awaiting_reboot', 'os_verified')


def kit_path(folder):
    folder = Path(folder)
    if folder.is_symlink() or folder.is_junction():
        raise root.SetupError('image_not_verified')
    return folder.resolve()


def stock_images(stock):
    spec = json.loads((resource_root() / 'materials/stock-upgrade.json').read_text(encoding='utf-8'))
    item = spec['families'].get(stock['family'])
    if (spec.get('schema') != 1 or spec.get('target') != TARGET_OS or not item
            or item.get('firmware_id') != stock['id'] or item.get('stock_sha256') != stock['extracted_sha256']):
        raise root.SetupError('image_not_verified')
    return item['images']


def write_state(folder, state):
    target = kit_path(folder) / JOURNAL
    if target.is_symlink():
        raise root.SetupError('image_not_verified')
    temporary = target.with_name(JOURNAL + '.' + uuid.uuid4().hex + '.partial')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(state, stream, indent=2)
    temporary.replace(target)


def read_state(folder):
    folder = kit_path(folder)
    path = folder / JOURNAL
    if folder.is_symlink() or folder.is_junction() or path.is_symlink() or path.stat().st_size > 65536:
        raise root.SetupError('image_not_verified')
    value = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or value.get('schema') != 1 or value.get('target') != TARGET_OS
            or value.get('stage') not in STAGES or value.get('platform') not in ('win32', 'darwin')):
        raise root.SetupError('image_not_verified')
    return value


def prepare_upgrade(variant, progress, proxy=None, cache_dir=None, offline=False):
    if sys.platform not in ('win32', 'darwin'):
        raise root.SetupError('root_platform_mismatch')
    private_root().mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(private_root()).free < 24 * 1024 ** 3:
        raise root.SetupError('upgrade_insufficient_disk')
    # One prepared kit binds stock and Root to the same model, source and keys.
    # The Root builder's source hash check also verifies the extracted stock EXE.
    folder = Path(root.prepare_root_kit(variant, progress, proxy, cache_dir, offline))
    state, _ = root.prepared_images(folder)
    if state.get('variant') != variant:
        raise root.SetupError('image_not_verified')
    stock = root.stock_firmware(variant)
    original = folder / 'stock' / stock['extracted_file']
    if original.is_symlink() or sha(original) != stock['extracted_sha256']:
        raise root.SetupError('image_not_verified')
    images = []
    if sys.platform == 'win32':
        images.append({'phase': 'stock', 'file': original.relative_to(folder).as_posix(),
                       'bytes': original.stat().st_size, 'sha256': stock['extracted_sha256']})
    elif sys.platform == 'darwin':
        from macos_root import verified_tools, native_environment
        tools = verified_tools(folder / 'autoroot')
        output = folder / 'stock-upgrade'
        output.mkdir()
        progress(tr('提取原版签名系统与无线固件，尚不刷写手机…'))
        with (folder / 'stock-split.log').open('xb') as log:
            result = subprocess.run([str(tools['bb10mt']), 'split', '-i', str(original), '-o', str(output)],
                                    cwd=tools['bb10mt'].parent, env=native_environment(tools),
                                    stdout=log, stderr=subprocess.STDOUT, timeout=600)
        log_text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '',
                          (folder / 'stock-split.log').read_text(encoding='utf-8', errors='replace'))
        if result.returncode or re.search(r'(?im)^\s*(?:error|failed|exception)\b', log_text):
            raise root.SetupError('image_not_verified')
        expected = stock_images(stock)
        if {p.name for p in output.iterdir()} != {original.stem + '.0.signed', original.stem + '.1.signed'}:
            raise root.SetupError('image_not_verified')
        for number, phase in ((0, 'stock_os'), (1, 'stock_radio')):
            path = output / (original.stem + '.' + str(number) + '.signed')
            if path.is_symlink() or not path.is_file() or path.stat().st_size < 1024:
                raise root.SetupError('image_not_verified')
            digest = sha(path)
            if digest != expected[phase]['sha256'] or path.stat().st_size != expected[phase]['bytes']:
                raise root.SetupError('image_not_verified')
            images.append({'phase': phase, 'file': path.relative_to(folder).as_posix(),
                           'bytes': path.stat().st_size, 'sha256': digest})
    else:
        raise root.SetupError('root_platform_mismatch')
    receipt = {'schema': 1, 'stage': 'prepared', 'variant': variant, 'platform': sys.platform,
               'target': TARGET_OS, 'firmware_id': stock['id'], 'stock_sha256': stock['extracted_sha256'],
               'images': images, 'phone_contacted': False}
    write_state(folder, receipt)
    verify_kit(folder)
    return str(folder)


def verify_kit(folder, allowed=('prepared',)):
    folder = kit_path(folder)
    state = read_state(folder)
    if state['stage'] not in allowed:
        raise root.SetupError('flash_state_unknown')
    if state['platform'] != sys.platform:
        raise root.SetupError('root_platform_mismatch')
    stock = root.stock_firmware(state.get('variant'))
    if state.get('firmware_id') != stock['id'] or state.get('stock_sha256') != stock['extracted_sha256']:
        raise root.SetupError('image_not_verified')
    original = folder / 'stock' / stock['extracted_file']
    if (original.is_symlink() or original.parent.is_symlink() or original.parent.is_junction()
            or not original.is_file() or sha(original) != stock['extracted_sha256']):
        raise root.SetupError('image_not_verified')
    expected = (('stock', 'stock/' + stock['extracted_file']),) if state['platform'] == 'win32' else (
        ('stock_os', 'stock-upgrade/' + original.stem + '.0.signed'),
        ('stock_radio', 'stock-upgrade/' + original.stem + '.1.signed'))
    items = state.get('images')
    if not isinstance(items, list) or len(items) != len(expected):
        raise root.SetupError('image_not_verified')
    signed = stock_images(stock) if state['platform'] == 'darwin' else {}
    images = []
    for item, (phase, name) in zip(items, expected):
        if not isinstance(item, dict) or item.get('file') != name or item.get('phase') != phase:
            raise root.SetupError('image_not_verified')
        if signed and (item.get('sha256') != signed[phase]['sha256'] or item.get('bytes') != signed[phase]['bytes']):
            raise root.SetupError('image_not_verified')
        path = folder / name
        if (path.is_symlink() or path.parent.is_symlink() or path.parent.is_junction()
                or not path.is_file() or path.stat().st_size != item.get('bytes') or sha(path) != item.get('sha256')):
            raise root.SetupError('image_not_verified')
        images.append((phase, path))
    return state, images


def connected_target(variant, usb):
    if usb.get('usb_count') != 1 or (usb.get('device') or {}).get('ModelName') != variant:
        raise root.SetupError('device_model_not_verified')
    if sys.platform == 'darwin' and usb.get('usb_address_ready') is not True:
        raise root.SetupError('usb_source_address_required')
    return assess_version(usb['device'].get('PlatformVersion'))


def upgrade(folder, confirmed, current_version, progress):
    if confirmed is not True or sys.platform not in ('win32', 'darwin'):
        raise root.SetupError('flash_confirmation_required')
    folder = kit_path(folder)
    state, images = verify_kit(folder)
    observed = connected_target(state['variant'], root.local_usb_state())
    if observed.state != 'upgrade':
        raise root.SetupError({'ready': 'firmware_already_current', 'newer': 'firmware_downgrade_blocked',
                               'unknown': 'firmware_version_unknown'}[observed.state])
    if observed.current != current_version:
        raise root.SetupError('firmware_device_changed')
    lock = root.root_lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    try:
        with lock.open('x', encoding='utf-8') as stream:
            json.dump({'pid': os.getpid(), 'kit': str(folder), 'operation': 'stock-upgrade', 'token': token}, stream)
    except FileExistsError:
        raise root.SetupError('flash_state_unknown') from None
    state.update(confirmation_token=token, previous_os=observed.current, phone_contacted=True)
    try:
        for phase, _ in images:
            state['stage'] = phase + '_started'
            write_state(folder, state)
            progress(tr('正在升级原版系统。请保持 USB 连接，仅在工具窗口中输入手机密码。'))
            from firmware_flash import launch_stage
            result = launch_stage(folder, phase, token)
            if not isinstance(result, dict) or result.get('completed') is not True or result.get('stage') != phase:
                raise root.SetupError('flash_state_unknown')
    except BaseException:
        state['stage'] = 'uncertain'
        write_state(folder, state)
        # Keep the shared lock: no Root or stock retry after an uncertain write.
        raise
    state['stage'] = 'awaiting_reboot'
    state.pop('confirmation_token', None)
    write_state(folder, state)
    if json.loads(lock.read_text(encoding='utf-8')).get('token') != token:
        raise root.SetupError('flash_state_unknown')
    lock.unlink()
    return str(folder)


def verify_boot(folder):
    folder = kit_path(folder)
    state, _ = verify_kit(folder, allowed=('awaiting_reboot', 'os_verified'))
    if root.root_lock_path().exists():
        raise root.SetupError('flash_state_unknown')
    usb = root.local_usb_state()
    observed = connected_target(state['variant'], usb)
    if observed.state != 'ready':
        raise root.SetupError('firmware_boot_not_verified')
    state['stage'] = 'os_verified'
    state['verified_os'] = observed.current
    write_state(folder, state)
    return dict(state, usb=usb)


def pending_upgrades():
    result = []
    for folder in sorted(private_root().glob('root-kit-*'))[:200]:
        try:
            state = read_state(folder)
            result.append({'folder': str(folder), 'variant': state['variant'], 'stage': state['stage'],
                           'platform': state['platform']})
        except (OSError, ValueError, KeyError, root.SetupError):
            continue
    return result
