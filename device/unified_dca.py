"""Phone-local UE-usage transactions, backed up once during installation.

The original four source files are independent of the SIM. Each later SIM
transition gets its own transaction; no desktop receipt is invented per SIM.
"""
import errno
import json
import os
import re
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
SELECTION_RECORD = BASE + '/state/network-selection.json'
NETWORK_LOCK = BASE + '/state/network-lock.json'
RADIO_CONTROL = '/pps/services/cellular/radioctrl/control'
RADIO_PUBLIC = '/pps/services/cellular/radioctrl/status_public'
RADIO_STATUS = '/pps/services/cellular/radioctrl/status_persistent'
MODE_STATUS = '/pps/services/radioctrl/modem0/status_persistent'
CELLULAR_IMAGE = '/radio/bin/cellular-control'
CELLULAR_HASH = '1fb9b34d9e4b401ce2e7add1dff20f1c8c08dc926d6f25b0ae6b586f122470ec'
TECH_BITS = ((1, 'gsm'), (2, 'umts'), (4, 'cdma_1x'), (8, 'evdo'), (16, 'lte'))
PRIMARY_LTE_MNCS = {'mobile': '00', 'unicom': '01', 'telecom': '11'}
deferred_lte_lock = False


def mobile_radio_state():
    """Return ON/OFF only for one complete, unambiguous public PPS value."""
    try:
        blob = n.read(RADIO_PUBLIC)
        if not isinstance(blob, bytes) or len(blob) > 65536 or not blob.endswith(b'\n'):
            return None
        rows = []
        for line in blob.decode('ascii').splitlines():
            line = re.sub(r'^\[[^]]*\]', '', line)
            if line.startswith(('-@', '#@', '*@')) or re.match(r'\A-power_status(?:[:\s]|\Z)', line):
                return None
            if re.match(r'\Apower_status(?:[:\s]|\Z)', line):
                rows.append(line)
        if rows == ['power_status::OFF']:
            return 'OFF'
        if rows == ['power_status::ON']:
            return 'ON'
    except (IOError, OSError, ValueError, TypeError, UnicodeError, AttributeError):
        pass
    return None


def _radio_control_rpc(msg, dat_line, id_prefix, timeout, err_prefix, accept_err_reply=False,
                       read_size=262144, max_polls=None):
    """Send one bounded PPS request to cellular-control and await its matching reply."""
    identifier = id_prefix + '-' + str(os.getpid()) + '-' + str(int(time.time() * 1000))
    request = ('msg::' + msg + '\nid::' + identifier + '\n' + dat_line + '\n').encode('ascii')
    fd = os.open(RADIO_CONTROL + '?wait', os.O_RDWR | os.O_NONBLOCK)
    has_err = False
    try:
        assert os.write(fd, request) == len(request), err_prefix + '_write_failed'
        acknowledged = False
        if max_polls is not None:
            for unused in range(max_polls):
                ready, unused1, unused2 = select.select([fd], [], [], 0.5)
                if not ready:
                    continue
                try:
                    reply = n.attrs(os.read(fd, read_size))
                except (IOError, OSError) as error:
                    if error.errno == errno.EAGAIN:
                        continue
                    raise
                if n.value(reply, 'id') != identifier:
                    continue
                if 'res' in reply or 'err' in reply:
                    if accept_err_reply:
                        assert n.value(reply, 'res') == msg, err_prefix + '_rejected'
                        has_err = 'err' in reply
                    else:
                        assert n.value(reply, 'res') == msg and 'err' not in reply, err_prefix + '_rejected'
                    acknowledged = True
                    break
        else:
            deadline = time.time() + timeout
            reads = 0
            while time.time() < deadline and reads < 200:
                reads += 1
                ready, unused1, unused2 = select.select([fd], [], [], max(0, deadline - time.time()))
                if not ready:
                    break
                try:
                    reply = n.attrs(os.read(fd, read_size))
                except (IOError, OSError) as error:
                    if error.errno == errno.EAGAIN:
                        continue
                    raise
                if n.value(reply, 'id') != identifier:
                    continue
                if 'res' in reply or 'err' in reply:
                    if accept_err_reply:
                        assert n.value(reply, 'res') == msg, err_prefix + '_rejected'
                        has_err = 'err' in reply
                    else:
                        assert n.value(reply, 'res') == msg and 'err' not in reply, err_prefix + '_rejected'
                    acknowledged = True
                    break
        assert acknowledged, err_prefix + '_reply_timeout'
    finally:
        os.close(fd)
    return has_err


