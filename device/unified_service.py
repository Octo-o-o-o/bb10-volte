"""Unified Q10/Classic/Passport runtime. One native IMS launch per normal boot.

SIM identity stays on the phone. A SIM change never restarts native IMS in the
same boot; the next normal boot selects a fresh profile without a desktop.
"""
import binascii
import ctypes
import json
import os
import posixpath
import re
import signal
import sys
import time
import native as n
import profiles
import device_info
import carrier_policy as policy
import ims_image
import service as s

if __name__ == '__main__':
    sys.modules['unified_service'] = sys.modules[__name__]

BASE = policy.BASE
BOOT = '/dev/shmem/bb10-unified-boot.json'
SELECTION = BASE + '/state/selection.json'
ATTEMPT = BASE + '/state/native-attempt.json'
selected = None
sim_missing_since = None
core_stopping = s.stopping
core_configure = s.configure
core_collect = s.collect_vpn_evidence


def save(path, value):
    n.atomic(path, profiles.canonical(value))


def boot_token(create=True):
    if not os.path.isfile(BOOT):
        if not create:
            return None
        fd = os.open(BOOT, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(profiles.canonical({'owner': policy.OWNER,
                'nonce': binascii.hexlify(os.urandom(24)).decode('ascii')}))
    value = s.load(BOOT)
    assert value['owner'] == policy.OWNER and re.match(r'\A[a-f0-9]{48}\Z', value['nonce'])
    return [policy.OWNER, value['nonce']]


def card():
    attrs = n.attrs(n.read('/pps/services/cellular/uicc/card0/status_private'))
    restricted = n.attrs(n.read('/pps/services/cellular/uicc/card0/status_restricted'))
    home = n.value(attrs, 'hplmn', {})
    return {'state': n.value(attrs, 'uicc_state', {}).get('state'), 'kind': n.value(attrs, 'uicc_type'),
            'mcc': home.get('mcc'), 'mnc': home.get('mnc'), 'imsi': str(n.value(restricted, 'imsi'))}


def verify():
    assert os.geteuid() == 0 and os.uname()[0] == 'QNX' and ctypes.sizeof(ctypes.c_void_p) == 4
    facts = device_info.read_identity()
    policy.model(facts)
    manifest = s.load(BASE + '/payload.json')
    assert manifest['owner'] == policy.OWNER and manifest['schema'] == 1
    assert set(manifest['files']) == set(PAYLOAD_FILES)
    for name, expected in manifest['files'].items():
        path = BASE + '/' + name
        assert not os.path.islink(path) and n.digest(n.read(path)) == expected, 'payload_changed'
    verify_native()
    assert n.digest(n.read(s.MODULE)) == n.HELPER_HASH
    receipt = s.load(BASE + '/desktop-backup-receipt.json')
    assert receipt['owner'] == policy.OWNER and receipt['all_original_hashes_verified'] is True
    assert receipt['backup_manifest_sha256'] == n.digest(n.read(BASE + '/backup/manifest.json'))
    return facts


PAYLOAD_FILES = ('device/native.py', 'device/profiles.py', 'device/device_info.py',
    'device/compatibility.py', 'device/service.py', 'device/ims_image.py', 'device/radio_api.py',
    'device/telecom_native.py', 'device/telecom_dca.py', 'device/carrier_policy.py',
    'device/unified_service.py', 'device/unified_dca.py', 'device/unified_install.py',
    'device/unified_migrate.py', 'device/unified_boot.sh', 'device/unified_operator_name.py',
    'device/unified_own_number.py',
    'driver/devnp-volte_swcrypto_probe.so')


def verify_native():
    from telecom_native import QCT_HASH
    expected = dict(n.STOCK_HASHES)
    expected['/radio/bin/qct_rrm'] = QCT_HASH
    expected['/usr/sbin/dca'] = '5ebafa9b5b0949090fda37c1b5e6083362bac1007f281d6f1900772aedc1ae06'
    for path, digest in expected.items():
        assert n.digest(n.read(path)) == digest, 'unknown_native_image'


def setup():
    for key, value in {'BASE': BASE, 'STATE': BASE + '/state', 'RUNTIME': BASE + '/runtime',
            'JOURNAL': BASE + '/state/journal.json', 'STATUS': BASE + '/state/status.json',
            'LOCK': BASE + '/state/lock.json', 'STOP': BASE + '/state/stop-request',
            'BIN': BASE + '/runtime/ims_rrm', 'MODULE': BASE + '/driver/devnp-volte_swcrypto_probe.so',
            'APN': BASE + '/runtime/carrier/36-ims.xml'}.items():
        setattr(s, key, value)
    s.boot_token, s.restore, s.prepare_connection = boot_token, restore, prepare
    s.stopping, s.configure = stopping, configure
    s.collect_vpn_evidence = collect
    s.live = live
    n.verify_stock = verify_native


def live():
    def at(path):
        try:
            return n.attrs(n.read(path))
        except OSError:
            return {}
    public = at('/pps/services/ims/status_public')
    private = at('/pps/services/ims/cellular/status_private')
    radio = at(s.RADIO)
    return {'ims': n.value(public, 'status'), 'register_status': n.value(private, 'register_status'),
            'ran': n.value(public, 'default_ran'), 'radio': n.value(radio, 'network_technology'),
            'power': n.value(radio, 'power_status')}


def idle_stock(pid):
    assert n.ims_pids() == [pid] and s.phone_idle() and not n.active_vpn_sessions()
    assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
    assert s.live()['ims'] in (None, 'idle', 'disconnected')
    attrs = n.attrs(n.read(s.IMS))
    assert all(n.value(attrs, key) in (None, []) for key in ('IMS_profiles', 'IMS_profilesV2'))
    rows = [line.strip().split() for line in n.command(
        ['/bin/pidin', '-p', str(pid), '-f', 'A']).decode('ascii').splitlines() if line.strip()]
    assert rows == [['Arguments'], ['/radio/bin/ims_rrm', '-U', '453:31,80,387,427,521,1001']]
    rows = [line.strip() for line in n.command(
        ['/bin/pidin', '-p', str(pid), '-F', '%80N']).decode('ascii').splitlines() if line.strip()]
    assert len(rows) == 2 and rows[0] == 'name' and posixpath.normpath('/' + rows[1].lstrip('/')) == '/radio/bin/ims_rrm'
    logs = n.command(['/bin/slog2info', '-b', 'ims_rrm'], 10).decode('utf-8', 'replace')
    own = '\n'.join(line for line in logs.splitlines() if 'ims_rrm.' + str(pid) + ' ' in line)
    assert 'No IMS profiles provisioned .. waiting' in own and 'exit req but wait acl' not in own
    assert not re.search(r'CSeq:\s*\d+\s+(?:REGISTER|INVITE)\b', own)


def handoff():
    """Only two current-PID idle proofs permit one SIGTERM, never SIGKILL."""
    record = BASE + '/state/stock-handoff.json'
    prior = s.load(record) if os.path.isfile(record) else {}
    deadline = time.time() + 330
    while n.ims_pids() and time.time() < deadline:
        assert not core_stopping(), 'stopped'
        if prior.get('boot') != boot_token():
            try:
                pids = n.ims_pids()
                assert len(pids) == 1
                idle_stock(pids[0])
                time.sleep(3)
                idle_stock(pids[0])
            except (AssertionError, OSError, ValueError):
                time.sleep(3)
                continue
            prior = {'boot': boot_token(), 'pid': pids[0], 'at': time.time()}
            save(record, prior)
            os.kill(pids[0], signal.SIGTERM)
        time.sleep(1)
    assert not n.ims_pids(), 'stock_ims_not_idle'
    time.sleep(3)
    assert not n.ims_pids(), 'stock_ims_reappeared'


def restore(previous_boot=False):
    """Keep software crypto registered until the OS clears it on normal reboot."""
    assert s.j is not None and s.phone_idle()
    assert s.j['owner'] == 'q10-unicom-volte-v1' and s.j['original_voice_policy'] == 0
    if previous_boot:
        assert s.j.get('boot') != boot_token()
        assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
        assert not n.ims_pids()
        # Never signal a PID recorded by an earlier boot, even if it is reused.
        s.j['native_pid'] = None
    else:
        assert s.j.get('boot') == boot_token()
    s.stop_native()
    for path, applied in s.applied_updates().items():
        assert path in (s.IMS, s.CDSC, s.VOICE,
            '/pps/services/carrier_config/ims/ir92', '/pps/services/ims/status_persistent')
        changes = policy.restore_fields(n.attrs(n.read(path)), s.j['pps_before'][path], applied)
        if changes:
            n.update_pps(path, changes)
        assert all(n.attrs(n.read(path)).get(k) == v for k, v in changes.items())
    s.remove_owned(s.XML)
    s.remove_platform()
    crypto = n.crypto_policy()
    if crypto['swcr_id'] >= 0:
        assert s.j.get('crypto_boot') == boot_token() and s.j.get('provider') == crypto['swcr_id']
    voice = n.voice_policy()
    if voice != 0:
        assert voice == 3 and s.set_voice_preference(4)['rc'] == 0
    for unused in range(2):
        time.sleep(1.2)
        assert n.voice_policy() == 0
    if s.BASE == BASE and not os.path.isfile(BASE + '/enabled'):
        import unified_dca
        unified_dca.restore_original()
    if s.BASE == BASE and selected is not None:
        try:
            import unified_operator_name
            unified_operator_name.restore(selected, boot_token())
        except Exception as error:
            save(BASE + '/state/operator-name-status.json', {'error_type': type(error).__name__})
        if not previous_boot:
            try:
                import unified_own_number
                unified_own_number.restore(n, boot_token(), s.current_usim())
            except Exception as error:
                save(BASE + '/state/own-number-status.json', {'error_type': type(error).__name__})
    s.j.update(native_pid=None, configuration_restored=True,
               restore_completed=crypto['swcr_id'] == -1,
               lifecycle='retain-provider-until-reboot',
               provider_retained_until_reboot=crypto['swcr_id'] >= 0)
    s.save_journal()
    s.status('reboot_required' if crypto['swcr_id'] >= 0 else 'stopped')


def reconcile():
    if not os.path.isfile(s.JOURNAL):
        return
    s.j = s.load(s.JOURNAL)
    assert s.j.get('boot') != boot_token(), 'reboot_required'
    restore(previous_boot=True)
    for path, expected in s.j['managed_files'].items():
        if path.startswith(s.RUNTIME + '/') and os.path.exists(path):
            assert not os.path.islink(path) and n.digest(n.read(path)) == expected
            os.unlink(path)
    archive = BASE + '/archive/journal-' + binascii.hexlify(os.urandom(8)).decode('ascii') + '.json'
    os.rename(s.JOURNAL, archive)
    s.j = None


def prepare():
    global selected
    facts = verify()
    attempt = s.load(ATTEMPT) if os.path.isfile(ATTEMPT) else None
    assert not attempt or attempt.get('boot') != boot_token(), 'reboot_required'
    assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}, 'reboot_required'
    handoff()
    import unified_migrate
    unified_migrate.finish_previous_boot()
    reconcile()
    deadline = time.time() + 300
    while time.time() < deadline:
        assert not core_stopping(), 'stopped'
        try:
            snapshot = card()
        except OSError:
            snapshot = {'state': None}
        if snapshot['state'] == 'READY':
            try:
                selected = policy.select(facts, snapshot)
            except ValueError:
                import unified_dca
                unified_dca.restore_original()
                s.status('unsupported_sim')
                return False
            break
        s.status('waiting_for_sim')
        time.sleep(3)
    assert selected is not None, 'sim_not_ready'
    previous = s.load(SELECTION) if os.path.isfile(SELECTION) else None
    assert policy.transition(previous, selected, boot_token(),
        n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}, attempt) != 'reboot_required', 'reboot_required'
    s.ACTIVE_REQUEST, s.ACTIVE_PROFILE = selected['request'], selected['request']['profile']
    template, unused_xml = profiles.carrier_template(s.ACTIVE_PROFILE, '460', s.ACTIVE_PROFILE['carrier']['mncs'][0])
    selected = policy.bind_template(selected, template)
    selected.update(boot=boot_token(), selected_unix=time.time())
    s.ACTIVE_REQUEST, s.ACTIVE_PROFILE = selected['request'], selected['request']['profile']
    s.UPDATES = s.profile_updates(s.ACTIVE_PROFILE, '460', s.ACTIVE_PROFILE['carrier']['mncs'][0])
    save(SELECTION, selected)
    s.temporary_binary = ims_image.mobile_binary if selected['operator'] == 'mobile' else ims_image.temporary_binary
    # Persist start intent before any modem/provider change. A crash cannot
    # trigger another native IMS attempt during this boot.
    save(ATTEMPT, {'owner': policy.OWNER, 'boot': boot_token(), 'at': time.time()})
    s.init_journal()
    s.j.update(boot=boot_token(), sim_sha256=selected['sim_sha256'], operator=selected['operator'])
    s.save_journal()
    import unified_dca
    if not unified_dca.prepare(selected):
        s.status('carrier_reboot_required')
        return False
    assert s.wait_for_network(), 'network_not_ready'
    assert policy.select(facts, card())['sim_sha256'] == selected['sim_sha256'], 'sim_changed'
    s.configure()
    assert not n.ims_pids()
    return True


