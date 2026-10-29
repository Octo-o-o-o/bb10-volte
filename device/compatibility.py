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
import profiles
import device_info

PROFILE = profiles.DEFAULT['id']
OWNER = 'q10-unicom-volte-v1'
BASE = '/var/rootdata/q10_volte'
ADDON = '/var/addons/q10-unicom-volte'
LEGACY_FILES = {'device/install.py', 'device/service.py', 'device/native.py',
                'device/ims_image.py', 'device/radio_api.py', 'device/run.sh',
                'device/addon-start.sh', 'driver/devnp-volte_swcrypto_probe.so'}
V02_FILES = LEGACY_FILES | {'device/compatibility.py'}
FILES = V02_FILES | {'device/profiles.py', 'device/device_info.py'}
RADIO = '/pps/services/cellular/radioctrl/status_public'
DATA = '/pps/services/cds/cnice/status'
NETWORK_FLAGS = ('radio_on', 'lte', 'apn_matches', 'data_connected',
                 'radio_read_error', 'data_read_error', 'network_read_error')
PUBLIC_APNS = ('ctnet', 'ctlte', 'cmnet', '3gnet')
CONFIGURATION_FLAGS = ('ims_override_absent', 'probe_override_absent', 'cdsc_directory_empty',
                       'voice_override_absent', 'ims_profiles_absent', 'ims_networks_absent',
                       'ims_services_absent', 'ims_domain_default', 'cdsc_selection_default')
NATIVE_BASELINE_FIELDS = ('voice_policy', 'crypto', 'ims_count', 'vpn_count')
DIAGNOSTIC_VALUES = {
    'ims_state': (str, ('connected', 'disconnected', 'idle')),
    'ims_ran': (str, ('LTE', 'WLAN')),
    'allow_volte_provisioning': (int, (0, 1)),
    'engineering_voice_override': (str, ('2', '3', '4', '5', '6')),
    'dca_voice_preference': (int, (0, 1, 2, 3)),
    'use_preconditions': (int, (0, 1)),
}


def public_incoming_diagnostics(values):
    values = values if isinstance(values, dict) else {}
    result = {'scope': 'configuration_observation_only', 'call_acceptance': 'not_assessed'}
    for key, (kind, allowed) in DIAGNOSTIC_VALUES.items():
        value = values.get(key)
        result[key] = value if type(value) is kind and value in allowed else None
    return result


def public_flags(values, keys):
    values = values if isinstance(values, dict) else {}
    return {key: values.get(key) if type(values.get(key)) is bool else None for key in keys}


def public_network_diagnostics(values):
    result = public_flags(values, NETWORK_FLAGS)
    apn = values.get('observed_data_apn')
    result['observed_data_apn'] = apn if apn in PUBLIC_APNS + ('other',) else 'unknown'
    result['scope'] = 'snapshot_only_not_registration_or_band_proof'
    return result


def public_baseline(values):
    """Bound numeric observations and exclude exception text and arbitrary data."""
    def number(value, low, high):
        return value if type(value) is int and low <= value <= high else None
    crypto = values.get('crypto')
    crypto = crypto if isinstance(crypto, dict) else {}
    result = {'voice_policy': number(values.get('voice_policy'), 0, 255),
              'crypto': {key: number(crypto.get(key), -2147483648, 2147483647)
                         for key in ('swcr_id', 'crypto_support')},
              'ims_count': number(values.get('ims_count'), 0, 65535),
              'vpn_count': number(values.get('vpn_count'), 0, 65535)}
    result.update(public_flags(values, ('clean_configuration', 'native_read_error')))
    return result


def public_native_read_status(values):
    values = values if isinstance(values, dict) else {}
    return {key: values.get(key) if values.get(key) in ('read', 'failed', 'not_checked') else 'unknown'
            for key in NATIVE_BASELINE_FIELDS}


