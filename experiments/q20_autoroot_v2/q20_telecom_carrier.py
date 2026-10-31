"""Q20/460-11 bootstrap proved by native UE1 + voice3 + modem reload.

Called by the Q20 wrapper only; retains the core engine's LTE/data gate.
Source originals and the original UE0/voice0 policies remain recoverable.
"""
import hashlib
import json
import os
import posixpath
import re
import signal
import time

OWNER = 'q20-telecom-carrier-v1'
QCT_HASH = '71835f701affcb9254eadb4ee299e8f7d07547543b3e0f61519456b8241dcb3b'


def selected(q):
    carrier = q.s.ACTIVE_PROFILE['carrier']
    return carrier['mcc'] == '460' and carrier['mncs'] == ['11']


def dca(q):
    import q20_telecom_dca_usage_phone as module
    module.q = q
    return module


def load_plan(q):
    assert selected(q) and q.n.digest(q.n.read('/radio/bin/qct_rrm')) == QCT_HASH
    module = dca(q)
    folder, value = module.plan()
    receipt = q.s.load(folder + '/desktop-backup-receipt.json')
    assert receipt['owner'] == module.OWNER and receipt['all_original_hashes_verified'] is True
    assert receipt['plan_sha256'] == q.n.digest(q.n.read(folder + '/plan.json'))
    assert q.n.digest(q.n.read('/usr/sbin/dca')) == value['dca_sha256']
    for name in module.SOURCES:
        item = value['files'][name]
        original = q.n.read(folder + '/' + name + '.original')
        assert q.n.digest(original) == item['original_sha256']
        assert q.n.read(module.source_path(name)) in (original, module.payload(original, 'data_centric'))
    return module, folder, value


def preflight(q):
    module, folder, value = load_plan(q)
    assert not os.path.exists(folder + '/done'), 'Prepare a new private-backed-up Telecom plan'
    assert q.n.voice_policy() == 0 and module.ue_usage_policy() == 0
    for name in module.SOURCES:
        assert q.n.digest(q.n.read(module.source_path(name))) == value['files'][name]['original_sha256']
    q.s.current_usim()
    return {'source_backups_verified': True, 'original_ue_usage': 0, 'original_voice': 0,
            'lte_bootstrap_required': not q.s.ready(), 'plan_folder': folder}


def wait_for_idle_stock(q):
    pids = q.n.ims_pids()
    if not pids:
        return
    # One exact no-profile stock instance; no name-wide signal or SIGKILL.
    candidate = len(pids) == 1 and q.s.phone_idle() and not q.n.active_vpn_sessions()
    if candidate:
        pid = pids[0]
        rows = [line.strip().split() for line in q.n.command(
            ['/bin/pidin', '-p', str(pid), '-f', 'A']).decode('ascii').splitlines() if line.strip()]
        candidate = rows == [['Arguments'], ['/radio/bin/ims_rrm', '-U', '453:31,80,387,427,521,1001']]
        names = [line.strip() for line in q.n.command(
            ['/bin/pidin', '-p', str(pid), '-F', '%80N']).decode('ascii').splitlines() if line.strip()]
        candidate = (candidate and len(names) == 2 and names[0] == 'name' and
                     posixpath.normpath('/' + names[1].lstrip('/')) == '/radio/bin/ims_rrm')
        ims = q.n.attrs(q.n.read(q.s.IMS))
        candidate = candidate and all(q.n.value(ims, key) in (None, []) for key in ('IMS_profiles', 'IMS_profilesV2'))
        logs = q.n.command(['/bin/slog2info', '-b', 'ims_rrm'], 10).decode('utf-8', 'replace')
        own = '\n'.join(line for line in logs.splitlines() if 'ims_rrm.' + str(pid) + ' ' in line)
        candidate = (candidate and 'No IMS profiles provisioned .. waiting' in own and
                     not re.search(r'CSeq:\s*\d+\s+(?:REGISTER|INVITE)\b', own) and
                     q.live()['ims'] in (None, 'idle', 'disconnected'))
    receipt_path = q.s.STATE + '/telecom-stock-handoff.json'
    prior = q.s.load(receipt_path) if os.path.isfile(receipt_path) else {}
    if candidate and prior.get('boot') != q.boot_token():
        assert q.n.ims_pids() == pids and q.s.phone_idle() and not q.n.active_vpn_sessions()
        q.n.atomic(receipt_path, json.dumps({'boot': q.boot_token(), 'pid': pid,
            'requested_at': time.time(), 'reason': 'exact_idle_stock_no_profiles',
            'profile_sha256': q.profiles.fingerprint(q.s.ACTIVE_REQUEST)}).encode('ascii'))
        os.kill(pid, signal.SIGTERM)
    q.s.wait_until(lambda: not q.n.ims_pids(), q.s.ACTIVE_PROFILE['runtime']['existing_ims_wait_seconds'],
                   'pre-existing native IMS before Telecom attach', phase='waiting_for_native_ims')


