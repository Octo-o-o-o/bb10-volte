"""Fill the Q20 display cache from its authenticated IMS associated identity.

Never changes SIM records, caller-ID presentation, SIP identity or radio settings.
Actual telephone numbers remain in root-only on-device state.
"""
import hashlib
import json
import os
import re
import sys
import time
import q20_volte_phone as q

JOURNAL = q.BASE + '/state/own-number-display.json'
PATHS = ('/pps/services/phone/private/lines/cellular', '/pps/services/phone/public/lines/cellular')


def phone_numbers(value):
    candidates = re.findall(r'(?:tel:|sip:)(\+?(?:86)?1[3-9][0-9]{9})(?=[@;>,\s]|$)', value)
    result = set()
    for number in candidates:
        digits = number.lstrip('+')
        if len(digits) == 11:
            digits = '86' + digits
        if len(digits) == 13 and digits.startswith('861'):
            result.add('+' + digits)
    return result


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
            current = {'inbound': 'IN' in body, 'associated': ''}
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
    if current is not None:
        packets.append(current)
    values = set()
    for item in packets:
        if item.get('inbound') and item.get('code') == 200 and item.get('method') == 'REGISTER':
            values.update(phone_numbers(item['associated']))
    return values


def candidate(status):
    pid = status['native_pid']
    active = q.s.load(q.s.STATE + '/acceptance-active.json')
    assert active['boot'] == status['boot'] and active['native_pid'] == pid
    folder = active['phone_folder']
    assert folder.startswith(q.s.STATE + '/acceptance-') and '..' not in folder
    paths = [folder + '/owned-ims.log']
    numbers = set()
    for path in paths:
        numbers.update(registered_numbers(q.n.read(path).decode('utf-8', 'replace'), pid))
    if not numbers:
        data = q.n.command(['/bin/slog2info', '-b', 'ims_rrm'], 12).decode('utf-8', 'replace')
        numbers.update(registered_numbers(data, pid))
    identity = q.n.value(q.n.attrs(q.n.read('/pps/services/ims/cellular/status_private')), 'impu', '')
    own = phone_numbers(identity) if isinstance(identity, str) else set()
    if len(numbers) > 1 and len(numbers.intersection(own)) == 1:
        numbers.intersection_update(own)
    assert len(numbers) == 1, 'A unique current IMS-associated telephone number is required'
    return next(iter(numbers))


def main():
    q.setup()
    q.verify()
    action = sys.argv[1]
    assert action in ('inspect', 'apply', 'rollback')
    status = q.status()
    assert status['registered'] and q.s.phone_idle()
    number = candidate(status)
    before = {path: q.n.attrs(q.n.read(path)).get('address') for path in PATHS}
    result = {'action': action, 'unique_number_from_authenticated_register_200': True,
              'display_fields_present': {path: value is not None for path, value in before.items()},
              'actual_number_exported': False, 'sim_writes': 0, 'radio_setting_writes': 0}
    fingerprint = hashlib.sha256(q.s.current_usim().encode('ascii')).hexdigest()
    if action == 'apply':
        assert all(value in (None, ':', ':' + number) for value in before.values()), 'Preserve a different existing display address'
        assert not os.path.exists(JOURNAL), 'Inspect the previous display-cache attempt first'
        journal = {'owner': 'q20-own-number-display-v1', 'boot': status['boot'],
                   'sim_fingerprint': fingerprint, 'before': before, 'number': number,
                   'phase': 'write_pending', 'source': 'current_native_REGISTER_200_P-Associated-URI'}
        q.n.atomic(JOURNAL, json.dumps(journal).encode('ascii'))
        for path in PATHS:
            q.n.update_pps(path, {'address': ':' + number})
        time.sleep(2)
        assert all(q.n.attrs(q.n.read(path)).get('address') == ':' + number for path in PATHS)
        journal['phase'] = 'applied'
        q.n.atomic(JOURNAL, json.dumps(journal).encode('ascii'))
        result.update(cache_fields_written=2, readback_verified=True, current_ims=q.status()['current'])
    elif action == 'rollback':
        journal = q.s.load(JOURNAL)
        assert journal['owner'] == 'q20-own-number-display-v1'
        assert journal['boot'] == status['boot'] and journal['sim_fingerprint'] == fingerprint
        for path, value in journal['before'].items():
            assert path in PATHS and q.n.attrs(q.n.read(path)).get('address') in (':' + journal['number'], value)
            q.n.update_pps(path, {'address': value})
        journal['phase'] = 'restored'
        q.n.atomic(JOURNAL, json.dumps(journal).encode('ascii'))
        result['cache_restored'] = True
    print(json.dumps(result))


if __name__ == '__main__':
    main()
