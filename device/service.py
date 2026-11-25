"""Phone-managed BB10 VoLTE service, with an owned journal and explicit stop.

No phone calls are initiated. Stock executable files are never overwritten.
Python 3.2 compatible; intended only for the exact native hashes in native.py.
"""
import json
import os
import posixpath
import re
import select
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import traceback

import native as n
import compatibility
import profiles
import device_info
from ims_image import mt_voice_binary as temporary_binary
from radio_api import set_voice_preference

BASE = '/var/rootdata/q10_volte'
STATE = BASE + '/state'
RUNTIME = BASE + '/runtime'
JOURNAL = STATE + '/journal.json'
STATUS = STATE + '/status.json'
LOCK = STATE + '/lock.json'
STOP = STATE + '/stop-request'
BIN = RUNTIME + '/ims_rrm'
MODULE = BASE + '/driver/devnp-volte_swcrypto_probe.so'
CFG_DIR = '/pps/volte_probe'
CFG = CFG_DIR + '/ims'
XML = '/var/ims/carrier/imsconfig_user.xml'
APN = RUNTIME + '/carrier/36-ims.xml'
IMS = '/pps/services/carrier_config/ims/ims'
IR92 = '/pps/services/carrier_config/ims/ir92'
VOICE = '/pps/services/carrier_config/radio_common/cellular_protocol_configuration'
CDSC = '/pps/services/cds/cnice/status_persistent'
CDSC_OVERLAYS = '/var/radio/cdsc'
EMPTY_CDSC_OVERLAY = b'{"CDSCOverlayVersion":3,"CarrierDataConfiguration":{"ServiceConfiguration":[]}}'
NET_INTERFACES = '/pps/services/networking/interfaces'
ROUTE_BIN = '/sbin/route'
MAX_OWNED_ROUTES = 8
ROUTE_ADD_RE = re.compile(r'add host ([0-9a-fA-F.:]+):\s*gateway ([0-9a-fA-F.:]+):\s*Permission denied\b')
ROUTE_DEL_RE = re.compile(r'delete host ([0-9a-fA-F.:]+)(?::\s*gateway [0-9a-fA-F.:]+)?:\s*Permission denied\b')
RADIO = '/pps/services/cellular/radioctrl/status_public'
DATA = '/pps/services/cds/cnice/status'
BB_SERVICE = '/pps/system/navigator/status/bb_service'
BB_SERVICE_ON = b'[n]dat:json:{"bb_service":{"state":"on"}}\n'
DOMAIN = 'ims.mnc001.mcc460.3gppnetwork.org'
UPDATES = {
    VOICE: {'voice_domain_preference_EUTRAN': 'n:3'},
    IMS: {'IMS_profilesV2': 'json:["IR92"]', 'supported_networks': 'json:["LTE"]',
          'IMS_services': 'json:[{"service":"voice","feature_tag":"","network":["LTE"]},{"service":"sms","feature_tag":"","network":["LTE"]}]',
          'Home_network_domain_name': ':' + DOMAIN},
    CDSC: {'cdsc_xml': ':' + APN},
}
shutdown = False
j = None
child = None
berry_fd = None
event_seen = set()
startup_handoff = {}
startup_timing = {}
last_status_snapshot = None
last_status_write = None
route_log_state = {'inode': None, 'offset': 0}
ACTIVE_REQUEST = profiles.request()
ACTIVE_PROFILE = ACTIVE_REQUEST['profile']


def load(path):
    return json.loads(n.read(path).decode('utf-8'))


def save_journal():
    j['updated_unix'] = time.time()
    n.atomic(JOURNAL, json.dumps(j, indent=2).encode('ascii'))


def boot_token():
    st = os.stat('/tmp/root.done')
    return [st.st_ino, st.st_mtime]


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (IOError, OSError):
        return False


def live():
    public = n.attrs(n.read('/pps/services/ims/status_public'))
    engine = n.attrs(n.read('/pps/services/ims/cellular/status_private'))
    radio = n.attrs(n.read(RADIO))
    return {'ims': n.value(public, 'status'), 'register_status': n.value(engine, 'register_status'),
            'ran': n.value(public, 'default_ran'), 'radio': n.value(radio, 'network_technology'),
            'power': n.value(radio, 'power_status')}


def close_berry_indicator():
    global berry_fd
    fd, berry_fd = berry_fd, None
    if fd is not None:
        try:
            os.close(fd)
        except Exception:
            pass


def set_cloexec(fd):
    import fcntl
    flags = fcntl.fcntl(fd, fcntl.F_GETFD)
    fcntl.fcntl(fd, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)


def berry_ready(phase, observation):
    return (not stopping() and child is not None and child.poll() is None and
            j is not None and j.get('boot') == boot_token() and j.get('native_pid') == child.pid and
            phase == 'running' and isinstance(observation, dict) and
            observation.get('ims') == 'connected' and
            observation.get('register_status') == '200 OK' and
            observation.get('ran') in ('LTE', 'lte') and
            observation.get('radio') == ['lte'] and
            observation.get('power') == 'ON')


