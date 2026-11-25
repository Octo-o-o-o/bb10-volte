#!/usr/bin/env python3
"""Offline Apache-2.0 overseas carrier catalog loader and experimental CLI.

Provides non-460 reference APN/IMS parameters derived from AOSP (Apache-2.0)
for explicit user opt-in. Catalog entries are reference parameters only and
do not claim BB10 hardware validation.
"""
import argparse
from functools import lru_cache
import json
import shlex
import sys
import time
from pathlib import Path

from desktop_paths import resource_root

ROOT = resource_root()
if str(ROOT / 'device') not in sys.path:
    sys.path.insert(0, str(ROOT / 'device'))
if str(ROOT / 'tools') not in sys.path:
    sys.path.insert(0, str(ROOT / 'tools'))

import profiles
import service as device_service
from workflow import public_status

CATALOG_REL = 'materials/overseas-carriers.json'
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
    'exp_trial_summary',
    'radio_lte',
    'lte_data_connected',
    'lte_active_band_mask',
    'lte_band_capability_mask',
    'lte_bands_disabled',
    'stock_template_verified',
    'mobile_network_off',
    'reboot_required',
    'scope_error',
)


@lru_cache(maxsize=4)
def _load_catalog_cached(path_str):
    raw = json.loads(Path(path_str).read_text(encoding='utf-8'))
    if (not isinstance(raw, dict) or raw.get('schema') not in (1, 2) or
            not isinstance(raw.get('carriers'), dict)):
        raise ValueError('invalid_overseas_catalog')
    mcc_regions = raw.get('mcc_regions') if isinstance(raw.get('mcc_regions'), dict) else {}
    default_status = str(raw.get('default_bb10_status') or 'untested')
    carriers = []
    for plmn, item in sorted(raw['carriers'].items()):
        if not isinstance(item, dict):
            continue
        if '-' in plmn:
            plmn_mcc, plmn_mnc = plmn.split('-', 1)
        else:
            plmn_mcc, plmn_mnc = '', ''
        mcc = str(item.get('mcc') or plmn_mcc)
        mnc = str(item.get('mnc') or plmn_mnc)
        if mcc == '460' or not profiles.match(r'[0-9]{3}', mcc) or not profiles.match(r'[0-9]{2,3}', mnc):
            continue
        geo = mcc_regions.get(mcc)
        geo_country = str(geo[0]) if isinstance(geo, list) and len(geo) >= 1 else ''
        geo_region = str(geo[1]) if isinstance(geo, list) and len(geo) >= 2 else ''
        ip_family = item.get('ims_ip_family') or item.get('ip_family') or 'IPv4v6'
        carriers.append({
            'plmn': plmn,
            'mcc': mcc,
            'mnc': mnc,
            'country': str(item.get('country') or geo_country),
            'region': str(item.get('region') or geo_region),
            'name': str(item.get('name', plmn)),
            'data_apns': tuple(item.get('data_apns') or ()),
            'ims_apn': str(item.get('ims_apn') or 'ims'),
            'ip_family': ip_family if ip_family in ('IPv4', 'IPv6', 'IPv4v6') else 'IPv4v6',
            'bb10_status': str(item.get('bb10_status') or default_status),
            'source': str(item.get('source', 'aosp')),
        })
    return tuple(carriers)


def load_catalog(path=None):
    target = Path(path) if path is not None else ROOT / CATALOG_REL
    return [dict(entry, data_apns=list(entry['data_apns']))
            for entry in _load_catalog_cached(str(target.resolve()))]


def lookup_plmn(mcc, mnc, path=None):
    mcc = str(mcc or '').strip()
    mnc = str(mnc or '').strip()
    if mcc == '460':
        return None
    for entry in load_catalog(path):
        if entry.get('mcc') == mcc and entry.get('mnc') == mnc:
            return dict(entry)
    return None


def lookup_plmn_code(plmn, path=None):
    if not isinstance(plmn, str) or '-' not in plmn:
        return None
    mcc, mnc = plmn.strip().split('-', 1)
    return lookup_plmn(mcc, mnc, path=path)


