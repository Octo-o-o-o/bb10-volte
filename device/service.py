"""Phone-managed BB10 VoLTE service, with an owned journal and explicit stop.

No phone calls are initiated. Stock executable files are never overwritten.
Python 3.2 compatible; intended only for the exact native hashes in native.py.
"""
import json
import os
import re
import signal
import subprocess
import sys
import time
import traceback

import native as n
import compatibility
import profiles
import device_info
from ims_image import temporary_binary
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
VOICE = '/pps/services/carrier_config/radio_common/cellular_protocol_configuration'
CDSC = '/pps/services/cds/cnice/status_persistent'
RADIO = '/pps/services/cellular/radioctrl/status_public'
DATA = '/pps/services/cds/cnice/status'
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
event_seen = set()
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
    except OSError:
        return False


def live():
    public = n.attrs(n.read('/pps/services/ims/status_public'))
    engine = n.attrs(n.read('/pps/services/ims/cellular/status_private'))
    radio = n.attrs(n.read(RADIO))
    return {'ims': n.value(public, 'status'), 'register_status': n.value(engine, 'register_status'),
            'ran': n.value(public, 'default_ran'), 'radio': n.value(radio, 'network_technology'),
            'power': n.value(radio, 'power_status')}


def status(phase, error=None, details=None):
    result = {'phase': phase, 'at': time.time(), 'manager_pid': os.getpid(),
              'native_pid': j.get('native_pid') if j else None, 'error': error,
              'boot': boot_token(),
              'ims_observation_scope': 'owned_native' if phase in ('running', 'registering')
              and j and j.get('native_pid') else 'system_status_only'}
    if details is not None:
        result['startup_wait'] = details
    try:
        result.update(live())
    except Exception:
        result['native_status_unavailable'] = True
    n.atomic(STATUS, json.dumps(result, indent=2).encode('ascii'))


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
    assert kind & 2 and not kind & 16, 'Only the verified USIM-without-ISIM route is supported'
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
    return {VOICE: {'voice_domain_preference_EUTRAN': 'n:3'},
            IMS: {'IMS_profilesV2': 'json:["IR92"]', 'supported_networks': 'json:["LTE"]',
                  'IMS_services': 'json:' + json.dumps(services, separators=(',', ':')),
                  'Home_network_domain_name': ':' + profiles.home_domain(profile, mcc, mnc)},
            CDSC: {'cdsc_xml': ':' + APN}}


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
            if (sim_ready and network.get('radio_on') and network.get('lte') and
                    item.get('apn') == ACTIVE_PROFILE['ims']['apn'] and item.get('connected') is True):
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


def init_journal():
    global j
    if os.path.isfile(JOURNAL):
        j = load(JOURNAL)
        assert j['owner'] == 'q10-unicom-volte-v1' and j['original_voice_policy'] == 0
        return
    assert not n.ims_pids(), 'Existing IMS instance; wait or stop the other experiment first'
    assert not os.path.lexists(XML) and not os.path.lexists(CFG_DIR), 'Existing IMS override'
    assert not os.listdir('/var/radio/cdsc'), 'Existing APN overlay'
    assert n.voice_policy() == 0, 'Initial modem policy is not the tested original00'
    assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}, 'Existing software crypto provider'
    assert not n.active_vpn_sessions(), 'Stop an existing VPN before initial installation'
    before = {path: {key: n.attrs(n.read(path)).get(key) for key in updates} for path, updates in UPDATES.items()}
    assert before[CDSC]['cdsc_xml'] == ':'
    assert before[VOICE]['voice_domain_preference_EUTRAN'] is None
    assert all(v is None for k, v in before[IMS].items() if k != 'Home_network_domain_name')
    assert before[IMS]['Home_network_domain_name'] in (None, ':')
    j = {'owner': 'q10-unicom-volte-v1', 'created_unix': time.time(), 'original_voice_policy': 0,
         'pps_before': before, 'known_vpn_uids': [], 'vpn_before_uids': [], 'native_pid': None,
         'managed_files': {}, 'restore_completed': True}
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