def external_berry_active():
    fd = os.open(BB_SERVICE, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
    try:
        raw = os.read(fd, 4096)
    finally:
        os.close(fd)
    dat = n.value(n.attrs(raw), 'dat')
    return (isinstance(dat, dict) and isinstance(dat.get('bb_service'), dict) and
            dat['bb_service'].get('state') == 'on')


def sync_berry_indicator(phase, observation):
    """Hold a QNX ?critical Navigator indicator descriptor only while registered."""
    global berry_fd
    try:
        if not berry_ready(phase, observation):
            close_berry_indicator()
            return
        if berry_fd is not None or not hasattr(os, 'uname') or os.uname()[0] != 'QNX' or external_berry_active():
            return
        fd = os.open(BB_SERVICE + '?critical', os.O_WRONLY)
        try:
            set_cloexec(fd)
            if os.write(fd, BB_SERVICE_ON) != len(BB_SERVICE_ON):
                raise IOError('short_bb_service_write')
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            raise
        berry_fd = fd
    except Exception:
        close_berry_indicator()


def status(phase, error=None, details=None, observation=None):
    global last_status_snapshot, last_status_write
    startup_timing.setdefault(phase, time.time())
    result = {'phase': phase, 'at': time.time(), 'manager_pid': os.getpid(),
              'native_pid': j.get('native_pid') if j else None, 'error': error,
              'boot': boot_token(),
              'startup_timing': dict(startup_timing),
              'stock_handoff': dict(startup_handoff),
              'ims_observation_scope': 'owned_native' if phase in ('running', 'registering', 'monitoring_unknown')
              and j and j.get('native_pid') else 'system_status_only'}
    if details is not None:
        result['startup_wait'] = details
    obs = None
    try:
        obs = live() if observation is None else observation
        result.update(obs)
    except Exception:
        result['native_status_unavailable'] = True
    sync_berry_indicator(phase, obs)
    snapshot = dict(result)
    snapshot.pop('at')
    now = result['at']
    # This is a transition record, not a liveness lease. Both clients check
    # the current boot, processes and live PPS when the user requests status.
    if (snapshot != last_status_snapshot or last_status_write is None or
            not os.path.isfile(STATUS)):
        n.atomic(STATUS, json.dumps(result, indent=2).encode('ascii'))
        last_status_snapshot, last_status_write = snapshot, now


def stopping():
    return shutdown or os.path.exists(STOP)


def wait_until(predicate, timeout, label, phase=None):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if stopping():
            raise RuntimeError('Stopped while ' + label)
        if predicate():
            return
        if phase is not None:
            status(phase)
        time.sleep(1)
    raise RuntimeError('Timeout: ' + label)


def read_status():
    result = load(STATUS) if os.path.isfile(STATUS) else {'phase': 'not_started'}
    lock = load(LOCK) if os.path.isfile(LOCK) else {}
    token = boot_token()
    same_boot = result.get('boot', lock.get('boot')) == token
    result['status_from_current_boot'] = same_boot
    result['enabled'] = os.path.isfile(BASE + '/enabled')
    result['manager_alive'] = bool(lock.get('boot') == token and alive(lock['pid']))
    result['current'] = live()
    result['native_alive'] = bool(same_boot and result['manager_alive'] and
                                  result.get('native_pid') in n.ims_pids())
    if not same_boot:
        result.update(phase='not_started_this_boot', error=None, native_pid=None,
                      ims_observation_scope='system_status_only')
    return result


def current_usim():
    base = '/pps/services/cellular/uicc/card0/'
    card = n.attrs(n.read(base + 'status_private'))
    restricted = n.attrs(n.read(base + 'status_restricted'))
    assert n.value(card, 'uicc_state', {}).get('state') == 'READY', 'SIM not ready'
    kind = n.value(card, 'uicc_type')
    allow_isim = bool(ACTIVE_PROFILE.get('experimental', {}).get('allow_isim'))
    assert kind & 2 and (allow_isim or not kind & 16), 'Only the verified USIM-without-ISIM route is supported'
    home = n.value(card, 'hplmn')
    assert (home.get('mcc') == ACTIVE_PROFILE['carrier']['mcc'] and
            home.get('mnc') in ACTIVE_PROFILE['carrier']['mncs']), 'SIM does not match the installed operator profile'
    imsi = str(n.value(restricted, 'imsi'))
    assert profiles.identity_matches(imsi, home.get('mcc'), home.get('mnc')), 'Unexpected USIM identity layout'
    return imsi


def ready():
    return compatibility.network_state(compatibility.read_network(ACTIVE_PROFILE), ACTIVE_PROFILE) == 'ready'


def wait_for_network(timeout=None):
    timeout = ACTIVE_PROFILE['runtime']['sim_wait_seconds'] if timeout is None else timeout
    deadline = time.time() + timeout
    while time.time() < deadline:
        snapshot = compatibility.read_network(ACTIVE_PROFILE)
        state = compatibility.network_state(snapshot, ACTIVE_PROFILE)
        if state == 'needs_adaptation':
            raise RuntimeError('SIM/carrier needs adaptation; check the installed profile and USIM-without-ISIM route')
        if state == 'ready':
            return True
        if stopping():
            status('stopped_before_configuration')
            return False
        status('waiting_for_lte_and_usim')
        time.sleep(ACTIVE_PROFILE['runtime']['poll_seconds'])
    raise RuntimeError('Readiness timed out after %s seconds; check SIM, LTE and the profile data APN' % timeout)


def profile_updates(profile, mcc, mnc):
    services = [{'service': 'voice', 'feature_tag': '', 'network': ['LTE']}]
    if profile['ims']['sms']:
        services.append({'service': 'sms', 'feature_tag': '', 'network': ['LTE']})
    ims_fields = {
        'IMS_profilesV2': 'json:["IR92"]', 'supported_networks': 'json:["LTE"]',
        'IMS_services': 'json:' + json.dumps(services, separators=(',', ':')),
        # Advertising SMS does not initialize DomainSelection.smsIP.
        # The pinned IMS carrier parser applies this boolean through
        # 0x105692 -> 0x93cda -> 0x9091c; registration is still required.
        'SMS_Over_IP_Network_Indication': 'b:' + ('true' if profile['ims']['sms'] else 'false'),
        'Home_network_domain_name': ':' + profiles.home_domain(profile, mcc, mnc),
    }
    ims_pps = profile['ims'].get('ims_pps') or {}
    if 'SilentRedial' in ims_pps:
        ims_fields['SilentRedial'] = 'b:' + ('true' if ims_pps['SilentRedial'] else 'false')
    if 'SIP_Timer_CSFB' in ims_pps:
        ims_fields['SIP_Timer_CSFB'] = 'n:' + str(ims_pps['SIP_Timer_CSFB'])
    result = {VOICE: {'voice_domain_preference_EUTRAN': 'n:3'},
              IMS: ims_fields,
              CDSC: {'cdsc_xml': ':' + APN}}
    ir92 = profile['ims'].get('ir92') or {}
    if ir92:
        ir92_fields = {}
        if 'UsePreconditions' in ir92:
            ir92_fields['UsePreconditions'] = 'n:' + str(ir92['UsePreconditions'])
        if 'SMS_Format' in ir92:
            ir92_fields['SMS_Format'] = ':' + ir92['SMS_Format']
        if 'amr_modeset_list' in ir92:
            ir92_fields['amr_modeset_list'] = ':' + ir92['amr_modeset_list']
        if 'amrwb_modeset_list' in ir92:
            ir92_fields['amrwb_modeset_list'] = ':' + ir92['amrwb_modeset_list']
        if ir92_fields:
            result[IR92] = ir92_fields
    return result


def wait_for_ims_apn(expected_imsi):
    """Let the native AlwaysOn bearer recover through three bounded wait rounds.

    Retrying here only observes the already requested connection. It never
    toggles the modem, repeats configuration, or interrupts an IMS process.
    A changed SIM/configuration is a conflict, not a retryable network outage.
    """
    attempts = 3
    timeout = ACTIVE_PROFILE['runtime']['ims_apn_wait_seconds']
    for attempt in range(1, attempts + 1):
        assert n.digest(n.read(APN)) == j['managed_files'][APN], 'Owned IMS APN file changed'
        deadline = time.time() + timeout
        while time.time() < deadline:
            if stopping():
                raise RuntimeError('Stopped while waiting for dedicated IMS APN')
            assert n.attrs(n.read(CDSC)).get('cdsc_xml') == applied_updates()[CDSC]['cdsc_xml'], 'IMS APN override changed'
            network = compatibility.read_network(ACTIVE_PROFILE)
            if compatibility.network_state(network, ACTIVE_PROFILE) == 'needs_adaptation':
                raise RuntimeError('SIM/carrier changed while waiting for dedicated IMS APN')
            sim_ready = network.get('sim_state') == 'READY' and not network.get('sim_read_error')
            if sim_ready and current_usim() != expected_imsi:
                raise RuntimeError('SIM changed while waiting for dedicated IMS APN')
            item = n.value(n.attrs(n.read(DATA)), 'ims', {})
            ims_apn = profiles.normalize_apn(item.get('apn'))
            if (sim_ready and network.get('radio_on') and network.get('lte') and
                    network.get('apn_matches') is not False and
                    ims_apn == ACTIVE_PROFILE['ims']['apn'].lower() and item.get('connected') is True):
                return
            status('waiting_for_ims_apn', details={'attempt': attempt, 'max_attempts': attempts,
                   'seconds_per_attempt': timeout, 'sim_ready': bool(sim_ready),
                   'lte_ready': bool(network.get('radio_on') and network.get('lte'))})
            time.sleep(ACTIVE_PROFILE['runtime']['poll_seconds'])
    raise RuntimeError('Timeout: dedicated IMS APN after 3 bounded attempts')


def applied_updates():
    # Restore the exact values that were applied, even if a different operator
    # profile was selected later. Pre-v0.3 journals use the original baseline.
    return j.get('pps_applied', UPDATES)


def _overseas_profile_active():
    return (isinstance(ACTIVE_PROFILE, dict) and
            ('experimental' in ACTIVE_PROFILE or ACTIVE_PROFILE.get('carrier', {}).get('mcc') != '460'))


def known_empty_cdsc_overlay(name):
    overseas = _overseas_profile_active()
    if overseas:
        if not re.match(r'\A[0-9]{1,6}\.json\Z', name):
            return False
    elif name not in ('36.json', '404.json'):
        return False
    path = os.path.join(CDSC_OVERLAYS, name)
    try:
        before = os.lstat(path)
        max_size = 65536 if overseas else len(EMPTY_CDSC_OVERLAY)
        if not stat.S_ISREG(before.st_mode) or before.st_size > max_size:
            return False
        if not overseas and before.st_size != len(EMPTY_CDSC_OVERLAY):
            return False
        flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(path, flags | getattr(os, 'O_BINARY', 0))
        with os.fdopen(fd, 'rb') as source:
            opened = os.fstat(source.fileno())
            if not os.path.samestat(before, opened):
                return False
            raw = source.read(max_size + 1)
            if raw == EMPTY_CDSC_OVERLAY:
                return True
            if not overseas or len(raw) > max_size:
                return False
            parsed = json.loads(raw.decode('utf-8'))
            if (not isinstance(parsed, dict) or parsed.get('CDSCOverlayVersion') != 3 or
                    not isinstance(parsed.get('CarrierDataConfiguration'), dict)):
                return False
            cdc = parsed['CarrierDataConfiguration']
            if not set(cdc) <= {'ServiceConfiguration', 'ServiceConfigurationAlias'}:
                return False
            entries = cdc.get('ServiceConfiguration', [])
            aliases = cdc.get('ServiceConfigurationAlias', [])
            if not isinstance(entries, list) or not isinstance(aliases, list):
                return False
            for entry in entries:
                if not isinstance(entry, dict):
                    return False
                if str(entry.get('Name', '')).strip().lower() == 'ims' or 'IMSConfiguration' in entry:
                    return False
            for alias in aliases:
                if not isinstance(alias, dict):
                    return False
                if str(alias.get('Name', '')).strip().lower() == 'ims':
                    return False
            return True
    except (IOError, OSError, ValueError, TypeError):
        return False


def _valid_initial_pps_value(path, key, value, unified=False):
    if path == CDSC and key == 'cdsc_xml':
        return value in (None, ':') if unified else value == ':'
    if path == VOICE and key == 'voice_domain_preference_EUTRAN':
        return value in (None, 'n:0', 'n:1', 'n:2') if unified else value is None
    if path == IMS:
        if key in ('SMS_Over_IP_Network_Indication', 'SilentRedial'):
            return value in (None, 'b:true', 'b:false')
        if key == 'SIP_Timer_CSFB':
            return value is None or (isinstance(value, str) and re.match(r'\An:[0-9]{1,6}\Z', value) is not None)
        if key == 'Home_network_domain_name':
            if value in (None, ':'):
                return True
            return bool(unified and _overseas_profile_active() and isinstance(value, str) and value.startswith(':'))
        return value is None or (unified and value == 'json:[]')
    if path == IR92:
        if key == 'UsePreconditions':
            return value in (None, 'n:0', 'n:1')
        if key == 'SMS_Format':
            return value in (None, ':', ':3GPP', ':3GPP2')
        if key in ('amr_modeset_list', 'amrwb_modeset_list'):
            return value is None or (isinstance(value, str) and value.startswith(':'))
    return False


def init_journal(allow_known_empty_overlays=False):
    global j
    if os.path.isfile(JOURNAL):
        j = load(JOURNAL)
        assert j['owner'] == 'q10-unicom-volte-v1' and j['original_voice_policy'] == 0
        return
    assert not n.ims_pids(), 'Existing IMS instance; wait or stop the other experiment first'
    assert not os.path.lexists(XML) and not os.path.lexists(CFG_DIR), 'Existing IMS override'
    overlays = sorted(os.listdir(CDSC_OVERLAYS))
    if overlays:
        # Version-3 placeholders observed on stock carrier IDs 36/404 (and non-IMS
        # user data APN overlays on overseas carriers) have no IMS entries.
        assert (allow_known_empty_overlays and all(known_empty_cdsc_overlay(name) for name in overlays) and
                sorted(os.listdir(CDSC_OVERLAYS)) == overlays), 'Existing APN overlay'
    assert n.voice_policy() == 0, 'Initial modem policy is not the tested original00'
    assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}, 'Existing software crypto provider'
    assert not n.active_vpn_sessions(), 'Stop an existing VPN before initial installation'
    before = {}
    for path, updates in UPDATES.items():
        if path == IR92 and not os.path.isfile(IR92):
            continue
        attrs = n.attrs(n.read(path))
        before[path] = {key: attrs.get(key) for key in updates}
        for key, val in before[path].items():
            assert _valid_initial_pps_value(path, key, val, unified=allow_known_empty_overlays), (
                'Unexpected initial PPS value: ' + key)
    j = {'owner': 'q10-unicom-volte-v1', 'created_unix': time.time(), 'original_voice_policy': 0,
         'pps_before': before, 'known_vpn_uids': [], 'vpn_before_uids': [], 'native_pid': None,
         'managed_files': {}, 'restore_completed': True, 'owned_ims_routes': [],
         'ims_route_summary': {'status': 'idle', 'family': 'none', 'count': 0, 'verified': False}}
    save_journal()