def baseline_diagnostics(values):
    """Explain every existing gate without changing installation eligibility.

    This also accepts older report observations: missing details remain unknown.
    Read failures are per probe, so one failure cannot erase the other readings.
    """
    baseline = public_baseline(values)
    read_status = values.get('native_read_status', {})
    read_status = read_status if isinstance(read_status, dict) else {}
    rows = []
    def add(key, actual, expected, source=None):
        read = read_status.get(source) if source else None
        reason = ('read_failed' if read == 'failed' else 'not_checked' if read == 'not_checked'
                  else 'unavailable' if actual is None else 'observed')
        if reason != 'observed':
            actual = None
        status = 'unknown' if actual is None else 'pass' if actual == expected else 'wait'
        rows.append({'id': key, 'status': status, 'actual': actual,
                     'expected': expected, 'reason': reason})
    add('voice_policy', baseline['voice_policy'], 0, 'voice_policy')
    add('crypto_swcr_id', baseline['crypto']['swcr_id'], -1, 'crypto')
    add('crypto_support', baseline['crypto']['crypto_support'], 0, 'crypto')
    add('ims_count', baseline['ims_count'], 0, 'ims_count')
    add('vpn_count', baseline['vpn_count'], 0, 'vpn_count')
    # Old reports omit the flag on success. Only infer success from complete reads.
    error = baseline['native_read_error']
    if error is None and all(row['actual'] is not None for row in rows):
        error = False
    add('native_read_error', error, False)
    add('clean_configuration', baseline['clean_configuration'], True)
    configuration = public_flags(values.get('configuration_diagnostics'), CONFIGURATION_FLAGS)
    for key in CONFIGURATION_FLAGS:
        add(key, configuration[key], True)
    return rows


def autostart_supported(device, profile):
    # Issue #1 reports a boot-animation hang on community variants. Only the
    # existing Q10/carrier baseline has this project's normal-reboot acceptance.
    return device.get('hardware_tested') is True and profiles.baseline_parameters(profile)


def incoming_diagnostics():
    """Read configuration hints only; never infer incoming-call readiness.

    Fixed enums keep identities, arbitrary PPS text and exception details out
    of exported reports. An absent/malformed field is unknown, not disabled.
    """
    def object_at(path):
        try:
            return n.attrs(n.read(path))
        except (OSError, ValueError, TypeError):
            return {}

    def field(attrs, key, allowed, kind):
        try:
            value = n.value(attrs, key)
            return value if type(value) is kind and value in allowed else None
        except (ValueError, TypeError, AttributeError):
            return None

    ims = object_at('/pps/services/ims/status_public')
    engineering = object_at('/pps/services/escreens/config')
    dca = object_at('/pps/services/carrier_config/radio_common/cellular_protocol_configuration')
    ir92 = object_at('/pps/services/carrier_config/ims/ir92')
    ran = field(ims, 'default_ran', ('LTE', 'lte', 'WLAN', 'wlan'), str)
    return {'scope': 'configuration_observation_only', 'call_acceptance': 'not_assessed',
            'ims_state': field(ims, 'status', ('connected', 'disconnected', 'idle'), str),
            'ims_ran': ran.upper() if ran else None,
            'allow_volte_provisioning': field(ims, 'allowVoLteProvisioning', (0, 1), int),
            'engineering_voice_override': field(engineering, 'voice_domain_preference_EUTRAN_override',
                                                ('2', '3', '4', '5', '6'), str),
            'dca_voice_preference': field(dca, 'voice_domain_preference_EUTRAN', (0, 1, 2, 3), int),
            'use_preconditions': field(ir92, 'UsePreconditions', (0, 1), int)}