def enable_mobile_network():
    """One ON request during explicit setup; never cycle or poll-retry power.

    The caller holds the management lock and verifies model/native/SIM scope.
    Use cellular-control's own power-manager-aware PPS handler, not a modem
    setter, data-service setting, or persistent-status write.
    """
    before = mobile_radio_state()
    if before == 'ON':
        return {'before': 'ON', 'after': 'ON', 'changed': False}
    assert before == 'OFF', 'mobile_network_state_unknown'
    assert n.digest(n.read(CELLULAR_IMAGE)) == CELLULAR_HASH, 'unknown_radio_controller'
    assert s.phone_idle(), 'call_active'
    # Recheck after verification; an independent ON needs no second command.
    current = mobile_radio_state()
    if current == 'ON':
        return {'before': before, 'after': 'ON', 'changed': False}
    assert current == 'OFF', 'mobile_network_state_unknown'
    _radio_control_rpc('power', 'dat:json:{"state":"ON"}', 'bb10-auto-power', 10,
                       'mobile_network', read_size=65536, max_polls=20)
    for unused in range(31):
        if mobile_radio_state() == 'ON':
            return {'before': before, 'after': 'ON', 'changed': True}
        if unused < 30:
            time.sleep(0.5)
    raise RuntimeError('mobile_network_enable_unconfirmed')


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
    _radio_control_rpc('configure_rats', 'dat:json:' + json.dumps(value),
                       'bb10-auto-rat', 15, 'network_mode')
    for unused in range(8):
        try:
            if same_mode(mode_snapshot(), value):
                return
        except AssertionError as error:
            if str(error) != 'network_mode_readback_conflict':
                raise
        time.sleep(1)
    raise RuntimeError('network_mode_readback_failed')


def scan_mode_snapshot():
    """Return AUTO/MANUAL when readable from cellular-control PPS status."""
    for path in (RADIO_PUBLIC, RADIO_STATUS):
        try:
            mode = n.value(n.attrs(n.read(path)), 'scan_mode')
            if isinstance(mode, str) and mode in ('AUTO', 'MANUAL'):
                return mode
        except (IOError, OSError, ValueError, TypeError, AttributeError):
            pass
    return None


def serving_network_snapshot():
    """Read current radio technology and serving PLMN without exposing cell IDs."""
    try:
        attrs = n.attrs(n.read(RADIO_PUBLIC))
        serving = n.value(attrs, 'serving_network', {})
        serving = serving if isinstance(serving, dict) else {}
        mcc, mnc = serving.get('mcc'), serving.get('mnc')
        service = n.value(attrs, 'network_service')
        tech = n.value(attrs, 'network_technology')
        return {
            'power_on': n.value(attrs, 'power_status') == 'ON',
            'lte': tech == ['lte'],
            'mcc': str(mcc) if mcc is not None and profiles.match(r'[0-9]{3}', str(mcc)) else None,
            'mnc': str(mnc) if mnc is not None and profiles.match(r'[0-9]{2,3}', str(mnc)) else None,
            'emergency_only': bool(service & 0x1) and not bool(service & 0x200000) if type(service) is int and 0 <= service <= 0xffffffff else False,
        }
    except (IOError, OSError, ValueError, TypeError, AttributeError):
        return {}


def request_scan_mode(mode):
    assert mode in ('AUTO', 'MANUAL'), 'invalid_scan_mode'
    assert n.digest(n.read(CELLULAR_IMAGE)) == CELLULAR_HASH, 'unknown_radio_controller'
    has_err = _radio_control_rpc('scan_mode', 'dat::' + mode, 'bb10-auto-scan', 15,
                                 'scan_mode', accept_err_reply=True)
    # Global 3GPP+3GPP2 SKUs (e.g. SQC100-3) may report 3GPP2 manual-mode
    # unsupported while 3GPP scan_mode transitions cleanly. Verify readback.
    for unused in range(6):
        if scan_mode_snapshot() == mode:
            return
        time.sleep(0.5)
    raise RuntimeError('scan_mode_rejected' if has_err else 'scan_mode_readback_failed')