def journal_sms_policy():
    """Add the new field to a restored legacy journal before any PPS mutation.

    UPDATES remains the pre-SMS fallback for old journals without pps_applied.
    An active old installation must be restored before its ownership expands.
    """
    key = 'SMS_Over_IP_Network_Indication'
    if key in j['pps_before'][IMS]:
        return
    assert j.get('restore_completed') is True, 'Restore legacy configuration before adding SMS policy'
    original = n.attrs(n.read(IMS)).get(key)
    assert original in (None, 'b:true', 'b:false'), 'Unexpected SMS policy type'
    j['pps_before'][IMS][key] = original
    save_journal()


def journal_extra_pps(updates, unified=True):
    """Snapshot newly owned optional IMS/IR92 fields into a restored journal."""
    if not updates or not j or 'pps_before' not in j:
        return
    changed = False
    for path, fields in updates.items():
        if path not in (IMS, IR92, CDSC, VOICE):
            continue
        missing = [key for key in fields if key not in j['pps_before'].get(path, {})]
        if not missing:
            continue
        assert j.get('restore_completed') is True, 'Restore previous configuration before expanding PPS ownership'
        attrs = n.attrs(n.read(path))
        bucket = j['pps_before'].setdefault(path, {})
        for key in missing:
            original = attrs.get(key)
            assert _valid_initial_pps_value(path, key, original, unified=unified), (
                'Unexpected initial PPS value: ' + key)
            bucket[key] = original
            changed = True
    if changed:
        save_journal()


def write_owned(path, data, mode, uid=None, gid=None):
    assert path == XML or path.startswith(RUNTIME + '/')
    expected = j['managed_files'].get(path)
    previous = j.get('pending_previous_file_hashes', {}).get(path)
    if os.path.exists(path):
        assert expected and n.digest(n.read(path)) in (expected, previous), 'Externally changed file: ' + path
    # Journal the intended bytes before the write so interrupted application is recoverable.
    j.setdefault('pending_previous_file_hashes', {})[path] = expected
    j['managed_files'][path] = n.digest(data)
    save_journal()
    n.atomic(path, data, mode)
    if uid is not None:
        os.chown(path, uid, gid)
    j['pending_previous_file_hashes'].pop(path, None)
    save_journal()


def apply_fields(path):
    current = n.attrs(n.read(path))
    updates = applied_updates()[path]
    for key, target in updates.items():
        assert current.get(key) in (j['pps_before'][path][key], target), 'Concurrent carrier change: ' + key
    n.update_pps(path, updates)
    actual = n.attrs(n.read(path))
    assert all(actual.get(k) == v for k, v in updates.items())


def crypto_command(option):
    assert n.digest(n.read(MODULE)) == n.HELPER_HASH
    n.command(['/proc/boot/pathtrust', '!' + MODULE])
    mount = next(p for p in ('/bin/mount', '/sbin/mount', '/proc/boot/mount') if os.path.isfile(p))
    n.command([mount, '-T', 'io-pkt', '-o', option, MODULE], 8)


def _is_ipv6_literal(text):
    core = text.split('%', 1)[0]
    if ':' not in core:
        return False
    try:
        socket.inet_pton(socket.AF_INET6, core)
        return True
    except (socket.error, ValueError, IOError, OSError):
        return False


def _redact_ipv6_token(match):
    prefix = match.group(1) or ''
    token = match.group(2)
    for keep, body in (('', prefix + token), (prefix, token)):
        if not body:
            continue
        if body.endswith(':') and _is_ipv6_literal(body[:-1]):
            return keep + '[redacted-ip]:'
        if _is_ipv6_literal(body):
            return keep + '[redacted-ip]'
    return match.group(0)


def redact_ims_event_line(line):
    """Strip URIs, Call-ID, IP literals and numeric subscriber IDs; retain VPN UID proof."""
    uids = re.findall(r'vpn_login response: uid= (' + n.UUID + ')', line)
    for index, uid in enumerate(uids):
        line = line.replace('vpn_login response: uid= ' + uid, 'vpn_login response: uid= __VPN_UID_%d__' % index)
    line = re.sub(r'(?i)\b(?:sips?|tel):[^\s>;,"\'()<>]+', '[redacted-uri]', line)
    line = re.sub(r'(?i)\b(Call-ID\s*:\s*)\S+', r'\1[redacted-call-id]', line)
    line = re.sub(r'(?i)\b(imsi|impi|impu|iccid|msisdn)(\s*[:=]\s*)\S+', r'\1\2[redacted-id]', line)
    line = re.sub(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?![\w.])', '[redacted-ip]', line)
    line = re.sub(r'\[[0-9a-fA-F:.]+(?:%[^\s\]]+)?\](?::\d{1,5})?', '[redacted-ip]', line)
    line = re.sub(
        r'(?<![0-9a-zA-Z_])([A-Za-z_][A-Za-z0-9_-]*:)?([0-9a-fA-F:]*:[0-9a-fA-F:]+(?:%[A-Za-z0-9_.-]+)?)(?![0-9a-zA-Z_])',
        _redact_ipv6_token, line)
    line = re.sub(r'(?<!\d)\+?\d{11,20}(?!\d)', '[redacted-id]', line)
    for index, uid in enumerate(uids):
        line = line.replace('vpn_login response: uid= __VPN_UID_%d__' % index, 'vpn_login response: uid= ' + uid)
    return line


