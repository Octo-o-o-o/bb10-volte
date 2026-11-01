"""Offline SMS/SIP correlation checks. Never export identities or message bodies.

Accepts slog2info output or a native SIP file. Missing/redacted headers are
unknown evidence, not proof of an on-wire omission. No phone access or sends.
"""
import argparse
import json
import re
from pathlib import Path

SLOG = re.compile(r'\bims_rrm\.(\d+)\s+(\w+\*?)\s+\d+\s{1,2}(.*)$')
ALIASES = {'i': 'call-id', 'c': 'content-type', 'l': 'content-length',
           'f': 'from', 't': 'to', 'v': 'via'}
MAX_BYTES = 64 * 1024 * 1024


def visible(value):
    return bool(value and not re.search(r'PII|redacted|\*|\[hidden\]', value, re.I))


def header(message, name):
    values = message['headers'].get(name, [])
    return values[0] if len(values) == 1 else None


def uri(value):
    if not visible(value):
        return None
    match = re.search(r'<([^>]+)>', value)
    value = match.group(1) if match else value.strip()
    return value if value.lower().startswith(('sip:', 'sips:', 'tel:')) else None


def parse(text):
    messages, active, pending_rp = [], {}, {}
    events = {'cs_domain': 0, 'ps_domain': 0, 'no_retry_default': 0,
              'ims_disabled_after_network_failure': 0, 'ack_despite_cs_domain': 0}
    config = set()
    for number, line in enumerate(text.splitlines(), 1):
        slog = SLOG.search(line)
        pid, channel, body = slog.groups() if slog else ('file', 'sip', line)
        if 'ImsApiSms.cpp' in body:
            domain = re.search(r'\bprocess\s+\d+\s+domain\s+([12])\b', body)
            if domain:
                events['cs_domain' if domain.group(1) == '1' else 'ps_domain'] += 1
            if 'no retry default' in body:
                events['no_retry_default'] += 1
            if 'SMS is disabled due to network failure' in body:
                events['ims_disabled_after_network_failure'] += 1
            if 'RP ACK Message' in body and 'not PS' in body:
                events['ack_despite_cs_domain'] += 1
            rp = re.search(r'\brptype=\s*([0-6])\b', body)
            if rp:
                pending_rp[pid] = (int(rp.group(1)), number)
        setting = re.search(r'SmsConfig: smsOverIp\[(\d+)\]=\s*([01])\b', body)
        if setting:
            config.add(tuple(map(int, setting.groups())))
        if channel != 'sip':
            continue
        marker = re.search(r'(<<<<<< IN|>>>>>> OUT)', body)
        if marker:
            message = {'line': number, 'pid': pid, 'direction': 'in' if marker.group(1).startswith('<') else 'out',
                       'headers': {}, 'started': False, 'in_body': False,
                       'rp_type': None, 'rp_reference': None}
            active[pid] = message
            messages.append(message)
            continue
        message = active.get(pid)
        if message is None:
            continue
        body = body.strip()
        if not message['started']:
            request = re.fullmatch(r'([A-Z]+)\s+(\S+)\s+SIP/2\.0', body)
            response = re.fullmatch(r'SIP/2\.0\s+(\d{3})(?:\s+(.*))?', body)
            if not request and not response:
                continue
            message['started'] = True
            if request:
                message['method'], message['target'] = request.groups()
                prior = pending_rp.pop(pid, None)
                if (message['direction'] == 'out' and message['method'] == 'MESSAGE'
                        and prior and number - prior[1] <= 40):
                    message['rp_type'] = prior[0]
            else:
                message['status'] = int(response.group(1))
                # Export only this known protocol reason, never arbitrary text.
                message['gateway_correlation_rejected'] = bool(
                    re.search(r'cannot find in-reply-to', response.group(2) or '', re.I))
            continue
        if not body:
            message['in_body'] = True
            continue
        if not message['in_body']:
            field = re.fullmatch(r'([\w-]+)\s*:\s*(.*)', body)
            if field:
                name = field.group(1).lower()
                name = ALIASES.get(name, name)
                message['headers'].setdefault(name, []).append(field.group(2))
                continue
        # Decode only a clearly hex-encoded RPDU. Never interpret SMS text as hex.
        if message['in_body'] and re.fullmatch(r'(?:RPDU:\s*)?(?:[0-9a-fA-F]{2}\s+)+[0-9a-fA-F]{2}', body):
            octets = bytes.fromhex(re.sub(r'^RPDU:\s*', '', body))
            if len(octets) >= 2 and octets[0] <= 6 and message['rp_reference'] is None:
                message['rp_type'], message['rp_reference'] = octets[:2]
    return messages, events, config