def read_network(profile=None):
    """Return derived facts, never IMSI/ICCID/IMEI or the raw PPS objects."""
    p = profiles.validate(profiles.default() if profile is None else profile)
    result = {}
    try:
        card = n.attrs(n.read('/pps/services/cellular/uicc/card0/status_private'))
        result['sim_state'] = n.value(card, 'uicc_state', {}).get('state')
        result['sim_type'] = n.value(card, 'uicc_type')
        home = n.value(card, 'hplmn', {})
        result['mcc'], result['mnc'] = home.get('mcc'), home.get('mnc')
        restricted = n.attrs(n.read('/pps/services/cellular/uicc/card0/status_restricted'))
        result['identity_matches'] = profiles.identity_matches(str(n.value(restricted, 'imsi')), result['mcc'], result['mnc'])
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        result['sim_read_error'] = True
    try:
        radio = n.attrs(n.read(RADIO))
        result.update(radio_on=n.value(radio, 'power_status') == 'ON',
                      lte=n.value(radio, 'network_technology') == ['lte'])
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        result['radio_read_error'] = result['network_read_error'] = True
    try:
        internet = n.value(n.attrs(n.read(DATA)), 'internet', {})
        apn = internet.get('apn')
        present = isinstance(apn, str) and bool(apn)
        connected = internet.get('connected')
        result.update(apn_matches=apn in p['carrier']['data_apns'] if present else None,
                      data_connected=connected if type(connected) is bool else None,
                      observed_data_apn=apn if apn in PUBLIC_APNS else 'other' if present else 'unknown')
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        result['data_read_error'] = result['network_read_error'] = True
    return result


def network_checks(s, profile=None):
    p = profiles.validate(profiles.default() if profile is None else profile)
    checks = []
    def add(key, status, code):
        checks.append({'id': key, 'status': status, 'code': code})
    ready = s.get('sim_state') == 'READY' and not s.get('sim_read_error')
    add('sim', 'pass' if ready else 'wait', 'sim_ready' if ready else 'sim_unavailable')
    if ready:
        carrier = s.get('mcc') == p['carrier']['mcc'] and s.get('mnc') in p['carrier']['mncs']
        add('carrier', 'pass' if carrier else 'adapt', 'carrier_matches_profile' if carrier else 'carrier_not_profiled')
        kind = s.get('sim_type')
        supported = isinstance(kind, int) and bool(kind & 2) and not bool(kind & 16)
        add('sim_route', 'pass' if supported else 'adapt', 'usim_without_isim' if supported else 'sim_route_not_profiled')
        if carrier and supported:
            add('identity', 'pass' if s.get('identity_matches') else 'adapt',
                'identity_layout_matches' if s.get('identity_matches') else 'identity_layout_unknown')
    online = s.get('radio_on') and s.get('lte')
    add('lte', 'pass' if online else 'wait', 'lte_ready' if online else 'lte_not_ready')
    data = (s.get('apn_matches') is True and s.get('data_connected') is True and
            not s.get('network_read_error'))
    code = ('data_apn_ready' if data else
            'data_apn_state_unknown' if s.get('network_read_error') else
            'data_apn_profile_mismatch' if s.get('apn_matches') is False else
            'data_apn_disconnected' if s.get('apn_matches') is True and s.get('data_connected') is False else
            'data_apn_state_unknown')
    add('apn', 'pass' if data else 'wait', code)
    return checks


def network_state(s, profile=None):
    checks = network_checks(s, profile)
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
        if manifest['owner'] != OWNER or names not in (LEGACY_FILES, V02_FILES, FILES):
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
        if names == FILES:
            if os.path.islink(BASE + '/carrier-profile.json'):
                return {'state': 'conflict'}
            request = profiles.installed_request(BASE)
            result['carrier_profile_sha256'] = profiles.fingerprint(request)
            result['carrier_profile_id'] = request['profile']['id']
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