def request_network_select(mcc, mnc, rat=16):
    """Select an explicit 3GPP PLMN; cellular-control requires string MCC/MNC and int RAT."""
    mcc, mnc = str(mcc), str(mnc)
    assert profiles.match(r'[0-9]{3}', mcc) and profiles.match(r'[0-9]{2,3}', mnc), 'invalid_plmn'
    assert type(rat) is int and rat == 16, 'invalid_rat'
    assert n.digest(n.read(CELLULAR_IMAGE)) == CELLULAR_HASH, 'unknown_radio_controller'
    payload = json.dumps({'mcc': mcc, 'mnc': mnc, 'rat': rat}, separators=(',', ':'))
    _radio_control_rpc('network_select', 'dat:json:' + payload, 'bb10-auto-plmn', 35, 'network_select')


def configured_network_lock(sim_sha256=None):
    if not os.path.isfile(NETWORK_LOCK):
        return None
    record = s.load(NETWORK_LOCK)
    assert record.get('owner') == policy.OWNER, 'network_lock_owner_changed'
    if sim_sha256 is not None and record.get('sim_sha256') != sim_sha256:
        return None
    return record


def apply_network_selection(selected, mcc=None, mnc=None, reason='explicit'):
    assert_policy_idle()
    assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}, 'network_mode_requires_fresh_boot'
    assert mobile_radio_state() == 'ON', 'mobile_network_off'
    operator = selected['operator']
    target_mcc = str(mcc or '460')
    target_mnc = str(mnc or PRIMARY_LTE_MNCS[operator])
    assert target_mcc == '460' and target_mnc in profiles.OPERATOR_MNCS[operator], 'invalid_plmn'
    from unified_service import card, ready_sim_hash
    assert ready_sim_hash(card()) == selected['sim_sha256'], 'sim_changed'
    previous = s.load(SELECTION_RECORD) if os.path.isfile(SELECTION_RECORD) else None
    if previous:
        assert previous.get('owner') == policy.OWNER
        if previous.get('sim_sha256') != selected['sim_sha256'] and not previous.get('restored'):
            restore_network_selection()
            previous = None
    current_scan = scan_mode_snapshot()
    assert current_scan in ('AUTO', 'MANUAL'), 'scan_mode_unknown'
    owned = previous and not previous.get('restored')
    # A system-selected MANUAL PLMN is not recoverable from serving_network:
    # an emergency camp may differ from the user's selected network. Preserve it.
    assert owned or current_scan == 'AUTO', 'system_manual_selection_preserved'
    before_scan = previous['before_scan_mode'] if owned else current_scan
    assert before_scan == 'AUTO', 'network_selection_backup_unknown'
    record = {
        'owner': policy.OWNER,
        'before_scan_mode': before_scan,
        'target': {'mcc': target_mcc, 'mnc': target_mnc, 'rat': 16},
        'operator': operator,
        'sim_sha256': selected['sim_sha256'],
        'reason': reason,
        'boot': s.boot_token(),
        'phase': 'applying',
        'restored': False,
        'at': time.time(),
    }
    n.atomic(SELECTION_RECORD, profiles.canonical(record))
    try:
        request_scan_mode('MANUAL')
        assert_policy_idle()
        assert ready_sim_hash(card()) == selected['sim_sha256'], 'sim_changed'
        request_network_select(target_mcc, target_mnc, 16)
    except Exception:
        # Retain the applying receipt if rollback fails, so a later explicit
        # unlock/disable can finish recovery instead of claiming success.
        restore_network_selection()
        raise
    record['phase'] = 'ready'
    n.atomic(SELECTION_RECORD, profiles.canonical(record))
    return record


