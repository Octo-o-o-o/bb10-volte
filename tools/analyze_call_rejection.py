#!/usr/bin/env python3
"""Summarize an existing IMS/qct log without exporting call identifiers.

This offline tool does not contact a phone, change radio state, or infer that
an absent event proves a failed call. Log excerpts can be incomplete or from
different calls; counts are observations, never call acceptance or a diagnosis.
"""
import argparse
import json
from pathlib import Path
import re
import sys

MAX_CHARACTERS = 8 * 1024 * 1024
MAX_LINE_CHARACTERS = 16384
MAX_LINES = 100000

# Fixed strings from the hash-pinned 10.3.3.3216 ims_rrm/qct_rrm images.
# Never retain a matched line, URI, phone number, call ID, PID or timestamp.
EVENTS = {
    'reject_requested': 'PHONE: [IMS] Calling Reject',
    'reject_refused': 'Cannot reject call, mgr state ',
    'answer_refused': 'Cannot answer call, mgr state ',
    'hangup_not_completed': 'Call not hung up',
    'phone_command_failed': 'PHONE: [IMS] tlvRet not success (',
    'duplicate_incoming_slot': 'PHONE: [IMS] Already have an INCOMING call',
    'busy_disconnect_deferred': 'Busy, do not send DISCONNECT now, will send later',
    'incoming_or_missing_dialog': 'dialog is NULL or incoming call',
}
NOTIFICATION = re.compile(r'Notification\s+\d+\s+\(NOTIFY_PHONE_(INCOMING|DISCONNECTED)\)\s+Rx\b')
CALL_ENDED = re.compile(r'\bcallEnded \.\.\..*?\bstatus code ([0-9]{3}) endReason [0-6]\b')
STATE_ENDED = re.compile(r'\bbb\.eng\.cmgr:[0-9]+ state=0, reason=[0-6], code=([0-9]{3}), stackState=[0-9]+\b')


def analyze(stream):
    """Read bounded text and return only fixed keys, counts and SIP statuses."""
    counts = {key: 0 for key in EVENTS}
    counts.update(incoming_notification=0, disconnected_notification=0,
                  call_ended_callback=0, engine_ended_state=0)
    statuses = {}
    consumed = lines = 0
    truncated = False
    while True:
        # readline(size) also bounds an input consisting of one enormous line.
        line = stream.readline(min(MAX_LINE_CHARACTERS + 1, MAX_CHARACTERS - consumed + 1))
        if not line:
            break
        if lines >= MAX_LINES or len(line) > MAX_LINE_CHARACTERS or consumed + len(line) > MAX_CHARACTERS:
            truncated = True
            break
        consumed += len(line)
        lines += 1
        for key, needle in EVENTS.items():
            if needle in line:
                counts[key] += 1
        notification = NOTIFICATION.search(line)
        if notification:
            key = 'incoming_notification' if notification.group(1) == 'INCOMING' else 'disconnected_notification'
            counts[key] += 1
        for key, expression in (('call_ended_callback', CALL_ENDED), ('engine_ended_state', STATE_ENDED)):
            match = expression.search(line)
            if match and 100 <= int(match.group(1)) <= 699:
                counts[key] += 1
                code = match.group(1)
                statuses[code] = statuses.get(code, 0) + 1
    observations = []
    if any(counts[key] for key in ('reject_refused', 'answer_refused', 'hangup_not_completed', 'phone_command_failed')):
        observations.append('phone_command_error_observed')
    if counts['duplicate_incoming_slot']:
        observations.append('existing_incoming_slot_observed')
    if counts['busy_disconnect_deferred']:
        observations.append('deferred_busy_disconnect_observed')
    if counts['disconnected_notification']:
        observations.append('disconnect_notification_observed_not_correlated_to_a_call')
    if not observations:
        observations.append('insufficient_evidence')
    return {
        'schema_version': 1,
        'scope': 'partial_log_observation_only',
        'call_acceptance': 'not_assessed',
        'root_cause': 'not_determined',
        'input': {'lines_processed': lines, 'truncated': truncated},
        'events': counts,
        'end_status_observations': statuses,
        'observations': observations,
        'limitations': ['events_not_correlated_between_calls',
                        'missing_events_do_not_prove_failure',
                        'log_authenticity_not_verified',
                        'no_device_or_radio_changes'],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='Existing local log; keep the raw file private')
    parser.add_argument('--output', type=Path, help='Write only the sanitized JSON summary')
    args = parser.parse_args(argv)
    try:
        if args.output and args.output.resolve() == args.input.resolve():
            raise ValueError('input and output must be different')
        if args.output and args.output.exists():
            raise ValueError('output already exists')
        with args.input.open('r', encoding='utf-8', errors='replace') as stream:
            report = analyze(stream)
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
        if args.output:
            # Exclusive creation also protects against replacing another log.
            with args.output.open('x', encoding='utf-8') as stream:
                stream.write(rendered)
        else:
            sys.stdout.write(rendered)
    except (OSError, ValueError):
        # Error messages must not disclose local paths or raw input.
        print(json.dumps({'ok': False, 'error': 'input_or_output_unavailable'}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
