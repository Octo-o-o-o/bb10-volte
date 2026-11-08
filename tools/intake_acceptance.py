"""Evaluate exact-device evidence and append a version-scoped intake verdict.

This local tool does not contact a phone or change runtime admission. Missing
tests stay unknown; sound and visible message counts require owner evidence.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'device')]
CHECKS = ('identity_root_native', 'original_backups', 'normal_boot_registration',
          'normal_stop_restore', 'outgoing_call', 'incoming_call', 'two_way_audio',
          'LTE_during_calls', 'data_during_calls', 'HTTP_HTTPS', 'short_SMS',
          'long_SMS', 'identical_incoming_SMS', 'SMS_idle', 'desktop_package',
          'mobile_package', 'mobile_UI')
SMS_CHECKS = frozenset(('short_SMS', 'long_SMS', 'identical_incoming_SMS', 'SMS_idle'))
SCOPE_KEYS = ('variant', 'board', 'os_version', 'home_plmn', 'SIM_type')
HEX = re.compile(r'\A[a-f0-9]{64}\Z')


def require(value, code):
    if not value:
        raise ValueError(code)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    require(path.is_file() and not path.is_symlink(), 'evidence_not_regular')
    require(path.stat().st_size <= 4 * 1024 * 1024, 'evidence_too_large')
    data = path.read_bytes()
    return data, json.loads(data.decode('utf-8-sig'))


def pointer(value, path):
    require(isinstance(path, str) and path.startswith('/') and len(path) <= 240,
            'invalid_evidence_pointer')
    for part in path[1:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        require(isinstance(value, dict) and part in value, 'evidence_pointer_missing')
        value = value[part]
    require(value is True or value is False or value is None, 'evidence_value_not_boolean')
    return value


def source_scope(value):
    return {'variant': value.get('variant'), 'board': value.get('board', value.get('board_type')),
            'os_version': value.get('os_version'), 'home_plmn': value.get('home_plmn')}


def product_scope(scope):
    import carrier_policy
    import device_support
    import profiles
    mcc, mnc = scope['home_plmn'].split('-')
    blocked = profiles.carrier_adaptation_blocked(scope['variant'], mcc, (mnc,))
    admitted = False
    if not blocked:
        try:
            carrier_policy.model({'variant':scope['variant'], 'board_type':scope['board'],
                                  'os_version':scope['os_version']})
            admitted = (mcc == '460' and mnc in carrier_policy.VALIDATED_MNCS.get(scope['variant'], ())
                        and device_support.assess(scope['variant'])['automatic_volte'])
        except ValueError:
            pass
    return {'runtime_scope_enabled':admitted, 'explicit_product_exclusion':bool(blocked),
            'carrier_policy_sha256':digest((ROOT/'device/carrier_policy.py').read_bytes()),
            'support_catalog_sha256':digest((ROOT/'materials/device-support.json').read_bytes())}


def evaluate(manifest, evidence_root, admission=None):
    require(isinstance(manifest, dict) and manifest.get('schema') == 1, 'unsupported_schema')
    require(set(manifest) <= {'schema','scope','sources','checks','known_SMS_limitations'}, 'unknown_manifest_field')
    scope = manifest.get('scope')
    require(isinstance(scope, dict) and set(scope) == set(SCOPE_KEYS), 'invalid_exact_scope')
    require(re.fullmatch(r'SQ[NCW]100-[1-5]', scope['variant']) is not None, 'invalid_variant')
    require(re.fullmatch(r'[A-Z0-9_]{3,40}', scope['board']) is not None, 'invalid_board')
    require(re.fullmatch(r'\d{2}\.\d\.\d\.\d{4}', scope['os_version']) is not None, 'invalid_os')
    require(re.fullmatch(r'460-\d{2,3}', scope['home_plmn']) is not None, 'invalid_home_plmn')
    require(scope['SIM_type'] == 'USIM_without_ISIM', 'unvalidated_SIM_route')
    root = Path(evidence_root).resolve(strict=True)
    sources = manifest.get('sources')
    require(isinstance(sources, dict) and 1 <= len(sources) <= 64, 'invalid_sources')
    loaded, source_receipts = {}, {}
    for key, source in sources.items():
        require(re.fullmatch(r'[a-z][a-z0-9_]{0,39}', key) is not None, 'invalid_source_id')
        require(isinstance(source, dict) and set(source) == {'path','sha256'}, 'invalid_source')
        name = source['path']
        require(isinstance(name, str) and '\\' not in name and ':' not in name and
                not name.startswith('/') and all(x not in ('','..','.') for x in name.split('/')),
                'unsafe_evidence_path')
        path = root / name
        require(path.resolve(strict=True).is_relative_to(root), 'evidence_outside_case')
        cursor = path
        while cursor != root:
            require(not cursor.is_symlink(), 'linked_evidence_path'); cursor = cursor.parent
        require(isinstance(source['sha256'], str) and HEX.fullmatch(source['sha256']), 'invalid_evidence_hash')
        data, value = read_json(path)
        require(digest(data) == source['sha256'], 'evidence_hash_changed')
        require(source_scope(value) == {k:scope[k] for k in ('variant','board','os_version','home_plmn')},
                'evidence_scope_mismatch')
        if 'SIM_type' in value:
            require(value['SIM_type'] == scope['SIM_type'], 'evidence_SIM_route_mismatch')
        loaded[key] = value
        source_receipts[key] = {'path':name, 'sha256':source['sha256'],
            'versions':{k:value[k] for k in ('mobile_version','desktop_revision','runtime_map_sha256',
                'private_runtime_map_fingerprint') if k in value}}
    checks = manifest.get('checks')
    require(isinstance(checks, dict) and set(checks) <= set(CHECKS), 'unknown_check')
    outcomes = {}
    def observe(ref):
        require(isinstance(ref, dict) and set(ref) == {'source','pointer'}, 'invalid_reference')
        require(ref['source'] in loaded, 'unknown_evidence_source')
        return pointer(loaded[ref['source']], ref['pointer'])
    for name in CHECKS:
        item = checks.get(name, {'evidence':[], 'scope_note':'Not tested'})
        require(isinstance(item, dict) and set(item) == {'evidence','scope_note'}, 'invalid_check')
        require(isinstance(item['scope_note'], str) and len(item['scope_note']) <= 400, 'invalid_scope_note')
        refs = item['evidence']
        require(isinstance(refs, list) and len(refs) <= 8, 'invalid_references')
        values = [observe(ref) for ref in refs]
        result = 'failed' if False in values else 'passed' if values and all(x is True for x in values) else 'not_tested'
        outcomes[name] = dict(item, result=result)
    limitations = manifest.get('known_SMS_limitations', [])
    require(isinstance(limitations, list) and len(limitations) <= 4, 'invalid_limitations')
    waived = set()
    for issue in limitations:
        require(isinstance(issue, dict) and set(issue) == {'code','checks','owner_authorization'}, 'invalid_limitation')
        require(re.fullmatch(r'[a-z][a-z0-9_]{1,79}', issue['code']) is not None, 'invalid_issue_code')
        require(isinstance(issue['checks'], list) and issue['checks'] and
                set(issue['checks']) <= SMS_CHECKS, 'only_SMS_limitations_may_be_authorized')
        require(observe(issue['owner_authorization']) is True, 'missing_owner_authorization')
        waived.update(issue['checks'])
    missing = [k for k in CHECKS if outcomes[k]['result'] == 'not_tested' and k not in waived]
    failed = [k for k in CHECKS if outcomes[k]['result'] == 'failed' and k not in waived]
    admitted = product_scope(scope) if admission is None else admission
    if admitted['explicit_product_exclusion']:
        status = 'blocked'
    elif failed:
        status = 'failed'
    elif missing:
        status = 'incomplete'
    elif not admitted['runtime_scope_enabled']:
        status = 'validated_pending_integration'
    else:
        status = 'adapted_with_SMS_limitations' if limitations else 'adapted'
    return {'schema':1, 'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'scope':scope, 'status':status, 'checks':outcomes, 'sources':source_receipts,
            'missing_checks':missing, 'failed_checks':failed, 'known_SMS_limitations':limitations,
            'product_scope':admitted, 'all_checks_fresh_same_version_claimed':False,
            'phone_contacted':False, 'runtime_admission_modified':False, 'public_release_performed':False}


def register(path, report, manifest_sha256):
    """Append immutable evidence; never replace an earlier verdict in place."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.is_symlink(), 'linked_registry')
    lock = path.with_suffix(path.suffix + '.lock')
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    temporary = None
    try:
        os.close(fd)
        old = path.read_bytes() if path.exists() else None
        value = json.loads(old.decode('utf8')) if old is not None else {'schema':1,'records':[]}
        require(value.get('schema') == 1 and isinstance(value.get('records'), list), 'invalid_registry')
        report_sha = digest(json.dumps({k:v for k,v in report.items() if k != 'at_utc'}, sort_keys=True).encode())
        if any(x.get('manifest_sha256') == manifest_sha256 and x.get('report_sha256') == report_sha for x in value['records']):
            return False
        value['records'].append({'manifest_sha256':manifest_sha256,'report_sha256':report_sha,'verdict':report})
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        require((path.read_bytes() if path.exists() else None) == old, 'registry_changed_concurrently')
        os.replace(temporary, path); temporary = None
        return True
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--evidence-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--registry', type=Path)
    args = parser.parse_args()
    require(not args.output.exists(), 'preserve_previous_output')
    raw, manifest = read_json(args.manifest)
    report = evaluate(manifest, args.evidence_root)
    # The public report contains only explicitly selected facts and source hashes.
    from check_release import SENSITIVE
    public = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    require(not any(pattern.search(public) for pattern in SENSITIVE.values()), 'private_data_in_public_report')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf8') as stream: stream.write(public)
    if args.registry: register(args.registry, report, digest(raw))
    print(json.dumps({'status':report['status'],'missing_checks':report['missing_checks'],
        'failed_checks':report['failed_checks'],'runtime_admission_modified':False}))
    return 0 if report['status'] in ('adapted','adapted_with_SMS_limitations','validated_pending_integration') else 2


if __name__ == '__main__':
    raise SystemExit(main())
