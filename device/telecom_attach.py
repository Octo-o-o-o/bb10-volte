"""Explicit, manual Q10 port of the Q20/460-11 UE1 + voice3 LTE bootstrap.

No action on import/probe. IMS configuration still requires normal LTE data.
Q20 Root-v2 uses its separately accepted adapter; Passport remains gated.
"""
import binascii
import hashlib
import json
import os
import stat
import sys
import time

import native as n
import profiles
import device_info
import telecom_native as native
import telecom_dca as dca

MODE = 'telecom_data_centric_v1'
OWNER = 'bb10-telecom-attach-v1'
BASE = '/var/rootdata/q10_volte'


def selected(profile):
    return profile.get('lte_attach') == MODE


def supported(identity):
    device = device_info.identify(identity)
    return (device['recognized'] and not device['identity_conflict'] and
            device['family'] == 'q10' and device['variant'] == 'SQN100-3' and
            identity.get('os_version') == device_info.OS_VERSION)


def bind(service):
    class Context(object):
        pass
    context = Context()
    context.s, context.n, context.BASE = service, n, service.BASE
    dca.q = context
    return context


def source_baseline():
    for name in dca.SOURCES:
        path = dca.source_path(name)
        info = os.lstat(path)
        assert stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
        dca.payload(n.read(path), 'data_centric')
    return True


def observe(base=BASE):
    result = {'native_supported': False, 'source_baseline': False,
              'original_usage': False, 'backup_verified': False}
    try:
        result['native_supported'] = (n.digest(n.read('/radio/bin/qct_rrm')) == native.QCT_HASH and
                                      n.digest(n.read('/usr/sbin/dca')) == native.DCA_HASH)
        result['source_baseline'] = source_baseline()
        if result['native_supported']:
            result['original_usage'] = native.ue_usage_policy() == 0
        # Only a boolean leaves the device; private plan/SIM fingerprint stays local.
        pointer = json.loads(n.read(base + '/state/telecom-plan.json').decode('ascii'))
        folder = pointer['folder']
        assert pointer['owner'] == OWNER and folder.startswith(base + '/state/telecom-attach-')
        assert os.path.realpath(folder) == folder
        receipt = json.loads(n.read(folder + '/desktop-backup-receipt.json').decode('ascii'))
        result['backup_verified'] = (receipt['owner'] == OWNER and
            receipt['all_original_hashes_verified'] is True and
            receipt['plan_sha256'] == n.digest(n.read(folder + '/plan.json')))
    except (OSError, ValueError, TypeError, KeyError, AssertionError):
        pass
    return result


def prepare(service):
    """Save original sources only. The desktop must independently back them up."""
    bind(service)
    assert selected(service.ACTIVE_PROFILE) and supported(device_info.read_identity())
    native.verify()
    assert service.phone_idle() and not n.ims_pids() and not n.active_vpn_sessions()
    assert n.voice_policy() == 0 and native.ue_usage_policy() == 0
    assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
    source_baseline()
    pointer = service.STATE + '/telecom-plan.json'
    if os.path.isfile(pointer):
        old_folder, old_value = dca.plan()
        if (old_value['profile_sha256'] == profiles.fingerprint(service.ACTIVE_REQUEST) and
                old_value['sim_fingerprint'] == hashlib.sha256(service.current_usim().encode('ascii')).hexdigest()):
            assert all(n.digest(n.read(dca.source_path(name))) == old_value['files'][name]['original_sha256']
                       for name in dca.SOURCES)
            return {'folder': old_folder, 'plan_sha256': n.digest(n.read(old_folder + '/plan.json'))}
        assert os.path.isfile(old_folder + '/done'), 'Restore the earlier Telecom plan before updating'
    folder = service.STATE + '/telecom-attach-' + binascii.hexlify(os.urandom(8)).decode('ascii')
    os.mkdir(folder, 0o700)
    value = {'owner': OWNER, 'original_usage': 0, 'original_voice': 0,
             'profile_sha256': profiles.fingerprint(service.ACTIVE_REQUEST),
             'sim_fingerprint': hashlib.sha256(service.current_usim().encode('ascii')).hexdigest(),
             'dca_sha256': native.DCA_HASH, 'files': {}}
    for name in dca.SOURCES:
        path = dca.source_path(name)
        info, original = os.lstat(path), n.read(path)
        assert stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
        value['files'][name] = {'path': path, 'original_sha256': n.digest(original),
            'applied_sha256': n.digest(dca.payload(original, 'data_centric')),
            'identity': [info.st_ino, info.st_mode & 0o7777, info.st_uid, info.st_gid]}
        n.atomic(folder + '/' + name + '.original', original)
    n.atomic(folder + '/plan.json', json.dumps(value, indent=2).encode('ascii'))
    n.atomic(pointer, json.dumps({'owner': OWNER, 'folder': folder}).encode('ascii'))
    return {'folder': folder, 'plan_sha256': n.digest(n.read(folder + '/plan.json'))}