def _validate_route_ip(text):
    """Canonicalize an IPv4/IPv6 host or gateway; reject loopback, link-local and USB."""
    if not isinstance(text, str):
        return None
    raw_text = text.strip()
    if not raw_text or len(raw_text) > 64 or '%' in raw_text or '/' in raw_text:
        return None
    if ':' not in raw_text:
        try:
            packed = socket.inet_pton(socket.AF_INET, raw_text)
        except (socket.error, ValueError, IOError, OSError):
            return None
        b0, b1 = packed[0], packed[1]
        if b0 in (0, 127) or (b0 == 169 and b1 == 254) or b0 >= 224:
            return None
        return 'ipv4', socket.inet_ntop(socket.AF_INET, packed)
    try:
        packed = socket.inet_pton(socket.AF_INET6, raw_text)
    except (socket.error, ValueError, IOError, OSError):
        return None
    if packed == b'\x00' * 16 or packed == b'\x00' * 15 + b'\x01':
        return None
    if packed[0] == 0xfe and (packed[1] & 0xc0) == 0x80:
        return None
    if packed[0] == 0xff:
        return None
    if packed[:12] == b'\x00' * 10 + b'\xff\xff':
        return None
    return 'ipv6', socket.inet_ntop(socket.AF_INET6, packed)


def _run_route(argv, timeout=5):
    """Run /sbin/route with bounded output; never raises on non-zero status."""
    try:
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            proc = subprocess.Popen(argv, stdout=out, stderr=err)
            deadline = time.time() + timeout
            while proc.poll() is None and time.time() < deadline:
                time.sleep(0.05)
            if proc.poll() is None:
                proc.kill()
                proc.wait()
                return -1, '', 'timeout'
            out.seek(0)
            err.seek(0)
            return (proc.returncode,
                    out.read(8192).decode('utf-8', 'replace'),
                    err.read(8192).decode('utf-8', 'replace'))
    except (IOError, OSError, ValueError):
        return -1, '', 'exec_error'


def _extract_ip_candidates(val):
    items = []
    if isinstance(val, list):
        items = val
    elif isinstance(val, str) and val:
        items = [part.strip() for part in val.split(',') if part.strip()]
    out = []
    for item in items:
        if not isinstance(item, str):
            continue
        cleaned = item.split('/', 1)[0].split('%', 1)[0].strip()
        parsed = _validate_route_ip(cleaned)
        if parsed is not None:
            out.append(parsed)
    return out


def _verify_local_bind(family, addr):
    if not hasattr(os, 'uname') or os.uname()[0] != 'QNX':
        return True
    sock = None
    try:
        af = socket.AF_INET6 if family == 'ipv6' else socket.AF_INET
        sock = socket.socket(af, socket.SOCK_DGRAM)
        sock.bind((addr, 0))
        return True
    except (socket.error, IOError, OSError):
        return False
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def _safe_pps_value(attrs, key):
    try:
        return True, n.value(attrs, key)
    except (ValueError, TypeError, AttributeError):
        return False, None


def live_cellular_gateways():
    """Return verified live cellular gateways/local IPs from active msm* interfaces.

    Returns (peer_gws, local_ips, incomplete). Any per-interface read or parse
    error sets incomplete=True without aborting subsequent msm* interfaces, and
    prevents stale-gateway sweeping on partial observations.
    """
    peer_gws = set()
    local_ips = set()
    incomplete = False
    try:
        if not os.path.isdir(NET_INTERFACES):
            return None, None, True
        names = sorted(os.listdir(NET_INTERFACES))
    except (IOError, OSError):
        return None, None, True
    for name in names:
        if not re.match(r'\Amsm[0-9]{1,3}\Z', name):
            continue
        path = NET_INTERFACES + '/' + name
        if os.path.islink(path):
            incomplete = True
            continue
        try:
            attrs = n.attrs(n.read(path))
        except (IOError, OSError, ValueError, TypeError):
            incomplete = True
            continue
        ok_type, if_type = _safe_pps_value(attrs, 'type')
        if not ok_type:
            incomplete = True
            continue
        if if_type not in (None, 'cellular', 'cellular_system'):
            continue
        ok_up, up_val = _safe_pps_value(attrs, 'up')
        ok_conn, conn_val = _safe_pps_value(attrs, 'connected')
        ok_v4, ip_ok = _safe_pps_value(attrs, 'ip_ok')
        ok_v6, ip6_ok = _safe_pps_value(attrs, 'ip6_ok')
        if not (ok_up and ok_conn and ok_v4 and ok_v6):
            incomplete = True
        if up_val is False or conn_val is False:
            continue
        if not any(flag is True for flag in (ip_ok, ip6_ok, up_val, conn_val)):
            continue
        for key in ('ip_gateway', 'ip6_gateway'):
            ok_field, val = _safe_pps_value(attrs, key)
            if not ok_field:
                incomplete = True
            else:
                peer_gws.update(_extract_ip_candidates(val))
        ok_addrs, addr_val = _safe_pps_value(attrs, 'ip_addresses')
        if not ok_addrs:
            incomplete = True
        else:
            local_ips.update(_extract_ip_candidates(addr_val))
    return peer_gws, local_ips, incomplete


def _route_summary(owned, status_name=None, verified=False):
    families = set(item['family'] for item in owned)
    if not families:
        family = 'none'
    elif len(families) > 1:
        family = 'dual'
    else:
        family = next(iter(families))
    if status_name is None:
        status_name = 'synced' if owned else 'idle'
    return {
        'status': status_name,
        'family': family,
        'count': len(owned),
        'verified': bool(verified or owned),
    }


