"""Q10 Telecom display-name fallback, independent of the radio/IMS engine.

Preserve the stock SE13 table, overlay one missing PLMN through QNX pathmgr,
and notify the existing ONS consumer only while that same SIM is on 460-11.
"""
import ctypes as C
import hashlib
import json
import os
import signal
import sys
import time
import native as n
import profiles
import device_info

BASE = '/var/rootdata/q10_volte'
OWNER = 'q10-telecom-operator-name-v1'
ADDON = '/var/addons/q10-operator-name'
STOCK = '/base/etc/network/BBSE-se13-network-override-list.txt'
STOCK_HASH = 'bddd9ab02035490838c39c2ca33668d920753083153ffcd209a640d28febf810'
TABLE = BASE + '/runtime/operator-name/BBSE-se13-network-override-list.txt'
ORIGINAL = BASE + '/state/operator-name-original.txt'
STATE = BASE + '/state/operator-name.json'
WORKER = BASE + '/state/operator-name-worker.json'
PUBLIC = '/pps/services/cellular/uicc/card0/status_public'
PRIVATE = '/pps/services/cellular/uicc/card0/status_private'
CELL = '/pps/services/cellular/radioctrl/status_cell_public'
NAME = '\u4e2d\u56fd\u7535\u4fe1'


def load(path):
    assert not os.path.islink(path)
    return json.loads(n.read(path).decode('ascii'))


def boot():
    info = os.stat('/tmp/root.done')
    return [info.st_ino, info.st_mtime]


def payload(original):
    assert n.digest(original) == STOCK_HASH
    rows = original.decode('utf-8').splitlines()
    assert rows[0] == 'PPCI&N|Abrev. Net. Name|MCC|MNC'
    assert not any(len(row.split('|')) == 4 and row.split('|')[2:] == ['460', '11'] for row in rows[1:])
    return original + ('' if original.endswith(b'\n') else '\n').encode('ascii') + (NAME + '|' + NAME + '|460|11\n').encode('utf-8')


def eligible(receipt):
    facts = device_info.read_identity()
    if facts['variant'] != 'SQN100-3' or facts['os_version'] != '10.3.3.3216': return False
    if not os.path.isfile(BASE + '/enabled'): return False
    request = profiles.installed_request(BASE)
    if request['profile'].get('lte_attach') != 'telecom_data_centric_v1': return False
    if profiles.fingerprint(request) != receipt['profile_sha256']: return False
    card = n.attrs(n.read(PRIVATE))
    home = n.value(card, 'hplmn', {})
    if n.value(card, 'uicc_state', {}).get('state') != 'READY': return False
    if home.get('mcc') != '460' or home.get('mnc') != '11': return False
    identity = str(n.value(n.attrs(n.read('/pps/services/cellular/uicc/card0/status_restricted')), 'imsi'))
    if hashlib.sha256(identity.encode('ascii')).hexdigest() != receipt['sim_fingerprint']: return False
    cell = n.attrs(n.read(CELL))
    serving = n.value(cell, 'serving_network', {})
    return (serving.get('mcc') == '460' and serving.get('mnc') == '11' and
            n.value(cell, 'network_technology') == 'lte' and
            n.value(cell, 'network_service') == 2097152 and
            n.value(cell, 'roaming', {}).get('state') == 'NOT_ROAMING')


def authorized_receipt():
    import autostart_evidence
    request = profiles.installed_request(BASE)
    assert autostart_evidence.observe(BASE, request['profile'])['autostart_authorized'] is True
    return load(BASE + '/state/telecom-autostart-acceptance.json')


def observe():
    result = {'name': None, 'table_overlay_owned': False, 'worker_alive': False}
    try:
        ons = n.value(n.attrs(n.read(PUBLIC)), 'current_ons', {})
        value = ons.get('name_long')
        result['name'] = value if value in (NAME, '460-11') else 'other' if value else None
        if link_target() == TABLE:
            result['table_overlay_owned'] = n.read(STOCK) == payload(n.read(ORIGINAL))
        if os.path.isfile(WORKER):
            worker = load(WORKER)
            result['worker_alive'] = worker['owner'] == OWNER and worker['boot'] == boot() and alive(worker['pid'])
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        pass
    return result