def adopt_journal(q, folder):
    q.s.init_journal()
    assert q.s.j['original_voice_policy'] == 0
    current = q.boot_token()
    if q.s.j.get('boot') != current:
        q.s.j['telecom_previous_native_pid'] = q.s.j.get('native_pid')
        q.s.j['native_pid'] = None
    q.s.j.update(boot=current, telecom_dca_plan=folder, telecom_bootstrap_owner=OWNER)
    q.s.save_journal()


def ensure_lte(q):
    q.verify()
    module, folder, value = load_plan(q)
    assert q.s.phone_idle() and not q.n.active_vpn_sessions()
    assert q.n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
    deadline = time.time() + q.s.ACTIVE_PROFILE['runtime']['sim_wait_seconds']
    while q.c.read_network(q.s.ACTIVE_PROFILE).get('sim_state') != 'READY':
        assert time.time() < deadline and not q.s.stopping(), 'SIM readiness timed out/stopped'
        time.sleep(2)
    imsi = q.s.current_usim()
    wait_for_idle_stock(q)
    usage_before, voice_before = module.ue_usage_policy(), q.n.voice_policy()
    assert usage_before in (0, 1) and voice_before in (0, 3), 'Unowned native policy'
    applied = any(q.n.digest(q.n.read(module.source_path(name))) != value['files'][name]['original_sha256']
                  for name in module.SOURCES)
    if applied or usage_before != 0 or voice_before != 0:
        previous = q.s.load(q.s.STATE + '/telecom-bootstrap.json')
        previous_journal = q.s.load(q.s.JOURNAL)
        assert previous['owner'] == OWNER and previous['plan_folder'] == folder
        assert previous_journal.get('telecom_dca_plan') == folder
        assert previous['profile_sha256'] == q.profiles.fingerprint(q.s.ACTIVE_REQUEST)
    adopt_journal(q, folder)
    path = q.s.STATE + '/telecom-bootstrap.json'
    record = {'owner': OWNER, 'boot': q.boot_token(), 'profile_sha256': q.profiles.fingerprint(q.s.ACTIVE_REQUEST),
              'sim_fingerprint': hashlib.sha256(imsi.encode('ascii')).hexdigest(),
              'plan_folder': folder, 'phase': 'applying', 'original_voice': 0, 'original_usage': 0}
    q.n.atomic(path, json.dumps(record).encode('ascii'))
    try:
        q.s.status('telecom_bootstrap_configuring')
        for name in module.SOURCES:
            item = value['files'][name]
            original = q.n.read(folder + '/' + name + '.original')
            current = q.n.read(module.source_path(name))
            if current == original:
                module.write_existing(module.source_path(name), current, module.payload(original, 'data_centric'), item)
        record['publish'] = module.publish(folder, 'service-apply')
        assert 'error_type' not in record['publish'] and module.ue_usage_policy() == 1
        voice = q.n.voice_policy()
        assert voice in (0, 3)
        if voice == 0:
            # Persist the restore intent before the native setter resets modem.
            q.n.atomic(folder + '/report.json', json.dumps({'owner': module.OWNER,
                'voice_preference_change_attempted': True, 'service_bootstrap': True}).encode('ascii'))
            record['voice_setter'] = q.s.set_voice_preference(1)
            assert record['voice_setter']['rc'] == 0
        deadline = time.time() + 120
        while time.time() < deadline:
            assert q.s.phone_idle() and not q.s.stopping()
            network = q.c.read_network(q.s.ACTIVE_PROFILE)
            if network.get('sim_state') == 'READY':
                assert q.s.current_usim() == imsi
            if q.s.ready() and module.ue_usage_policy() == 1 and q.n.voice_policy() == 3:
                record.update(phase='ready', ready_at=time.time(), network=network)
                q.n.atomic(path, json.dumps(record).encode('ascii'))
                return
            q.s.status('telecom_waiting_for_lte_data')
            time.sleep(3)
        raise RuntimeError('Telecom native UE1/voice3 LTE bootstrap timed out')
    except Exception:
        record['restore'] = module.restore(folder, value)
        record['phase'] = 'restored_after_error' if record['restore']['restored'] else 'cleanup_required'
        q.n.atomic(path, json.dumps(record).encode('ascii'))
        raise


def restore(q):
    path = q.s.STATE + '/telecom-bootstrap.json'
    if not os.path.isfile(path):
        return
    record = q.s.load(path)
    assert record['owner'] == OWNER
    if record.get('phase') == 'restored':
        return
    module, folder, value = load_plan(q)
    assert folder == record['plan_folder']
    record['restore'] = module.restore(folder, value)
    record['phase'] = 'restored' if record['restore']['restored'] else 'cleanup_required'
    q.n.atomic(path, json.dumps(record).encode('ascii'))
    assert record['restore']['restored'], 'Telecom source/native baseline needs recovery'