def configure():
    core_configure()
    s.j.update(sim_sha256=selected['sim_sha256'], operator=selected['operator'],
               lifecycle='retain-provider-until-reboot')
    s.save_journal()


def collect():
    core_collect()
    if selected is None or not s.j or s.j.get('boot') != boot_token() or not s.j.get('native_pid'):
        return
    try:
        import unified_operator_name
        unified_operator_name.synchronize(selected, boot_token())
    except Exception as error:
        save(BASE + '/state/operator-name-status.json', {'error_type': type(error).__name__})
    current = live()
    if current['ims'] == 'connected' and current['register_status'] == '200 OK':
        try:
            import unified_own_number
            result = unified_own_number.synchronize(n, s.j['native_pid'], boot_token(), s.current_usim(),
                                                    selected['sim_sha256'])
        except Exception as error:
            result = {'error_type': type(error).__name__, 'actual_number_exported': False}
        save(BASE + '/state/own-number-status.json', result)


def stopping():
    global sim_missing_since
    if core_stopping():
        return True
    if selected is None or s.child is None:
        return False
    try:
        current = policy.select(device_info.read_identity(), card())
        changed = current['sim_sha256'] != selected['sim_sha256']
        sim_missing_since = None
    except (OSError, ValueError, TypeError):
        sim_missing_since = sim_missing_since or time.time()
        changed = time.time() - sim_missing_since >= 30
    if changed and s.phone_idle():
        n.atomic(s.STOP, b'SIM changed; next normal boot selects current SIM\n')
        return True
    return False