def link_target():
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


def apply_once(receipt=None):
    receipt = authorized_receipt() if receipt is None else receipt
    if not eligible(receipt): return {'applied': False, 'reason': 'not_current_home_Telecom_LTE'}
    target = link_target()
    assert target in (None, TABLE), 'Unknown name-table link; preserve it'
    original = n.read(ORIGINAL) if target == TABLE else n.read(STOCK)
    overlay = payload(original)
    if not os.path.isfile(ORIGINAL): n.atomic(ORIGINAL, original)
    assert n.read(ORIGINAL) == original
    directory = os.path.dirname(TABLE)
    if not os.path.isdir(directory): os.mkdir(directory, 0o755)
    assert not os.path.islink(directory)
    if not os.path.exists(TABLE): n.atomic(TABLE, overlay, 0o644)
    assert not os.path.islink(TABLE) and n.read(TABLE) == overlay
    if target is None:
        assert n.digest(n.read(STOCK)) == STOCK_HASH
        lib = manager()
        assert lib.pathmgr_symlink(TABLE.encode('ascii'), STOCK.encode('ascii')) == 0, 'Name-table overlay failed: %d' % C.get_errno()
    assert link_target() == TABLE and n.read(STOCK) == overlay
    current = n.value(n.attrs(n.read(PUBLIC)), 'current_ons', {})
    changed = False
    if current.get('name_long') == '460-11' and current.get('name_short') in ('', '460-11'):
        before = dict(current)
        current.update(name_long=NAME, name_short=NAME)
        record = {'owner': OWNER, 'boot': boot(), 'stock_sha256': STOCK_HASH,
                  'overlay_sha256': n.digest(overlay), 'profile_sha256': receipt['profile_sha256'],
                  'original_ons': before, 'displayed_name': NAME, 'radio_or_IMS_writes': 0}
        n.atomic(STATE, json.dumps(record).encode('ascii'))
        n.update_pps(PUBLIC, {'current_ons': 'json:' + json.dumps(current, ensure_ascii=False)})
        changed = True
    return {'applied': True, 'name': NAME, 'ons_changed': changed, 'stock_sha256': STOCK_HASH,
            'overlay_sha256': n.digest(overlay), 'radio_or_IMS_writes': 0}


def restore():
    if link_target() == TABLE:
        original = n.read(ORIGINAL)
        assert n.read(STOCK) == payload(original)
        assert manager().pathmgr_unlink(STOCK.encode('ascii')) == 0
        assert link_target() is None and n.digest(n.read(STOCK)) == STOCK_HASH
    elif link_target() is not None:
        raise RuntimeError('Unknown name-table link; preserve it')
    if os.path.isfile(STATE):
        state = load(STATE)
        assert state['owner'] == OWNER
        current = n.value(n.attrs(n.read(PUBLIC)), 'current_ons', {})
        cell = n.value(n.attrs(n.read(CELL)), 'serving_network', {})
        if (state['boot'] == boot() and cell.get('mcc') == '460' and cell.get('mnc') == '11' and
                current.get('name_long') == NAME and current.get('name_short') == NAME):
            n.update_pps(PUBLIC, {'current_ons': 'json:' + json.dumps(state['original_ons'])})
    return {'restored': True, 'stock_sha256': n.digest(n.read(STOCK)), 'radio_or_IMS_writes': 0}


def alive(pid):
    try: os.kill(pid, 0); return True
    except OSError: return False


def stop():
    if os.path.isfile(WORKER):
        worker = load(WORKER)
        assert worker['owner'] == OWNER
        if worker['boot'] == boot() and alive(worker['pid']):
            args = n.command(['/bin/pidin', '-p', str(worker['pid']), '-f', 'A']).decode('ascii')
            assert BASE + '/device/operator_name.py watch' in args
            os.kill(worker['pid'], signal.SIGTERM)
            for unused in range(25):
                if not alive(worker['pid']): break
                time.sleep(0.2)
            assert not alive(worker['pid'])
    return restore()


