#!/usr/bin/env python3
"""Compatibility wrapper for ISIM + stock 0.xml carrier trials (defaults to kt-45008-trial.json).

Delegates probe, apply, start, status, restore and redaction to tools/overseas_carrier.py.
"""
import argparse
import json
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _entry in (str(ROOT / 'tools'), str(ROOT / 'device')):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import connection
import overseas_carrier as oc
import profiles
from auto_carrier import AutoClient

DEFAULT_CONFIG = ROOT / 'kt-45008-trial.json'
SAFE_PROBE_FIELDS = oc.SAFE_PROBE_FIELDS
sanitize_probe = oc.sanitize_probe
read_redacted_ims_events = oc.read_redacted_ims_events


def load_local_config(path):
    return profiles.validate_exp_trial(json.loads(Path(path).read_text(encoding='utf-8')))


def connect(args):
    client, meta = connection.resolve_connection(args.host, args.ssh_config or '')
    return client, AutoClient(client), meta


def push_trial_config(client, auto, validated):
    return auto.set_exp_trial(validated)


def remove_trial_config(client, auto=None):
    if auto is not None:
        return auto.clear_exp_trial()
    client.remote('rm -f ' + shlex.quote(profiles.EXP_TRIAL_PATH) + ' ' + shlex.quote(profiles.EXP_TRIAL_PATH + '.new'))


def cmd_probe(args):
    _, auto, _ = connect(args)
    return oc.run_probe(auto)


def cmd_apply(args):
    _, auto, _ = connect(args)
    return oc.run_apply(auto, args.config)


def cmd_start(args):
    client, auto, _ = connect(args)
    return oc.run_start(client, auto)


def cmd_status(args):
    client, auto, _ = connect(args)
    return oc.run_status(client, auto, args.lines)


def cmd_restore(args):
    _, auto, _ = connect(args)
    return oc.run_restore(auto)


def main(argv=None):
    oc.configure_stdio()
    parser = argparse.ArgumentParser(description='Experimental ISIM + stock 0.xml carrier trial runner')
    parser.add_argument('--host', default='bb10-root', help='Saved SSH host alias or IP (default: bb10-root)')
    parser.add_argument('--ssh-config', default='', help='Optional path to SSH config file')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('probe', help='Read-only probe including ISIM status, stock template and data APN')
    p_apply = sub.add_parser('apply', help='Push trial JSON and install/update the experimental service')
    p_apply.add_argument('--config', default=str(DEFAULT_CONFIG), help='Path to trial JSON (default: kt-45008-trial.json)')
    sub.add_parser('start', help='Start the installed service if stopped and ready')
    p_status = sub.add_parser('status', help='Print sanitized VoLTE status and redacted IMS event trace')
    p_status.add_argument('--lines', type=int, default=40, help='Max redacted IMS log lines (default: 40)')
    sub.add_parser('restore', help='Disable service and remove experimental trial config')
    args = parser.parse_args(argv)
    handlers = {
        'probe': cmd_probe,
        'apply': cmd_apply,
        'start': cmd_start,
        'status': cmd_status,
        'restore': cmd_restore,
    }
    try:
        code, payload = handlers[args.command](args)
    except Exception as exc:
        code, payload = 1, {'ok': False, 'action': args.command, 'error': str(exc)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