def configuration_diagnostics():
    """Observe the existing baseline gates; export only fixed boolean fields.

    A non-default field does not establish who changed it or whether it is
    harmful. Never delete an override or reset a user's APN from a probe.
    """
    result = dict((key, None) for key in CONFIGURATION_FLAGS)
    for key, path in (('ims_override_absent', '/var/ims/carrier/imsconfig_user.xml'),
                      ('probe_override_absent', '/pps/volte_probe')):
        try:
            result[key] = not os.path.lexists(path)
        except OSError:
            pass
    try:
        result['cdsc_directory_empty'] = not bool(os.listdir('/var/radio/cdsc'))
    except OSError:
        pass
    fields = {
        '/pps/services/carrier_config/radio_common/cellular_protocol_configuration':
            [('voice_domain_preference_EUTRAN', 'voice_override_absent', (None,))],
        '/pps/services/carrier_config/ims/ims':
            [('IMS_profilesV2', 'ims_profiles_absent', (None,)),
             ('supported_networks', 'ims_networks_absent', (None,)),
             ('IMS_services', 'ims_services_absent', (None,)),
             ('Home_network_domain_name', 'ims_domain_default', (None, ':'))],
        '/pps/services/cds/cnice/status_persistent':
            [('cdsc_xml', 'cdsc_selection_default', (':',))],
    }
    for path, entries in fields.items():
        try:
            attrs = n.attrs(n.read(path))
            for key, label, allowed in entries:
                result[label] = attrs.get(key) in allowed
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    return result


def pristine_configuration():
    return all(value is True for value in configuration_diagnostics().values())


def observe(profile=None):
    p = profiles.validate(profiles.default() if profile is None else profile)
    s = read_network(p)
    s['root_ready'] = os.geteuid() == 0 and os.path.isfile('/tmp/root.done')
    s['arm32_qnx'] = ctypes.sizeof(ctypes.c_void_p) == 4 and os.uname()[0] == 'QNX'
    try:
        s.update(device_info.read_identity())
    except (OSError, ValueError, TypeError):
        pass
    s['incoming_diagnostics'] = incoming_diagnostics()
    s['native_hashes'] = {}
    s['native_sha256'] = {}
    for path, expected in n.STOCK_HASHES.items():
        try:
            digest = n.digest(n.read(path))
            s['native_hashes'][path] = digest == expected
            s['native_sha256'][path] = digest
        except OSError:
            s['native_hashes'][path] = False
    s['installation'] = installed_state()
    try:
        s['carrier_template'], _ = profiles.carrier_template(p, s.get('mcc'), s.get('mnc'))
        s['carrier_template_ready'] = True
    except Exception:
        s['carrier_template_ready'] = False
    # Never call native ARM functions on a different build, host or privilege level.
    s['native_read_status'] = dict((key, 'not_checked') for key in NATIVE_BASELINE_FIELDS)
    if s['root_ready'] and device_info.engine_matches(s):
        s['configuration_diagnostics'] = configuration_diagnostics()
        s['clean_configuration'] = all(value is True for value in s['configuration_diagnostics'].values())
        s['native_read_error'] = False
        for key, read in (('voice_policy', n.voice_policy), ('crypto', n.crypto_policy),
                          ('ims_count', lambda: len(n.ims_pids())),
                          ('vpn_count', lambda: len(n.active_vpn_sessions()))):
            try:
                s[key] = read()
                s['native_read_status'][key] = 'read'
            except Exception:
                s['native_read_status'][key] = 'failed'
                s['native_read_error'] = True
    return s