def sync_ims_routes():
    """Execute P-CSCF host routes denied to non-root ims_rrm on active msm* interfaces."""
    global route_log_state
    if j is None or j.get('boot') != boot_token() or not j.get('native_pid'):
        return
    path = STATE + '/native.log'
    if not os.path.isfile(path) or os.path.islink(path):
        return
    try:
        st = os.stat(path)
    except (IOError, OSError):
        return
    if route_log_state.get('inode') != st.st_ino or st.st_size < route_log_state.get('offset', 0):
        route_log_state = {'inode': st.st_ino, 'offset': 0}
    owned = [dict(item) for item in (j.get('owned_ims_routes') or []) if isinstance(item, dict)]
    old_owned = [dict(item) for item in owned]
    old_summary = dict(j.get('ims_route_summary') or _route_summary(owned))
    ops = []
    if st.st_size > route_log_state['offset']:
        try:
            with open(path, 'rb') as stream:
                stream.seek(route_log_state['offset'])
                for unused in range(4):
                    remaining = st.st_size - route_log_state['offset']
                    if remaining <= 0:
                        break
                    chunk = stream.read(min(remaining, 262144))
                    if not chunk:
                        break
                    last_nl = chunk.rfind(b'\n')
                    if last_nl < 0:
                        break
                    route_log_state['offset'] += last_nl + 1
                    stream.seek(route_log_state['offset'])
                    text = chunk[:last_nl + 1].decode('utf-8', 'replace')
                    for line in text.splitlines():
                        found_add = ROUTE_ADD_RE.search(line)
                        if found_add:
                            host = _validate_route_ip(found_add.group(1))
                            gw = _validate_route_ip(found_add.group(2))
                            if host is not None and gw is not None and host[0] == gw[0] and host[1] != gw[1]:
                                ops.append(('add', host[0], host[1], gw[1]))
                            continue
                        found_del = ROUTE_DEL_RE.search(line)
                        if found_del:
                            host = _validate_route_ip(found_del.group(1))
                            if host is not None:
                                ops.append(('del', host[0], host[1], None))
        except (IOError, OSError):
            return
    if not ops and not owned:
        return
    peer_gws, local_ips, incomplete = live_cellular_gateways()
    status_name = old_summary.get('status', 'idle')
    verified_any = bool(old_summary.get('verified', False))
    route_available = os.path.isfile(ROUTE_BIN)
    # Sweep stale owned routes only when msm* interface observation is complete.
    if owned and not incomplete and peer_gws is not None and local_ips is not None:
        live_all = peer_gws | local_ips
        kept = []
        swept = False
        for entry in owned:
            key = (entry.get('family'), entry.get('gateway'))
            if key in live_all:
                kept.append(entry)
                continue
            valid = _validate_route_ip(entry.get('host', ''))
            if valid is None:
                swept = True
                continue
            if not route_available:
                kept.append(entry)
                status_name = 'unavailable'
                continue
            family_v, host_v = valid
            argv = [ROUTE_BIN, '-n', 'delete'] + (['-inet6'] if family_v == 'ipv6' else []) + ['-host', host_v]
            rc, out_txt, err_txt = _run_route(argv)
            if rc == 0 or 'not in table' in (out_txt + err_txt).lower():
                swept = True
            else:
                kept.append(entry)
                status_name = 'route_error'
        owned = kept
        if swept:
            status_name = 'synced' if owned else 'deleted'
    for kind, family, host, gw in ops:
        if not route_available:
            status_name = 'unavailable'
            break
        existing_idx = next((idx for idx, item in enumerate(owned)
                             if item['family'] == family and item['host'] == host), None)
        if kind == 'del':
            if existing_idx is None:
                continue
            argv = [ROUTE_BIN, '-n', 'delete'] + (['-inet6'] if family == 'ipv6' else []) + ['-host', host]
            rc, out_txt, err_txt = _run_route(argv)
            if rc == 0 or 'not in table' in (out_txt + err_txt).lower():
                owned.pop(existing_idx)
                status_name = 'synced' if owned else 'deleted'
            else:
                status_name = 'route_error'
            continue
        if peer_gws is None or local_ips is None:
            status_name = 'gateway_unverified'
            continue
        gw_key = (family, gw)
        if gw_key in peer_gws:
            gw_ok = True
        elif gw_key in local_ips:
            gw_ok = _verify_local_bind(family, gw)
        else:
            gw_ok = False
        if not gw_ok:
            if not owned:
                status_name = 'gateway_unverified'
            continue
        verified_any = True
        if existing_idx is not None:
            if owned[existing_idx]['gateway'] == gw:
                status_name = 'synced'
                continue
            del_argv = [ROUTE_BIN, '-n', 'delete'] + (['-inet6'] if family == 'ipv6' else []) + ['-host', host]
            d_rc, d_out, d_err = _run_route(del_argv)
            if not (d_rc == 0 or 'not in table' in (d_out + d_err).lower()):
                status_name = 'route_error'
                continue
            owned.pop(existing_idx)
        if len(owned) >= MAX_OWNED_ROUTES:
            continue
        add_argv = [ROUTE_BIN, '-n', 'add'] + (['-inet6'] if family == 'ipv6' else []) + ['-host', host, gw]
        rc, out_txt, err_txt = _run_route(add_argv)
        combined = (out_txt + ' ' + err_txt).lower()
        if rc == 0:
            owned.append({'family': family, 'host': host, 'gateway': gw})
            status_name = 'synced'
        elif 'file exists' in combined:
            if not owned:
                status_name = 'existing_kept'
        else:
            if not owned:
                status_name = 'route_error'
    new_summary = _route_summary(owned, status_name=status_name, verified=verified_any)
    if owned != old_owned or new_summary != old_summary:
        j['owned_ims_routes'] = owned
        j['ims_route_summary'] = new_summary
        save_journal()


def cleanup_ims_routes(current_boot=True):
    """Remove only host routes owned by this boot's IMS service."""
    global route_log_state
    route_log_state = {'inode': None, 'offset': 0}
    if j is None:
        return
    owned = [dict(item) for item in (j.get('owned_ims_routes') or []) if isinstance(item, dict)]
    if not owned and j.get('ims_route_summary') in (None, {'status': 'idle', 'family': 'none', 'count': 0, 'verified': False}):
        return
    if current_boot and owned and os.path.isfile(ROUTE_BIN):
        for entry in owned:
            valid = _validate_route_ip(entry.get('host', ''))
            if valid is None:
                continue
            family, host = valid
            argv = [ROUTE_BIN, '-n', 'delete'] + (['-inet6'] if family == 'ipv6' else []) + ['-host', host]
            _run_route(argv)
    j['owned_ims_routes'] = []
    j['ims_route_summary'] = {'status': 'idle', 'family': 'none', 'count': 0, 'verified': False}
    save_journal()


def public_route_summary(journal_data=None):
    """Export only sanitized route status fields; never expose raw IP addresses."""
    src = journal_data
    if src is None:
        if j is not None and j.get('boot') == boot_token():
            src = j
        elif os.path.isfile(JOURNAL):
            try:
                loaded = load(JOURNAL)
                if loaded.get('boot') == boot_token():
                    src = loaded
            except Exception:
                src = None
    raw = (src or {}).get('ims_route_summary') if isinstance(src, dict) else None
    if not isinstance(raw, dict):
        return {'pcscf_route_status': 'idle', 'pcscf_route_family': 'none',
                'pcscf_route_count': 0, 'pcscf_route_verified': False}
    status_val = raw.get('status')
    if status_val not in ('idle', 'synced', 'deleted', 'existing_kept', 'gateway_unverified', 'route_error', 'unavailable'):
        status_val = 'idle'
    family_val = raw.get('family')
    if family_val not in ('none', 'ipv4', 'ipv6', 'dual'):
        family_val = 'none'
    count_val = raw.get('count')
    if type(count_val) is not int or count_val < 0 or count_val > MAX_OWNED_ROUTES:
        count_val = 0
    return {
        'pcscf_route_status': status_val,
        'pcscf_route_family': family_val,
        'pcscf_route_count': count_val,
        'pcscf_route_verified': bool(raw.get('verified')),
    }


def collect_vpn_evidence():
    global event_seen
    known = set(j.get('known_vpn_uids', []))
    path = STATE + '/native.log'
    if os.path.isfile(path):
        stdout = n.read(path).decode('utf-8', 'replace')
        known.update(re.findall(r'^\s*uid \(string\) (' + n.UUID + r')\s*$', stdout, re.M))
    if j.get('native_pid') and j.get('boot') == boot_token():
        try:
            data = n.command(['/bin/slog2info', '-b', 'ims_rrm'], 8).decode('utf-8', 'replace')
        except (IOError, OSError, RuntimeError):
            data = ''
        prefix = 'ims_rrm.' + str(j['native_pid']) + ' '
        own = '\n'.join(line for line in data.splitlines() if prefix in line)
        known.update(re.findall(r'vpn_login response: uid= (' + n.UUID + ')', own))
        markers = ('vpn_new:', 'vpn_login response:', 'voice:', 'cellular RAT:',
                   'Domain is CS', 'incoming call is rejected', 'SIP/2.0 ', 'CSeq:',
                   'ImsPhoneIfDial', 'selectDomainVoice', 'onRegistrationSuccessful',
                   'MediaDialog', 'SDPState', 'RTPMediaSession', 'AudioMediaSession',
                   'ImsAudio', 'setAudioQuality', 'startAudio', 'stopAudio',
                   'UICCRequired', 'ISIM', 'no impu', 'not provisioned',
                   'aka auth', 'pcscf', 'P-CSCF', 'Domain name from UICC', 'REGISTER')
        events = [redact_ims_event_line(line) for line in own.splitlines() if any(m in line for m in markers)]
        fresh = [line for line in events if line not in event_seen]
        event_seen = set(events)
        if fresh:
            event_path = STATE + '/owned-ims-events.log'
            existing = n.read(event_path) if os.path.isfile(event_path) else b''
            combined = existing + ('\n'.join(fresh)+'\n').encode('utf-8')
            if len(combined) > 1048576:
                combined = combined[-524288:].split(b'\n', 1)[-1]
            n.atomic(event_path, combined)
    if known != set(j.get('known_vpn_uids', [])):
        j['known_vpn_uids'] = sorted(known)
        save_journal()
    try:
        sync_ims_routes()
    except Exception:
        pass  # Optional route sync never disrupts live IMS or VPN evidence.
    if os.path.isfile(path) and os.stat(path).st_size > 1048576:
        # Ownership was saved first. Keep one bounded private previous log;
        # O_APPEND on the child's descriptor permits truncation of this inode.
        n.atomic(STATE + '/native-previous.log', n.read(path)[-1048576:])
        with open(path, 'wb'):
            pass
        route_log_state['offset'] = 0


def cleanup_vpn():
    assert not n.ims_pids(), 'An IMS process still owns VPN resources'
    collect_vpn_evidence()
    known = set(j['known_vpn_uids'])
    original = set(j['vpn_before_uids'])
    assert not known & original
    for data in n.vpn_configs().values():
        for line in data.decode('utf-8').splitlines():
            obj = json.loads(line)
            uid = obj.get('uid')
            if uid not in known:
                continue  # Preserve all unrelated existing or subsequently added VPNs.
            assert obj.get('adapter') == 'ims' and obj.get('owner') == 'ims_rrm' and obj.get('server_type') == 'ims'
            assert re.match(r'^ims_[0-9]+$', obj.get('name', ''))
            n.vpn_delete(uid)
    assert not (set(x.decode('ascii') for x in n.vpn_ids(n.vpn_configs())) & known)


