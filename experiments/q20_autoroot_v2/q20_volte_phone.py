"""Device-specific Classic/AutoRoot-v2 VoLTE lifecycle. Python 3.2.

Reuses the hash-pinned native implementation. A volatile private boot cookie
replaces v4's absent root.done marker; it does not impersonate that marker.
Software crypto is retained until reboot instead of unregistering a provider.
"""
import binascii
import ctypes
import hashlib
import json
import os
import signal
import sys
import time

BASE = '/var/q20_volte'
BOOT = '/dev/shmem/q20-volte-boot.json'
sys.path.insert(0, BASE + '/device')
import native as n
import profiles
import device_info
import compatibility as c
import service as s


def verify():
    assert os.geteuid() == 0 and os.uname()[0] == 'QNX' and ctypes.sizeof(ctypes.c_void_p) == 4
    facts = device_info.read_identity()
    assert facts['variant'] == 'SQC100-2' and facts['board_type'] == 'CLASSICATT'
    assert facts['os_version'] == '10.3.3.3216'
    manifest = s.load(BASE + '/payload-manifest.json')
    assert manifest['owner'] == 'q20-sqc100-2-volte-v1'
    for name, digest in manifest['files'].items():
        assert '..' not in name and not os.path.islink(BASE + '/' + name)
        assert n.digest(n.read(BASE + '/' + name)) == digest, 'Q20 payload changed'
    for path, digest in n.STOCK_HASHES.items():
        assert n.digest(n.read(path)) == digest, 'Unknown native build: ' + path
    assert n.digest(n.read(s.MODULE)) == n.HELPER_HASH
    return facts