def search_catalog(query='', path=None):
    entries = load_catalog(path)
    needle = (query or '').strip().lower()
    if not needle:
        return entries
    out = []
    for entry in entries:
        haystack = ' '.join([
            str(entry.get('plmn', '')),
            str(entry.get('country', '')),
            str(entry.get('region', '')),
            str(entry.get('name', '')),
            ' '.join(entry.get('data_apns') or ()),
            str(entry.get('ims_apn', '')),
        ]).lower()
        if needle in haystack:
            out.append(entry)
    return out


def format_catalog_entry(entry):
    country = (' (' + entry['country'] + ')') if entry.get('country') else ''
    return '{} · {}{} · APN: {} · IMS: {}/{}'.format(
        entry.get('plmn', ''),
        entry.get('name', ''),
        country,
        ','.join((entry.get('data_apns') or ())[:2]) or 'auto',
        entry.get('ims_apn', 'ims'),
        entry.get('ip_family', 'IPv4v6'),
    )


def build_trial_config(mcc, mncs, data_apns, ims_apn='ims', ip_family='IPv4v6', home_domain='auto',
                       sms=True, allow_isim=False, allow_stock_default_xml=True, label='',
                       stock_config='auto', ue_usage='auto', always_on=True,
                       request_signalling_bearer_via_pco=False, disable_dad=False,
                       ir92=None, ims_pps=None, enabled=True):
    ims = {
        'apn': profiles.normalize_apn(ims_apn or 'ims') or 'ims',
        'ip_family': ip_family or 'IPv4v6',
        'home_domain': (home_domain or 'auto').strip().lower() or 'auto',
        'sms': bool(sms),
    }
    if not always_on:
        ims['always_on'] = False
    if request_signalling_bearer_via_pco:
        ims['request_signalling_bearer_via_pco'] = True
    if disable_dad:
        ims['disable_dad'] = True
    if ir92:
        ims['ir92'] = dict(ir92)
    if ims_pps:
        ims['ims_pps'] = dict(ims_pps)
    apns = []
    for item in (data_apns or ['auto']):
        cleaned = str(item).strip().lower()
        if not cleaned:
            continue
        val = 'auto' if cleaned == 'auto' else profiles.normalize_apn(cleaned)
        if val and val not in apns:
            apns.append(val)
    if not apns:
        apns = ['auto']
    mnc_list = []
    for item in mncs:
        cleaned = str(item).strip()
        if cleaned and cleaned not in mnc_list:
            mnc_list.append(cleaned)
    cfg = {
        'schema': 2,
        'enabled': bool(enabled),
        'mcc': str(mcc).strip(),
        'mncs': mnc_list,
        'allow_isim': bool(allow_isim),
        'allow_stock_default_xml': bool(allow_stock_default_xml),
        'data_apns': apns,
        'ims': ims,
    }
    clean_label = (label or '').strip()[:80]
    if clean_label:
        cfg['label'] = clean_label
    if stock_config and stock_config != 'auto':
        cfg['stock_config'] = str(stock_config).strip()
    if ue_usage and ue_usage != 'auto':
        cfg['ue_usage'] = ue_usage
    return profiles.validate_exp_trial(cfg)


def usable_observed_apn(observed_apn):
    return profiles.usable_observed_apn(observed_apn)


def preset_to_trial_config(entry, allow_isim=False, allow_stock_default_xml=True, observed_apn=None):
    apns = ['auto']
    obs = usable_observed_apn(observed_apn)
    if obs and obs not in apns:
        apns.append(obs)
    for item in entry.get('data_apns') or ():
        norm = profiles.normalize_apn(item)
        if norm and norm not in apns:
            apns.append(norm)
    label = '{} {}'.format(entry.get('name', '').strip(), entry.get('plmn', '').strip()).strip()
    return build_trial_config(
        mcc=entry['mcc'],
        mncs=[entry['mnc']],
        data_apns=apns[:16],
        ims_apn=entry.get('ims_apn') or 'ims',
        ip_family=entry.get('ip_family') or 'IPv4v6',
        home_domain='auto',
        sms=True,
        allow_isim=allow_isim,
        allow_stock_default_xml=allow_stock_default_xml,
        label=label,
    )


