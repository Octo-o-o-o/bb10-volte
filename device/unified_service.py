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
core_stopping = s.stopping
core_configure = s.configure
core_collect = s.collect_vpn_evidence
core_status = s.status
notification_boot = None
attention_boot = None
sim_notice_boot = None

# Only terminal, actionable outcomes are alerts. Network/SIM waits, opaque
# errors, registration timeouts and native exit during shutdown stay silent.
ATTENTION_ERRORS = ('network_mode_rejected', 'network_mode_readback_failed',
    'network_mode_changed', 'network_mode_requires_fresh_boot',
    'usage_readback_failed', 'usage_restore_unconfirmed', 'dca_publish_failed',
    'reboot_required')
NOTICE_TEXT = {
    'sim_restart': ('SIM 卡已更换 / SIM changed',
        '已确认更换 SIM 卡。请使用电源菜单正常重启，让后台重新识别运营商；需要查看状态时可打开 BB10 VoLTE。\nThe SIM has changed. Restart normally to select the new carrier. Open BB10 VoLTE to review status.',
        'SIM 卡已更换，请正常重启'),
    'sim_review': ('已识别更换后的 SIM / Changed SIM detected',
        '本次开机已识别更换后的 SIM。可打开 BB10 VoLTE 查看当前状态和下一步，不要重复启用；是否需要再次重启以应用的明确提示为准。\nThis boot detected a different SIM. Open BB10 VoLTE to review status and next steps. Do not enable repeatedly or restart again unless prompted.',
        '已识别新 SIM，可打开应用查看'),
    'connected': ('VoLTE 服务已连接 / VoLTE connected',
        '本次开机已完成 IMS 注册，可用系统拨号器测试通话和声音。\nIMS registered on this boot. Test calls and audio with the system dialer.',
        'VoLTE 已连接'),
    'restart': ('VoLTE 需要正常重启 / Restart needed',
        '本次配置步骤已完成，需要正常重启。请打开 BB10 VoLTE 查看下一步。\nThis configuration step completed. Open BB10 VoLTE for the normal restart step.',
        'VoLTE 需要重启，请查看应用'),
    'task_failed': ('VoLTE 任务未完成 / VoLTE task incomplete',
        '备份步骤未完成。请打开 BB10 VoLTE 查看原任务和处理步骤。\nThe backup step did not complete. Open BB10 VoLTE to review the saved task.',
        'VoLTE 任务未完成，请查看应用'),
    'activation_failed': ('VoLTE 启动未完成 / VoLTE setup incomplete',
        '本次启动已停止并恢复通话配置。请打开 BB10 VoLTE 查看处理步骤。\nStartup stopped and the voice configuration was restored. Open BB10 VoLTE to review the next step.',
        'VoLTE 启动未完成，请查看应用'),
    'recovery': ('VoLTE 需要检查 / VoLTE needs attention',
        '配置恢复未完成。请打开 BB10 VoLTE 查看状态和恢复步骤。\nConfiguration restoration did not complete. Open BB10 VoLTE to review recovery.',
        'VoLTE 需要检查，请查看应用'),
}


def save(path, value):
    n.atomic(path, profiles.canonical(value))


def save_if_changed(path, value):
    if not os.path.isfile(path) or s.load(path) != value:
        save(path, value)


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
    from unified_install import verify_backup_receipt, management_identity
    verify_backup_receipt()
    assert s.load(BASE + '/backup/manifest.json')['variant'] == facts['variant'], 'backup_device_changed'
    if os.path.isfile(BASE + '/management.json'):
        management_identity(facts)
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
    s.boot_token, s.restore, s.prepare_connection = boot_token, locked_restore, locked_prepare
    s.stopping, s.configure = stopping, configure
    s.collect_vpn_evidence = collect
    s.status = status
    s.live = live
    n.verify_stock = verify_native


def notification_ready(value):
    """Use the same live registration boundary as the mobile home screen."""
    current = value.get('current') or {}
    return (all(value.get(key) is True for key in (
                'enabled', 'status_from_current_boot', 'selected_this_boot',
                'current_sim_matches', 'manager_alive', 'native_alive'))
            and value.get('phase') == 'running'
            and current.get('ims') == 'connected'
            and current.get('register_status') == '200 OK'
            and current.get('ran') in ('LTE', 'lte')
            and current.get('radio') == ['lte'])