def collect_vpn_evidence():
    global event_seen
    known = set(j.get('known_vpn_uids', []))
    path = STATE + '/native.log'
    if os.path.isfile(path):
        stdout = n.read(path).decode('utf-8', 'replace')
        known.update(re.findall(r'^\s*uid \(string\) (' + n.UUID + r')\s*$', stdout, re.M))
    if j.get('native_pid') and j.get('boot') == boot_token():
        data = subprocess.check_output(['/bin/slog2info', '-b', 'ims_rrm']).decode('utf-8', 'replace')
        prefix = 'ims_rrm.' + str(j['native_pid']) + ' '
        own = '\n'.join(line for line in data.splitlines() if prefix in line)
        known.update(re.findall(r'vpn_login response: uid= (' + n.UUID + ')', own))
        markers = ('vpn_new:', 'vpn_login response:', 'voice:', 'cellular RAT:',
                   'Domain is CS', 'incoming call is rejected', 'SIP/2.0 ', 'CSeq:',
                   'ImsPhoneIfDial', 'selectDomainVoice', 'onRegistrationSuccessful')
        events = [line for line in own.splitlines() if any(m in line for m in markers)]
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
    if os.path.isfile(path) and os.stat(path).st_size > 1048576:
        # Ownership was saved first. Keep one bounded private previous log;
        # O_APPEND on the child's descriptor permits truncation of this inode.
        n.atomic(STATE + '/native-previous.log', n.read(path)[-1048576:])
        with open(path, 'wb'):
            pass


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
    for path in (IMS, CDSC, VOICE):
        current = n.attrs(n.read(path))
        updates = {}
        for key, applied in applied_updates()[path].items():
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
    j.update(restore_completed=True, provider=None, native_pid=None)
    save_journal()
    status('stopped')


def configure():
    assert ready(), 'SIM/network changed after preflight; recheck compatibility'
    imsi = current_usim()
    network = compatibility.read_network(ACTIVE_PROFILE)
    assert profiles.identity_matches(imsi, network.get('mcc'), network.get('mnc')), 'SIM identity changed during configuration'
    template, carrier_xml = profiles.carrier_template(ACTIVE_PROFILE, network.get('mcc'), network.get('mnc'))
    updates = profile_updates(ACTIVE_PROFILE, network.get('mcc'), network.get('mnc'))
    init_journal()
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
    changed, patches = temporary_binary(original, True)
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
    wait_for_ims_apn(imsi)
    apply_fields(IMS)
    n.command(['/proc/boot/pathtrust', '!' + BIN])
    save_journal()


def prepare_connection():
    n.verify_stock()
    if not wait_for_network():
        return False
    wait_until(lambda: not n.ims_pids(), ACTIVE_PROFILE['runtime']['existing_ims_wait_seconds'],
               'pre-existing native IMS instance', phase='waiting_for_native_ims')
    # The stock process can take several minutes to exit. Its initial LTE
    # snapshot is no longer enough to authorize carrier configuration.
    if not wait_for_network():
        return False
    status('configuring')
    configure()
    assert not n.ims_pids(), 'A new native IMS instance appeared during configuration'
    return True


def serve():
    global child, shutdown, j
    token = boot_token()
    if os.path.exists(LOCK):
        old = load(LOCK)
        if old.get('boot') == token and alive(old['pid']):
            raise RuntimeError('Service is already running')
        os.unlink(LOCK)
    fd = os.open(LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(json.dumps({'pid': os.getpid(), 'boot': token}).encode('ascii'))
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    def terminate(signum, frame):
        global shutdown
        shutdown = True
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        if not prepare_connection():
            return
        stdout_fd = os.open(STATE + '/native.log', os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_APPEND, 0o600)
        with os.fdopen(stdout_fd, 'wb') as output:
            child = subprocess.Popen([BIN, '-U', '453:31,80,387,427,521,1001'], stdout=output,
                                     stderr=subprocess.STDOUT)
        j['native_pid'] = child.pid
        save_journal()
        status('registering')
        count = 0
        while not stopping():
            if child.poll() is not None:
                # QNX may terminate IMS before delivering our shutdown signal.
                # Preserve the journal instead of reloading the modem mid-shutdown.
                try:
                    collect_vpn_evidence()
                except Exception:
                    pass
                status('native_exited', 'Native IMS exited; explicit stop restores configuration')
                return
            if count in (1, 2) or count % 10 == 0:
                collect_vpn_evidence()
            state = live()
            status('running' if state['ims'] == 'connected' and state['register_status'] == '200 OK' else 'registering')
            # LTE loss is handled by the native IMS state machine; never toggle radio here.
            time.sleep(ACTIVE_PROFILE['runtime']['poll_seconds'])
            count += 1
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