def evaluate(s, profile=None, allow_experimental=False):
    req = profiles.request(profile, allow_experimental)
    p = req['profile']
    device = device_info.identify(s)
    checks = []
    def check(key, passed, code, failure='block'):
        checks.append({'id': key, 'status': 'pass' if passed else failure, 'code': code})
    check('model', device['recognized'], 'device_identified' if device['recognized'] else 'device_identity_unknown')
    if device['family'] == 'passport':
        check('provider_lifecycle', device_info.provider_lifecycle_supported(device),
              'passport_provider_lifecycle_unvalidated', 'adapt')
    check('os', s.get('os_version') == device_info.OS_VERSION, 'os_3216_required')
    check('root', s.get('root_ready') and s.get('arm32_qnx'), 'root_qnx_arm32_required', 'wait')
    hashes = s.get('native_hashes', {})
    check('native', set(hashes) == set(n.STOCK_HASHES) and all(hashes.values()), 'native_hashes_required')
    checks.extend(network_checks(s, p))
    check('carrier_config', s.get('carrier_template_ready') is True, 'carrier_template_required', 'adapt')
    experimental = not autostart_supported(device, p)
    check('experiment', not experimental or allow_experimental, 'experimental_opt_in' if experimental else 'recorded_baseline', 'wait')
    if experimental:
        check('autostart_policy', not p['runtime']['autostart'],
              'experimental_manual_start_required', 'wait')
    statuses = [c['status'] for c in checks]
    outcome = ('unsupported' if 'block' in statuses else 'needs_adaptation' if 'adapt' in statuses
               else 'not_ready' if 'wait' in statuses else 'experimental' if experimental else 'compatible')
    installation = s.get('installation', {'state': 'conflict'})
    pristine = (not s.get('native_read_error') and s.get('voice_policy') == 0 and
                s.get('crypto') == {'swcr_id': -1, 'crypto_support': 0} and
                s.get('ims_count') == 0 and s.get('vpn_count') == 0 and
                s.get('clean_configuration') is True)
    state = installation['state']
    allowed = outcome in ('compatible', 'experimental') and pristine
    checks.append({'id': 'installation', 'status': 'pass' if state in ('absent', 'stopped', 'busy') else 'wait',
                   'code': 'installation_' + state})
    checks.append({'id': 'baseline', 'status': 'pass' if pristine else 'wait',
                   'code': 'baseline_clean' if pristine else 'baseline_not_clean'})
    request_sha = profiles.fingerprint(req)
    matching_profile = installation.get('carrier_profile_sha256') == request_sha
    check('saved_profile', state == 'absent' or not installation.get('current_profile') or matching_profile,
          'saved_profile_matches' if matching_profile else 'profile_update_required', 'wait')
    return {'schema': 2, 'profile': p['id'], 'profile_sha256': request_sha,
            'profile_parameters': p, 'experimental': experimental, 'experimental_allowed': allow_experimental,
            'device': device, 'native_sha256': s.get('native_sha256', {}),
            'incoming_diagnostics': public_incoming_diagnostics(s.get('incoming_diagnostics')),
            'network_diagnostics': public_network_diagnostics(s),
            'configuration_diagnostics': public_flags(s.get('configuration_diagnostics'), CONFIGURATION_FLAGS),
            'carrier_template': s.get('carrier_template'), 'checked_at': int(time.time()),
            'outcome': outcome, 'checks': checks,
            'facts': {key: s.get(key) for key in ('model', 'variant', 'os_version', 'mcc', 'mnc')},
            'installation': installation,
            'baseline': public_baseline(s),
            'native_read_status': public_native_read_status(s.get('native_read_status')),
            'baseline_diagnostics': baseline_diagnostics(s),
            'can_install': allowed and state == 'absent',
            'can_update': allowed and state == 'stopped',
            'can_start': allowed and state == 'stopped' and installation.get('current_profile') is True and matching_profile,
            'can_enable': allowed and not experimental and state == 'stopped' and installation.get('current_profile') is True and matching_profile,
            'can_restore': device_info.provider_lifecycle_supported(device),
            'hardware_validation': 'not_hardware_validated' if experimental else 'single_q10_beijing_unicom_only',
            'carrier_provisioning': 'requires_user_confirmation_and_real_calls'}


def probe(profile=None, allow_experimental=False):
    return evaluate(observe(profile), profile, allow_experimental)


def require(action, profile=None, allow_experimental=False):
    report = probe(profile, allow_experimental)
    if not report.get('can_' + action):
        failures = ','.join(c['code'] for c in report['checks'] if c['status'] != 'pass')
        raise RuntimeError('Preflight blocked ' + action + ': ' + report['outcome'] + ' ' + failures)
    return report


if __name__ == '__main__':
    req = profiles.load_request(sys.argv[2]) if len(sys.argv) == 3 and sys.argv[1] == '--request' else profiles.request()
    print(json.dumps(probe(req['profile'], req['allow_experimental']), sort_keys=True))