def restore_network_selection(preserve_locked_sim=None):
    has_lock = os.path.isfile(NETWORK_LOCK)
    if has_lock:
        lock = s.load(NETWORK_LOCK)
        assert lock.get('owner') == policy.OWNER, 'network_lock_owner_changed'
        if preserve_locked_sim is not None and lock.get('sim_sha256') == preserve_locked_sim:
            return {'restored': False, 'locked_for_current_sim': True}
    if not os.path.isfile(SELECTION_RECORD):
        assert not has_lock, 'network_selection_backup_missing'
        return {'restored': True, 'changed': False}
    record = s.load(SELECTION_RECORD)
    assert record.get('owner') == policy.OWNER
    if record.get('restored'):
        if has_lock:
            os.unlink(NETWORK_LOCK)
        return {'restored': True, 'changed': False}
    assert s.phone_idle(), 'call_active'
    changed = False
    desired_scan = record.get('before_scan_mode')
    assert desired_scan == 'AUTO', 'network_selection_backup_unknown'
    if scan_mode_snapshot() != desired_scan:
        assert mobile_radio_state() == 'ON', 'mobile_network_off'
        assert not n.ims_pids() and not n.active_vpn_sessions(), 'startup_resources_busy'
        request_scan_mode(desired_scan)
        changed = True
    record.update(phase='restored', restored=True, restored_at=time.time())
    n.atomic(SELECTION_RECORD, profiles.canonical(record))
    if has_lock:
        os.unlink(NETWORK_LOCK)
    return {'restored': True, 'changed': changed}


def set_network_lock(selected, mcc=None, mnc=None):
    operator = selected['operator']
    target_mcc = str(mcc or '460')
    serving = serving_network_snapshot()
    current_home = (serving.get('mnc') if serving.get('mcc') == '460' and
                    serving.get('mnc') in profiles.OPERATOR_MNCS[operator] else None)
    target_mnc = str(mnc or current_home or PRIMARY_LTE_MNCS[operator])
    assert profiles.match(r'[0-9]{3}', target_mcc) and profiles.match(r'[0-9]{2,3}', target_mnc), 'invalid_plmn'
    applied = apply_network_selection(selected, target_mcc, target_mnc, reason='explicit_lock')
    lock = {
        'owner': policy.OWNER,
        'operator': operator,
        'sim_sha256': selected['sim_sha256'],
        'mcc': target_mcc,
        'mnc': target_mnc,
        'at': time.time(),
    }
    n.atomic(NETWORK_LOCK, profiles.canonical(lock))
    try:
        ensure_lte_mode(selected)
    except Exception:
        try:
            restore_network_selection()
        except Exception:
            pass
        try:
            restore_lte_mode()
        except Exception:
            pass
        raise
    return {'network_locked': True, 'operator': operator, 'target_plmn': target_mcc + '-' + target_mnc,
            'lte_only_applied': True, 'scan_mode': scan_mode_snapshot(),
            'phase': applied['phase']}


def clear_network_lock():
    assert_policy_idle()
    result = restore_network_selection(preserve_locked_sim=None)
    if not os.path.isfile(BASE + '/enabled'):
        restore_lte_mode()
    return {'network_locked': False, 'restored': result['restored'],
            'changed': result.get('changed', False), 'scan_mode': scan_mode_snapshot()}


def ensure_lte_mode(selected, allow_rplmn_attach=False):
    """Use LTE only while enabled; reconcile wireless_manager mode shifts."""
    global deferred_lte_lock
    assert_policy_idle()
    current = mode_snapshot()
    previous = s.load(MODE_RECORD) if os.path.isfile(MODE_RECORD) else None
    if previous:
        assert previous['owner'] == policy.OWNER
    target = {'enabled_technologies': 16, 'preferred_technologies': 0}
    if allow_rplmn_attach:
        serving = serving_network_snapshot()
        if serving.get('power_on') is True and serving.get('lte') is False:
            if current['enabled_technologies'] & 16:
                deferred_lte_lock = not same_mode(current, target)
                if not deferred_lte_lock and previous and not previous.get('restored') and previous.get('phase') != 'ready':
                    previous.update(applied=target, phase='ready')
                    n.atomic(MODE_RECORD, profiles.canonical(previous))
                return
            target = {'enabled_technologies': (current['enabled_technologies'] & 3) | 16, 'preferred_technologies': 0}
            deferred_lte_lock = target['enabled_technologies'] != 16
        else:
            deferred_lte_lock = False
    else:
        deferred_lte_lock = False
    if same_mode(current, target):
        if previous and not previous.get('restored') and previous.get('phase') != 'ready':
            previous.update(applied=target, phase='ready')
            n.atomic(MODE_RECORD, profiles.canonical(previous))
        return
    assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}, 'network_mode_requires_fresh_boot'
    if previous and not previous.get('restored'):
        record = dict(previous)
        owned = [previous['before'], previous['applied']]
        if 'transition_from' in previous:
            owned.append(previous['transition_from'])
        if not any(same_mode(current, value) for value in owned):
            record['external_mode_reconciled'] = dict(current)
    else:
        record = {'owner': policy.OWNER, 'before': current}
    # Preserve the original pre-VoLTE mode across wireless_manager / Settings
    # adjustments and interrupted replies; restore_lte_mode returns to before.
    record.update(applied=target, transition_from=current)
    record.update(boot=s.boot_token(), phase='applying', restored=False,
                  operator=selected['operator'], sim_sha256=selected['sim_sha256'])
    n.atomic(MODE_RECORD, profiles.canonical(record))
    request_mode(record['applied'])
    assert same_mode(mode_snapshot(), record['applied']), 'network_mode_readback_failed'
    record['phase'] = 'ready'
    n.atomic(MODE_RECORD, profiles.canonical(record))