def checked_plan(service, restoring=False):
    bind(service)
    native.verify()
    assert selected(service.ACTIVE_PROFILE) and supported(device_info.read_identity())
    folder, value = dca.plan()
    assert value['profile_sha256'] == profiles.fingerprint(service.ACTIVE_REQUEST)
    assert value['dca_sha256'] == native.DCA_HASH
    assert set(value['files']) == set(dca.SOURCES)
    receipt = service.load(folder + '/desktop-backup-receipt.json')
    assert receipt['owner'] == OWNER and receipt['all_original_hashes_verified'] is True
    assert receipt['plan_sha256'] == n.digest(n.read(folder + '/plan.json'))
    for name in dca.SOURCES:
        item = value['files'][name]
        original = n.read(folder + '/' + name + '.original')
        assert n.digest(original) == item['original_sha256']
        assert item['path'] == dca.source_path(name)
        allowed = (original, dca.payload(original, 'data_centric'))
        if restoring:
            allowed += (dca.payload(original, 'voice_centric'),)
        assert n.read(item['path']) in allowed
    return folder, value


def ensure_lte(service):
    """Configure attach first; the caller separately checks LTE before IMS."""
    folder, value = checked_plan(service)
    assert not service.ACTIVE_PROFILE['runtime']['autostart'], 'Q10 Telecom has no reboot acceptance yet'
    assert service.phone_idle() and not n.active_vpn_sessions()
    assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
    identity = service.current_usim()
    fingerprint = hashlib.sha256(identity.encode('ascii')).hexdigest()
    assert fingerprint == value['sim_fingerprint'], 'Reprepare Telecom backups after changing SIM'
    # New port keeps the passive stock wait; it never kills an unowned process.
    service.wait_until(lambda: not n.ims_pids(), service.ACTIVE_PROFILE['runtime']['existing_ims_wait_seconds'],
                       'native IMS before Telecom attach', phase='waiting_for_native_ims')
    usage, voice = native.ue_usage_policy(), n.voice_policy()
    original = all(n.digest(n.read(dca.source_path(name))) == value['files'][name]['original_sha256']
                   for name in dca.SOURCES)
    path = service.STATE + '/telecom-bootstrap.json'
    if not (original and usage == 0 and voice == 0):
        prior = service.load(path)
        assert prior['owner'] == OWNER and prior['plan_folder'] == folder
        assert prior['profile_sha256'] == value['profile_sha256'] and prior['sim_fingerprint'] == fingerprint
        assert usage == 1 and voice == 3, 'Partial Telecom application needs explicit restoration'
        assert service.load(service.JOURNAL).get('telecom_dca_plan') == folder
    service.init_journal()
    assert (service.j.get('restore_completed') is True or
            service.j.get('profile_sha256') in (None, value['profile_sha256'])), 'Restore the previous carrier first'
    if service.j.get('boot') != service.boot_token():
        service.j['native_pid'] = None
    service.j.update(boot=service.boot_token(), telecom_dca_plan=folder, restore_completed=False,
                     profile_sha256=value['profile_sha256'])
    service.save_journal()
    record = {'owner': OWNER, 'plan_folder': folder, 'profile_sha256': value['profile_sha256'],
              'sim_fingerprint': fingerprint, 'phase': 'applying'}
    n.atomic(path, json.dumps(record).encode('ascii'))
    try:
        service.status('telecom_bootstrap_configuring')
        for name in dca.SOURCES:
            item = value['files'][name]
            before = n.read(folder + '/' + name + '.original')
            if n.read(item['path']) == before:
                dca.write_existing(item['path'], before, dca.payload(before, 'data_centric'), item)
        published = dca.publish(folder, 'service-apply')
        assert 'error_type' not in published and native.ue_usage_policy() == 1
        if voice == 0:
            n.atomic(folder + '/report.json', json.dumps({'owner': OWNER,
                'voice_preference_change_attempted': True}).encode('ascii'))
            assert service.set_voice_preference(1)['rc'] == 0
        deadline = time.time() + 120
        while time.time() < deadline:
            assert service.phone_idle() and not service.stopping()
            network = service.compatibility.read_network(service.ACTIVE_PROFILE)
            if network.get('sim_state') == 'READY':
                assert service.current_usim() == identity, 'SIM changed during modem reload'
            if service.ready() and native.ue_usage_policy() == 1 and n.voice_policy() == 3:
                record.update(phase='ready', ready_at=time.time())
                n.atomic(path, json.dumps(record).encode('ascii'))
                return
            service.status('telecom_waiting_for_lte_data')
            time.sleep(3)
        raise RuntimeError('Telecom LTE data bootstrap timed out')
    except Exception:
        restored = dca.restore(folder, value)
        record.update(phase='restored' if restored['restored'] else 'cleanup_required')
        n.atomic(path, json.dumps(record).encode('ascii'))
        raise


def restore(service):
    path = service.STATE + '/telecom-bootstrap.json'
    if not os.path.isfile(path):
        return
    record = service.load(path)
    assert record['owner'] == OWNER
    if record['phase'] == 'restored':
        return
    folder, value = checked_plan(service, restoring=True)
    assert folder == record['plan_folder']
    restored = dca.restore(folder, value)
    record['phase'] = 'restored' if restored['restored'] else 'cleanup_required'
    n.atomic(path, json.dumps(record).encode('ascii'))
    assert restored['restored'], 'Telecom native/source restoration needs inspection'