def notify_connection():
    """One best-effort popup and Hub item per boot, independent of the UI.

    Reserve the attempt durably before notifying. An ambiguous timeout or
    process restart must not repeat an alert. The helper has a bounded lifetime;
    notification failures must never enter the modem's recovery path.
    """
    global notification_boot
    token = boot_token(False)
    if token is None or notification_boot == token or selected is None:
        return
    receipt_path = BASE + '/state/connection-notification.json'
    if os.path.isfile(receipt_path) and s.load(receipt_path).get('boot') == token:
        notification_boot = token
        return
    if s.stopping() or s.child is None or s.child.poll() is not None:
        return
    if not s.j or s.j.get('boot') != token or s.j.get('native_pid') != s.child.pid:
        return
    value = s.read_status()
    value['selected_this_boot'] = selected.get('boot') == token
    current = policy.select(device_info.read_identity(), card())
    value['current_sim_matches'] = current['sim_sha256'] == selected['sim_sha256']
    if not notification_ready(value):
        return
    receipt = {'schema': 1, 'boot': token, 'at': time.time(), 'state': 'attempted'}
    save(receipt_path, receipt)
    notification_boot = token
    item = 'bb10volte_' + n.digest(profiles.canonical(token))[:24]
    try:
        # Keep notification I/O outside the IMS manager process.
        result = json.loads(n.command([sys.executable, BASE + '/device/unified_service.py',
                                       'notify-connected', item], timeout=5).decode('ascii'))
        assert isinstance(result, dict) and set(result) == set(('hub', 'popup', 'popup_dismissal'))
        assert all(v in ('accepted', 'error', 'unconfirmed') for v in result.values())
        receipt.update(state='finished', result=result)
    except Exception as error:
        receipt.update(state='unconfirmed', error_type=type(error).__name__)
    save(receipt_path, receipt)


def notify_attention(phase, error=None):
    """One conservative action-needed notice per boot, after a known outcome."""
    global attention_boot
    reason = ('restart' if phase == 'carrier_reboot_required' else
              'recovery' if phase == 'cleanup_required' else
              'activation_failed' if phase == 'error_restored' and error in ATTENTION_ERRORS else None)
    if reason is None or s.shutdown or core_stopping() or selected is None:
        return
    token = boot_token(False)
    if token is None or attention_boot == token or selected.get('boot') != token:
        return
    if not s.j or s.j.get('boot') != token:
        return
    path = BASE + '/state/attention-notification.json'
    for previous in (path, BASE + '/state/connection-notification.json'):
        if os.path.isfile(previous) and s.load(previous).get('boot') == token:
            attention_boot = token
            return
    current = policy.select(device_info.read_identity(), card())
    if current['sim_sha256'] != selected['sim_sha256']:
        return
    value = s.read_status()
    if (value.get('phase') != phase or not all(value.get(key) is True for key in
            ('enabled', 'status_from_current_boot', 'manager_alive')) or
            value.get('current', {}).get('power') != 'ON' or
            value.get('current', {}).get('ims') != 'disconnected' or
            value.get('native_alive') is not False):
        return
    if reason == 'activation_failed' and s.j.get('configuration_restored') is not True:
        return
    receipt = {'schema': 1, 'boot': token, 'at': time.time(), 'state': 'attempted', 'reason': reason}
    save(path, receipt)
    attention_boot = token
    item = 'bb10volte_' + n.digest(profiles.canonical([token, 'attention']))[:24]
    try:
        result = json.loads(n.command([sys.executable, BASE + '/device/unified_service.py',
            'notify-attention', item, reason], timeout=5).decode('ascii'))
        assert isinstance(result, dict) and set(result) == set(('hub', 'popup', 'popup_dismissal'))
        assert all(v in ('accepted', 'error', 'unconfirmed') for v in result.values())
        receipt.update(state='finished', result=result)
    except Exception as failure:
        receipt.update(state='unconfirmed', error_type=type(failure).__name__)
    save(path, receipt)


