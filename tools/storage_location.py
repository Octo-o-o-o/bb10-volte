"""Optional large-file directory. Personal keys and the saved choice stay put.

A missing, linked or unreadable choice falls back to the original directory.
Nothing here moves existing files or stops an operation that already started.
"""
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

from desktop_paths import frozen, private_root, resource_root
from i18n import tr

SETTING = 'storage-location.json'
MAX_KNOWN = 8
KIT_NAME = re.compile(r'^root-kit(?:-[0-9a-f]{12})?$')
DRIVER_NAME = re.compile(r'^windows-usb(?:-[0-9a-f]{12})?$')
TREE_NAMES = ('stock', 'images', 'stock-upgrade')
PURPOSE = {
    'download': tr('已下载的材料。删除后，下次需要时会重新下载。'),
    'partial': tr('未完成的下载。删除后需要重新下载。'),
    'receipt': tr('下载失败留下的小记录。可以删除。'),
    'stock': tr('解包出的原厂固件。删除后，再次准备需要重新解包。'),
    'images': tr('成品刷写镜像。删除后不能再用这份镜像刷写。'),
    'stock-upgrade': tr('升级用的签名分区。删除后需要重新准备升级镜像。'),
    'driver': tr('已解包的驱动安装材料。删除不会卸载已经安装到 Windows 的驱动。'),
}


def _linked(path):
    from preparation_cache import linked
    return linked(Path(path))


def _inside(child, parent):
    try:
        Path(child).resolve().relative_to(Path(parent).resolve())
        return True
    except (OSError, ValueError):
        return False


def default_download_location(stable=None):
    stable = Path(stable) if stable is not None else private_root()
    if frozen():
        return stable / 'downloads'
    return resource_root() / 'downloads'


def read_setting(stable=None):
    stable = Path(stable) if stable is not None else private_root()
    path = stable / SETTING
    empty = {'schema': 1, 'work_root': None, 'known_roots': []}
    try:
        if _linked(stable) or _linked(path) or not path.is_file() or path.stat().st_size > 65536:
            return empty
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return empty
    if not isinstance(data, dict) or data.get('schema') != 1:
        return empty
    work = data.get('work_root')
    known = data.get('known_roots')
    if not isinstance(known, list):
        known = []
    return {
        'schema': 1,
        'work_root': work if isinstance(work, str) and work else None,
        'known_roots': [item for item in known if isinstance(item, str) and item][:MAX_KNOWN],
    }


def write_setting(stable, work_root, known_roots):
    stable = Path(stable)
    if _linked(stable):
        raise ValueError('link')
    stable.mkdir(parents=True, exist_ok=True)
    target = stable / SETTING
    if _linked(target):
        raise ValueError('link')
    temporary = stable / (SETTING + '.' + uuid.uuid4().hex + '.partial')
    payload = {'schema': 1, 'work_root': work_root, 'known_roots': list(known_roots)[:MAX_KNOWN]}
    temporary.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    temporary.replace(target)


def usable_work_directory(path, stable):
    """Return (ok, problem code). Never raises for a bad user choice."""
    stable = Path(stable)
    path = Path(path)
    try:
        if not path.is_absolute():
            return False, 'not_absolute'
        if _linked(path):
            return False, 'link'
        if not path.is_dir():
            return False, 'missing'
        resolved = path.resolve()
        try:
            stable_resolved = stable.resolve()
        except OSError:
            stable_resolved = stable.absolute()
        if resolved == stable_resolved:
            return False, 'default'
        if _inside(resolved, stable_resolved):
            return False, 'inside_private'
        bundle = resource_root().resolve()
        if resolved == bundle or _inside(resolved, bundle):
            return False, 'bundle'
        download = default_download_location(stable)
        try:
            download_resolved = download.resolve()
            if resolved == download_resolved or _inside(resolved, download_resolved):
                return False, 'downloads'
        except OSError:
            pass
        if frozen():
            try:
                program = Path(sys.executable).resolve().parent
            except OSError:
                program = None
            if program is not None and (resolved == program or _inside(resolved, program)):
                return False, 'bundle'
        for part in resolved.parts:
            if KIT_NAME.fullmatch(part) or DRIVER_NAME.fullmatch(part):
                return False, 'nested'
    except OSError:
        return False, 'unavailable'
    return True, ''


def _remember(known, path):
    if not path:
        return list(known)[:MAX_KNOWN]
    text = str(Path(path))
    result = [text]
    for item in known:
        if str(Path(item)) != text:
            result.append(item)
    return result[:MAX_KNOWN]