def public_status():
    verify()
    raw = s.read_status() if boot_token(False) is not None else {}
    value = {k: raw.get(k) for k in ('phase', 'enabled', 'manager_alive', 'native_alive',
                                    'status_from_current_boot', 'current')}
    value['enabled'] = os.path.isfile(BASE + '/enabled')
    value['variant'] = device_info.read_identity()['variant']
    value['automatic_carrier_selection'] = True
    value['normal_reboot_after_sim_change'] = True
    if os.path.isfile(SELECTION):
        saved = s.load(SELECTION)
        value['selected_operator'] = saved['operator']
        value['selected_this_boot'] = saved['boot'] == boot_token(False)
    return value


def launch():
    verify()
    assert os.path.isfile(BASE + '/enabled'), 'automatic_service_disabled'
    token = boot_token()
    migration = s.load(BASE + '/migration.json') if os.path.isfile(BASE + '/migration.json') else {}
    if migration.get('installed_boot') == token and not migration.get('completed'):
        return {'reboot_required': True}
    if os.path.isfile(s.LOCK):
        lock = s.load(s.LOCK)
        if lock.get('boot') == token and s.alive(lock['pid']):
            return {'already_running': True}
    if os.path.isfile(ATTEMPT) and s.load(ATTEMPT).get('boot') == token:
        return {'reboot_required': True}
    if os.path.exists(s.STOP):
        os.unlink(s.STOP)
    pid = os.fork()
    if pid:
        return {'started_manager_pid': pid, 'independent_of_usb': True}
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
    if action in ('boot', 'start'):
        result = launch()
    elif action == 'status':
        result = public_status()
    elif action == 'disable':
        verify()
        assert s.phone_idle(), 'call_active'
        if os.path.isfile(BASE + '/enabled'):
            os.unlink(BASE + '/enabled')
        n.atomic(s.STOP, b'disabled by owner\n')
        lock = s.load(s.LOCK) if os.path.isfile(s.LOCK) else {}
        active = lock.get('boot') == boot_token() and s.alive(lock['pid'])
        if not active and os.path.isfile(s.JOURNAL):
            s.j = s.load(s.JOURNAL)
            if s.j.get('boot') == boot_token():
                restore()
        result = {'disabled': True, 'reboot_required': True, 'restoration_pending': active}
    elif action == 'enable':
        verify()
        n.atomic(BASE + '/enabled', b'automatic SIM selection re-enabled by owner\n')
        result = {'enabled': True, 'reboot_required': True}
    else:
        raise ValueError('unknown_action')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