def stop_native():
    global child
    close_berry_indicator()
    pid = j.get('native_pid')
    if pid and j.get('boot') == boot_token() and pid in n.ims_pids():
        args = n.command(['/bin/pidin', '-p', str(pid), '-f', 'A']).decode('utf-8', 'replace')
        assert BIN in args, 'PID is not the owned executable'
        collect_vpn_evidence()
        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + 7
        while pid in n.ims_pids() and time.time() < deadline:
            time.sleep(0.25)
        if pid in n.ims_pids():
            os.kill(pid, signal.SIGKILL)
            deadline = time.time() + 5
            while pid in n.ims_pids() and time.time() < deadline:
                time.sleep(0.25)
        assert pid not in n.ims_pids(), 'Owned IMS did not stop'
    if child is not None:
        child.wait()
    collect_vpn_evidence()
    cleanup_vpn()
    try:
        cleanup_ims_routes(current_boot=(j.get('boot') == boot_token()))
    except Exception:
        pass
    j['native_pid'] = None
    save_journal()


def remove_owned(path):
    assert path == XML or path.startswith(RUNTIME + '/')
    expected = j['managed_files'].get(path)
    if os.path.exists(path):
        assert not os.path.islink(path)
        previous = j.get('pending_previous_file_hashes', {}).get(path)
        assert expected and n.digest(n.read(path)) in (expected, previous), 'Refuse to remove changed file: ' + path
        os.unlink(path)


def remove_platform():
    if os.path.exists(CFG):
        assert not os.path.islink(CFG_DIR) and not os.path.islink(CFG)
        assert set(os.listdir(CFG_DIR)) == {'ims'}
        # Nonpersistent PPS attributes disappear at reboot; our object remains.
        assert n.attrs(n.read(CFG)) in ({}, {'IMS_platform': ':common'})
        os.unlink(CFG)
        os.rmdir(CFG_DIR)


def restore():
    stop_native()
    applied_map = applied_updates()
    for path in (IMS, IR92, CDSC, VOICE):
        if path not in applied_map:
            continue
        current = n.attrs(n.read(path))
        updates = {}
        for key, applied in applied_map[path].items():
            original = j['pps_before'][path][key]
            assert current.get(key) in (applied, original), 'Refuse to overwrite concurrent carrier change'
            updates[key] = original
        n.update_pps(path, updates)
        assert all(n.attrs(n.read(path)).get(k) == v for k, v in updates.items())
    remove_owned(XML)
    remove_platform()
    policy = n.crypto_policy()
    if policy['swcr_id'] >= 0:
        assert j.get('crypto_boot') == boot_token() and policy['swcr_id'] == j.get('provider')
        assert not n.active_vpn_sessions(), 'A VPN remains active; keep software provider available'
        crypto_command('rollback=' + str(policy['swcr_id']))
    assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
    if n.voice_policy() != j['original_voice_policy']:
        assert set_voice_preference(4)['rc'] == 0
    time.sleep(1.2)
    assert n.voice_policy() == 0
    time.sleep(1.2)
    assert n.voice_policy() == 0
    if ACTIVE_PROFILE.get('lte_attach'):
        import telecom_attach
        telecom_attach.restore(sys.modules[__name__])
    j.update(restore_completed=True, provider=None, native_pid=None)
    save_journal()
    status('stopped')


def audio_tap_requested():
    path = BASE + '/audio-tap.json'
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            return False
        st = os.lstat(path)
        if st.st_uid != 0 or (st.st_mode & 0o077) != 0 or st.st_size > 4096:
            return False
        value = json.loads(n.read(path).decode('utf-8'))
        return isinstance(value, dict) and value.get('schema') == 1 and value.get('enabled') is True
    except Exception:
        return False


def configure():
    assert ready(), 'SIM/network changed after preflight; recheck compatibility'
    imsi = current_usim()
    network = compatibility.read_network(ACTIVE_PROFILE)
    assert profiles.identity_matches(imsi, network.get('mcc'), network.get('mnc')), 'SIM identity changed during configuration'
    template, carrier_xml = profiles.carrier_template(ACTIVE_PROFILE, network.get('mcc'), network.get('mnc'))
    updates = profile_updates(ACTIVE_PROFILE, network.get('mcc'), network.get('mnc'))
    if IR92 in updates and not os.path.isfile(IR92):
        updates = dict(updates)
        updates.pop(IR92, None)
    init_journal()
    journal_sms_policy()
    journal_extra_pps(updates, unified=(BASE != '/var/rootdata/q10_volte'))
    request_sha = profiles.fingerprint(ACTIVE_REQUEST)
    if not j.get('restore_completed') and j.get('profile_sha256') not in (None, request_sha):
        raise RuntimeError('Restore the previous profile before applying another configuration')
    assert not n.ims_pids(), 'An existing IMS instance must finish before activation'
    collect_vpn_evidence()  # Preserve proof from the previous run before replacing its stdout.
    cleanup_vpn()
    j.update(boot=boot_token(), native_pid=None, restore_completed=False, pps_applied=updates,
             profile_sha256=request_sha, carrier_template=template,
             vpn_before_uids=sorted(x.decode('ascii') for x in n.vpn_ids(n.vpn_configs())))
    save_journal()
    original = n.read('/radio/bin/ims_rrm')
    telecom_mo_ack = (network.get('mcc') == '460' and network.get('mnc') in profiles.TELECOM_MNCS and
                      bool(ACTIVE_PROFILE['ims']['sms']))
    extra = {'audio_tap': True} if (audio_tap_requested() and bool(ACTIVE_PROFILE['ims']['sms'])) else {}
    changed, patches = (temporary_binary(original, True, sms_ack=True, telecom_mo_ack=True, **extra)
                        if telecom_mo_ack else temporary_binary(original, True, sms_ack=True, **extra))
    write_owned(BIN, changed, 0o755)
    j['binary_patches'] = patches
    write_owned(APN, carrier_xml, 0o644)
    write_owned(RUNTIME + '/carrier/emergency.xml', n.read('/radio/etc/carrier/config/emergency.xml'), 0o644)
    if not os.path.exists(CFG_DIR):
        os.mkdir(CFG_DIR, 0o755)
        os.chmod(CFG_DIR, 0o755)
    assert not os.path.islink(CFG_DIR)
    if not os.path.exists(CFG):
        fd = os.open(CFG, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        os.close(fd)
    assert not os.path.islink(CFG) and set(os.listdir(CFG_DIR)) == {'ims'}
    assert n.attrs(n.read(CFG)) in ({}, {'IMS_platform': ':common'})
    n.update_pps(CFG, {'IMS_platform': ':common'})
    os.chmod(CFG, 0o644)
    assert n.attrs(n.read(CFG)) == {'IMS_platform': ':common'}
    impi = imsi + '@' + profiles.home_domain(ACTIVE_PROFILE, network['mcc'], network['mnc'])
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<ims><ImsConfig>'
           '<Impi>%s</Impi><Imsi>%s</Imsi><ImpuList><Impu>sip:%s</Impu></ImpuList>'
           '</ImsConfig></ims>\n' % (impi, imsi, impi)).encode('ascii')
    write_owned(XML, xml, 0o600, 453, 31)
    policy = n.voice_policy()
    assert policy in (0, 3), 'Unexpected modem policy'
    if policy == 0:
        assert set_voice_preference(1)['rc'] == 0
    assert n.voice_policy() == 3, 'IMS-preferred policy did not apply'
    apply_fields(VOICE)
    crypto = n.crypto_policy()
    if crypto['swcr_id'] == -1:
        assert crypto['crypto_support'] == 0 and not n.active_vpn_sessions()
        j.update(crypto_boot=boot_token(), provider_enable_attempted=True)
        save_journal()
        crypto_command('enable')
        j['provider'] = n.crypto_policy()['swcr_id']
        save_journal()
    else:
        assert j.get('crypto_boot') == boot_token() and crypto['swcr_id'] == j.get('provider'), 'Unowned crypto provider'
    assert 0 <= j['provider'] <= 127
    apply_fields(CDSC)
    if ACTIVE_PROFILE['ims'].get('always_on', True):
        wait_for_ims_apn(imsi)
    apply_fields(IMS)
    if IR92 in applied_updates():
        apply_fields(IR92)
    n.command(['/proc/boot/pathtrust', '!' + BIN])
    save_journal()


