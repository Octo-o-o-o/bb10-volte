"""Versioned, fail-closed Q10 preflight. Python 3.2; no changes on import/probe.

Only allowlisted facts leave the phone. SIM identities are evaluated locally and
are never included in a report, exception, fingerprint or installation receipt.
"""
import ctypes
import json
import os
import re
import sys
import time

import native as n

PROFILE = 'q10-sqn100-3-os3216-unicom01-usim-v1'
OWNER = 'q10-unicom-volte-v1'
BASE = '/var/rootdata/q10_volte'
ADDON = '/var/addons/q10-unicom-volte'
LEGACY_FILES = {'device/install.py', 'device/service.py', 'device/native.py',
                'device/ims_image.py', 'device/radio_api.py', 'device/run.sh',
                'device/addon-start.sh', 'driver/devnp-volte_swcrypto_probe.so'}
FILES = LEGACY_FILES | {'device/compatibility.py'}
RADIO = '/pps/services/cellular/radioctrl/status_public'
DATA = '/pps/services/cds/cnice/status'


def read_network():
    """Return derived facts, never IMSI/ICCID/IMEI or the raw PPS objects."""
    result = {}
    try:
        card = n.attrs(n.read('/pps/services/cellular/uicc/card0/status_private'))
        result['sim_state'] = n.value(card, 'uicc_state', {}).get('state')
        result['sim_type'] = n.value(card, 'uicc_type')
        home = n.value(card, 'hplmn', {})
        result['mcc'], result['mnc'] = home.get('mcc'), home.get('mnc')
        restricted = n.attrs(n.read('/pps/services/cellular/uicc/card0/status_restricted'))
        result['identity_matches'] = bool(re.match(r'^46001[0-9]{10}$', str(n.value(restricted, 'imsi'))))
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        result['sim_read_error'] = True
    try:
        radio = n.attrs(n.read(RADIO))
        internet = n.value(n.attrs(n.read(DATA)), 'internet', {})
        result.update(radio_on=n.value(radio, 'power_status') == 'ON',
                      lte=n.value(radio, 'network_technology') == ['lte'],
                      apn_matches=internet.get('apn') == '3gnet',
                      data_connected=internet.get('connected') is True)
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        result['network_read_error'] = True
    return result


def network_checks(s):
    checks = []
    def add(key, status, code):
        checks.append({'id': key, 'status': status, 'code': code})
    ready = s.get('sim_state') == 'READY' and not s.get('sim_read_error')
    add('sim', 'pass' if ready else 'wait', 'sim_ready' if ready else 'sim_unavailable')
    if ready:
        carrier = (s.get('mcc'), s.get('mnc')) == ('460', '01')
        add('carrier', 'pass' if carrier else 'adapt', 'unicom_46001' if carrier else 'carrier_not_profiled')
        kind = s.get('sim_type')
        supported = isinstance(kind, int) and bool(kind & 2) and not bool(kind & 16)
        add('sim_route', 'pass' if supported else 'adapt', 'usim_without_isim' if supported else 'sim_route_not_profiled')
        if carrier and supported:
            add('identity', 'pass' if s.get('identity_matches') else 'adapt',
                'identity_layout_matches' if s.get('identity_matches') else 'identity_layout_unknown')
    online = s.get('radio_on') and s.get('lte')
    add('lte', 'pass' if online else 'wait', 'lte_ready' if online else 'lte_not_ready')
    data = s.get('apn_matches') and s.get('data_connected') and not s.get('network_read_error')
    add('apn', 'pass' if data else 'wait', 'data_apn_ready' if data else 'data_apn_not_ready')
    return checks


def network_state(s):
    checks = network_checks(s)
    return ('needs_adaptation' if any(c['status'] == 'adapt' for c in checks) else
            'not_ready' if any(c['status'] != 'pass' for c in checks) else 'ready')


def installed_state():
    """Validate ownership and every installed byte before permitting an update."""
    if not os.path.lexists(BASE):
        return {'state': 'absent' if not os.path.lexists(ADDON) else 'conflict'}
    result = {'state': 'conflict'}
    try:
        for path in (BASE, BASE + '/device', BASE + '/driver', BASE + '/state',
                     BASE + '/runtime', BASE + '/runtime/carrier', ADDON,
                     ADDON + '/init', ADDON + '/data'):
            if not os.path.isdir(path) or os.path.islink(path):
                return result
        if os.path.lexists(BASE + '/install-transaction.json'):
            return {'state': 'interrupted'}
        if any(os.path.islink(BASE + '/' + name) for name in
               ('installation.json', 'enabled', 'state/journal.json', 'state/lock.json')):
            return result
        manifest = json.loads(n.read(BASE + '/installation.json').decode('ascii'))
        names = set(manifest['files'])
        if manifest['owner'] != OWNER or names not in (LEGACY_FILES, FILES):
            return result
        for name, expected in manifest['files'].items():
            path = BASE + '/' + name
            if os.path.islink(path) or n.digest(n.read(path)) != expected:
                return result
        if (os.path.islink(ADDON + '/init/start.sh') or
                n.digest(n.read(ADDON + '/init/start.sh')) != manifest['files']['device/addon-start.sh']):
            return result
        result = {'state': 'stopped', 'version': manifest.get('version'),
                  'enabled': os.path.isfile(BASE + '/enabled'), 'payload_verified': True,
                  'current_profile': names == FILES}
        if os.path.exists(BASE + '/state/lock.json'):
            # Never delete a stale/unknown lock from a preflight.
            result['state'] = 'busy'
        elif os.path.isfile(BASE + '/state/journal.json'):
            journal = json.loads(n.read(BASE + '/state/journal.json').decode('ascii'))
            if journal.get('owner') != OWNER or journal.get('original_voice_policy') != 0:
                return {'state': 'conflict'}
            if not journal.get('restore_completed'):
                result['state'] = 'recovery_required'
        return result
    except (OSError, ValueError, TypeError, KeyError):
        return {'state': 'conflict'}