def boot_token(create=True):
    if not os.path.isfile(BOOT):
        assert create, 'Q20 service has not started in this boot'
        record = {'owner': 'q20-volte-boot-v1', 'nonce': binascii.hexlify(os.urandom(24)).decode('ascii'),
                  'created_unix': time.time()}
        fd = os.open(BOOT, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(json.dumps(record).encode('ascii'))
    record = s.load(BOOT)
    assert record['owner'] == 'q20-volte-boot-v1' and len(record['nonce']) == 48
    return ['q20-volte-boot-v1', record['nonce']]


def live():
    def at(path):
        return n.attrs(n.read(path)) if os.path.isfile(path) else {}
    public = at('/pps/services/ims/status_public')
    private = at('/pps/services/ims/cellular/status_private')
    radio = at(s.RADIO)
    return {'ims': n.value(public, 'status'), 'register_status': n.value(private, 'register_status'),
            'ran': n.value(public, 'default_ran'), 'radio': n.value(radio, 'network_technology'),
            'power': n.value(radio, 'power_status')}


def recover_runtime_ownership():
    """Recover exact old runtime hashes after a completed carrier epoch."""
    managed = s.j.setdefault('managed_files', {})
    archive = BASE + '/archive'
    for path in (s.BIN, s.APN, s.RUNTIME + '/carrier/emergency.xml'):
        if not os.path.exists(path) or path in managed:
            continue
        assert not os.path.islink(path)
        actual = n.digest(n.read(path))
        proof = None
        for name in sorted(os.listdir(archive) if os.path.isdir(archive) else [], reverse=True):
            candidate = archive + '/' + name + '/journal-original.json'
            if not os.path.isfile(candidate) or os.path.islink(candidate):
                continue
            previous = s.load(candidate)
            if (previous.get('owner') == 'q10-unicom-volte-v1' and previous.get('original_voice_policy') == 0
                    and previous.get('native_pid') is None
                    and (previous.get('configuration_restored') is True or previous.get('restore_completed') is True)
                    and previous.get('managed_files', {}).get(path) == actual):
                proof = name
                break
        assert proof is not None, 'Unowned existing runtime file: ' + path
        managed[path] = actual
        s.j.setdefault('runtime_ownership_from_archive', {})[path] = proof
    s.save_journal()


def restore_configuration():
    """Restore owned phone configuration while retaining the owned provider."""
    assert s.j is not None and s.j.get('boot') == boot_token()
    assert s.phone_idle(), 'Call active; defer restoration until idle'
    s.stop_native()
    for path in (s.IMS, s.CDSC, s.VOICE):
        current = n.attrs(n.read(path))
        updates = {}
        for key, applied in s.applied_updates()[path].items():
            original = s.j['pps_before'][path][key]
            assert current.get(key) in (applied, original), 'Concurrent carrier change'
            updates[key] = original
        n.update_pps(path, updates)
        assert all(n.attrs(n.read(path)).get(key) == value for key, value in updates.items())
    s.remove_owned(s.XML)
    s.remove_platform()
    crypto = n.crypto_policy()
    if crypto['swcr_id'] >= 0:
        assert s.j.get('crypto_boot') == boot_token() and crypto['swcr_id'] == s.j.get('provider')
    if n.voice_policy() != s.j['original_voice_policy']:
        assert n.voice_policy() == 3 and s.set_voice_preference(4)['rc'] == 0
    for unused in range(2):
        time.sleep(1.2)
        assert n.voice_policy() == 0
    if s.ACTIVE_PROFILE['carrier']['mncs'] == ['11']:
        import q20_telecom_carrier as telecom
        telecom.restore(sys.modules[__name__])
    s.j.update(configuration_restored=True, restore_completed=crypto['swcr_id'] == -1,
               provider_retained_until_reboot=crypto['swcr_id'] >= 0, native_pid=None,
               lifecycle='retain-provider-until-reboot')
    s.save_journal()
    s.status('configuration_restored_reboot_required' if crypto['swcr_id'] >= 0 else 'stopped')


def setup():
    for key, value in {'BASE': BASE, 'STATE': BASE + '/state', 'RUNTIME': BASE + '/runtime',
            'JOURNAL': BASE + '/state/journal.json', 'STATUS': BASE + '/state/status.json',
            'LOCK': BASE + '/state/lock.json', 'STOP': BASE + '/state/stop-request',
            'BIN': BASE + '/runtime/ims_rrm', 'MODULE': BASE + '/driver/devnp-volte_swcrypto_probe.so',
            'APN': BASE + '/runtime/carrier/36-ims.xml'}.items():
        setattr(s, key, value)
    s.ACTIVE_REQUEST = profiles.load_request(BASE + '/profile-request.json')
    s.ACTIVE_PROFILE = s.ACTIVE_REQUEST['profile']
    assert s.ACTIVE_REQUEST['allow_experimental'] is True
    assert s.ACTIVE_PROFILE['runtime']['autostart'] is False
    carrier = s.ACTIVE_PROFILE['carrier']
    families = {'01': ('unicom', ('3gnet',)), '09': ('unicom', ('3gnet',)),
                '00': ('mobile', ('cmnet',)), '02': ('mobile', ('cmnet',)), '07': ('mobile', ('cmnet',)),
                '03': ('telecom', ('ctnet', 'ctlte')), '05': ('telecom', ('ctnet', 'ctlte')),
                '11': ('telecom', ('ctnet', 'ctlte'))}
    assert carrier['mcc'] == '460' and len(carrier['mncs']) == 1
    mnc = carrier['mncs'][0]
    assert mnc in families
    family, allowed_apns = families[mnc]
    assert s.ACTIVE_PROFILE['id'] == 'q20-sqc100-2-' + family + '-460' + mnc
    assert carrier['data_apns'] and set(carrier['data_apns']).issubset(set(allowed_apns))
    s.UPDATES = s.profile_updates(s.ACTIVE_PROFILE, '460', mnc)
    s.boot_token, s.live, s.restore = boot_token, live, restore_configuration
    n.verify_stock = verify
    original_init_journal = s.init_journal
    def init_journal():
        original_init_journal()
        recover_runtime_ownership()
    s.init_journal = init_journal
    if mnc == '11':
        import q20_telecom_carrier as telecom
        original_prepare = s.prepare_connection
        def prepare_connection():
            telecom.ensure_lte(sys.modules[__name__])
            return original_prepare()
        s.prepare_connection = prepare_connection
    import q20_own_number_auto as display
    original_configure = s.configure
    original_collect = s.collect_vpn_evidence
    def configure():
        imsi = s.current_usim()
        original_configure()
        assert s.current_usim() == imsi
        s.j['configured_sim_fingerprint'] = hashlib.sha256(imsi.encode('ascii')).hexdigest()
        s.save_journal()
    def collect():
        original_collect()
        if os.path.exists(s.STOP):
            return
        if not s.j or s.j.get('boot') != boot_token() or not s.j.get('native_pid'):
            return
        current = live()
        if current.get('ims') != 'connected' or current.get('register_status') != '200 OK':
            return
        try:
            result = display.synchronize(n, s.j['native_pid'], boot_token(), s.current_usim(),
                                         s.j.get('configured_sim_fingerprint'))
        except Exception as error:
            result = {'display_updated': False, 'error_type': type(error).__name__,
                      'actual_number_exported': False}
        n.atomic(s.STATE + '/own-number-status.json', json.dumps(result).encode('ascii'))
    s.configure, s.collect_vpn_evidence = configure, collect


def precheck():
    verify()
    assert s.phone_idle() and not n.ims_pids() and not n.active_vpn_sessions()
    assert n.voice_policy() == 0 and n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
    assert all(c.configuration_diagnostics().values())
    telecom_bootstrap = None
    if s.ACTIVE_PROFILE['carrier']['mncs'] == ['11']:
        import q20_telecom_carrier as telecom
        telecom_bootstrap = telecom.preflight(sys.modules[__name__])
    else:
        assert s.ready()
    assert not os.path.lexists('/var/rootdata/q10_volte')
    return {'precheck_passed': True, 'identity': device_info.read_identity(),
            'network': c.read_network(s.ACTIVE_PROFILE), 'native_hashes_match': True,
            'profile_sha256': profiles.fingerprint(s.ACTIVE_REQUEST),
            'provider_lifecycle': 'retain-provider-until-reboot', 'automatic_start_enabled': False,
            'telecom_bootstrap': telecom_bootstrap}


def status():
    verify()
    if not os.path.isfile(BOOT):
        return {'phase': 'not_started_this_boot', 'manager_alive': False, 'native_alive': False,
                'enabled': os.path.isfile(BASE + '/enabled'), 'current': live()}
    raw = s.read_status()
    result = {key: raw.get(key) for key in ('phase', 'at', 'manager_pid', 'native_pid', 'boot',
                  'enabled', 'manager_alive', 'native_alive', 'status_from_current_boot',
                  'current', 'startup_timing', 'stock_handoff', 'ims_observation_scope', 'error')}
    result['registered'] = (result.get('phase') == 'running' and result.get('manager_alive') is True
        and result.get('native_alive') is True and result['current'].get('ims') == 'connected'
        and result['current'].get('register_status') == '200 OK' and result['current'].get('radio') == ['lte'])
    return result


def launch(automatic=False):
    verify()
    if automatic:
        assert os.path.isfile(BASE + '/enabled')
        receipt = s.load(BASE + '/state/manual-call-acceptance.json')
        assert receipt['owner'] == 'q20-call-acceptance-v1' and receipt['variant'] == 'SQC100-2'
        assert receipt['profile_sha256'] == profiles.fingerprint(s.ACTIVE_REQUEST)
        assert all(receipt[key] is True for key in
                   ('incoming', 'outgoing', 'audio_both_directions', 'lte', 'sip_dialogs_verified'))
    else:
        precheck()
    boot_token()
    if os.path.isfile(s.LOCK):
        lock = s.load(s.LOCK)
        if lock.get('boot') == boot_token() and s.alive(lock['pid']):
            return {'already_running': True, 'manager_pid': lock['pid']}
    if os.path.exists(s.STOP):
        os.unlink(s.STOP)
    launch_record = {'boot': boot_token(), 'at': time.time(),
                     'source': 'root-v2-boot-hook' if automatic else 'desktop-manual',
                     'profile_sha256': profiles.fingerprint(s.ACTIVE_REQUEST)}
    n.atomic(s.STATE + '/last-launch.json', json.dumps(launch_record).encode('ascii'))
    pid = os.fork()
    if pid:
        return {'started_manager_pid': pid, 'independent_of_usb': True, 'automatic': automatic}
    os.setsid()
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    null = os.open('/dev/null', os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(null, fd)
    if null > 2:
        os.close(null)
    os.umask(0o077)
    try:
        s.serve()
    finally:
        os._exit(0)


def main():
    setup()
    action = sys.argv[1]
    if action == 'precheck':
        result = precheck()
    elif action in ('launch', 'boot'):
        result = launch(action == 'boot')
    elif action == 'status':
        result = status()
    elif action == 'stop':
        verify()
        assert s.phone_idle()
        if os.path.isfile(s.LOCK) and s.load(s.LOCK).get('boot') == boot_token() and s.alive(s.load(s.LOCK)['pid']):
            n.atomic(s.STOP, b'owner requested Q20 stop\n')
            result = {'stop_requested': True}
        else:
            s.j = s.load(s.JOURNAL)
            restore_configuration()
            result = {'configuration_restored': True, 'provider_retained_until_reboot': True}
    else:
        raise SystemExit('Use precheck, launch, boot, status or stop')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