def start():
    assert os.geteuid() == 0 and os.uname()[0] == 'QNX'
    facts = device_info.read_identity()
    assert facts['variant'] == 'SQN100-3' and facts['os_version'] == '10.3.3.3216'
    receipt = load(BASE + '/state/telecom-autostart-acceptance.json')
    assert receipt['owner'] == 'q10-telecom-autostart-accepted-v1'
    assert profiles.fingerprint(profiles.installed_request(BASE)) == receipt['profile_sha256']
    if os.path.isfile(WORKER):
        old = load(WORKER)
        assert old['owner'] == OWNER
        if old['boot'] == boot() and alive(old['pid']):
            args = n.command(['/bin/pidin', '-p', str(old['pid']), '-f', 'A']).decode('ascii')
            assert BASE + '/device/operator_name.py watch' in args
            return {'started': False, 'already_running': True}
    pid = os.fork()
    if pid == 0:
        os.setsid()
        null = os.open('/dev/null', os.O_RDWR)
        for fd in (0, 1, 2): os.dup2(null, fd)
        if null > 2: os.close(null)
        os.execv('/usr/bin/python3.2', ['/usr/bin/python3.2', BASE + '/device/operator_name.py', 'watch'])
        os._exit(1)
    n.atomic(WORKER, json.dumps({'owner': OWNER, 'boot': boot(), 'pid': pid}).encode('ascii'))
    return {'started': True, 'worker_pid': pid, 'radio_or_IMS_writes': 0}


def watch():
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        # Root addons may run before UICC READY. Do not assume a SIM identity or
        # apply any name while waiting for the full per-SIM acceptance check.
        deadline = time.time() + 900
        receipt = None
        while os.path.isfile(BASE + '/enabled') and time.time() < deadline:
            try:
                receipt = authorized_receipt()
                break
            except (OSError, ValueError, KeyError, TypeError, AssertionError):
                time.sleep(5)
        if receipt is None: return
        while os.path.isfile(BASE + '/enabled'):
            if eligible(receipt): apply_once(receipt)
            elif link_target() == TABLE: restore()
            time.sleep(10)
    finally:
        restore()


def setup():
    source = BASE + '/device/operator-name-start.sh'
    assert not os.path.islink(ADDON)
    if not os.path.exists(ADDON):
        for path in (ADDON, ADDON + '/data', ADDON + '/init'): os.mkdir(path, 0o755)
    assert set(os.listdir(ADDON)) == {'data', 'init'} and not os.listdir(ADDON + '/data')
    assert set(os.listdir(ADDON + '/init')) <= {'start.sh'}
    if os.path.isfile(ADDON + '/init/start.sh'):
        assert n.read(ADDON + '/init/start.sh') == n.read(source)
    n.atomic(ADDON + '/init/start.sh', n.read(source), 0o700)
    n.command(['/proc/boot/pathtrust', '!' + ADDON + '/init/start.sh'])


def uninstall():
    stop()
    if os.path.exists(ADDON):
        assert not os.path.islink(ADDON)
        assert set(os.listdir(ADDON)) == {'data', 'init'} and not os.listdir(ADDON + '/data')
        assert os.listdir(ADDON + '/init') == ['start.sh']
        assert n.read(ADDON + '/init/start.sh') == n.read(BASE + '/device/operator-name-start.sh')
        os.unlink(ADDON + '/init/start.sh')
        os.rmdir(ADDON + '/init'); os.rmdir(ADDON + '/data'); os.rmdir(ADDON)


if __name__ == '__main__':
    assert os.geteuid() == 0 and os.uname()[0] == 'QNX' and C.sizeof(C.c_void_p) == 4
    facts = device_info.read_identity()
    assert facts['variant'] == 'SQN100-3' and facts['os_version'] == '10.3.3.3216'
    action = sys.argv[1]
    if action == 'apply-once': result = apply_once()
    elif action == 'restore': result = restore()
    elif action == 'start': result = start()
    elif action == 'stop': result = stop()
    elif action == 'watch': watch(); result = {'finished': True}
    else: raise SystemExit('Use apply-once, restore, start, stop or watch')
    print(json.dumps(result))
