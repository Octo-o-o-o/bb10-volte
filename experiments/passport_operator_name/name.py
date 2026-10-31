"""Independent Passport display fallback. Never writes radio, IMS or SIM settings."""
import ctypes as C
import hashlib
import json
import os
import signal
import sys
import time

BASE = '/var/rootdata/passport_operator_name'
CORE = '/var/rootdata/passport_volte_research'
OWNER = 'passport-operator-name-independent-v1'
ADDON = '/var/addons/passport-operator-name'
STOCK = '/base/etc/network/BBSE-se13-network-override-list.txt'
STOCK_HASH = 'bddd9ab02035490838c39c2ca33668d920753083153ffcd209a640d28febf810'
TABLE = BASE + '/table.txt'
ORIGINAL = BASE + '/state/original.txt'
STATE = BASE + '/state/display.json'
WORKER = BASE + '/state/worker.json'
PUBLIC = '/pps/services/cellular/uicc/card0/status_public'
PRIVATE = '/pps/services/cellular/uicc/card0/status_private'
CELL = '/pps/services/cellular/radioctrl/status_cell_public'
NAME = '\u4e2d\u56fd\u7535\u4fe1'
n = None


def load(path):
    assert not os.path.islink(path)
    return json.loads(n.read(path).decode('utf-8'))


def verify():
    global n
    assert os.geteuid() == 0 and os.uname()[0] == 'QNX' and C.sizeof(C.c_void_p) == 4
    with open(BASE + '/manifest.json', 'rb') as source:
        manifest = json.loads(source.read().decode('ascii'))
    assert manifest['owner'] == OWNER
    assert set(manifest['files']) == {'name.py', 'native.py', 'device_info.py', 'start.sh'}
    for name, digest in manifest['files'].items():
        assert not os.path.islink(BASE + '/' + name)
        with open(BASE + '/' + name, 'rb') as source:
            assert hashlib.sha256(source.read()).hexdigest() == digest
    assert manifest['files']['native.py'] == 'a8055a901e26781c66f77c940b37faecd0843ee10ee2bef9da3715dbebdb0dd4'
    assert manifest['files']['device_info.py'] == 'acd6f8c04bca0f2d24a8a8dbf7417a8bf5a70852208761bbc6a76ad07a07a847'
    sys.path.insert(0, BASE)
    import native
    n = native
    import device_info
    facts = device_info.read_identity()
    assert facts['variant'] == 'SQW100-4' and facts['board_type'] == 'WINDERMERE4ROW'
    assert facts['os_version'] == '10.3.3.3216'
    assert os.path.isfile('/tmp/root.done')
    return facts


def boot():
    info = os.stat('/tmp/root.done')
    return [info.st_ino, info.st_mtime]


def at(path):
    return n.attrs(n.read(path)) if os.path.isfile(path) else {}


def home():
    card = at(PRIVATE)
    return n.value(card, 'uicc_state', {}).get('state'), n.value(card, 'hplmn', {})


def eligible():
    ready, network = home()
    if ready != 'READY' or network.get('mcc') != '460' or network.get('mnc') != '11':
        return False
    cell = at(CELL)
    serving = n.value(cell, 'serving_network', {})
    service = n.value(cell, 'network_service')
    return (serving.get('mcc') == '460' and serving.get('mnc') == '11' and
            n.value(cell, 'network_technology') == 'lte' and type(service) is int and
            service & 0x200000 != 0 and service & 1 == 0 and
            n.value(cell, 'roaming', {}).get('state') == 'NOT_ROAMING')


def payload(original):
    assert n.digest(original) == STOCK_HASH, 'Unknown original name table'
    rows = original.decode('utf-8').splitlines()
    assert rows[0] == 'PPCI&N|Abrev. Net. Name|MCC|MNC'
    assert not any(row.split('|')[2:] == ['460', '11'] for row in rows[1:])
    return original + (b'' if original.endswith(b'\n') else b'\n') + (NAME + '|' + NAME + '|460|11\n').encode('utf-8')


def target():
    try:
        return os.readlink(STOCK)
    except OSError:
        return None


def manager():
    lib = C.CDLL('libc.so.3', use_errno=True)
    lib.pathmgr_symlink.argtypes = [C.c_char_p, C.c_char_p]
    lib.pathmgr_symlink.restype = C.c_int
    lib.pathmgr_unlink.argtypes = [C.c_char_p]
    lib.pathmgr_unlink.restype = C.c_int
    return lib


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def observe():
    ons = n.value(at(PUBLIC), 'current_ons', {})
    cell = at(CELL)
    private = at('/pps/services/ims/cellular/status_private')
    values = n.value(at('/pps/system/navigator/status/cellular'), 'dat', {})
    worker = load(WORKER) if os.path.isfile(WORKER) else {}
    status = load(CORE + '/state/status.json') if os.path.isfile(CORE + '/state/status.json') else {}
    return {'boot': boot(), 'eligible': eligible(), 'home': home()[1],
            'display': {key: ons.get(key) for key in ('name_long', 'name_short')},
            'rum': n.value(at('/pps/services/rum/csm/status_public'), 'network_name'),
            'navigator': values.get('cellular', {}).get('operator_name_string'),
            'network': {key: n.value(cell, key) for key in ('serving_network', 'network_technology', 'network_service', 'roaming')},
            'table': {'target': target(), 'bytes': len(n.read(STOCK)), 'sha256': n.digest(n.read(STOCK)),
                      'has_460_11': any(row.split('|')[2:] == ['460', '11'] for row in n.read(STOCK).decode('utf-8').splitlines()[1:])},
            'worker_alive': bool(worker.get('owner') == OWNER and worker.get('boot') == boot() and alive(worker['pid'])),
            'enabled': os.path.isfile(BASE + '/enabled'),
            'ims': {'status': n.value(at('/pps/services/ims/status_public'), 'status'),
                    'register_status': n.value(private, 'register_status'), 'native_pids': n.ims_pids(),
                    'saved_phase': status.get('phase')},
            'core_manifest_sha256': n.digest(n.read(CORE + '/research-manifest.json')),
            'radio_or_IMS_writes': 0}