def restore_lte_mode():
    global deferred_lte_lock
    deferred_lte_lock = False
    if not os.path.isfile(MODE_RECORD):
        return
    record = s.load(MODE_RECORD)
    assert record['owner'] == policy.OWNER
    if record.get('restored'):
        return
    assert_policy_idle()
    current = mode_snapshot()
    owned = [record['before'], record['applied']]
    if 'transition_from' in record:
        owned.append(record['transition_from'])
    if not any(same_mode(current, value) for value in owned):
        # Preserve an independent user or wireless_manager selection instead of
        # overwriting it or aborting disable/uninstall into cleanup_required.
        record.update(phase='restored', restored=True, external_mode_preserved=current)
        n.atomic(MODE_RECORD, profiles.canonical(record))
        return
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
    from unified_install import verify_backup_receipt
    verify_backup_receipt()
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


def source_versions(original):
    return {'original': original, 'data': dca.payload(original, 'data_centric'),
            'voice': dca.payload(original, 'voice_centric')}


def write_source(record, name, before, after, files, versions):
    choices = versions[name]
    record['source_write'] = {
        'name': name, 'identity': list(files[name]['identity']),
        'before': next(key for key in choices if choices[key] == before),
        'after': next(key for key in choices if choices[key] == after)}
    n.atomic(RECORD, profiles.canonical(record))
    dca.write_existing(dca.source_path(name), before, after, files[name])
    del record['source_write']


def finish_source_write(record, files, versions):
    pending = record.get('source_write')
    if pending is None:
        return
    assert record['phase'] in ('applying', 'republishing_original', 'republishing_data'), 'dca_write_phase_changed'
    name = pending['name']
    assert name in files and pending['identity'] == list(files[name]['identity']), 'dca_write_identity_changed'
    before, after = (versions[name][pending[key]] for key in ('before', 'after'))
    assert before != after, 'dca_write_invalid'
    path = dca.source_path(name)
    info = os.lstat(path)
    assert not os.path.islink(path) and [info.st_ino, info.st_mode & 0o7777, info.st_uid, info.st_gid] == pending['identity'], 'dca_write_identity_changed'
    current = n.read(path)
    assert dca.interrupted_write_matches(current, before, after), 'dca_source_changed'
    # A full readback may follow an interruption before the source was synced.
    dca.write_existing(path, current, after, files[name])
    del record['source_write']
    n.atomic(RECORD, profiles.canonical(record))
    return name, after


