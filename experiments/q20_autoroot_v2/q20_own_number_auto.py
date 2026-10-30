"""Scoped, reversible own-number display cache; no SIM or radio write API."""
import hashlib
import json
import os
import re
import time

BASE = '/var/q20_volte'
JOURNAL = BASE + '/state/own-number-display.json'
PATHS = ('/pps/services/phone/private/lines/cellular', '/pps/services/phone/public/lines/cellular')


def phone_numbers(value):
    values = set()
    for number in re.findall(r'(?:tel:|sip:)(\+?(?:86)?1[3-9][0-9]{9})(?=[@;>,\s]|$)', value):
        digits = number.lstrip('+')
        if len(digits) == 11:
            digits = '86' + digits
        if len(digits) == 13 and digits.startswith('861'):
            values.add('+' + digits)
    return values


def registered_numbers(text, pid):
    expr = re.compile(r'\b\d\d:\d\d:\d\d[.]\d+\s+ims_rrm[.]' + str(pid) + r'\s+sip\s+\d+\s+(.*)$')
    packets = []
    current = None
    for line in text.splitlines():
        match = expr.search(line)
        if not match:
            continue
        body = match.group(1)
        if re.match(r'(?:>{3,}\s+OUT|<{3,}\s+IN)', body):
            if current is not None:
                packets.append(current)
            current = {'inbound': 'IN' in body, 'associated': '', 'to': ''}
            continue
        if current is None:
            continue
        found = re.match(r'SIP/2[.]0\s+(\d{3})', body)
        if found:
            current['code'] = int(found.group(1))
        found = re.match(r'CSeq:\s*\d+\s+(\w+)', body)
        if found:
            current['method'] = found.group(1)
        if body.lower().startswith('p-associated-uri:'):
            current['associated'] += body.split(':', 1)[1]
        elif body.lower().startswith('to:'):
            current['to'] += body.split(':', 1)[1]
    if current is not None:
        packets.append(current)
    result = set()
    for item in packets:
        if item.get('inbound') and item.get('code') == 200 and item.get('method') == 'REGISTER':
            result.update(phone_numbers(item['associated']))
    return result


def load(n, path):
    return json.loads(n.read(path).decode('utf-8'))


def synchronize(n, pid, boot, imsi, configured_sim_fingerprint, apply=True):
    """Only the current SIM's authenticated REGISTER200 may supply a number."""
    fingerprint = hashlib.sha256(imsi.encode('ascii')).hexdigest()
    assert configured_sim_fingerprint == fingerprint, 'SIM changed since this native IMS process was configured'
    old = load(n, JOURNAL) if os.path.isfile(JOURNAL) else None
    cached = (old and old.get('owner') == 'q20-own-number-display-v1' and old.get('boot') == boot
              and old.get('sim_fingerprint') == fingerprint and old.get('phase') == 'applied')
    if cached:
        number = old['number']
    else:
        text = n.command(['/bin/slog2info', '-b', 'ims_rrm'], 12).decode('utf-8', 'replace')
        values = registered_numbers(text, pid)
        if len(values) != 1:
            return {'display_updated': False, 'candidate_count': len(values),
                    'reason': 'unique_current_sim_REGISTER200_number_required', 'actual_number_exported': False}
        number = next(iter(values))
    before = {path: n.attrs(n.read(path)).get('address') for path in PATHS}
    stale_owned = ':' + old['number'] if old and old.get('owner') == 'q20-own-number-display-v1' else None
    if any(value not in (None, ':', ':' + number, stale_owned) for value in before.values()):
        return {'display_updated': False, 'reason': 'different_existing_address_preserved',
                'actual_number_exported': False}
    changes = [path for path, value in before.items() if value != ':' + number]
    result = {'unique_current_sim_number': True, 'actual_number_exported': False,
              'cache_fields_to_write': len(changes), 'sim_write_requests': 0, 'radio_setting_write_requests': 0}
    if not apply:
        return result
    if not changes:
        result.update(display_updated=True, readback_verified=True)
        return result
    if old and not cached:
        history = BASE + '/state/own-number-history'
        if not os.path.isdir(history):
            os.mkdir(history, 0o700)
        n.atomic(history + '/before-' + str(int(time.time())) + '.json', json.dumps(old).encode('ascii'))
    journal = old if cached else {'owner': 'q20-own-number-display-v1', 'boot': boot,
        'sim_fingerprint': fingerprint, 'before': before, 'number': number,
        'source': 'current_native_REGISTER_200_on_boot_and_SIM_pinned_PID', 'changed_paths': changes}
    journal['phase'] = 'write_pending'
    n.atomic(JOURNAL, json.dumps(journal).encode('ascii'))
    for path in changes:
        n.update_pps(path, {'address': ':' + number})
    assert all(n.attrs(n.read(path)).get('address') == ':' + number for path in PATHS)
    journal['phase'] = 'applied'
    n.atomic(JOURNAL, json.dumps(journal).encode('ascii'))
    result.update(display_updated=True, readback_verified=True)
    return result


def restore(n, boot, imsi):
    if not os.path.isfile(JOURNAL):
        return {'display_cache_owned': False}
    journal = load(n, JOURNAL)
    assert journal['owner'] == 'q20-own-number-display-v1'
    if journal.get('phase') == 'restored':
        return {'display_cache_restored': True}
    assert journal['boot'] == boot
    assert journal['sim_fingerprint'] == hashlib.sha256(imsi.encode('ascii')).hexdigest()
    for path in journal.get('changed_paths', journal['before']):
        assert path in PATHS
        original = journal['before'][path]
        assert n.attrs(n.read(path)).get('address') in (':' + journal['number'], original)
        n.update_pps(path, {'address': original})
    journal['phase'] = 'restored'
    n.atomic(JOURNAL, json.dumps(journal).encode('ascii'))
    return {'display_cache_restored': True, 'sim_write_requests': 0, 'radio_setting_write_requests': 0}
