"""Hash-pinned management of the already accepted Q20 Root-v2 installation.

Python 3.2. Imports the existing adapter only after checking every pinned byte.
This helper never replaces the running native image, driver or boot hook.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time

BASE = '/var/q20_volte'
BOOT_HOOK = '/apps/sys.android.gYABgKAOw1czN6neiAT72SGO.ns/native/system/xbin/btool'
BOOT_HOOK_HASH = 'bdcd111afbbfe802e4489a85a4c6eb2e0ba0b8dbe8a429f01ea88045e8b4d501'


def checked_manifest(expected):
    assert re.match(r'^[a-f0-9]{64}$', expected)
    assert os.geteuid() == 0 and os.uname()[0] == 'QNX'
    with open('/pps/services/deviceproperties', 'rb') as source:
        assert b'modelnumber::SQC100-2\n' in source.read()
    with open(BASE + '/payload-manifest.json', 'rb') as source:
        raw = source.read()
    assert hashlib.sha256(raw).hexdigest() == expected, 'Q20 adapter revision needs inspection'
    manifest = json.loads(raw.decode('ascii'))
    assert manifest['owner'] == 'q20-sqc100-2-volte-v1'
    assert len(manifest['files']) == 16
    for name, digest in manifest['files'].items():
        assert re.match(r'^(?:(?:device|driver)/)?[A-Za-z0-9_.-]+$', name)
        path = BASE + '/' + name
        assert not os.path.islink(path)
        with open(path, 'rb') as source:
            assert hashlib.sha256(source.read()).hexdigest() == digest
    # All code was verified before granting PathTrust or importing any of it.
    for name in manifest['files']:
        if name.endswith('.py'):
            subprocess.check_call(['/proc/boot/pathtrust', '!' + BASE + '/' + name])
    sys.path.insert(0, BASE)
    sys.path.insert(0, BASE + '/device')
    import q20_volte_phone as q
    q.setup()
    q.verify()
    return q


def inspect(q):
    state = q.status()
    request = q.s.ACTIVE_REQUEST
    network = q.c.read_network(request['profile'])
    facts = q.device_info.read_identity()
    checks = [{'id': key, 'status': 'pass', 'code': code} for key, code in
              (('model', 'device_identified'), ('os', 'os_3216_required'),
               ('root', 'q20_root_v2_verified'), ('native', 'native_hashes_required'),
               ('installation', 'q20_adapter_verified'))]
    try:
        hook_verified = not os.path.islink(BOOT_HOOK) and q.n.digest(q.n.read(BOOT_HOOK)) == BOOT_HOOK_HASH
    except OSError:
        hook_verified = False
    checks.append({'id': 'autostart_policy', 'status': 'pass' if hook_verified else 'adapt',
                   'code': 'q20_boot_accepted' if hook_verified else 'q20_boot_hook_changed'})
    checks += q.c.network_checks(network, request['profile'])
    native_error = False
    try:
        baseline = {'voice_policy': q.n.voice_policy(), 'crypto': q.n.crypto_policy(),
                    'ims_count': len(q.n.ims_pids()), 'vpn_count': len(q.n.active_vpn_sessions()),
                    'clean_configuration': all(q.c.configuration_diagnostics().values())}
    except Exception:
        native_error, baseline = True, {}
    baseline['native_read_error'] = native_error
    pristine = (not native_error and baseline.get('voice_policy') == 0 and
                baseline.get('crypto') == {'swcr_id': -1, 'crypto_support': 0} and
                baseline.get('ims_count') == 0 and baseline.get('vpn_count') == 0 and
                baseline.get('clean_configuration') is True and q.s.phone_idle())
    carrier = request['profile']['carrier']
    current_card = (network.get('mcc') == carrier['mcc'] and
                    network.get('mnc') in carrier['mncs'] and network.get('sim_state') == 'READY')
    checks.append({'id': 'baseline', 'status': 'pass' if pristine else 'wait',
                   'code': 'baseline_clean' if pristine else 'baseline_not_clean'})
    alive = state.get('manager_alive') is True
    installation = {'state': 'busy' if alive else 'stopped' if pristine else 'recovery_required',
                    'payload_verified': True, 'current_profile': True,
                    'version': 'q20-accepted-v3', 'enabled': state.get('enabled') is True,
                    'carrier_profile_id': request['profile']['id'],
                    'carrier_profile_sha256': q.profiles.fingerprint(request)}
    selected = q.n.value(q.n.attrs(q.n.read(q.s.CDSC)), 'cdsc_xml')
    content_ok = None
    if alive and current_card:
        template, expected = q.profiles.carrier_template(request['profile'], network['mcc'], network['mnc'])
        runtime = q.n.read(q.s.APN)
        journal = q.s.load(q.s.JOURNAL)
        content_ok = (runtime == expected and journal.get('managed_files', {}).get(q.s.APN) == q.n.digest(runtime))
    path_ok = selected == q.s.APN and content_ok is True if alive else selected in (None, '', ':')
    if not path_ok:
        checks.append({'id': 'carrier_selection', 'status': 'adapt', 'code': 'carrier_selection_conflict'})
    return {'schema': 2, 'managed_adapter': 'q20_root_v2', 'use_installed_profile': True, 'checked_at': int(time.time()),
            'profile': request['profile']['id'], 'profile_parameters': request['profile'],
            'profile_sha256': q.profiles.fingerprint(request), 'experimental': False,
            'device': q.device_info.identify(facts), 'facts': dict(facts, mcc=network.get('mcc'), mnc=network.get('mnc')),
            'baseline': q.c.public_baseline(baseline), 'checks': checks,
            'network_diagnostics': q.c.public_network_diagnostics(network),
            'incoming_diagnostics': q.c.incoming_diagnostics(),
            'configuration_diagnostics': q.c.configuration_diagnostics(),
            'carrier_selection': {'owned_runtime_selected': selected == q.s.APN,
                                  'selected_content_matches_profile': content_ok,
                                  'selection_matches_lifecycle': path_ok},
            'installation': installation, 'status': state,
            'outcome': 'compatible' if current_card and path_ok else 'needs_adaptation',
            'can_install': False, 'can_update': False, 'can_enable': False,
            'can_start': pristine and current_card, 'can_restore': True,
            'hardware_validation': 'q20_sqc100_2_' + carrier['mcc'] + ''.join(carrier['mncs']) + '_see_validation_record',
            'provider_lifecycle': 'retain_provider_until_normal_reboot'}


def perform(q, action):
    if action in ('inspect', 'status'):
        return inspect(q)
    if action == 'prepare':
        report = inspect(q)
        assert report['can_start'] is True
        if q.s.ACTIVE_PROFILE['carrier']['mncs'] != ['11']:
            q.precheck()
            return {'prepared': True, 'backup_required': False,
                    'profile_sha256': q.profiles.fingerprint(q.s.ACTIVE_REQUEST)}
        import q20_telecom_dca_usage_phone as dca
        try:
            q.precheck()
            folder, value = dca.plan()
            return {'prepared': True, 'folder': folder,
                    'plan_sha256': q.n.digest(q.n.read(folder + '/plan.json'))}
        except AssertionError:
            assert not os.path.isfile(BASE + '/enabled'), 'Disable automatic start before preparing a fresh plan'
            return dca.prepare()
    if action == 'start':
        return q.launch(False)
    assert action == 'disable'
    assert q.s.phone_idle(), 'Call active; defer restoration'
    if os.path.isfile(BASE + '/enabled'):
        os.unlink(BASE + '/enabled')
    if os.path.isfile(q.s.LOCK):
        lock = q.s.load(q.s.LOCK)
        if lock.get('boot') == q.boot_token() and q.s.alive(lock['pid']):
            q.n.atomic(q.s.STOP, b'Q20 app requested disable\n')
            return {'stop_requested': True}
    if not os.path.isfile(q.s.JOURNAL):
        return {'restored': True}
    q.s.j = q.s.load(q.s.JOURNAL)
    if q.s.j.get('boot') != q.boot_token():
        # Do not adopt or signal an old PID from another boot in a stop action.
        assert inspect(q)['can_start'] is True
        return {'restored': True}
    if q.s.j.get('configuration_restored') is not True:
        q.restore_configuration()
    return {'stop_requested': False}


def main():
    assert len(sys.argv) == 3 and sys.argv[1] in ('inspect', 'status', 'prepare', 'start', 'disable')
    q = checked_manifest(sys.argv[2])
    print(json.dumps(perform(q, sys.argv[1])))
    # Only the one exact generated helper is removed. Unexpected additions stay.
    parent = os.path.dirname(os.path.abspath(__file__))
    if (re.match(r'^/var/q20_app_probe_[a-f0-9]{12}$', parent) and
            not os.path.islink(parent) and set(os.listdir(parent)) == {'probe.py'}):
        os.unlink(parent + '/probe.py')
        os.rmdir(parent)


if __name__ == '__main__':
    main()