def set_usage(desired, selected):
    assert desired in (0, 1)
    context()
    radio.verify()
    assert_policy_idle()
    files, values = originals()
    previous = s.load(RECORD) if os.path.isfile(RECORD) else None
    versions = {name: source_versions(raw) for name, raw in values.items()}
    if previous is not None:
        assert previous['owner'] == policy.OWNER
    current_usage = radio.ue_usage_policy()
    assert current_usage in (0, 1)
    current = {name: n.read(dca.source_path(name)) for name in dca.SOURCES}
    pending_name = (previous or {}).get('source_write', {}).get('name')
    for name, raw in current.items():
        assert name == pending_name or raw in versions[name].values(), 'dca_source_changed'
        if raw != values[name] or current_usage != 0:
            assert previous is not None, 'unowned_dca_policy'
    if pending_name is not None:
        name, raw = finish_source_write(previous, files, versions)
        current[name] = raw
    targets = {name: choices['data' if desired else 'original'] for name, choices in versions.items()}
    changed = current_usage != desired or current != targets
    if not changed:
        if previous and previous.get('phase') in ('applying', 'republishing_original', 'republishing_data'):
            assert 'error_type' not in dca.publish(BACKUP, 'auto-usage'), 'dca_publish_failed'
            assert radio.ue_usage_policy() == desired, 'usage_readback_failed'
            assert all(n.read(dca.source_path(name)) == targets[name] for name in dca.SOURCES), 'dca_source_changed'
            previous.update(phase='ready', desired=desired)
            n.atomic(RECORD, profiles.canonical(previous))
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
            write_source(record, name, current[name], targets[name], files, versions)
    record['publish'] = dca.publish(BACKUP, 'auto-usage')
    assert 'error_type' not in record['publish'], 'dca_publish_failed'
    if desired == 0 and radio.ue_usage_policy() != 0:
        # Stock missing-key state alone does not necessarily revert NV.
        record.update(policy_changed_boot=token, source_repair_only=False)
        n.atomic(RECORD, profiles.canonical(record))
        for name in dca.SOURCES:
            write_source(record, name, targets[name], versions[name]['voice'], files, versions)
        result = dca.publish(BACKUP, 'auto-explicit-original')
        assert 'error_type' not in result, 'dca_publish_failed'
        for unused in range(8):
            if radio.ue_usage_policy() == 0:
                break
            time.sleep(3)
        assert radio.ue_usage_policy() == 0, 'usage_restore_unconfirmed'
        for name in dca.SOURCES:
            write_source(record, name, versions[name]['voice'], targets[name], files, versions)
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
            write_source(record, name, targets[name], versions[name]['voice'], files, versions)
        result = dca.publish(BACKUP, 'auto-republish-original')
        assert 'error_type' not in result and radio.ue_usage_policy() == 0, 'usage_baseline_unconfirmed'
        assert s.phone_idle() and not n.ims_pids() and not n.active_vpn_sessions()
        record['phase'] = 'republishing_data'
        n.atomic(RECORD, profiles.canonical(record))
        for name in dca.SOURCES:
            write_source(record, name, versions[name]['voice'], targets[name], files, versions)
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


def prepare(selected, allow_rplmn_attach=False):
    wait_policy_idle()
    restore_network_selection(preserve_locked_sim=selected.get('sim_sha256'))
    lock = configured_network_lock(selected.get('sim_sha256'))
    if lock is not None and mobile_radio_state() == 'ON':
        apply_network_selection(selected, lock.get('mcc'), lock.get('mnc'), reason='saved_lock')
        ensure_lte_mode(selected)
    elif allow_rplmn_attach:
        ensure_lte_mode(selected, allow_rplmn_attach=True)
    else:
        ensure_lte_mode(selected)
    wait_policy_idle()
    # Q10/Mobile previously lost LTE after CS-domain rejection 18. Passport/
    # Mobile also lost its bearer and call after that rejection with usage=0,
    # although its configured LTE mask stayed enabled. Data-centric is the
    # candidate mitigation for Passport; longer real calls remain a release
    # gate. Apply only through the backed-up, idle-before-IMS transaction.
    exp_usage = ((selected.get('request') or {}).get('profile', {}).get('experimental', {}).get('ue_usage', 'auto')
                 if selected.get('operator') == 'other' else 'auto')
    desired = 1 if (selected['operator'] == 'telecom' or
                    selected['family'] in ('q10', 'p9983', 'passport') and selected['operator'] == 'mobile' or
                    selected['operator'] == 'other' and exp_usage == 'data_centric') else 0
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


def restore_radio_overrides(raise_error=True, preserve_locked_sim=None):
    """Release owned network-selection and LTE-only overrides, preserving first error."""
    first_error = None
    try:
        if preserve_locked_sim is None:
            restore_network_selection()
        else:
            restore_network_selection(preserve_locked_sim=preserve_locked_sim)
    except Exception as error:
        first_error = error
    try:
        restore_lte_mode()
    except Exception as error:
        if first_error is None:
            first_error = error
    if raise_error and first_error is not None:
        raise first_error
    return first_error


def restore_original():
    first_error = None
    result = None
    try:
        result = set_usage(0, {'operator': 'original', 'sim_sha256': None})
    except Exception as error:
        first_error = error
    radio_error = restore_radio_overrides(raise_error=False, preserve_locked_sim=None)
    if first_error is None:
        first_error = radio_error
    if first_error is not None:
        raise first_error
    return result