def sanitize_probe(raw):
    out = {key: raw[key] for key in SAFE_PROBE_FIELDS if key in raw}
    if isinstance(raw.get('status'), dict):
        out['status'] = public_status(raw['status'])
    return out


def read_redacted_ims_events(client, max_lines=40):
    from auto_carrier import BASE
    path = BASE + '/state/owned-ims-events.log'
    cmd = 'if [ -f ' + shlex.quote(path) + ' ]; then tail -n ' + str(int(max_lines)) + ' ' + shlex.quote(path) + '; fi'
    try:
        raw = client.remote(cmd, 15)
    except Exception:
        return []
    return [device_service.redact_ims_event_line(line) for line in raw.splitlines() if line.strip()]


def configure_stdio():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            try:
                stream.reconfigure(encoding='utf-8', errors='replace')
            except (OSError, ValueError):
                pass


def _connect(args):
    import connection
    from auto_carrier import AutoClient
    client, meta = connection.resolve_connection(args.host, args.ssh_config or '')
    return client, AutoClient(client), meta


def run_probe(auto):
    return 0, {'ok': True, 'action': 'probe', 'probe': sanitize_probe(auto.probe())}


def run_apply(auto, config_path):
    raw_cfg = json.loads(Path(config_path).read_text(encoding='utf-8'))
    validated = profiles.validate_exp_trial(raw_cfg)
    saved = auto.set_exp_trial(validated)
    probe_after = saved.get('probe') or auto.probe()
    payload = {
        'ok': True,
        'action': 'apply',
        'trial_config': validated,
        'probe_before_install': sanitize_probe(probe_after),
    }
    if probe_after.get('scope_error'):
        payload['ok'] = False
        payload['error'] = probe_after['scope_error']
        return 1, payload
    if probe_after.get('update_available') and not probe_after.get('can_update'):
        payload['ok'] = False
        payload['error'] = 'unified_update_needs_stop_and_reboot'
        return 1, payload
    if probe_after.get('sim_supported') is not True and not probe_after.get('can_prepare_mobile_network'):
        payload['ok'] = False
        payload['error'] = probe_after.get('sim_reason') or 'sim_not_supported'
        return 1, payload
    if (probe_after.get('installed') and not probe_after.get('installation_pending') and
            not probe_after.get('can_update') and not probe_after.get('update_available')):
        payload['install_result'] = 'already_installed_current_payload'
        return 0, payload
    result = auto.install()
    install_summary = {
        k: result[k] for k in ('installed', 'updated', 'reboot_required', 'phone_backup')
        if k in result
    }
    if 'desktop_backup' in result:
        install_summary['desktop_backup_verified'] = bool(result.get('desktop_backup'))
    payload['install_result'] = install_summary
    if isinstance(result.get('status'), dict):
        payload['status'] = public_status(result['status'])
    return 0, payload


def run_start(client, auto):
    res = auto.action('start')
    return 0, {
        'ok': True,
        'action': 'start',
        'status': public_status(res) if isinstance(res, dict) else res,
        'recent_ims_events': read_redacted_ims_events(client, 30),
    }


def run_status(client, auto, lines=40):
    return 0, {
        'ok': True,
        'action': 'status',
        'probe': sanitize_probe(auto.probe()),
        'recent_ims_events': read_redacted_ims_events(client, lines),
    }


def run_restore(auto, wait_seconds=90.0):
    try:
        disabled = auto.action('disable')
    except Exception as exc:
        disabled = {'note': str(exc)}
    deadline = time.time() + float(wait_seconds)
    while time.time() < deadline:
        try:
            st = auto.action('status')
        except Exception:
            break
        if not isinstance(st, dict) or not st.get('manager_alive'):
            break
        time.sleep(1.5)
    cleared = auto.clear_exp_trial()
    return 0, {
        'ok': True,
        'action': 'restore',
        'trial_config_removed': bool(cleared.get('cleared')),
        'disable_result': public_status(disabled) if isinstance(disabled, dict) and 'phase' in disabled else disabled,
    }


