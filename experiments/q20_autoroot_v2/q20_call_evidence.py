"""Parse only native SIP packet dumps; never export addresses or identities."""
import datetime
import hashlib
import json
from pathlib import Path
import re
import sys


def packets(text, pid):
    expression = re.compile(r'\b(\d\d:\d\d:\d\d[.]\d+)\s+ims_rrm[.]' + str(pid) +
                            r'\s+sip\s+\d+\s+(.*)$')
    result = []
    current = None
    for line in text.splitlines():
        match = expression.search(line)
        if not match:
            continue
        at, body = match.groups()
        marker = re.match(r'(?:>{3,}\s+OUT|<{3,}\s+IN)', body)
        if marker:
            if current is not None:
                result.append(current)
            current = {'at': at, 'direction': 'out' if 'OUT' in body else 'in'}
            continue
        if current is None:
            continue
        if re.match(r'SIP/2[.]0\s+\d{3}\b', body):
            current['code'] = int(body.split()[1])
        elif re.match(r'(?:INVITE|ACK|BYE|CANCEL|REGISTER|UPDATE|PRACK|OPTIONS|NOTIFY)\s+', body):
            current['request'] = body.split()[0]
        elif body.startswith('Call-ID:'):
            current['dialog'] = hashlib.sha256(body.split(':', 1)[1].strip().encode()).hexdigest()[:20]
        elif body.startswith('CSeq:'):
            seq = re.match(r'CSeq:\s*(\d+)\s+(\w+)', body)
            if seq:
                current.update(cseq=int(seq.group(1)), method=seq.group(2))
    if current is not None:
        result.append(current)
    return [item for item in result if 'method' in item and ('code' in item or 'request' in item)]


def dialogs(items):
    groups = {}
    for index, item in enumerate(items):
        if item.get('dialog'):
            groups.setdefault(item['dialog'], []).append(dict(item, index=index))
    result = []
    for key, group in groups.items():
        invites = [item for item in group if item.get('request') == 'INVITE']
        if not invites:
            continue
        invite = invites[0]
        answers = [item for item in group if item['index'] > invite['index'] and item.get('code') == 200
                   and item['method'] == 'INVITE' and item['cseq'] == invite['cseq']
                   and item['direction'] != invite['direction']]
        if not answers:
            continue
        answer = answers[0]
        acks = [item for item in group if item['index'] > answer['index'] and item.get('request') == 'ACK'
                and item['cseq'] == invite['cseq'] and item['direction'] == invite['direction']]
        if not acks:
            continue
        ack = acks[0]
        byes = [item for item in group if item['index'] > ack['index'] and item.get('request') == 'BYE']
        if not byes:
            continue
        bye = byes[0]
        bye_ok = [item for item in group if item['index'] > bye['index'] and item.get('code') == 200
                  and item['method'] == 'BYE' and item['cseq'] == bye['cseq']
                  and item['direction'] != bye['direction']]
        if not bye_ok:
            continue
        start = datetime.datetime.strptime(answer['at'], '%H:%M:%S.%f')
        end = datetime.datetime.strptime(bye['at'], '%H:%M:%S.%f')
        duration = (end - start).total_seconds() % 86400
        result.append({'direction': 'outgoing' if invite['direction'] == 'out' else 'incoming',
                       'invite_at': invite['at'], 'invite_cseq': invite['cseq'],
                       'answer_200_at': answer['at'], 'ack_at': ack['at'],
                       'bye_at': bye['at'], 'bye_200_at': bye_ok[0]['at'],
                       'established_seconds_to_bye': round(duration, 3),
                       'invite_200_ack_bye_verified': True})
    return result


def summarize(folder):
    folder = Path(folder)
    meta = json.loads((folder / 'meta.json').read_text())
    samples = json.loads((folder / 'samples.json').read_text())
    path = folder / 'owned-ims.log'
    data = path.read_bytes()
    messages = packets(data.decode('utf-8', 'replace'), meta['native_pid'])
    calls = dialogs(messages)
    attempts = []
    seen = set()
    for initial in messages:
        key = initial.get('dialog')
        if initial.get('request') != 'INVITE' or not key or key in seen:
            continue
        seen.add(key)
        related = [item for item in messages if item.get('dialog') == key]
        replies = [item['code'] for item in related if item.get('method') == 'INVITE'
                   and item.get('cseq') == initial['cseq'] and item.get('code', 0) >= 200]
        attempts.append({'direction': 'outgoing' if initial['direction'] == 'out' else 'incoming',
            'invite_at': initial['at'], 'invite_cseq': initial['cseq'],
            'final_responses': sorted(set(replies)), 'answered_200_observed': 200 in replies,
            'cancel_observed': any(item.get('request') == 'CANCEL' for item in related),
            'termination_reason': 'not_established' if 200 not in replies else None})
    return {'schema': 1, 'label': meta['label'], 'boot': meta['boot'],
            'profile_id': meta.get('profile_id'), 'profile_sha256': meta.get('profile_sha256'),
            'carrier': meta.get('carrier'),
            'native_pid': meta['native_pid'], 'samples': len(samples),
            'all_samples_lte': bool(samples) and all(item['live']['radio'] == ['lte'] for item in samples),
            'raw_log_sha256': hashlib.sha256(data).hexdigest(), 'packet_count': len(messages),
            'calls': calls, 'attempts': attempts,
            'both_directions_verified': {item['direction'] for item in calls} == {'incoming', 'outgoing'}}


if __name__ == '__main__':
    print(json.dumps(summarize(sys.argv[1]), indent=2))
