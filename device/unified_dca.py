"""Phone-local UE-usage transactions, backed up once during installation.

The original four source files are independent of the SIM. Each later SIM
transition gets its own transaction; no desktop receipt is invented per SIM.
"""
import os
import sys
import time
import native as n
import profiles
import service as s
import carrier_policy as policy
import telecom_dca as dca
import telecom_native as radio

BASE = policy.BASE
BACKUP = BASE + '/backup'
RECORD = BASE + '/state/dca.json'


def context():
    class Context:
        pass
    result = Context()
    result.n, result.s = n, s
    dca.q = result


def originals():
    manifest = s.load(BACKUP + '/manifest.json')
    assert manifest['owner'] == policy.OWNER
    receipt = s.load(BASE + '/desktop-backup-receipt.json')
    assert receipt['owner'] == policy.OWNER and receipt['all_original_hashes_verified'] is True
    assert receipt['backup_manifest_sha256'] == n.digest(n.read(BACKUP + '/manifest.json'))
    files = manifest['dca']
    assert set(files) == set(dca.SOURCES)
    values = {}
    for name in dca.SOURCES:
        item = files[name]
        assert item['path'] == dca.source_path(name)
        raw = n.read(BACKUP + '/' + name + '.original')
        assert n.digest(raw) == item['original_sha256']
        dca.payload(raw, 'data_centric')
        values[name] = raw
    return files, values


def set_usage(desired, selected):
    assert desired in (0, 1)
    context()
    radio.verify()
    assert s.phone_idle() and not n.ims_pids() and not n.active_vpn_sessions()
    files, values = originals()
    previous = s.load(RECORD) if os.path.isfile(RECORD) else None
    if previous is not None:
        assert previous['owner'] == policy.OWNER
    current_usage = radio.ue_usage_policy()
    assert current_usage in (0, 1)
    current = {name: n.read(dca.source_path(name)) for name in dca.SOURCES}
    for name, raw in current.items():
        allowed = (values[name], dca.payload(values[name], 'data_centric'), dca.payload(values[name], 'voice_centric'))
        assert raw in allowed, 'dca_source_changed'
        if raw != values[name] or current_usage != 0:
            assert previous is not None, 'unowned_dca_policy'
    targets = {name: dca.payload(raw, 'data_centric') if desired else raw for name, raw in values.items()}
    changed = current_usage != desired or current != targets
    if not changed:
        return previous or {'owner': policy.OWNER, 'desired': desired, 'phase': 'ready', 'boot': None}
    # The transaction remains after interruption. Both old and intended bytes
    # are checked before any retry; unrelated source content is never replaced.
    record = {'owner': policy.OWNER, 'boot': s.boot_token(), 'phase': 'applying',
              'desired': desired, 'operator': selected['operator'],
              'sim_sha256': selected['sim_sha256'], 'at': time.time()}
    n.atomic(RECORD, profiles.canonical(record))
    for name in dca.SOURCES:
        if current[name] != targets[name]:
            dca.write_existing(dca.source_path(name), current[name], targets[name], files[name])
    record['publish'] = dca.publish(BACKUP, 'auto-usage')
    assert 'error_type' not in record['publish'], 'dca_publish_failed'
    if desired == 0 and radio.ue_usage_policy() != 0:
        # Stock missing-key state alone does not necessarily revert NV.
        for name in dca.SOURCES:
            dca.write_existing(dca.source_path(name), targets[name], dca.payload(values[name], 'voice_centric'), files[name])
        result = dca.publish(BACKUP, 'auto-explicit-original')
        assert 'error_type' not in result, 'dca_publish_failed'
        for unused in range(8):
            if radio.ue_usage_policy() == 0:
                break
            time.sleep(3)
        assert radio.ue_usage_policy() == 0, 'usage_restore_unconfirmed'
        for name in dca.SOURCES:
            dca.write_existing(dca.source_path(name), dca.payload(values[name], 'voice_centric'), targets[name], files[name])
        result = dca.publish(BACKUP, 'auto-original-files')
        assert 'error_type' not in result, 'dca_publish_failed'
    for unused in range(8):
        if radio.ue_usage_policy() == desired:
            break
        time.sleep(3)
    assert radio.ue_usage_policy() == desired, 'usage_readback_failed'
    assert all(n.read(dca.source_path(name)) == targets[name] for name in dca.SOURCES)
    record['phase'] = 'ready'
    n.atomic(RECORD, profiles.canonical(record))
    return record


def prepare(selected):
    desired = 1 if selected['operator'] == 'telecom' else 0
    record = set_usage(desired, selected)
    if selected['family'] == 'passport' and record.get('boot') == s.boot_token():
        # Passport's accepted path requires the selected UE policy at cold boot.
        # Airplane mode and native IMS restarts did not replace that requirement.
        return False
    if desired and selected['family'] != 'passport':
        voice = n.voice_policy()
        assert voice in (0, 3)
        if voice == 0:
            s.j['voice_preference_change_attempted'] = True
            s.save_journal()
            assert s.set_voice_preference(1)['rc'] == 0
        assert n.voice_policy() == 3
    return True


def restore_original():
    return set_usage(0, {'operator': 'original', 'sim_sha256': None})