def main(argv=None):
    configure_stdio()
    parser = argparse.ArgumentParser(description='Offline overseas carrier catalog and experimental runner')
    parser.add_argument('--host', default='bb10-root', help='Saved SSH host alias or IP (default: bb10-root)')
    parser.add_argument('--ssh-config', default='', help='Optional path to SSH config file')
    sub = parser.add_subparsers(dest='command', required=True)

    p_cat = sub.add_parser('catalog', help='Search offline Apache-2.0 overseas carrier reference catalog')
    p_cat.add_argument('--query', default='', help='Search keyword (PLMN, country, carrier name, APN)')
    p_cat.add_argument('--plmn', default='', help='Exact PLMN lookup (e.g. 450-08)')

    sub.add_parser('probe', help='Read-only probe including SIM PLMN, ISIM, LTE band mask and stock template')

    p_init = sub.add_parser('init', help='Generate a Schema 2 overseas trial JSON from catalog or custom PLMN')
    p_init.add_argument('--plmn', required=True, help='Home PLMN (MCC-MNC, e.g. 450-08 or 310-260)')
    p_init.add_argument('--allow-isim', action='store_true', help='Opt in to USIM+ISIM experimental trial')
    p_init.add_argument('--out', default='', help='Optional output JSON file path')

    p_apply = sub.add_parser('apply', help='Push validated overseas trial JSON via management lock and install/update')
    p_apply.add_argument('--config', required=True, help='Path to overseas trial JSON')

    sub.add_parser('start', help='Start the installed service if stopped and ready')

    p_status = sub.add_parser('status', help='Show sanitized VoLTE status, route status and redacted IMS events')
    p_status.add_argument('--lines', type=int, default=40, help='Max redacted IMS event lines (default: 40)')

    sub.add_parser('restore', help='Disable service and remove overseas trial configuration')

    args = parser.parse_args(argv)
    try:
        if args.command == 'catalog':
            if args.plmn:
                found = lookup_plmn_code(args.plmn)
                payload = {'ok': True, 'action': 'catalog', 'plmn': args.plmn, 'carrier': found}
            else:
                matches = search_catalog(args.query)
                payload = {'ok': True, 'action': 'catalog', 'count': len(matches), 'carriers': matches[:50]}
            code = 0
        elif args.command == 'init':
            entry = lookup_plmn_code(args.plmn)
            if entry is None:
                if '-' not in args.plmn:
                    raise ValueError('PLMN must be MCC-MNC')
                mcc, mnc = args.plmn.split('-', 1)
                cfg = build_trial_config(mcc, [mnc], ['auto'], allow_isim=args.allow_isim)
            else:
                cfg = preset_to_trial_config(entry, allow_isim=args.allow_isim)
            if args.out:
                Path(args.out).write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            payload = {'ok': True, 'action': 'init', 'from_catalog': entry is not None, 'config': cfg}
            code = 0
        elif args.command == 'probe':
            _, auto, _ = _connect(args)
            code, payload = run_probe(auto)
        elif args.command == 'apply':
            _, auto, _ = _connect(args)
            code, payload = run_apply(auto, args.config)
        elif args.command == 'start':
            client, auto, _ = _connect(args)
            code, payload = run_start(client, auto)
        elif args.command == 'status':
            client, auto, _ = _connect(args)
            code, payload = run_status(client, auto, args.lines)
        elif args.command == 'restore':
            _, auto, _ = _connect(args)
            code, payload = run_restore(auto)
        else:
            code, payload = 1, {'ok': False, 'error': 'unknown_command'}
    except Exception as exc:
        code, payload = 1, {'ok': False, 'action': args.command, 'error': str(exc)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