def ready_sim_hash(snapshot):
    """A supported carrier is not required to identify a physical SIM change."""
    if not isinstance(snapshot, dict) or snapshot.get('state') != 'READY':
        return None
    imsi = snapshot.get('imsi')
    if not isinstance(imsi, str) or not profiles.identity_matches(imsi, snapshot.get('mcc'), snapshot.get('mnc')):
        return None
    return n.digest(imsi.encode('ascii'))


def notify_sim_change(previous, snapshot, after_reboot=False):
    """Known identity change only; no additional watcher or retry timer."""
    global sim_notice_boot
    try:
        if (not isinstance(previous, dict) or s.shutdown or core_stopping() or
                not os.path.isfile(BASE + '/enabled') or not s.phone_idle()):
            return
        token = boot_token(False)
        old_boot = previous.get('boot')
        if (token is None or sim_notice_boot == token or not isinstance(old_boot, list) or
                len(old_boot) != 2 or old_boot[0] != token[0] or
                not isinstance(old_boot[1], str) or not re.match(r'\A[a-f0-9]{48}\Z', old_boot[1]) or
                (old_boot != token) is not after_reboot):
            return
        old_hash, new_hash = previous.get('sim_sha256'), ready_sim_hash(snapshot)
        if (not isinstance(old_hash, str) or not re.match(r'\A[a-f0-9]{64}\Z', old_hash) or
                new_hash is None or new_hash == old_hash or ready_sim_hash(card()) != new_hash):
            return
        path = BASE + '/state/sim-notification.json'
        if os.path.isfile(path) and s.load(path).get('boot') == token:
            sim_notice_boot = token
            return
        kind = 'sim_review' if after_reboot else 'sim_restart'
        receipt = {'schema': 1, 'boot': token, 'at': time.time(), 'state': 'attempted', 'reason': kind}
        save(path, receipt)
        sim_notice_boot = token
        item = 'bb10volte_' + n.digest(profiles.canonical([token, 'sim-change']))[:24]
        try:
            result = json.loads(n.command([sys.executable, BASE + '/device/unified_service.py',
                'notify-attention', item, kind], timeout=5).decode('ascii'))
            assert isinstance(result, dict) and set(result) == set(('hub', 'popup', 'popup_dismissal'))
            assert all(v in ('accepted', 'error', 'unconfirmed') for v in result.values())
            receipt.update(state='finished', result=result)
        except Exception as failure:
            receipt.update(state='unconfirmed', error_type=type(failure).__name__)
        save(path, receipt)
    except Exception:
        pass  # Missing identity/receipt/UI evidence never changes the SIM lifecycle.


def status(phase, error=None, details=None, observation=None):
    core_status(phase, error, details, observation=observation)
    if phase == 'running':
        try:
            notify_connection()
        except Exception:
            # A notification, receipt, library or UI failure is never an IMS
            # failure and must not restore or restart a working voice service.
            pass
    elif phase in ('carrier_reboot_required', 'error_restored', 'cleanup_required'):
        try:
            notify_attention(phase, error)
        except Exception:
            pass  # Unavailable evidence or notification I/O never changes IMS.