def transaction(message):
    call = header(message, 'call-id')
    cseq = header(message, 'cseq')
    if not visible(call) or not cseq:
        return None
    match = re.fullmatch(r'(\d+)\s+MESSAGE', cseq, re.I)
    if not match:
        return None
    # Via branch distinguishes transactions even when a peer reuses Call-ID.
    vias = message['headers'].get('via', [])
    branch = re.search(r'(?:^|;)\s*branch=([^;,\s]+)', vias[0]) if vias else None
    if not branch or not visible(branch.group(1)):
        return None
    return message['pid'], call, int(match.group(1)), branch.group(1)


def analyze(text):
    messages, events, config = parse(text)
    sms = [m for m in messages if m.get('method') == 'MESSAGE' and
           (header(m, 'content-type') or '').split(';')[0].strip().lower() == 'application/vnd.3gpp.sms']
    incoming = [m for m in sms if m['direction'] == 'in']
    records = []
    for index, message in enumerate(sms, 1):
        reply = header(message, 'in-reply-to')
        reply_state = 'not_visible' if reply is None else ('visible' if visible(reply) else 'redacted')
        record = {'index': index, 'line': message['line'], 'direction': message['direction'],
                  'rp_type': message['rp_type'], 'rp_reference': message['rp_reference'],
                  'in_reply_to': reply_state, 'related_incoming_index': None,
                  'ack_target_matches_p_asserted_identity': None,
                  'ack_to_matches_p_asserted_identity': None,
                  'rp_reference_matches': None, 'sip_response_codes': [],
                  'gateway_correlation_rejected': False}
        if message['direction'] == 'out' and reply_state == 'visible':
            candidates = [m for m in incoming if m['pid'] == message['pid'] and
                          m['line'] < message['line'] and visible(header(m, 'call-id')) and
                          header(m, 'call-id') == reply]
            if len(candidates) == 1:
                related = candidates[0]
                record['related_incoming_index'] = sms.index(related) + 1
                if message['rp_type'] in (2, 4):
                    target, gateway = uri(message.get('target')), uri(header(related, 'p-asserted-identity'))
                    if target and gateway:
                        record['ack_target_matches_p_asserted_identity'] = target == gateway
                    recipient = uri(header(message, 'to'))
                    if recipient and gateway:
                        record['ack_to_matches_p_asserted_identity'] = recipient == gateway
                    if message['rp_reference'] is not None and related['rp_reference'] is not None:
                        record['rp_reference_matches'] = message['rp_reference'] == related['rp_reference']
            elif not candidates:
                record['in_reply_to'] = 'unmatched_in_capture'
        key = transaction(message)
        if key is not None:
            replies = [m for m in messages if m.get('status') and m['line'] > message['line'] and
                       m['direction'] != message['direction'] and transaction(m) == key]
            record['sip_response_codes'] = sorted(set(m['status'] for m in replies))
            record['gateway_correlation_rejected'] = any(m.get('gateway_correlation_rejected') for m in replies)
        records.append(record)
    # Include rejection count even when the raw transaction ID was redacted.
    rejected = sum(bool(m.get('gateway_correlation_rejected')) for m in messages)
    return {'schema': 1, 'scope': 'offline_log_analysis', 'sms_delivery_verified': False,
            'events': events,
            'sms_config_observations': [{'priority': p, 'value': bool(v)} for p, v in sorted(config)],
            'gateway_correlation_rejections': rejected, 'messages': records,
            'limitations': ['Missing/redacted headers are not proof of wire-level omission.',
                           'SIP 2xx does not establish RP acceptance or single delivery to Hub.',
                           'URI comparisons are textual; aliases or equivalent forms need manual review.',
                           'No identities, SIP addresses, Call-IDs, filenames or SMS bodies are exported.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--output', type=Path, help='Create a new redacted JSON report; never overwrite an existing file')
    args = parser.parse_args(argv)
    with args.log.open('rb') as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        parser.error('Log exceeds 64 MiB; provide a bounded capture')
    report = json.dumps(analyze(raw.decode('utf-8', 'replace')), ensure_ascii=True, indent=2) + '\n'
    if args.output:
        with args.output.open('x', encoding='utf-8') as target:
            target.write(report)
    else:
        print(report, end='')


if __name__ == '__main__':
    main()