def _writable(path):
    probe = Path(path) / ('.bb10-write-probe-' + uuid.uuid4().hex)
    try:
        probe.write_text('ok', encoding='ascii')
        probe.unlink()
        return True
    except OSError:
        try:
            if probe.exists():
                probe.unlink()
        except OSError:
            pass
        return False


def set_work_root(stable, new_path):
    """Save a future download/preparation directory. Existing files stay where they are."""
    stable = Path(stable) if stable is not None else private_root()
    setting = read_setting(stable)
    previous = setting['work_root']
    known = list(setting['known_roots'])
    if new_path in (None, ''):
        if previous:
            known = _remember(known, previous)
        write_setting(stable, None, known)
        return 'default'
    ok, problem = usable_work_directory(new_path, stable)
    if not ok:
        if problem == 'default':
            if previous:
                known = _remember(known, previous)
            write_setting(stable, None, known)
        return problem
    if not _writable(new_path):
        return 'unwritable'
    chosen = str(Path(new_path))
    if previous and str(Path(previous)) != chosen:
        known = _remember(known, previous)
    known = [item for item in known if str(Path(item)) != chosen]
    write_setting(stable, chosen, known[:MAX_KNOWN])
    return 'saved'


def _resolve(stable=None, setting=None):
    """One setting read: where new files go, and why a saved choice is not fully used.

    Writability is checked again here. A folder that was writable when chosen can
    fill up or lose permission later; new work then stays on the original path.
    """
    stable = Path(stable) if stable is not None else private_root()
    if setting is None:
        setting = read_setting(stable)
    download = default_download_location(stable)
    work = setting.get('work_root')
    # The published Mac app stays on r43. Source checkouts on macOS keep the
    # original directories so a chosen folder cannot split downloads from kits.
    if sys.platform == 'darwin':
        return stable, download, 'macos_frozen' if work else None
    if not work:
        return stable, download, None
    ok, problem = usable_work_directory(work, stable)
    if not ok:
        return stable, download, problem
    if not _writable(work):
        return stable, download, 'unwritable'
    parent = Path(work)
    candidate = parent / 'downloads'
    try:
        if _linked(candidate) or (candidate.exists() and not candidate.is_dir()):
            return parent, download, 'download_link'
    except OSError:
        return stable, download, 'unavailable'
    return parent, candidate, None


def current_placement(stable=None):
    """Preparation directory and download directory for work that starts now."""
    parent, download, _problem = _resolve(stable)
    return parent, download


def preparation_parent(stable=None):
    return current_placement(stable)[0]


def active_download_root(stable=None):
    return current_placement(stable)[1]


def search_roots(stable=None):
    """Readable large-file directories, the original personal directory, then earlier choices.

    A saved folder that can no longer be written is still listed, so existing kits
    remain visible. New files use preparation_parent, which falls back.
    """
    stable = Path(stable) if stable is not None else private_root()
    setting = read_setting(stable)
    ordered, seen = [], set()

    def add(path, must_be_usable):
        path = Path(path)
        try:
            if _linked(path):
                return
            if must_be_usable:
                ok, _ = usable_work_directory(path, stable)
                if not ok or not path.is_dir():
                    return
            key = str(path.resolve()) if path.exists() else str(path)
        except OSError:
            return
        if key in seen:
            return
        seen.add(key)
        ordered.append(path)

    work = setting['work_root']
    if sys.platform != 'darwin' and work:
        ok, _problem = usable_work_directory(work, stable)
        if ok:
            add(work, True)
    add(stable, False)
    for item in setting['known_roots']:
        add(item, True)
    return ordered


def location_status(stable=None):
    stable = Path(stable) if stable is not None else private_root()
    setting = read_setting(stable)
    parent, download, problem = _resolve(stable, setting)
    return {'effective': str(parent), 'download': str(download), 'problem': problem,
            'configured': setting['work_root']}


def owner_of(folder, stable=None):
    folder = Path(folder)
    if _linked(folder):
        raise ValueError('Unsafe preparation directory')
    parent = folder.resolve().parent
    for root in search_roots(stable):
        try:
            if not _linked(root) and parent == Path(root).resolve():
                return parent
        except OSError:
            continue
    raise ValueError('Unsafe preparation directory')


def free_bytes(path):
    path = Path(path)
    probe = path if path.exists() else path.parent
    try:
        if _linked(probe):
            return None
        return shutil.disk_usage(probe).free
    except OSError:
        return None