def connection_toast(kind='connected'):
    """Native bottom toast: an explicit dismiss button and an absolute wait cap."""
    import ctypes as C
    lib = C.CDLL('libbps.so.3', use_errno=True)
    pointer, integer, boolean, string = C.c_void_p, C.c_int, C.c_bool, C.c_char_p
    def bind(name, args, result=integer):
        function = getattr(lib, name)
        function.argtypes, function.restype = args, result
        return function
    initialize = bind('bps_initialize', [])
    shutdown = bind('bps_shutdown', [], None)
    request = bind('dialog_request_events', [integer])
    create = bind('dialog_create_toast', [C.POINTER(pointer)])
    system = bind('dialog_set_system', [pointer, boolean])
    position = bind('dialog_set_toast_position', [pointer, integer])
    message = bind('dialog_set_toast_message_text', [pointer, string])
    button = bind('dialog_add_button', [pointer, string, boolean, string, boolean])
    automatic = bind('dialog_set_cancel_required', [pointer, boolean])
    show = bind('dialog_show', [pointer])
    cancel = bind('dialog_cancel', [pointer])
    destroy = bind('dialog_destroy', [pointer])
    event = bind('bps_get_event', [C.POINTER(pointer), integer])
    event_domain = bind('bps_event_get_domain', [pointer])
    domain = bind('dialog_get_domain', [])
    instance = bind('dialog_event_get_dialog_instance', [pointer], pointer)
    def checked(code):
        if code != 0:
            raise RuntimeError('toast_api_failed')
    checked(initialize())
    toast = pointer()
    result = dict(popup='error', popup_dismissal='unconfirmed')
    try:
        checked(request(0))
        checked(create(C.byref(toast)))
        checked(system(toast, True))
        checked(position(toast, 2))  # Bottom center, not a modal alert.
        checked(message(toast, NOTICE_TEXT[kind][2].encode('utf-8')))
        checked(button(toast, '关闭'.encode('utf-8'), True, b'dismiss', True))
        checked(automatic(toast, False))  # Button selection closes immediately.
        try:
            deadline = time.time() + 1.5
            checked(show(toast))
            result['popup'] = 'accepted'
            # The platform's button-toast timer can wait for a first touch.
            # Our independent 1.5-second wait cap starts at show(), even if the
            # phone is idle/locked or the user never sees the toast.
            for unused in range(15):
                remaining_ms = int((deadline - time.time()) * 1000)
                if remaining_ms <= 0:
                    break
                value = pointer()
                checked(event(C.byref(value), min(100, remaining_ms)))
                if value.value and event_domain(value) == domain() and instance(value) == toast.value:
                    break
        finally:
            result['popup_dismissal'] = 'accepted' if cancel(toast) == 0 else 'error'
    except Exception:
        pass  # Keep a successful Hub notification and the voice service alive.
    finally:
        try:
            if toast.value:
                destroy(toast)
        finally:
            shutdown()
    return result


def deliver_connection_notification(item, kind='connected'):
    """A persistent Hub event plus a separate short, dismissible native toast."""
    import errno
    import select
    assert re.match(r'\Abb10volte_[a-f0-9]{24}\Z', item), 'invalid_notification_id'
    assert kind in NOTICE_TEXT, 'invalid_notification_kind'
    result = dict(hub='unconfirmed', popup='error', popup_dismissal='unconfirmed')
    payload = {'Title': NOTICE_TEXT[kind][0], 'Subtitle': NOTICE_TEXT[kind][1],
               'Type': 'uib', 'AppId': 'sys.service', 'ItemId': item + '_hub'}
    request = item + '_hub'
    packet = ('id::' + request + '\nmsg::Notify\ndat:json:' +
              json.dumps(payload, ensure_ascii=True, separators=(',', ':')) + '\n').encode('ascii')
    fd = None
    try:
        fd = os.open('/pps/system/notify/control', os.O_RDWR | os.O_NONBLOCK)
        try:
            os.read(fd, 65536)
        except OSError as error:
            if error.errno not in (errno.EAGAIN, errno.EWOULDBLOCK):
                raise
        if os.write(fd, packet) != len(packet):
            result['hub'] = 'error'
        else:
            for unused in range(20):
                if not select.select([fd], [], [], 0.05)[0]:
                    continue
                text = os.read(fd, 65536).decode('utf-8')
                fields = dict(line.split('::', 1) for line in text.splitlines() if '::' in line)
                if fields.get('id') != request or fields.get('res', '').lower() != 'notify':
                    continue
                if fields.get('err'):
                    result['hub'] = 'error'
                    break
                if fields.get('dat') == 'ok':
                    result['hub'] = 'accepted'
                    break
    except Exception:
        result['hub'] = 'error'
    finally:
        if fd is not None:
            os.close(fd)
    # No Cancel/Delete is ever sent to the notification service. Closing the
    # native toast cannot remove the Hub item or another sys.service event.
    try:
        result.update(connection_toast() if kind == 'connected' else connection_toast(kind))
    except Exception:
        pass
    return result


def locked_prepare():
    from unified_install import management_lock
    with management_lock(blocking=True):
        assert os.path.isfile(BASE + '/enabled'), 'automatic_service_disabled'
        return prepare()