def phone_idle():
    # Both namespaces must be readable; absence is not proof of an idle phone.
    for path in ('/pps/services/phone/public/calls', '/pps/services/phone/private/calls'):
        if not os.path.isdir(path) or os.listdir(path):
            return False
    return True


def stock_exit_candidate():
    """Read-only proof for the tested stock instance's no-profile startup wait.

    Any missing/ambiguous evidence selects the original passive wait instead.
    A global REGISTER status may be stale across boots; use the current stock
    PID's no-profile log and disconnected public status, not that old value.
    """
    if stopping() or os.path.exists(BASE + '/conservative-start'):
        return None, 'conservative_or_stopping'
    if not os.path.isfile(BASE + '/enabled') or not os.path.isfile(JOURNAL):
        return None, 'not_an_enabled_reboot'
    previous = load(JOURNAL)
    if (previous.get('owner') != 'q10-unicom-volte-v1' or
            not previous.get('boot') or previous['boot'] == boot_token()):
        return None, 'not_a_previous_boot_journal'
    receipt = STATE + '/stock-handoff.json'
    if os.path.exists(receipt) and load(receipt).get('boot') == boot_token():
        return None, 'already_attempted_this_boot'
    identity = device_info.read_identity()
    if (not device_info.identify(identity)['hardware_tested'] or
            identity['os_version'] != device_info.OS_VERSION or
            not profiles.baseline_parameters(ACTIVE_PROFILE)):
        return None, 'outside_tested_baseline'
    pids = n.ims_pids()
    if len(pids) != 1:
        return None, 'no_unique_stock_process'
    pid = pids[0]
    arguments = n.command(['/bin/pidin', '-p', str(pid), '-f', 'A']).decode('ascii')
    rows = [line.strip().split() for line in arguments.splitlines() if line.strip()]
    expected = ['-U', '453:31,80,387,427,521,1001']
    if (len(rows) != 2 or rows[0] != ['Arguments'] or len(rows[1]) != 3 or
            posixpath.normpath(rows[1][0]) != '/radio/bin/ims_rrm' or rows[1][1:] != expected):
        return None, 'not_exact_stock_arguments'
    names = [line.strip() for line in n.command(
        ['/bin/pidin', '-p', str(pid), '-F', '%80N']).decode('ascii').splitlines() if line.strip()]
    if (len(names) != 2 or names[0] != 'name' or
            posixpath.normpath('/' + names[1].lstrip('/')) != '/radio/bin/ims_rrm'):
        return None, 'not_exact_stock_image'
    if not ready() or live().get('ims') != 'disconnected' or not phone_idle():
        return None, 'network_or_calls_not_idle'
    config = n.attrs(n.read(IMS))
    if any(n.value(config, key) not in (None, []) for key in ('IMS_profiles', 'IMS_profilesV2')):
        return None, 'carrier_profiles_present'
    if n.active_vpn_sessions():
        return None, 'active_vpn'
    text = n.command(['/bin/slog2info', '-b', 'ims_rrm'], 8).decode('utf-8', 'replace')
    prefix = 'ims_rrm.' + str(pid) + ' '
    own = '\n'.join(line for line in text.splitlines() if prefix in line)
    profiles_seen = re.findall(r'bb\.cfgmgr:\d+ imsProfiles= 0x([0-9a-fA-F]+)', own)
    if (not profiles_seen or int(profiles_seen[-1], 16) != 0 or
            'No IMS profiles provisioned .. waiting' not in own or
            'exit req but wait acl' in own or
            re.search(r'CSeq:\s*\d+\s+(?:REGISTER|INVITE)\b', own)):
        return None, 'no_current_idle_stock_evidence'
    return pid, 'verified_idle_stock'


def request_idle_stock_exit():
    """At most one SIGTERM per boot; never SIGKILL or a name-wide service stop."""
    global startup_handoff
    signalled = False
    try:
        pid, reason = stock_exit_candidate()
        startup_handoff = {'attempted': False, 'reason': reason}
        if pid is None:
            return False
        identity = current_usim()
        # Observe two separate idle snapshots, then revalidate the same PID,
        # carrier, calls, profile and log immediately before requesting exit.
        for unused in range(3):
            if stopping():
                return False
            time.sleep(1)
        second, reason = stock_exit_candidate()
        if second != pid or current_usim() != identity or stopping():
            startup_handoff['reason'] = 'changed_before_signal'
            return False
        if n.ims_pids() != [pid] or not phone_idle():
            startup_handoff['reason'] = 'changed_before_signal'
            return False
        # Persist the attempt before signalling; a manager restart must not
        # repeatedly terminate a replacement process in this boot.
        startup_handoff = {'attempted': True, 'reason': 'sigterm_requested',
                           'pid': pid, 'boot': boot_token(), 'requested_at': time.time()}
        n.atomic(STATE + '/stock-handoff.json', json.dumps(startup_handoff).encode('ascii'))
        os.kill(pid, signal.SIGTERM)
        signalled = True
        startup_timing['stock_exit_requested'] = time.time()
        startup_handoff['signal_delivered'] = True
        n.atomic(STATE + '/stock-handoff.json', json.dumps(startup_handoff).encode('ascii'))
        return True
    except Exception:
        # A failed observation or signal must not turn a working passive
        # startup into a configuration/restore failure.
        startup_handoff['reason'] = 'passive_wait_after_unavailable_evidence'
        return signalled


def prepare_connection():
    n.verify_stock()
    if ACTIVE_PROFILE.get('lte_attach'):
        import telecom_attach
        telecom_attach.ensure_lte(sys.modules[__name__])
    if not wait_for_network():
        return False
    requested = request_idle_stock_exit()
    quiet = [None]
    def stock_finished():
        if n.ims_pids():
            quiet[0] = None
            return False
        if not requested:
            return True
        if quiet[0] is None:
            quiet[0] = time.time()
        # Give a supervisor time to expose a replacement; it is never signalled.
        return time.time() - quiet[0] >= 3
    wait_until(stock_finished, ACTIVE_PROFILE['runtime']['existing_ims_wait_seconds'],
               'pre-existing native IMS instance', phase='waiting_for_native_ims')
    startup_timing['stock_finished'] = time.time()
    # The stock process can take several minutes to exit. Its initial LTE
    # snapshot is no longer enough to authorize carrier configuration.
    if not wait_for_network():
        return False
    status('configuring')
    configure()
    assert not n.ims_pids(), 'A new native IMS instance appeared during configuration'
    return True


class MonitorWaiter:
    """Read-only PPS subscriptions; unsupported/broken streams fall back safely.

    QNX full-mode subscriptions retain the latest object without a delta queue.
    Attribute filters avoid waking on unrelated radio counters. No object is
    created or modified. The 30 s guard also observes explicit stop/native exit.
    """
    WATCHES = (
        ('/pps/services/ims/status_public', ('status', 'default_ran')),
        ('/pps/services/ims/cellular/status_private', ('register_status',)),
        (RADIO, ('network_technology', 'power_status', 'network_service')),
        (DATA, ('internet',)),
        ('/pps/services/cellular/uicc/card0/status_private', ('uicc_state', 'hplmn')),
        ('/pps/services/cellular/uicc/card0/status_restricted', ('imsi',)),
    )

    def __init__(self):
        self.streams = {}
        try:
            import fcntl
            if os.uname()[0] != 'QNX':
                return
            for path, fields in self.WATCHES:
                fd = os.open(path + '?f=' + '+'.join(fields), os.O_RDONLY | os.O_NONBLOCK)
                self.streams[fd] = (fields, None)
                fcntl.fcntl(fd, fcntl.F_SETFD, fcntl.FD_CLOEXEC)
                self.streams[fd] = (fields, self.snapshot(fd, fields))
        except Exception:
            self.close()

    def snapshot(self, fd, fields):
        data = os.read(fd, 65536)
        # Deleted, truncated, unreadable or unexpectedly large objects are not
        # registration failures. Leave event mode instead of spinning on EOF.
        # Full-mode objects may carry qualifiers, e.g. the handset's radio
        # status uses [n]@status_public. Treat the qualifier like n.attrs().
        header = re.sub(br'^\[[^]]*\]', b'', data.split(b'\n', 1)[0])
        if not header.startswith(b'@') or len(data) >= 65536:
            raise ValueError('monitor_stream_unavailable')
        values = n.attrs(data)
        return tuple(values.get(name) for name in fields)

    def close(self):
        for fd in self.streams:
            try:
                os.close(fd)
            except (IOError, OSError):
                pass
        self.streams = {}

    def wait(self, seconds):
        if not self.streams:
            time.sleep(min(seconds, 30))
            return
        deadline = time.time() + seconds
        duplicate_events = 0
        try:
            while time.time() < deadline:
                if stopping() or (child is not None and child.poll() is not None):
                    return
                before = time.time()
                readable = select.select(list(self.streams), [], [], min(30, deadline - before))[0]
                changed = False
                for fd in readable:
                    fields, previous = self.streams[fd]
                    current = self.snapshot(fd, fields)
                    changed = changed or current != previous
                    self.streams[fd] = (fields, current)
                if changed:
                    # Coalesce a burst; never inspect faster than startup polling.
                    time.sleep(min(seconds, ACTIVE_PROFILE['runtime']['poll_seconds']))
                    return
                if time.time() < before:
                    return  # A wall-clock correction cannot extend this wait.
                if readable:
                    duplicate_events += 1
                    if duplicate_events >= 8:
                        raise ValueError('monitor_repeated_unchanged_events')
        except Exception:
            # Optional observation must not enter serve()'s configuration rollback.
            self.close()
            time.sleep(min(seconds, 30))


