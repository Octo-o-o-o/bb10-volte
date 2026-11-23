#!/usr/bin/env python3
"""Parameterized experimental runner for ISIM + stock 0.xml carrier trials (e.g. KT 450-08).

Uses the existing BB10 VoLTE SSH trust, 4-file desktop+phone backup, read-only stock
protections, and clean restore path. All output is sanitized for sharing on GitHub Issues.
"""
import argparse
import json
import shlex
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'device'))

import connection
import profiles
import service as device_service
from auto_carrier import AutoClient, BASE
from workflow import public_status

DEFAULT_CONFIG = ROOT / 'kt-45008-trial.json'
SAFE_PROBE_FIELDS = (
    'variant',
    'family',
    'os_version',
    'board_type',
    'installed',
    'can_install',
    'can_update',
    'update_available',
    'call_idle',
    'sim_supported',
    'sim_reason',
    'sim_plmn',
    'serving_plmn',
    'operator',
    'operator_trial',
    'sim_has_isim',
    'isim_status',
    'isim_services',
    'preloaded_carrier_config',
    'downloaded_carrier_config_present',
    'observed_data_apn',
    'exp_trial_active',
    'radio_lte',
    'lte_data_connected',
    'stock_template_verified',
    'mobile_network_off',
    'reboot_required',
    'scope_error',
)


def sanitize_probe(raw):
    out = {key: raw[key] for key in SAFE_PROBE_FIELDS if key in raw}
    if isinstance(raw.get('status'), dict):
        out['status'] = public_status(raw['status'])
    return out


def load_local_config(path):
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    return profiles.validate_exp_trial(raw)


def connect(args):
    client, meta = connection.resolve_connection(args.host, args.ssh_config or '')
    return client, AutoClient(client), meta


def push_trial_config(client, auto, validated):
    payload = profiles.canonical(validated)
    remote_tmp = profiles.EXP_TRIAL_PATH + '.new'
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(payload)
        local_tmp = Path(tmp.name)
    try:
        auto.upload(local_tmp, remote_tmp)
        client.remote(
            'chmod 600 ' + shlex.quote(remote_tmp) +
            ' && mv ' + shlex.quote(remote_tmp) + ' ' + shlex.quote(profiles.EXP_TRIAL_PATH)
        )
    finally:
        local_tmp.unlink(missing_ok=True)


def remove_trial_config(client):
    client.remote('rm -f ' + shlex.quote(profiles.EXP_TRIAL_PATH) + ' ' + shlex.quote(profiles.EXP_TRIAL_PATH + '.new'))


def read_redacted_ims_events(client, max_lines=40):
    path = BASE + '/state/owned-ims-events.log'
    cmd = 'if [ -f ' + shlex.quote(path) + ' ]; then tail -n ' + str(int(max_lines)) + ' ' + shlex.quote(path) + '; fi'
    try:
        raw = client.remote(cmd, 15)
    except Exception:
        return []
    return [device_service.redact_ims_event_line(line) for line in raw.splitlines() if line.strip()]


def cmd_probe(args):
    client, auto, _ = connect(args)
    report = auto.probe()
    return 0, {
        'ok': True,
        'action': 'probe',
        'probe': sanitize_probe(report),
    }


def cmd_apply(args):
    validated = load_local_config(args.config)
    client, auto, _ = connect(args)
    push_trial_config(client, auto, validated)
    probe_after = auto.probe()
    out = {
        'ok': True,
        'action': 'apply',
        'trial_config': validated,
        'probe_before_install': sanitize_probe(probe_after),
    }
    if probe_after.get('scope_error'):
        out['ok'] = False
        out['error'] = probe_after['scope_error']
        return 1, out
    if probe_after.get('sim_supported') is not True:
        out['ok'] = False
        out['error'] = probe_after.get('sim_reason') or 'sim_not_supported'
        return 1, out
    if probe_after.get('installed') and not probe_after.get('can_update') and not probe_after.get('update_available'):
        out['install_result'] = 'already_installed_current_payload'
        out['next_step'] = (
            'Experimental trial config has been updated on the phone. '
            'Use the phone power menu to restart normally, unlock, wait 2-3 minutes, then run: '
            'python tools/kt_isim_trial.py status'
        )
        return 0, out
    result = auto.install()
    out['install_result'] = {
        k: result[k] for k in ('installed', 'updated', 'reboot_required', 'desktop_backup', 'phone_backup')
        if k in result
    }
    if isinstance(result.get('status'), dict):
        out['status'] = public_status(result['status'])
    out['next_step'] = (
        'Backup and installation succeeded. Use the phone power menu to restart normally, unlock, '
        'wait 2-3 minutes on LTE, then run: python tools/kt_isim_trial.py status'
    )
    return 0, out


def cmd_start(args):
    client, auto, _ = connect(args)
    result = auto.action('start')
    return 0, {
        'ok': True,
        'action': 'start',
        'status': public_status(result) if isinstance(result, dict) else result,
        'recent_ims_events': read_redacted_ims_events(client, 30),
    }


def cmd_status(args):
    client, auto, _ = connect(args)
    probe_raw = auto.probe()
    events = read_redacted_ims_events(client, args.lines)
    return 0, {
        'ok': True,
        'action': 'status',
        'probe': sanitize_probe(probe_raw),
        'recent_ims_events': events,
    }


def cmd_restore(args):
    client, auto, _ = connect(args)
    disabled = None
    try:
        disabled = auto.action('disable')
    except Exception as exc:
        disabled = {'note': str(exc)}
    remove_trial_config(client)
    return 0, {
        'ok': True,
        'action': 'restore',
        'trial_config_removed': True,
        'disable_result': public_status(disabled) if isinstance(disabled, dict) and 'phase' in disabled else disabled,
        'next_step': 'Use the phone power menu to restart normally so stock cellular state is cleanly restored.',
    }


def main(argv=None):
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