def locked_restore(previous_boot=False):
    from unified_install import management_lock
    with management_lock(blocking=True):
        return restore(previous_boot)


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
    previous = s.load(SELECTION) if os.path.isfile(SELECTION) else None
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
                notify_sim_change(previous, snapshot, after_reboot=True)
                return False
            break
        s.status('waiting_for_sim')
        time.sleep(3)
    assert selected is not None, 'sim_not_ready'
    assert policy.transition(previous, selected, boot_token(),
        n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}, attempt) != 'reboot_required', 'reboot_required'
    s.ACTIVE_REQUEST, s.ACTIVE_PROFILE = selected['request'], selected['request']['profile']
    template, unused_xml = profiles.carrier_template(s.ACTIVE_PROFILE, '460', s.ACTIVE_PROFILE['carrier']['mncs'][0])
    selected = policy.bind_template(selected, template)
    selected.update(boot=boot_token(), selected_unix=time.time())
    s.ACTIVE_REQUEST, s.ACTIVE_PROFILE = selected['request'], selected['request']['profile']
    s.UPDATES = s.profile_updates(s.ACTIVE_PROFILE, '460', s.ACTIVE_PROFILE['carrier']['mncs'][0])
    save(SELECTION, selected)
    notify_sim_change(previous, snapshot, after_reboot=True)
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
    reconcile_stale_sms_busy(facts, selected, previous)
    s.configure()
    assert not n.ims_pids()
    return True


def configure():
    core_configure()
    s.j.update(sim_sha256=selected['sim_sha256'], operator=selected['operator'],
               lifecycle='retain-provider-until-reboot')
    s.save_journal()


def sms_native_state(name, path, expected_hash, windows, fields):
    """Read known native state through an O_RDONLY process descriptor."""
    import struct
    image = n.read(path)
    assert n.digest(image) == expected_hash, 'sms_native_image_unknown'
    output = n.command(['/bin/pidin', '-p', name, '-f', 'a']).decode('ascii')
    pids = set(re.findall(r'^\s*(\d+)\s*$', output, re.M))
    assert len(pids) == 1, 'sms_native_process_ambiguous'
    pid = pids.pop()
    mapping = n.command(['/bin/pidin', '-p', pid, 'mem']).decode('ascii')
    bases = set(re.findall(r'^\s+' + re.escape(name) + r'\s+@\s*([0-9a-fA-F]+)', mapping, re.M))
    assert len(bases) == 1, 'sms_native_mapping_unknown'
    bias = int(bases.pop(), 16)
    fd = os.open('/proc/' + pid + '/as', os.O_RDONLY)
    try:
        def read_at(offset, size):
            os.lseek(fd, bias + offset, os.SEEK_SET)
            raw = os.read(fd, size)
            assert len(raw) == size, 'sms_native_read_incomplete'
            return raw
        assert read_at(0, 4) == b'\x7fELF', 'sms_native_mapping_unknown'
        for offset, size in windows:
            assert read_at(offset, size) == image[offset:offset + size], 'sms_native_code_changed'
        values = {}
        for key, (offset, size) in fields.items():
            raw = read_at(offset, size)
            values[key] = struct.unpack('<I', raw)[0] if size == 4 else raw[0]
        return {'pid': pid, 'base': bias, 'values': values}
    finally:
        os.close(fd)


def sms_idle_snapshot():
    """Two independent native layers; offsets apply only to these exact images."""
    producer = sms_native_state('cellular-services', '/radio/bin/cellular-services',
        '750690d27b75005a579d9573e46fa98f50b2c036f35565a000d272b2d2707655',
        ((0x17c9c, 128), (0x17e14, 100)),
        {'busy': (0x7e40c, 1), 'state_138': (0x7d570 + 0x138, 4),
         'state_140': (0x7d570 + 0x140, 4), 'state_e9d': (0x7e40d, 1),
         'state_eb4': (0x7d570 + 0xeb4, 4)})
    modem = sms_native_state('qct_rrm', '/radio/bin/qct_rrm',
        '71835f701affcb9254eadb4ee299e8f7d07547543b3e0f61519456b8241dcb3b',
        ((0xe626c, 128), (0xe4f18, 128)),
        {'rl_state': (0x19ed4c + 8, 4), 'stored_sms': (0x19ed4c + 0x20d, 1)})
    assert all(v == 0 for row in (producer, modem) for v in row['values'].values()), 'sms_native_busy'
    return {'producer': producer, 'modem': modem}