def format_bytes(size):
    if size is None:
        return ''
    if size < 1024:
        return str(size) + ' B'
    if size < 1024 * 1024:
        return f'{size / 1024:.1f} KB'
    if size < 1024 ** 3:
        return f'{size / 1024 ** 2:.1f} MB'
    return f'{size / 1024 ** 3:.2f} GB'


def _stage_busy(stage):
    return isinstance(stage, str) and (stage == 'uncertain' or stage.endswith('_uncertain') or stage.endswith('_started'))


def _read_small_json(path):
    try:
        if _linked(path) or not path.is_file() or path.stat().st_size > 65536:
            return None
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _kit_blocked(folder, locked):
    try:
        if folder.resolve() in locked:
            return tr('正在刷写或结果尚未确认，完成前不能删除。')
    except OSError:
        return tr('目录暂时不可用，这次不能删除。')
    for name in ('setup-state.json', 'firmware-upgrade.json'):
        state = _read_small_json(folder / name)
        if state and _stage_busy(state.get('stage')):
            return tr('正在刷写或结果尚未确认，完成前不能删除。')
    marker = _read_small_json(folder / 'local-preparation.json')
    if marker and marker.get('status') == 'building':
        from preparation_cache import active_build
        try:
            if active_build(marker):
                return tr('正在准备，完成前不能删除。')
        except (OSError, ValueError, TypeError):
            return tr('正在准备，完成前不能删除。')
    return ''


