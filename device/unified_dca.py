"""Phone-local UE-usage transactions, backed up once during installation.

The original four source files are independent of the SIM. Each later SIM
transition gets its own transaction; no desktop receipt is invented per SIM.
"""
import errno
import json
import os
import select
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
MODE_RECORD = BASE + '/state/radio-mode.json'
RADIO_CONTROL = '/pps/services/cellular/radioctrl/control'
RADIO_STATUS = '/pps/services/cellular/radioctrl/status_persistent'
MODE_STATUS = '/pps/services/radioctrl/modem0/status_persistent'
CELLULAR_IMAGE = '/radio/bin/cellular-control'
CELLULAR_HASH = '1fb9b34d9e4b401ce2e7add1dff20f1c8c08dc926d6f25b0ae6b586f122470ec'
TECH_BITS = ((1, 'gsm'), (2, 'umts'), (4, 'cdma_1x'), (8, 'evdo'), (16, 'lte'))


def idle_resources():
    return {'call_idle': s.phone_idle(), 'ims_process_count': len(n.ims_pids()),
            'active_vpn_count': len(n.active_vpn_sessions())}


def wait_policy_idle(timeout=180):
    """Observe startup/call transitions without changing or stopping resources."""
    quiet = 0
    for elapsed in range(timeout + 1):
        if s.stopping():
            raise RuntimeError('stopped')
        state = idle_resources()
        ready = state['call_idle'] and not state['ims_process_count'] and not state['active_vpn_count']
        quiet = quiet + 1 if ready else 0
        if quiet >= 2:
            return
        s.status('waiting_for_phone_idle', details=state)
        if elapsed == timeout:
            raise RuntimeError('startup_resources_busy')
        time.sleep(1)


def assert_policy_idle():
    assert s.phone_idle(), 'call_or_phone_initialization_busy'
    assert not n.ims_pids(), 'native_ims_active'
    assert not n.active_vpn_sessions(), 'vpn_active'


def mode_snapshot():
    assert n.digest(n.read(CELLULAR_IMAGE)) == CELLULAR_HASH, 'unknown_radio_controller'
    raw = n.value(n.attrs(n.read(MODE_STATUS)), 'configure_rats_state')
    assert isinstance(raw, dict) and set(raw) == {'enabled_technologies', 'preferred_technologies'}, 'unknown_network_mode'
    enabled, preferred = raw['enabled_technologies'], raw['preferred_technologies']
    assert type(enabled) is int and 0 < enabled <= 31, 'unknown_network_mode'
    assert type(preferred) is int and (preferred == -1 or 0 <= preferred <= 31), 'unknown_network_preference'
    public = n.attrs(n.read(RADIO_STATUS))
    configured = n.value(public, 'configured_technologies', {})
    assert set(configured.get('enabled', [])) == {name for bit, name in TECH_BITS if enabled & bit}, 'network_mode_readback_conflict'
    allowed = n.value(public, 'swoop_technologies', {}).get('enabled', [])
    assert 'lte' in allowed, 'carrier_lte_not_allowed'
    return dict(raw)


def wire_mode(value):
    # The stock handler uses -1 as its missing-argument sentinel and rejects it.
    # Persisted -1 means no preferred technology; the request form is mask 0.
    result = dict(value)
    if result['preferred_technologies'] == -1:
        result['preferred_technologies'] = 0
    return result


def same_mode(first, second):
    return wire_mode(first) == wire_mode(second)