def monitor_native():
    """Preserve native IMS; only setup or an explicit/confirmed stop can restore."""
    connected_since, last_collect, previous_phase, previous_state = None, None, None, None
    fast_until = time.time() + 120
    was_steady, count = False, 0
    waiter = MonitorWaiter()
    try:
        while not stopping():
            if child.poll() is not None:
                # QNX may terminate IMS before delivering our shutdown signal.
                try:
                    collect_vpn_evidence()
                except Exception:
                    pass
                try:
                    status('native_exited', 'Native IMS exited; explicit stop restores configuration')
                except Exception:
                    pass
                return False
            try:
                state = live()
            except Exception:
                state = {}
            complete = all(state.get(key) is not None for key in
                           ('ims', 'register_status', 'ran', 'radio', 'power'))
            phase = ('running' if state.get('ims') == 'connected' and
                     state.get('register_status') == '200 OK' else
                     'registering' if complete else 'monitoring_unknown')
            now = time.time()
            lte_connected = (phase == 'running' and state.get('ran') in ('LTE', 'lte')
                             and state.get('radio') == ['lte'] and state.get('power') == 'ON')
            if not lte_connected:
                connected_since = None
            elif connected_since is None or now < connected_since:
                connected_since = now
            steady = connected_since is not None and now - connected_since >= 60
            if was_steady and not steady:
                fast_until = now + 60
            fast = not steady and now < fast_until
            interval = 10 * ACTIVE_PROFILE['runtime']['poll_seconds'] if fast else 300
            if (count in (0, 1, 2) or previous_phase != phase or previous_state != state or
                    (steady and not was_steady) or last_collect is None or
                    now < last_collect or now - last_collect >= interval):
                try:
                    collect_vpn_evidence()
                except Exception:
                    pass  # Diagnostic/display failures never tear down live IMS.
                last_collect = now
            elif fast and phase != 'running':
                try:
                    log_path = STATE + '/native.log'
                    if os.path.isfile(log_path) and os.stat(log_path).st_size != route_log_state.get('offset', 0):
                        sync_ims_routes()
                except Exception:
                    pass
            try:
                status(phase, observation=state)
            except Exception:
                pass  # A full disk or unreadable status receipt is not an IMS failure.
            # Native IMS handles re-registration itself. Prolonged unknown or
            # disconnected states also stop fast polling, without automatic retries.
            waiter.wait(ACTIVE_PROFILE['runtime']['poll_seconds'] if fast else 300)
            previous_phase, previous_state, was_steady = phase, state, steady
            count += 1
        return True
    finally:
        close_berry_indicator()
        waiter.close()


def claim_service_lock(atomic=False):
    token = boot_token()
    if os.path.exists(LOCK):
        old = load(LOCK)
        if old.get('boot') == token and alive(old['pid']):
            raise RuntimeError('Service is already running')
        if not atomic:
            os.unlink(LOCK)
    if atomic:
        n.atomic(LOCK, json.dumps({'pid': os.getpid(), 'boot': token}).encode('ascii'))
        return
    fd = os.open(LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(json.dumps({'pid': os.getpid(), 'boot': token}).encode('ascii'))


def serve():
    global child, shutdown, j
    startup_timing['manager_started'] = time.time()
    claim_service_lock()
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    def terminate(signum, frame):
        global shutdown
        shutdown = True
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        status('starting_handoff')
        if not prepare_connection():
            if os.path.exists(STOP) and j is not None and not shutdown:
                restore()
            return
        stdout_fd = os.open(STATE + '/native.log', os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_APPEND, 0o600)
        with os.fdopen(stdout_fd, 'wb') as output:
            child = subprocess.Popen([BIN, '-U', '453:31,80,387,427,521,1001'], stdout=output,
                                     stderr=subprocess.STDOUT)
        j['native_pid'] = child.pid
        save_journal()
        status('registering')
        if not monitor_native():
            return
        if os.path.exists(STOP):
            restore()
        else:
            # OS shutdown: avoid a radio-policy reload while the system is shutting down.
            status('suspended_for_shutdown')
    except Exception as error:
        n.atomic(STATE + '/last-error.txt', traceback.format_exc().encode('utf-8'))
        status('error', str(error))
        if j is not None and not shutdown:
            try:
                restore()
                status('error_restored', str(error))
            except Exception as cleanup_error:
                status('cleanup_required', str(cleanup_error))
    finally:
        close_berry_indicator()
        if os.path.exists(LOCK) and load(LOCK).get('pid') == os.getpid():
            os.unlink(LOCK)
        if os.path.exists(STOP):
            os.unlink(STOP)


def main():
    global ACTIVE_REQUEST, ACTIVE_PROFILE
    assert os.geteuid() == 0 and len(sys.argv) == 2
    action = sys.argv[1]
    if action == 'status':
        print(json.dumps(read_status()))
    elif action == 'start':
        ACTIVE_REQUEST = profiles.installed_request(BASE)
        ACTIVE_PROFILE = ACTIVE_REQUEST['profile']
        n.verify_stock()
        identity = device_info.read_identity()
        device = device_info.identify(identity)
        assert device['recognized'] and identity['os_version'] == device_info.OS_VERSION, 'Device/OS needs adaptation'
        if not device_info.provider_lifecycle_supported(device):
            raise RuntimeError('Passport provider lifecycle needs validation; see issue #1')
        if ACTIVE_PROFILE['runtime']['autostart'] and not compatibility.autostart_supported(device, ACTIVE_PROFILE):
            raise RuntimeError('Experimental combinations require autostart=false; see issue #1 boot report')
        assert (device['hardware_tested'] and profiles.baseline_parameters(ACTIVE_PROFILE)) or ACTIVE_REQUEST['allow_experimental'], 'Experimental opt-in is required'
        if os.path.isfile(LOCK):
            lock = load(LOCK)
            if lock.get('boot') == boot_token() and alive(lock['pid']):
                print(json.dumps({'already_running': True, 'pid': lock['pid']}))
                return
        if os.path.exists(STOP):
            os.unlink(STOP)
        pid = os.fork()
        if pid:
            print(json.dumps({'started_manager_pid': pid, 'independent_of_usb': True}))
            return
        os.setsid()
        null = os.open('/dev/null', os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(null, fd)
        if null > 2:
            os.close(null)
        try:
            serve()
        finally:
            os._exit(0)
    elif action == 'stop':
        ACTIVE_REQUEST = profiles.installed_request(BASE)
        ACTIVE_PROFILE = ACTIVE_REQUEST['profile']
        if not device_info.provider_lifecycle_supported(device_info.identify(device_info.read_identity())):
            raise RuntimeError('Provider lifecycle needs validation; preserve state and see issue #1')
        if os.path.isfile(LOCK) and load(LOCK).get('boot') == boot_token() and alive(load(LOCK)['pid']):
            n.atomic(STOP, b'explicit owner stop\n')
            print(json.dumps({'stop_requested': True}))
        else:
            global j
            if not os.path.isfile(JOURNAL):
                print(json.dumps({'not_started': True, 'configuration_unchanged': True}))
                return
            j = load(JOURNAL)
            n.verify_stock()
            restore()
            print(json.dumps({'restored': True}))
    elif action == 'check':
        req = profiles.installed_request(BASE)
        print(json.dumps(compatibility.probe(req['profile'], req['allow_experimental'])))
    else:
        raise SystemExit('Use start, stop, status or check')


if __name__ == '__main__':
    main()