def _locked_kits():
    from root_setup import _lock_kit_dir, root_lock_path
    lock = root_lock_path()
    try:
        if _linked(lock) or not lock.is_file() or lock.stat().st_size > 65536:
            return set()
        data = json.loads(lock.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return set()
    if not isinstance(data, dict):
        return set()
    kit = _lock_kit_dir(data)
    if not kit:
        return set()
    try:
        return {kit.resolve()}
    except OSError:
        return set()


def measure_tree(path):
    """Return byte size, or None when the tree contains a link and must not be deleted."""
    path = Path(path)
    if _linked(path) or not path.is_dir():
        return None
    total = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        kept = []
        for name in dirnames:
            if _linked(Path(dirpath) / name):
                return None
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            file = Path(dirpath) / name
            if _linked(file):
                return None
            try:
                total += file.stat().st_size
            except OSError:
                continue
    return total


def _download_dirs(stable):
    found, seen = [], set()
    candidates = [default_download_location(stable)]
    for root in search_roots(stable):
        candidates.append(Path(root) / 'downloads')
    for path in candidates:
        try:
            if _linked(path) or not path.is_dir():
                continue
            key = str(path.resolve())
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        found.append(path)
    return found


def _file_purpose(name):
    if name.endswith('.partial'):
        return PURPOSE['partial']
    if name.endswith('.invalid.json'):
        return PURPOSE['receipt']
    return PURPOSE['download']


def _material_stem(name):
    patterns = (
        r'^(.+)\.[0-9a-f]{64}\.partial(?:\.invalid\.json|\.json)?$',
        r'^(.+)\.[0-9a-f]{32}\.importing$',
        r'^(.+)\.[0-9a-f]{8}\.partial$',
        r'^(.+)\.invalid\.json$',
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, name)
        if match:
            return match.group(1)
    if name.endswith('.partial'):
        return name[:-len('.partial')]
    return name


def _lock_held(path):
    """True when another operation currently holds this lock file.

    The download lock file is left on disk after success. Its presence alone
    must not make a finished download undeletable.
    """
    path = Path(path)
    try:
        if _linked(path) or not path.is_file():
            return False
        with path.open('r+b') as lock:
            if lock.seek(0, 2) == 0:
                return False
            lock.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    except OSError:
        return True
    return False


def _download_blocked(path):
    directory = Path(path).parent
    stem = _material_stem(path.name)
    try:
        present = {child.name: child for child in directory.iterdir()}
    except OSError:
        return tr('目录暂时不可用，这次不能删除。')
    names = [path.name + '.lock', path.name + '.partial.lock', stem + '.lock', stem + '.partial.lock']
    candidates = [present[name] for name in names if name in present]
    prefix = stem + '.'
    suffix = '.partial.lock'
    for name, child in present.items():
        if not (name.startswith(prefix) and name.endswith(suffix)):
            continue
        middle = name[len(prefix):-len(suffix)]
        if re.fullmatch(r'[0-9a-f]{64}', middle):
            candidates.append(child)
    for candidate in candidates:
        if _lock_held(candidate):
            return tr('正在下载，完成前不能删除。')
    return ''


def _append_tree(items, root, folder, name, purpose, blocked):
    target = Path(folder) / name if name in TREE_NAMES else Path(root) / name
    try:
        if _linked(target) or not target.is_dir():
            return
    except OSError:
        return
    items.append({
        'kind': 'tree', 'path': str(target), 'root': str(root), 'folder': str(folder),
        'name': name, 'purpose': purpose, 'bytes': None, 'enabled': not blocked,
        'reason': blocked,
    })


def collect_inventory(stable=None, scope_kit=None):
    stable = Path(stable) if stable is not None else private_root()
    locked = _locked_kits()
    items = []
    for root in search_roots(stable):
        try:
            if _linked(root) or not root.is_dir():
                continue
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            name = child.name
            if KIT_NAME.fullmatch(name):
                blocked = _kit_blocked(child, locked)
                for tree_name in TREE_NAMES:
                    _append_tree(items, root, child, tree_name, PURPOSE[tree_name], blocked)
            elif DRIVER_NAME.fullmatch(name):
                _append_tree(items, root, root, name, PURPOSE['driver'], '')
    for directory in _download_dirs(stable):
        try:
            files = list(directory.iterdir())
        except OSError:
            continue
        for file in files:
            name = file.name
            if (not name or name.startswith('.bb10-write-probe-') or name.endswith('.lock')
                    or Path(name).name != name):
                continue
            try:
                if _linked(file) or not file.is_file():
                    continue
                size = file.stat().st_size
            except OSError:
                continue
            reason = _download_blocked(file)
            items.append({
                'kind': 'file', 'path': str(file), 'root': str(directory), 'folder': str(directory),
                'name': name, 'purpose': _file_purpose(name), 'bytes': size,
                'enabled': not reason, 'reason': reason,
            })
    if scope_kit is None:
        return items
    try:
        kit = Path(scope_kit).resolve()
    except OSError:
        return []
    names = set()
    state = _read_small_json(kit / 'setup-state.json')
    variant = state.get('variant') if state else None
    if isinstance(variant, str):
        try:
            from root_setup import stock_firmware
            stock = stock_firmware(variant)
            archive = stock.get('file')
            if isinstance(archive, str):
                names.update({archive, archive + '.partial', archive + '.invalid.json'})
        except Exception:
            # An unknown model must not prevent the success screen from opening.
            names = set()
    selected = []
    for item in items:
        try:
            if item['kind'] == 'tree' and item['name'] in TREE_NAMES and Path(item['folder']).resolve() == kit:
                selected.append(item)
            elif item['kind'] == 'file' and item['name'] in names:
                selected.append(item)
        except OSError:
            continue
    return selected


def delete_items(items, stable=None):
    """Delete only paths that are still listed and still allowed. Keys are never listed."""
    stable = Path(stable) if stable is not None else private_root()
    live = {item['path']: item for item in collect_inventory(stable)}
    deleted, failed = [], []
    for requested in items:
        current = live.get(requested.get('path'))
        if not current or not current['enabled']:
            failed.append(str(requested.get('path')))
            continue
        if current['kind'] == 'tree' and current['bytes'] is None and measure_tree(current['path']) is None:
            failed.append(current['path'])
            continue
        try:
            if current['kind'] == 'file':
                _delete_download_file(current['root'], current['name'])
            elif current['name'] in TREE_NAMES:
                from preparation_cache import remove_owned_tree
                remove_owned_tree(current['root'], current['folder'], current['name'])
            elif DRIVER_NAME.fullmatch(current['name'] or ''):
                from preparation_cache import remove_owned_tree
                remove_owned_tree(Path(current['root']).parent, current['root'], current['name'])
            else:
                raise ValueError('Unsafe cleanup item')
            deleted.append(current['path'])
            live.pop(current['path'], None)
        except (OSError, ValueError, TypeError):
            failed.append(current['path'])
    return deleted, failed


def _delete_download_file(directory, name):
    directory = Path(directory)
    if _linked(directory) or not directory.is_dir():
        raise ValueError('Unsafe download file')
    if (not isinstance(name, str) or Path(name).name != name or name.endswith('.lock')
            or name.startswith('.bb10-write-probe-')):
        raise ValueError('Unsafe download file')
    target = directory / name
    if _linked(target) or target.resolve().parent != directory.resolve() or not target.is_file():
        raise ValueError('Unsafe download file')
    if _download_blocked(target):
        raise ValueError('Unsafe download file')
    target.unlink()