def request_mode(value):
    # The pinned stock handler at 0x5be5e parses these two integers, calls its
    # capability/carrier-filtered setter at 0x5ef7c, then persists the selection.
    # Its 0x5af70 table maps LTE to 16 (the QMI NAS mask uses different bits).
    value = wire_mode(value)
    identifier = 'bb10-auto-rat-' + str(os.getpid()) + '-' + str(int(time.time() * 1000))
    request = ('msg::configure_rats\nid::' + identifier + '\ndat:json:' + json.dumps(value) + '\n').encode('ascii')
    fd = os.open(RADIO_CONTROL + '?wait', os.O_RDWR | os.O_NONBLOCK)
    try:
        assert os.write(fd, request) == len(request)
        deadline = time.time() + 15
        acknowledged = False
        while time.time() < deadline:
            ready, unused, unused2 = select.select([fd], [], [], max(0, deadline - time.time()))
            if not ready:
                break
            try:
                reply = n.attrs(os.read(fd, 262144))
            except OSError as error:
                if error.errno == errno.EAGAIN:
                    continue
                raise
            if n.value(reply, 'id') != identifier:
                continue
            if 'res' in reply or 'err' in reply:
                assert n.value(reply, 'res') == 'configure_rats' and 'err' not in reply, 'network_mode_rejected'
                acknowledged = True
                break
        assert acknowledged, 'network_mode_reply_timeout'
    finally:
        os.close(fd)
    for unused in range(8):
        try:
            if same_mode(mode_snapshot(), value):
                return
        except AssertionError as error:
            if str(error) != 'network_mode_readback_conflict':
                raise
        time.sleep(1)
    raise RuntimeError('network_mode_readback_failed')


def ensure_lte_mode(selected):
    assert_policy_idle()
    current = mode_snapshot()
    previous = s.load(MODE_RECORD) if os.path.isfile(MODE_RECORD) else None
    if previous:
        assert previous['owner'] == policy.OWNER
        if not previous.get('restored'):
            assert any(same_mode(current, value) for value in (previous['before'], previous['applied'])), 'network_mode_changed'
    if current['enabled_technologies'] & 16:
        if previous and not previous.get('restored') and previous.get('phase') != 'ready':
            previous['phase'] = 'ready'
            n.atomic(MODE_RECORD, profiles.canonical(previous))
        return
    assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}, 'network_mode_requires_fresh_boot'
    if previous:
        assert same_mode(current, previous['before']), 'network_mode_changed'
        record = dict(previous)
        record['applied'] = wire_mode(record['applied'])
    else:
        applied = wire_mode(dict(current, enabled_technologies=current['enabled_technologies'] | 16))
        record = {'owner': policy.OWNER, 'before': current, 'applied': applied}
    record.update(boot=s.boot_token(), phase='applying', restored=False,
                  operator=selected['operator'], sim_sha256=selected['sim_sha256'])
    n.atomic(MODE_RECORD, profiles.canonical(record))
    request_mode(record['applied'])
    assert same_mode(mode_snapshot(), record['applied']), 'network_mode_readback_failed'
    record['phase'] = 'ready'
    n.atomic(MODE_RECORD, profiles.canonical(record))