def pristine_configuration():
    if os.path.lexists('/var/ims/carrier/imsconfig_user.xml') or os.path.lexists('/pps/volte_probe'):
        return False
    if os.listdir('/var/radio/cdsc'):
        return False
    fields = {
        '/pps/services/carrier_config/radio_common/cellular_protocol_configuration': ['voice_domain_preference_EUTRAN'],
        '/pps/services/carrier_config/ims/ims': ['IMS_profilesV2', 'supported_networks', 'IMS_services', 'Home_network_domain_name'],
        '/pps/services/cds/cnice/status_persistent': ['cdsc_xml'],
    }
    for path, keys in fields.items():
        attrs = n.attrs(n.read(path))
        for key in keys:
            allowed = (':',) if key == 'cdsc_xml' else (None, ':') if key == 'Home_network_domain_name' else (None,)
            if attrs.get(key) not in allowed:
                return False
    return True


def observe():
    s = read_network()
    s['root_ready'] = os.geteuid() == 0 and os.path.isfile('/tmp/root.done')
    s['arm32_qnx'] = ctypes.sizeof(ctypes.c_void_p) == 4 and os.uname()[0] == 'QNX'
    try:
        props = n.attrs(n.read('/pps/services/deviceproperties'))
        # Model and version strings are not device-unique identifiers.
        s['model'] = n.value(props, 'modelname')
        s['variant'] = n.value(props, 'modelnumber')
        s['os_version'] = n.read('/etc/os.version').decode('ascii').strip()
    except (OSError, ValueError, TypeError):
        pass
    s['native_hashes'] = {}
    for path, expected in n.STOCK_HASHES.items():
        try:
            s['native_hashes'][path] = n.digest(n.read(path)) == expected
        except OSError:
            s['native_hashes'][path] = False
    s['installation'] = installed_state()
    # Never call native ARM functions on a different build, host or privilege level.
    if s['root_ready'] and s['arm32_qnx'] and all(s['native_hashes'].values()):
        try:
            s.update(voice_policy=n.voice_policy(), crypto=n.crypto_policy(),
                     ims_count=len(n.ims_pids()), vpn_count=len(n.active_vpn_sessions()),
                     clean_configuration=pristine_configuration())
        except Exception:
            s['native_read_error'] = True
    return s


def evaluate(s):
    checks = []
    def check(key, passed, code, failure='block'):
        checks.append({'id': key, 'status': 'pass' if passed else failure, 'code': code})
    check('model', s.get('model') == 'Q10' and s.get('variant') == 'SQN100-3', 'q10_sqn100_3_required')
    check('os', s.get('os_version') == '10.3.3.3216', 'os_3216_required')
    check('root', s.get('root_ready') and s.get('arm32_qnx'), 'root_qnx_arm32_required', 'wait')
    hashes = s.get('native_hashes', {})
    check('native', set(hashes) == set(n.STOCK_HASHES) and all(hashes.values()), 'native_hashes_required')
    checks.extend(network_checks(s))
    statuses = [c['status'] for c in checks]
    outcome = ('unsupported' if 'block' in statuses else 'needs_adaptation' if 'adapt' in statuses
               else 'not_ready' if 'wait' in statuses else 'compatible')
    installation = s.get('installation', {'state': 'conflict'})
    pristine = (not s.get('native_read_error') and s.get('voice_policy') == 0 and
                s.get('crypto') == {'swcr_id': -1, 'crypto_support': 0} and
                s.get('ims_count') == 0 and s.get('vpn_count') == 0 and
                s.get('clean_configuration') is True)
    state = installation['state']
    allowed = outcome == 'compatible' and pristine
    checks.append({'id': 'installation', 'status': 'pass' if state in ('absent', 'stopped', 'busy') else 'wait',
                   'code': 'installation_' + state})
    checks.append({'id': 'baseline', 'status': 'pass' if pristine else 'wait',
                   'code': 'baseline_clean' if pristine else 'baseline_not_clean'})
    return {'schema': 1, 'profile': PROFILE, 'checked_at': int(time.time()),
            'outcome': outcome, 'checks': checks,
            'facts': {key: s.get(key) for key in ('model', 'variant', 'os_version', 'mcc', 'mnc')},
            'installation': installation,
            'baseline': {key: s.get(key) for key in ('voice_policy', 'crypto', 'ims_count', 'vpn_count',
                                                    'clean_configuration', 'native_read_error')},
            'can_install': allowed and state == 'absent',
            'can_update': allowed and state == 'stopped',
            'can_start': allowed and state == 'stopped' and installation.get('current_profile') is True,
            'hardware_validation': 'single_q10_beijing_unicom_only',
            'carrier_provisioning': 'requires_user_confirmation_and_real_calls'}


def probe():
    return evaluate(observe())


def require(action):
    report = probe()
    if not report.get('can_' + action):
        failures = ','.join(c['code'] for c in report['checks'] if c['status'] != 'pass')
        raise RuntimeError('Preflight blocked ' + action + ': ' + report['outcome'] + ' ' + failures)
    return report


if __name__ == '__main__':
    print(json.dumps(probe(), sort_keys=True))