def apply_once():
    if not eligible():
        return {'applied': False, 'reason': 'not_home_46011_normal_lte', 'radio_or_IMS_writes': 0}
    link = target()
    assert link in (None, TABLE), 'Preserve another name-table overlay'
    original = n.read(ORIGINAL) if link == TABLE else n.read(STOCK)
    overlay = payload(original)
    if not os.path.isfile(ORIGINAL):
        n.atomic(ORIGINAL, original)
    assert n.read(ORIGINAL) == original
    if not os.path.isfile(TABLE):
        n.atomic(TABLE, overlay, 0o644)
    assert not os.path.islink(TABLE) and n.read(TABLE) == overlay
    if link is None:
        assert manager().pathmgr_symlink(TABLE.encode('ascii'), STOCK.encode('ascii')) == 0
    assert target() == TABLE and n.read(STOCK) == overlay
    ons = n.value(at(PUBLIC), 'current_ons', {})
    changed = False
    if ons.get('name_long') == '460-11' and ons.get('name_short') in (None, '', '460-11'):
        record = {'owner': OWNER, 'boot': boot(), 'before': dict(ons), 'name': NAME,
                  'stock_sha256': STOCK_HASH, 'overlay_sha256': n.digest(overlay), 'radio_or_IMS_writes': 0}
        n.atomic(STATE, json.dumps(record, ensure_ascii=False).encode('utf-8'))
        ons.update(name_long=NAME, name_short=NAME)
        n.update_pps(PUBLIC, {'current_ons': 'json:' + json.dumps(ons, ensure_ascii=False)})
        changed = True
    return {'applied': True, 'ons_changed': changed, 'overlay_sha256': n.digest(overlay), 'radio_or_IMS_writes': 0}


def restore():
    if target() == TABLE:
        assert n.read(STOCK) == payload(n.read(ORIGINAL))
        assert manager().pathmgr_unlink(STOCK.encode('ascii')) == 0
        assert target() is None and n.digest(n.read(STOCK)) == STOCK_HASH
    elif target() is not None:
        raise RuntimeError('Preserve another name-table overlay')
    if os.path.isfile(STATE):
        record = load(STATE)
        assert record['owner'] == OWNER
        ons = n.value(at(PUBLIC), 'current_ons', {})
        ready, network = home()
        if (record['boot'] == boot() and network == {'mcc': '460', 'mnc': '11'} and
                ons.get('name_long') == NAME and ons.get('name_short') == NAME):
            for key in ('name_long', 'name_short'):
                if key in record['before']:
                    ons[key] = record['before'][key]
                else:
                    ons.pop(key, None)
            n.update_pps(PUBLIC, {'current_ons': 'json:' + json.dumps(ons, ensure_ascii=False)})
        os.unlink(STATE)
    return {'restored': True, 'radio_or_IMS_writes': 0}


def start():
    if os.path.isfile(WORKER):
        previous = load(WORKER)
        assert previous['owner'] == OWNER
        if previous['boot'] == boot() and alive(previous['pid']):
            args = n.command(['/bin/pidin', '-p', str(previous['pid']), '-f', 'A']).decode('ascii')
            assert BASE + '/name.py watch' in args
            return {'already_running': True, 'worker_pid': previous['pid']}
    assert os.path.isfile(BASE + '/enabled')
    pid = os.fork()
    if pid == 0:
        os.setsid()
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        descriptor = os.open('/dev/null', os.O_RDWR)
        for item in (0, 1, 2):
            os.dup2(descriptor, item)
        if descriptor > 2:
            os.close(descriptor)
        os.execv('/usr/bin/python3.2', ['/usr/bin/python3.2', BASE + '/name.py', 'watch'])
        os._exit(1)
    n.atomic(WORKER, json.dumps({'owner': OWNER, 'boot': boot(), 'pid': pid}).encode('ascii'))
    return {'started': True, 'worker_pid': pid, 'radio_or_IMS_writes': 0}


def watch():
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        while os.path.isfile(BASE + '/enabled'):
            if eligible():
                apply_once()
            elif target() == TABLE:
                restore()
            time.sleep(10)
    finally:
        restore()


def install():
    assert not os.path.lexists(ADDON), 'Preserve an existing addon'
    parent = os.path.dirname(ADDON)
    if not os.path.lexists(parent):
        os.mkdir(parent, 0o755)
    assert os.path.isdir(parent) and not os.path.islink(parent), 'Preserve an unknown addon root'
    os.mkdir(ADDON, 0o700)
    os.mkdir(ADDON + '/init', 0o700)
    n.atomic(ADDON + '/init/start.sh', n.read(BASE + '/start.sh'), 0o700)
    n.atomic(BASE + '/enabled', b'independent display fallback only\n')
    return dict(start(), addon=ADDON, boot_tested=False)


def main():
    verify()
    action = sys.argv[1]
    if action == 'observe':
        result = observe()
    elif action == 'apply':
        result = apply_once()
    elif action == 'install':
        result = install()
    elif action == 'start':
        result = start()
    elif action == 'restore':
        assert not os.path.isfile(BASE + '/enabled')
        result = restore()
    elif action == 'watch':
        watch()
        return
    else:
        raise SystemExit('Use observe, apply, install, start, restore or watch')
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