def reconcile_stale_sms_busy(facts, choice, previous):
    """Before the first IMS launch, reconcile a proven stale PPS busy flag.

    This does not complete, cancel or retransmit a message. Native memory and
    message stores remain read-only. Restoring the old true flag on uninstall
    would recreate a false native state, so this is retained diagnostic evidence,
    not an owned carrier setting.
    """
    models = {'SQW100-1': 'WINDERMEREEMEA', 'SQW100-4': 'WINDERMERE4ROW'}
    if (facts.get('variant') not in models or facts.get('board_type') != models[facts['variant']]
            or facts.get('os_version') != '10.3.3.3216'
            or choice.get('operator') not in ('mobile', 'unicom')):
        return 'out_of_scope'
    token = boot_token(False)
    if not token or not previous or previous.get('boot') == token:
        return 'normal_boot_not_proven'
    path = '/pps/services/cellular/sms/status'
    record = BASE + '/state/sms-busy-recovery.json'
    if os.path.isfile(record) and s.load(record).get('boot') == token:
        return 'already_checked'
    marker = os.stat('/tmp/root.done')
    root_marker = [marker.st_ino, marker.st_mtime]
    receipt = {'schema': 1, 'owner': policy.OWNER, 'boot': token,
               'at': time.time(), 'state': 'checking', 'sim_sha256': choice['sim_sha256']}
    archive = None
    try:
        before = n.read(path)
        if n.value(n.attrs(before), 'smsServiceBusy') is not True:
            return 'not_busy'
        def guarded_idle():
            assert os.geteuid() == 0 and not core_stopping(), 'sms_recovery_stopped'
            current_marker = os.stat('/tmp/root.done')
            assert [current_marker.st_ino, current_marker.st_mtime] == root_marker, 'sms_boot_changed'
            assert boot_token(False) == token, 'sms_boot_changed'
            assert policy.select(facts, card())['sim_sha256'] == choice['sim_sha256'], 'sms_sim_changed'
            assert s.phone_idle() and not n.ims_pids(), 'sms_recovery_not_idle'
            assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}, 'sms_recovery_not_idle'
            return sms_idle_snapshot()
        first = guarded_idle()
        time.sleep(1)
        second = guarded_idle()
        assert first == second and n.read(path) == before, 'sms_state_changed'
        receipt.update(state='prepared', before_status=before.decode('utf8'),
                       before_sha256=n.digest(before), native_idle=first,
                       message_outcomes_changed=False, native_memory_modified=False)
        archive = BASE + '/archive/sms-busy-' + binascii.hexlify(os.urandom(16)).decode('ascii') + '.json'
        assert not os.path.lexists(archive)
        save(archive, receipt)
        assert s.load(archive) == receipt, 'sms_backup_not_verified'
        save(record, receipt)
        # Re-read immediately before the sole write, including producer PIDs.
        assert guarded_idle() == first and n.read(path) == before, 'sms_state_changed'
        receipt['state'] = 'write_intent'
        save(record, receipt)
        n.update_pps(path, {'smsServiceBusy': 'b:false'})
        receipt['state'] = 'field_written'
        save(record, receipt)
        after = n.read(path)
        before_attrs, after_attrs = n.attrs(before), n.attrs(after)
        assert after_attrs.get('smsServiceBusy') == 'b:false', 'sms_busy_readback_changed'
        assert {k: v for k, v in after_attrs.items() if k != 'smsServiceBusy'} == {
            k: v for k, v in before_attrs.items() if k != 'smsServiceBusy'}, 'sms_status_changed'
        assert guarded_idle() == first, 'sms_state_changed'
        receipt.update(state='reconciled', after_status=after.decode('utf8'), after_sha256=n.digest(after))
    except Exception as error:
        # An unknown image, busy queue or changed identity never permits a write.
        # Do not retry or restart IMS in this boot after an ambiguous outcome.
        receipt.update(state='unconfirmed' if receipt['state'] in ('write_intent', 'field_written') else 'deferred',
                       error_type=type(error).__name__)
    if archive is not None:
        save(archive, receipt)
    save(record, receipt)
    return receipt['state']