def restore_lte_mode():
    if not os.path.isfile(MODE_RECORD):
        return
    record = s.load(MODE_RECORD)
    assert record['owner'] == policy.OWNER
    if record.get('restored'):
        return
    assert_policy_idle()
    current = mode_snapshot()
    assert any(same_mode(current, value) for value in (record['before'], record['applied'])), 'network_mode_changed'
    record['phase'] = 'restoring'
    n.atomic(MODE_RECORD, profiles.canonical(record))
    if not same_mode(current, record['before']):
        request_mode(record['before'])
    observed = mode_snapshot()
    assert same_mode(observed, record['before']), 'network_mode_restore_unconfirmed'
    record.update(phase='restored', restored=True, restore_readback=observed)
    n.atomic(MODE_RECORD, profiles.canonical(record))


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
    assert_policy_idle()
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
    token = s.boot_token()
    policy_boot = None
    if previous is not None and previous.get('desired') == desired:
        policy_boot = previous.get('policy_changed_boot', previous.get('boot'))
    if current_usage != desired:
        policy_boot = token
    # The transaction remains after interruption. Both old and intended bytes
    # are checked before any retry; unrelated source content is never replaced.
    record = {'owner': policy.OWNER, 'boot': token, 'phase': 'applying',
              'desired': desired, 'operator': selected['operator'],
              'ue_usage_before': current_usage, 'policy_changed_boot': policy_boot,
              'source_repair_only': current_usage == desired,
              'sim_sha256': selected['sim_sha256'], 'at': time.time()}
    n.atomic(RECORD, profiles.canonical(record))
    for name in dca.SOURCES:
        if current[name] != targets[name]:
            dca.write_existing(dca.source_path(name), current[name], targets[name], files[name])
    record['publish'] = dca.publish(BACKUP, 'auto-usage')
    assert 'error_type' not in record['publish'], 'dca_publish_failed'
    if desired == 0 and radio.ue_usage_policy() != 0:
        # Stock missing-key state alone does not necessarily revert NV.
        record.update(policy_changed_boot=token, source_repair_only=False)
        n.atomic(RECORD, profiles.canonical(record))
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
    if desired == 1 and radio.ue_usage_policy() == 0:
        # A voice-policy reset can leave NV=0 while the published PPS value is
        # already data_centric. Re-publishing identical bytes emits no change.
        # The verified Passport recovery uses a bounded original->data edge,
        # through the same backed-up DCA sources, before any native IMS launch.
        assert s.phone_idle() and not n.ims_pids() and not n.active_vpn_sessions()
        record.update(phase='republishing_original', policy_changed_boot=token,
                      source_repair_only=False)
        n.atomic(RECORD, profiles.canonical(record))
        for name in dca.SOURCES:
            dca.write_existing(dca.source_path(name), targets[name],
                               dca.payload(values[name], 'voice_centric'), files[name])
        result = dca.publish(BACKUP, 'auto-republish-original')
        assert 'error_type' not in result and radio.ue_usage_policy() == 0, 'usage_baseline_unconfirmed'
        assert s.phone_idle() and not n.ims_pids() and not n.active_vpn_sessions()
        record['phase'] = 'republishing_data'
        n.atomic(RECORD, profiles.canonical(record))
        for name in dca.SOURCES:
            dca.write_existing(dca.source_path(name), dca.payload(values[name], 'voice_centric'),
                               targets[name], files[name])
        result = dca.publish(BACKUP, 'auto-republish-data')
        assert 'error_type' not in result, 'dca_publish_failed'
        for unused in range(8):
            if radio.ue_usage_policy() == 1:
                break
            time.sleep(3)
        record['republish_readback_verified'] = radio.ue_usage_policy() == 1
    assert radio.ue_usage_policy() == desired, 'usage_readback_failed'
    assert all(n.read(dca.source_path(name)) == targets[name] for name in dca.SOURCES)
    record['phase'] = 'ready'
    n.atomic(RECORD, profiles.canonical(record))
    return record


def prepare(selected):
    wait_policy_idle()
    ensure_lte_mode(selected)
    wait_policy_idle()
    # SQN100-3 / 460-00 can initially register IMS in voice-centric mode,
    # then receive CS-domain rejection 18 and have LTE disabled by the modem.
    # Use the backed-up DCA transaction before IMS starts, as for Telecom.
    # Other non-Telecom combinations retain their original usage policy.
    desired = 1 if (selected['operator'] == 'telecom' or
                    selected['family'] == 'q10' and selected['operator'] == 'mobile') else 0
    record = set_usage(desired, selected)
    policy_boot = record.get('policy_changed_boot', record.get('boot'))
    if selected['family'] == 'passport' and policy_boot == s.boot_token():
        # Passport's accepted path requires the selected UE policy at cold boot.
        # Airplane mode and native IMS restarts did not replace that requirement.
        # DCA may regenerate its source objects at boot while the modem already
        # has the selected NV value. Repairing those files is not a policy change.
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
    result = set_usage(0, {'operator': 'original', 'sim_sha256': None})
    restore_lte_mode()
    return result
