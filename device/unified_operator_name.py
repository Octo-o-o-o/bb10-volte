"""The accepted Q10/Passport 460-11 name fallback, scoped to the current SIM.

QNX pathmgr supplies a volatile overlay; original system bytes stay unchanged.
The cosmetic helper never changes network registration or radio policy.
"""
import ctypes as C
import json
import os
import native as n
import profiles
import carrier_policy as policy

STOCK = '/base/etc/network/BBSE-se13-network-override-list.txt'
STOCK_HASH = 'bddd9ab02035490838c39c2ca33668d920753083153ffcd209a640d28febf810'
BASE = policy.BASE
TABLE = BASE + '/runtime/operator-name/table.txt'
ORIGINAL = BASE + '/state/operator-name-original.txt'
STATE = BASE + '/state/operator-name.json'
PUBLIC = '/pps/services/cellular/uicc/card0/status_public'
CELL = '/pps/services/cellular/radioctrl/status_cell_public'
NAME = '\u4e2d\u56fd\u7535\u4fe1'


def payload(original):
    assert n.digest(original) == STOCK_HASH
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
    lib.pathmgr_symlink.argtypes, lib.pathmgr_symlink.restype = [C.c_char_p, C.c_char_p], C.c_int
    lib.pathmgr_unlink.argtypes, lib.pathmgr_unlink.restype = [C.c_char_p], C.c_int
    return lib


def eligible(selected):
    from unified_service import card
    import device_info
    actual = policy.select(device_info.read_identity(), card())
    if selected['operator'] != 'telecom' or actual['sim_sha256'] != selected['sim_sha256']:
        return False
    cell = n.attrs(n.read(CELL))
    home, service = n.value(cell, 'serving_network', {}), n.value(cell, 'network_service')
    return (home.get('mcc') == '460' and home.get('mnc') == '11' and type(service) is int and
            service & 0x200000 != 0 and service & 1 == 0 and
            n.value(cell, 'network_technology') == 'lte' and
            n.value(cell, 'roaming', {}).get('state') == 'NOT_ROAMING')


def synchronize(selected, boot):
    if not eligible(selected):
        return
    current_target = target()
    assert current_target in (None, TABLE), 'unowned_operator_name_overlay'
    original = n.read(ORIGINAL) if current_target == TABLE else n.read(STOCK)
    overlay = payload(original)
    if not os.path.isfile(ORIGINAL):
        n.atomic(ORIGINAL, original)
    assert n.read(ORIGINAL) == original
    directory = os.path.dirname(TABLE)
    if not os.path.isdir(directory):
        os.mkdir(directory, 0o755)
    assert not os.path.islink(directory)
    if not os.path.exists(TABLE):
        n.atomic(TABLE, overlay, 0o644)
    assert not os.path.islink(TABLE) and n.read(TABLE) == overlay
    if current_target is None:
        assert manager().pathmgr_symlink(TABLE.encode('ascii'), STOCK.encode('ascii')) == 0
    assert target() == TABLE and n.read(STOCK) == overlay
    current = n.value(n.attrs(n.read(PUBLIC)), 'current_ons', {})
    if current.get('name_long') == '460-11' and current.get('name_short') in ('', '460-11'):
        record = {'owner': policy.OWNER, 'boot': boot, 'sim_sha256': selected['sim_sha256'],
                  'original_ons': dict(current)}
        n.atomic(STATE, profiles.canonical(record))
        current.update(name_long=NAME, name_short=NAME)
        n.update_pps(PUBLIC, {'current_ons': 'json:' + json.dumps(current, ensure_ascii=False)})


def restore(selected, boot):
    if target() == TABLE:
        assert n.read(STOCK) == payload(n.read(ORIGINAL))
        assert manager().pathmgr_unlink(STOCK.encode('ascii')) == 0
        assert n.digest(n.read(STOCK)) == STOCK_HASH
    elif target() is not None:
        raise ValueError('unowned_operator_name_overlay')
    if not os.path.isfile(STATE):
        return
    record = profiles.read_json(STATE)
    assert record['owner'] == policy.OWNER
    # Never restore the previous SIM's displayed ONS onto a newly inserted SIM.
    if (record['boot'] == boot and record['sim_sha256'] == selected['sim_sha256'] and eligible(selected)):
        current = n.value(n.attrs(n.read(PUBLIC)), 'current_ons', {})
        if current.get('name_long') == NAME and current.get('name_short') == NAME:
            n.update_pps(PUBLIC, {'current_ons': 'json:' + json.dumps(record['original_ons'], ensure_ascii=False)})
    os.unlink(STATE)