def collect():
    core_collect()
    if selected is None or not s.j or s.j.get('boot') != boot_token() or not s.j.get('native_pid'):
        return
    try:
        import unified_operator_name
        unified_operator_name.synchronize(selected, boot_token())
    except Exception as error:
        save_if_changed(BASE + '/state/operator-name-status.json', {'error_type': type(error).__name__})
    current = live()
    if current['ims'] == 'connected' and current['register_status'] == '200 OK':
        try:
            import unified_own_number
            result = unified_own_number.synchronize(n, s.j['native_pid'], boot_token(), s.current_usim(),
                                                    selected['sim_sha256'])
        except Exception as error:
            result = {'error_type': type(error).__name__, 'actual_number_exported': False}
        save_if_changed(BASE + '/state/own-number-status.json', result)


def stopping():
    if core_stopping():
        return True
    if selected is None or s.child is None:
        return False
    try:
        snapshot = card()
        old_hash, current_hash = selected.get('sim_sha256'), ready_sim_hash(snapshot)
        # A missing/locked SIM, malformed identity or failed PPS read is not
        # proof of a replacement. Preserve the active native service.
        if (not isinstance(old_hash, str) or not re.match(r'\A[a-f0-9]{64}\Z', old_hash) or
                current_hash is None or current_hash == old_hash or not s.phone_idle() or
                ready_sim_hash(card()) != current_hash or not s.phone_idle()):
            return False
        notify_sim_change(selected, snapshot)
        if not s.phone_idle() or ready_sim_hash(card()) != current_hash:
            return False
        n.atomic(s.STOP, b'SIM changed; next normal boot selects current SIM\n')
        return True
    except Exception:
        # Observation/notification/storage failures cannot authorize a stop.
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
    value['management_schema'] = 2
    from unified_install import installed_management_schema
    value['installed_management_schema'] = installed_management_schema()
    value['installed_stage'] = 'managed' if value['installed_management_schema'] == 2 else 'legacy'
    value['current_sim_matches'] = None
    if os.path.isfile(SELECTION):
        saved = s.load(SELECTION)
        value['selected_operator'] = saved['operator']
        value['selected_this_boot'] = saved['boot'] == boot_token(False)
        try:
            current_selection = policy.select(device_info.read_identity(), card())
            value['current_sim_matches'] = current_selection['sim_sha256'] == saved['sim_sha256']
        except (OSError, ValueError, TypeError, KeyError):
            pass
    try:
        busy = n.value(n.attrs(n.read('/pps/services/cellular/sms/status')), 'smsServiceBusy')
        value['sms_service_busy'] = busy if type(busy) is bool else None
    except (OSError, ValueError, TypeError):
        value['sms_service_busy'] = None
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


def service_action(action):
    setup()
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
        if not active and os.path.isfile(s.STOP):
            assert n.read(s.STOP) == b'disabled by owner\n', 'stop_request_changed'
            os.unlink(s.STOP)
        result = {'disabled': True, 'reboot_required': True, 'restoration_pending': active}
    elif action == 'enable':
        verify()
        assert s.phone_idle(), 'call_active'
        assert not s.read_status().get('manager_alive'), 'restore_pending'
        n.atomic(BASE + '/enabled', b'automatic SIM selection re-enabled by owner\n')
        result = {'enabled': True, 'reboot_required': True}
    else:
        raise ValueError('unknown_action')
    return result


def main():
    if len(sys.argv) == 4 and sys.argv[1] == 'notify-attention':
        assert os.geteuid() == 0 and os.uname()[0] == 'QNX' and ctypes.sizeof(ctypes.c_void_p) == 4
        assert sys.argv[3] in ('restart', 'activation_failed', 'recovery', 'task_failed', 'sim_restart', 'sim_review')
        print(json.dumps(deliver_connection_notification(sys.argv[2], sys.argv[3])))
        return
    if len(sys.argv) == 3 and sys.argv[1] == 'notify-connected':
        assert os.geteuid() == 0 and os.uname()[0] == 'QNX' and ctypes.sizeof(ctypes.c_void_p) == 4
        print(json.dumps(deliver_connection_notification(sys.argv[2])))
        return
    from unified_install import manage
    print(json.dumps(manage('start' if sys.argv[1] == 'boot' else sys.argv[1])))


if __name__ == '__main__':
    main()
