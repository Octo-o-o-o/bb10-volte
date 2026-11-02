"""Phone-local transport, durable jobs and honest UI state. Python 3.2.

The shared device engine alone authorizes modem/configuration changes. No shell
text, arbitrary command, package member or user-supplied path is executable here.
"""
import binascii
import contextlib
import errno
import json
import os
import re
import signal
import stat
import sys
import time
import entry as e

ROOT = e.ROOT
JOBS = ROOT + '/jobs'
DOCS = '/accounts/1000/shared/documents'
SDCARD = '/accounts/1000/removable/sdcard'
PROFILE_IDS = ('china-unicom', 'china-mobile', 'china-telecom', 'china-telecom-46011')
JOB_ACTIONS = ('install', 'enable', 'disable', 'update', 'rollback', 'uninstall',
               'export', 'compatibility', 'legacy-install', 'legacy-start', 'legacy-stop',
               'legacy-update', 'legacy-uninstall')
TERMINAL = ('completed', 'failed', 'interrupted')

# Text is selected by state, never by a free-form native exception or modem log.
MESSAGES = {
    'ready_to_install': ('准备开启 VoLTE', '已通过当前设备检查。会先保存并校验原始备份，再配置自动服务。', '开启 VoLTE',
                         'Ready to enable VoLTE', 'Device checks passed. Original files will be backed up and verified first.', 'Enable VoLTE'),
    'working': ('正在处理', '可以离开此应用；任务在手机后台继续。请保持电量充足。', '查看进度',
                'Working', 'The task continues on the phone if you leave this app. Keep the battery charged.', 'Check progress'),
    'reboot_required': ('请正常重启手机', '使用电源菜单重启并解锁，等系统出现 Root 成功提示后，再打开应用一次。未打开时不要连续点图标。进入应用后会自动检查，网络可能需要约 3–5 分钟。', '立即检查',
                        'Restart your phone normally', 'Restart from the power menu and unlock. Wait for the system Root success notification, then open the app once. Do not tap repeatedly if it does not open. Checks run automatically inside the app; the network may take 3–5 minutes.', 'Check now'),
    'carrier_reboot_required': ('运营商配置已保存，请再重启一次', 'Passport 网络策略已变化，还需一次正常重启。解锁后先等系统 Root 成功提示，再打开应用一次；进入后会自动检查。不要连续点图标。', '立即检查',
                                'Carrier settings saved; restart again', 'The Passport network policy changed and needs another normal restart. Unlock, wait for the system Root success notification, then open the app once for automatic checking. Do not tap repeatedly.', 'Check now'),
    'registered': ('IMS 已连接，待通话验收', '请完成一次呼出和一次呼入，确认双方有声音且通话保持 LTE。', '验收通话',
                   'IMS connected; check calls', 'Make and receive a call. Confirm audio in both directions and LTE during the call.', 'Check calls'),
    'verified': ('当前 SIM 已完成通话验收', '本次开机、当前 SIM 和当前版本的双向通话已由你确认。短信能力请另外实测。', '刷新状态',
                 'Calls verified for this SIM', 'You confirmed calls for this boot, SIM and version. Test text messages separately.', 'Refresh'),
    'disabled': ('VoLTE 自动服务已停用', '需要使用时可重新启用，按任务提示正常重启，再检查 IMS 和通话。', '启用自动服务',
                 'Automatic service disabled', 'Enable the service when needed, restart when the task asks, then check IMS and calls.', 'Enable service'),
    'update_ready': ('手机服务可以更新', '现有服务已完成停用与恢复。使用应用内置版本更新，原始备份会保留，完成后按提示正常重启。', '更新手机服务',
                     'Phone service update ready', 'The existing service is stopped and restored. Apply the bundled update, keep the originals, then restart normally when prompted.', 'Update phone service'),
    'waiting': ('等待手机网络就绪', '此页面会自动检查。请保持移动网络和正常 LTE 数据可用；若长时间未就绪，可以导出不含身份信息的报告。', '立即检查',
                'Waiting for the network', 'This page checks automatically. Keep cellular and LTE data available; export a report if this persists.', 'Check now'),
    'waiting_ims': ('等待 IMS 通话注册', '通话注册与浏览器上网是不同的连接。此页面会自动检查；若持续等待，请导出诊断报告，不用反复点击检查或重新启用。', '立即检查',
                    'Waiting for IMS voice registration', 'Voice registration is separate from web access. This page checks automatically. If it keeps waiting, export a diagnostic report; repeated checks or enabling again are unnecessary.', 'Check now'),
    'waiting_ims_apn': ('等待通话专用网络', '正在等待运营商的 IMS 专用连接。浏览器能够上网仍不代表此连接已就绪，页面会自动检查。', '立即检查',
                        'Waiting for the IMS connection', 'Waiting for the carrier connection used by IMS. Web access alone does not confirm this connection is ready. This page checks automatically.', 'Check now'),
    'update_requires_stop': ('先停用旧版服务，再更新', '手机已有旧版服务。先停用并恢复配置，按提示正常重启后，首页会提供“更新手机服务”；原始备份会保留。', '停用旧版服务',
                             'Stop the old service before updating', 'An older service is installed. Stop it and restore its settings, then restart normally when prompted. The home page will offer Update phone service. Original backups are retained.', 'Stop old service'),
    'unsupported': ('需要进一步适配', '可以导出兼容性报告。检测到机型不代表已经验证可用；高级页面保留已有的实验路线。', '导出兼容性报告',
                    'Further adaptation needed', 'Export a compatibility report. Recognizing a model does not establish support. Existing experimental routes are in Advanced.', 'Export compatibility'),
    'sim_unsupported': ('当前 SIM 尚未通过检查', '请检查 SIM、LTE 数据服务及运营商 VoLTE 开通状态，换卡请关机后操作。', '重新检查',
                        'SIM checks incomplete', 'Check the SIM, LTE data and carrier VoLTE provisioning. Power off before changing SIMs.', 'Check again'),
    'recovery_required': ('需要检查上次操作', '已保留备份和任务记录。仅可继续已记录的可恢复步骤；请勿反复安装或删除文件。', '继续检查',
                          'Previous operation needs attention', 'Backups and the task journal are retained. Only recorded recoverable steps can resume.', 'Check recovery'),
    'uninstalled': ('已移除本项目服务', '原始备份和诊断记录仍保留。应用图标可在系统中单独卸载。', '刷新状态',
                    'Project service removed', 'Original backups and diagnostics are retained. Remove the app icon separately in the OS.', 'Refresh'),
    'ready_after_uninstall': ('恢复完成，可重新开启', '原始备份和旧记录仍保留。重新开启会建立新事务并再次校验备份。', '重新开启 VoLTE',
                              'Restored; ready to enable again', 'Original backups and old records remain. Enabling again creates a new verified transaction.', 'Enable VoLTE again'),
    'exported': ('文件已导出', '请在下方查看保存位置。内部存储备份不能防止手机丢失或存储损坏，建议另存一份。', '返回状态',
                 'Files exported', 'See the saved location below. Internal storage cannot protect against loss or storage failure; keep another copy.', 'Back to status'),
    'experimental': ('实验兼容性结果', '实验安装不会启用开机自启动。只有全部原生哈希、网络和恢复检查通过，才会提供可执行操作。', '刷新实验检查',
                     'Experimental compatibility', 'Experimental installs do not enable autostart. Actions require native hash, network and recovery checks.', 'Check experiment'),
    'error': ('操作未完成', '请查看下方提示或导出诊断报告，并保留现有文件。', '重新检查',
              'Operation incomplete', 'Read the details below or export diagnostics, and keep the existing files.', 'Check again'),
}


def nonce():
    return binascii.hexlify(os.urandom(16)).decode('ascii')


def checked_id(value):
    e.require(isinstance(value, str) and re.match(r'\A[a-f0-9]{32}\Z', value), 'invalid_operation_id')
    return value


def load(path, maximum=131072):
    return e.json_bytes(e.regular(path, maximum))


def save(path, value):
    # Every destination is in a root-private directory and never unlinked to
    # replace a lock inode. Journals use uniquely named atomic replacements.
    e.require(os.path.realpath(path) == path, 'unsafe_state_path')
    temporary = path + '.new-' + nonce()
    e.write_new(temporary, e.canonical(value))
    os.rename(temporary, path)


@contextlib.contextmanager
def job_lock(blocking=False):
    import fcntl
    e.private_directory(ROOT)
    e.private_directory(JOBS)
    path = JOBS + '/lock'
    e.require(not os.path.islink(path), 'job_lock_changed')
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        info, current = os.fstat(fd), os.lstat(path)
        e.require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and
                  info.st_mode & 0o077 == 0 and info.st_nlink == 1 and
                  (info.st_dev, info.st_ino) == (current.st_dev, current.st_ino), 'job_lock_changed')
        try:
            fcntl.lockf(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except IOError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN):
                raise e.MobileError('operation_in_progress')
            raise
        yield
        fcntl.lockf(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def engine():
    import unified_install
    return unified_install


def safe_error(error):
    code = str(error)
    return code if re.match(r'\A[a-z][a-z0-9_]{0,63}\Z', code) else 'preflight_or_recovery_check_failed'


def ui(state, language, action='status', details=None, ok=True, actions=None, **extra):
    values = MESSAGES.get(state, MESSAGES['error'])
    offset = 0 if language != 'en' else 3
    localized = {}
    for name, start in (('zh', 0), ('en', 3)):
        localized[name] = {'title': values[start], 'message': values[start + 1],
                           'primary_label': values[start + 2], 'level': 'error' if not ok else 'info'}
    result = {'schema': 2, 'ok': ok, 'state': state, 'title_code': state,
              'message_code': state, 'primary_action': action,
              'actions': actions if actions is not None else [action, 'compatibility'],
              'details': details or {}, 'display': {'title': values[offset],
              'message': values[offset + 1], 'primary_label': values[offset + 2],
              'level': 'error' if not ok else 'info'}, 'display_language': 'en' if language == 'en' else 'zh',
              'display_i18n': localized, 'call_context': ''}
    result.update(extra)
    return result


def sanitized_identity():
    import native as n
    result = {'variant': 'unknown', 'os_version': 'unknown', 'board_type': None}
    errors = []
    try:
        props = n.attrs(n.read('/pps/services/deviceproperties'))
        variant = n.value(props, 'modelnumber')
        if isinstance(variant, str) and re.match(r'\A[A-Z0-9]{2,12}-[0-9]{1,3}\Z', variant):
            result['variant'] = variant
    except Exception:
        errors.append('device_properties_unavailable')
    try:
        version = n.read('/etc/os.version').decode('ascii').strip()
        if re.match(r'\A[0-9.]{3,24}\Z', version):
            result['os_version'] = version
    except Exception:
        errors.append('os_version_unavailable')
    try:
        board = n.value(n.attrs(n.read('/pps/services/hw_info/inventory')), 'Board_Type')
        if isinstance(board, str) and re.match(r'\A[A-Z0-9_]{3,32}\Z', board):
            result['board_type'] = board
    except Exception:
        errors.append('board_unavailable')
    result['read_errors'] = errors
    return result


def compatibility_report(folder):
    """Partial read-only facts exist even when identity()/ABI gates reject."""
    import native as n
    import telecom_native
    checks = dict(n.STOCK_HASHES)
    checks.update({'/radio/bin/qct_rrm': telecom_native.QCT_HASH,
                   '/usr/sbin/dca': telecom_native.DCA_HASH})
    report = {'schema': 2, 'device': sanitized_identity(), 'native_files': {},
              'hardware_acceptance': 'not_established_by_detection',
              'mobile_version': load(folder + '/manifest.json')['version'],
              'identity_data_included': False, 'read_only': True}
    for path, expected in sorted(checks.items()):
        item = {'available': False, 'expected_match': False}
        try:
            data = e.regular(path)
            item.update(available=True, sha256=e.digest(data), expected_match=e.digest(data) == expected)
        except Exception:
            item['error'] = 'file_unavailable_or_unsafe'
        report['native_files'][path] = item
    report['root'] = {'uid0': os.geteuid() == 0, 'qnx': os.uname()[0] == 'QNX',
                      'autoroot_v4_marker': os.path.isfile('/tmp/root.done'),
                      'local_helper': os.path.isfile('/bin/__root')}
    report['next_step'] = 'evaluate_exact_native_abi_restore_and_real_calls'
    return report


def registered(status):
    current = status.get('current') or {}
    return (status.get('enabled') is True and status.get('status_from_current_boot') is True
            and status.get('selected_this_boot') is True and status.get('current_sim_matches') is True
            and status.get('phase') == 'running' and status.get('manager_alive') is True
            and status.get('native_alive') is True and current.get('ims') == 'connected'
            and current.get('register_status') == '200 OK' and current.get('ran') in ('LTE', 'lte')
            and current.get('radio') == ['lte'])


def call_context(create=True):
    import unified_service as u
    import carrier_policy as policy
    import device_info
    selection = policy.select(device_info.read_identity(), u.card())
    binding = {'boot': u.boot_token(False), 'sim': selection['sim_sha256'],
               'payload': e.digest(e.regular(policy.BASE + '/payload.json', 131072))}
    e.require(binding['boot'] is not None, 'boot_context_unavailable')
    path = ROOT + '/call-context.json'
    prior = load(path) if os.path.isfile(path) else None
    if prior and prior.get('binding') == binding:
        return prior
    if not create:
        return None
    value = {'context': nonce(), 'binding': binding, 'calls_verified': False}
    save(path, value)
    return value


def inspect(request, folder):
    language = request.get('language', 'zh')
    details = {'device': sanitized_identity(), 'version': load(folder + '/manifest.json')['version'],
               'support': 'new_mobile_workflow_pending_hardware_acceptance'}
    try:
        result = engine().manage('probe')
    except Exception as error:
        details['error_code'] = safe_error(error)
        return ui('unsupported', language, 'compatibility', details,
                  actions=['status', 'compatibility', 'legacy-inspect'])
    details['carrier'] = result.get('operator', 'unknown')
    details['installed'] = bool(result.get('installed'))
    if result.get('scope_error'):
        details['error_code'] = result['scope_error']
        return ui('unsupported', language, 'compatibility', details,
                  actions=['status', 'compatibility', 'legacy-inspect'])
    if result.get('installed_stage') == 'pending' and result.get('phase') in (
            'stop_requested', 'awaiting_reboot', 'awaiting_final_reboot', 'removing_hook', 'removing_payload'):
        details['phase'] = result['phase']
        return ui('reboot_required' if result.get('reboot_required') else 'recovery_required',
                  language, 'uninstall', details, actions=['uninstall', 'compatibility', 'status'])
    if not result.get('installed'):
        if result.get('installed_stage') == 'uninstalled':
            if result.get('can_install'):
                return ui('ready_after_uninstall', language, 'install', details, actions=['install', 'export', 'compatibility', 'status'])
            return ui('uninstalled', language, details=details, actions=['export', 'compatibility', 'status'])
        if not result.get('sim_supported'):
            return ui('sim_unsupported', language, details=details)
        if result.get('can_install'):
            return ui('ready_to_install', language, 'install', details, actions=['install', 'compatibility'])
        return ui('waiting', language, details=details)
    details['management_schema'] = result.get('installed_management_schema')
    details['bundled_update_available'] = result.get('can_update') is True
    if result.get('installation_pending') or result.get('update_pending'):
        return ui('recovery_required', language, details=details, actions=['status', 'compatibility'])
    status = result.get('status') or {}
    details['phase'] = status.get('phase', 'unknown')
    actions = ['status', 'disable', 'export', 'compatibility', 'uninstall']
    if result.get('can_update'):
        actions.append('update')
    rollback_available = (result.get('installed_management_schema') == 2 and
        (os.path.isfile(engine().BASE + '/last-update.json') or os.path.isfile(ROOT + '/last-update.json')))
    if rollback_available:
        actions.append('rollback')
    if not result.get('sim_supported'):
        return ui('sim_unsupported', language, details=details, actions=actions)
    if not status.get('enabled'):
        actions = ['enable', 'update', 'export', 'compatibility', 'uninstall', 'status']
        if rollback_available:
            actions.append('rollback')
        if result.get('can_update'):
            return ui('update_ready', language, 'update', details, actions=actions)
        return ui('disabled', language, 'enable', details, actions=actions)
    if status.get('current_sim_matches') is False or status.get('phase') in (
            'reboot_required', 'carrier_reboot_required', 'native_exited'):
        state = 'carrier_reboot_required' if status.get('phase') == 'carrier_reboot_required' else 'reboot_required'
        return ui(state, language, details=details, actions=actions)
    if result.get('update_available') is True and not result.get('can_update'):
        # A recognized older engine needs restoration before replacement even
        # when its IMS registration is waiting. Do not hide this behind Check.
        return ui('update_requires_stop', language, 'disable', details, actions=actions)
    if registered(status):
        context = call_context()
        state = 'verified' if context['calls_verified'] else 'registered'
        return ui(state, language, 'status' if context['calls_verified'] else 'confirm-calls', details,
                  actions=actions + ['confirm-calls'], call_context=context['context'])
    if status.get('phase') in ('error', 'error_restored', 'cleanup_required'):
        return ui('recovery_required', language, details=details, actions=actions)
    if status.get('phase') == 'registering':
        return ui('waiting_ims', language, details=details, actions=actions)
    if status.get('phase') == 'waiting_for_ims_apn':
        return ui('waiting_ims_apn', language, details=details, actions=actions)
    return ui('waiting', language, details=details, actions=actions)


def check_confirmation(request):
    e.require(all(request.get(key) is True for key in ('confirmed', 'incoming', 'outgoing', 'audio', 'lte')),
              'call_confirmation_incomplete')
    result = engine().manage('probe')
    e.require(registered(result.get('status') or {}), 'registration_no_longer_current')
    context = call_context(False)
    e.require(context is not None and checked_id(request.get('call_context')) == context['context'],
              'call_context_changed')
    context['calls_verified'] = True
    save(ROOT + '/call-context.json', context)


def export_directory(location, operation_id):
    e.require(location in ('internal', 'sdcard'), 'invalid_backup_location')
    parent = SDCARD if location == 'sdcard' else DOCS
    e.require(os.path.isdir(parent) and os.path.realpath(parent) == parent, 'backup_location_unavailable')
    if location == 'sdcard':
        e.require(os.stat(parent).st_dev != os.stat(DOCS).st_dev, 'removable_storage_not_mounted')
    root = parent + '/BB10-VoLTE'
    if not os.path.lexists(root):
        os.mkdir(root, 0o700)
    e.require(os.path.isdir(root) and os.path.realpath(root) == root, 'unsafe_backup_directory')
    destination = root + '/' + checked_id(operation_id)
    # Retry uses an exact manifest-verified set; it never overwrites old exports.
    if not os.path.lexists(destination):
        os.mkdir(destination, 0o700)
    e.require(os.path.isdir(destination) and os.path.realpath(destination) == destination,
              'unsafe_backup_directory')
    return destination


def export_as_user(blobs, location, operation_id):
    destination = export_directory(location, operation_id)
    e.require(set(os.listdir(destination)) <= set(blobs), 'backup_destination_not_empty')
    for name, blob in sorted(blobs.items()):
        e.require(isinstance(name, str) and re.match(r'\A[a-zA-Z0-9_.-]{1,80}\Z', name), 'invalid_backup_member')
        path = destination + '/' + name
        e.require(os.path.realpath(path) == path, 'unsafe_backup_file')
        if not os.path.lexists(path):
            e.write_new(path, blob)
        e.require(e.digest(e.regular(path)) == e.digest(blob), 'backup_readback_failed')
    return destination


def export_blobs(blobs, location, operation_id):
    """Never write as Root through user-writable directory components.

    Python 3.2 has no portable dir_fd/openat API. Drop privileges in an isolated
    child before traversing shared storage; even a parent-directory swap cannot
    redirect these writes into a privileged system or transaction directory.
    """
    e.require(os.geteuid() == 0, 'root_required')
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(read_fd)
            os.setgroups([])
            # BB10 account 1000's shared storage is root:1001 (02770).
            # Use the fixed shared-files group, never a caller-selected GID.
            os.setgid(1001)
            os.setuid(1000)
            e.require(os.getuid() == os.geteuid() == 1000 and
                      os.getgid() == os.getegid() == 1001 and not os.getgroups(),
                      'backup_privilege_drop_failed')
            result = {'ok': True, 'path': export_as_user(blobs, location, operation_id)}
        except Exception as error:
            result = {'ok': False, 'error': safe_error(error)}
        try:
            os.write(write_fd, e.canonical(result))
        finally:
            os._exit(0)
    os.close(write_fd)
    deadline = time.time() + 120
    try:
        while True:
            waited, status = os.waitpid(pid, os.WNOHANG)
            if waited == pid:
                e.require(os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0, 'backup_export_failed')
                break
            if time.time() >= deadline:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
                raise e.MobileError('backup_export_timeout')
            time.sleep(0.05)
        result = e.json_bytes(os.read(read_fd, 4096))
        e.require(result.get('ok') is True, result.get('error', 'backup_export_failed'))
        return result['path']
    finally:
        os.close(read_fd)


def backup_originals(request, prepared=None):
    m = engine()
    raw = e.regular(m.BASE + '/backup/manifest.json', 131072)
    manifest = e.json_bytes(raw)
    identity = load(m.BASE + '/management.json') if os.path.isfile(m.BASE + '/management.json') else None
    e.require(manifest.get('owner') == m.policy.OWNER, 'backup_owner_changed')
    blobs, hashes = {'manifest.json': raw}, {}
    for name, expected in manifest['files'].items():
        e.require(re.match(r'\A(?:ims|ims_defaults|omadm|test|btool)\.original\Z', name), 'invalid_backup_member')
        data = e.regular(m.BASE + '/backup/' + name)
        e.require(e.digest(data) == expected, 'original_backup_changed')
        blobs[name], hashes[name] = data, expected
    if prepared:
        e.require(identity is not None, 'installation_identity_missing')
        e.require(prepared['installation_id'] == identity['installation_id'] and
                  prepared['backup_manifest_sha256'] == e.digest(raw) and prepared['backup_files'] == hashes,
                  'backup_preparation_changed')
    location = request.get('backup_location', 'internal')
    destination = export_blobs(blobs, location, request['operation_id'])
    if prepared is None:
        # A manual export cannot change an activation receipt or the retained
        # inventory after uninstall. Historic r14 backups remain exportable
        # without inventing a protocol-2 installation identity.
        return destination
    receipt = {'schema': 2, 'owner': manifest['owner'], 'source': 'mobile',
               'installation_id': identity['installation_id'], 'operation_id': request['operation_id'],
               'variant': manifest['variant'], 'backup_manifest_sha256': e.digest(raw),
               'files': hashes, 'destination': {'type': 'removable' if location == 'sdcard' else 'same_device',
                                              'id': destination},
               'readback': dict((name, e.digest(e.regular(destination + '/' + name))) for name in hashes),
               'all_original_hashes_verified': True}
    m.manage('record-backup', receipt=receipt, operation_id=request['operation_id'])
    return destination


def stage_payload(folder, operation_id, legacy=False, profile=None):
    m = engine()
    if legacy:
        import compatibility
        names, manifest_name = compatibility.FILES, 'payload-manifest.json'
        parent = '/var/rootdata/q10_volte_stage_'
    else:
        names, manifest_name = m.u.PAYLOAD_FILES, 'payload.json'
        parent = '/var/bb10_auto_stage_'
    destination = parent + checked_id(operation_id)[:12]
    e.private_directory(destination)
    expected = set(names) | {manifest_name}
    if legacy:
        expected.add('profile-request.json')
    manifest = load(folder + '/payload/' + manifest_name)
    e.require(set(manifest['files']) == set(names), 'payload_file_set_changed')
    for name in sorted(names) + [manifest_name]:
        data = e.regular(folder + '/payload/' + name)
        if name != manifest_name:
            e.require(e.digest(data) == manifest['files'][name], 'payload_changed')
        target = destination + '/' + name
        parent_path = os.path.dirname(target)
        if parent_path != destination:
            e.private_directory(parent_path)
        if os.path.lexists(target):
            e.require(e.regular(target) == data, 'stage_changed')
        else:
            e.write_new(target, data, 0o700 if name.endswith('.sh') else 0o600)
    if legacy:
        import profiles
        data = e.canonical(profiles.request(profile, True))
        target = destination + '/profile-request.json'
        if os.path.lexists(target):
            e.require(e.regular(target) == data, 'stage_changed')
        else:
            e.write_new(target, data)
    # Reject stray data; a collision never grants ownership of an arbitrary tree.
    actual = set()
    for parent_path, dirs, files in os.walk(destination):
        for name in dirs + files:
            e.require(not os.path.islink(parent_path + '/' + name), 'stage_changed')
        actual.update((parent_path + '/' + name)[len(destination) + 1:] for name in files)
    e.require(actual == expected, 'stage_changed')
    return destination


def public_job(job):
    return dict((key, job.get(key)) for key in ('id', 'state', 'phase', 'action', 'message', 'error_code'))


def resumable_job(job):
    if job['state'] not in ('waiting_reboot', 'interrupted', 'failed'):
        return False
    if job['action'] == 'update' and job['state'] == 'failed' and not job.get('candidate'):
        return False  # Untrusted input never began a device transaction.
    if job['state'] == 'failed' and job.get('resumable_failure') is False:
        return False
    if job['action'] == 'rollback' and job['state'] == 'failed' and not job.get('resumable_failure'):
        return False  # Missing/invalid archives never began a rollback.
    return job['action'] in ('install', 'update', 'rollback', 'uninstall', 'enable', 'disable', 'legacy-install')


def job_path(job_id):
    return JOBS + '/' + checked_id(job_id) + '.json'


def progress(job, phase, **fields):
    job.update(phase=phase, updated=int(time.time()), **fields)
    save(job_path(job['id']), job)


def active_job():
    pointer = JOBS + '/active.json'
    if not os.path.isfile(pointer):
        return None
    return load(job_path(load(pointer)['id']))


def boot():
    import unified_service
    return unified_service.boot_token()


def recover_job(job):
    if job['state'] in ('queued', 'running'):
        # Success is never inferred from a vanished PID. A different boot or a
        # lock acquired by this caller proves no owned worker is still active.
        try:
            with job_lock():
                job = load(job_path(job['id']))
                # A newly forked child may not have taken the lock yet. Its
                # unique attempt is invalidated before an interrupted retry.
                recent_queue = (job['state'] == 'queued' and job.get('boot') == boot()
                                and time.time() - job.get('updated', job['created']) < 10)
                if job['state'] in ('queued', 'running') and not recent_queue:
                    progress(job, job['phase'], state='interrupted', error_code='worker_interrupted')
        except e.MobileError as error:
            if str(error) != 'operation_in_progress':
                raise
    return job


def job_response(job, request):
    state = ('working' if job['state'] in ('queued', 'running') else
             'reboot_required' if job['state'] == 'waiting_reboot' else
             'recovery_required' if job['state'] == 'interrupted' else
             'error' if job['state'] == 'failed' else
             'exported' if job['action'] in ('export', 'compatibility') else
             'uninstalled' if job.get('result', {}).get('uninstalled') else 'waiting')
    resume = resumable_job(job)
    if resume and job['state'] == 'failed':
        state = 'recovery_required'
    action = 'poll' if job['state'] in ('queued', 'running') else 'resume' if resume else 'status'
    return ui(state, request.get('language'), action, job.get('public_result', {}),
              ok=job['state'] != 'failed', actions=[action, 'compatibility'],
              job_id=job['id'], job=public_job(job))


def valid_boot(value):
    return (isinstance(value, list) and len(value) == 2 and
            isinstance(value[0], str) and bool(value[0]) and
            isinstance(value[1], str) and re.match(r'\A[a-f0-9]{48}\Z', value[1]) is not None)


def observed_job_response(job, request, folder):
    """Observe a committed reboot boundary, never retry a device operation."""
    def response(current):
        if current['state'] == 'completed' and current['action'] in ('install', 'update', 'enable', 'disable'):
            result = inspect(request, folder)
            result.update(job_id=current['id'], job=public_job(current), live_status=True)
            return result
        return job_response(current, request)

    if job['state'] not in ('waiting_reboot', 'completed') or job['action'] not in ('install', 'update', 'enable', 'disable'):
        return response(job)
    try:
        with job_lock():
            # Another client may have completed this job and submitted a new
            # one while we waited. Never write our earlier copy over its state.
            current = active_job()
            if current is None:
                return response(load(job_path(job['id'])))
            if current['id'] != job['id'] or current['state'] != 'waiting_reboot':
                return response(current)
            old_boot = current.get('boot')
            if not valid_boot(old_boot):
                return response(current)
            # A disabled boot hook does not create the volatile boot marker.
            # The existing engine creates it on the first observation; this
            # changes only its shmem nonce, never modem or service settings.
            new_boot = boot()
            if not valid_boot(new_boot) or old_boot[0] != new_boot[0] or old_boot == new_boot:
                return response(current)
            action = current['action']
            if action in ('enable', 'disable'):
                state = engine().manage('status')
                if state.get('enabled') is not (action == 'enable'):
                    return response(current)
                if action == 'disable' and state.get('manager_alive') is not False:
                    return response(current)
            else:
                committed = current.get('result') or {}
                keys = ('installed', 'activated') if action == 'install' else ('updated',)
                if not any(committed.get(key) is True for key in keys):
                    return response(current)
            progress(current, 'complete', state='completed')
            return response(current)
    except e.MobileError as error:
        if str(error) != 'operation_in_progress':
            raise
        return job_response(job, request)


def profile_for(request, folder):
    e.require(request.get('experimental') is True, 'experimental_opt_in_required')
    profile_id = request.get('profile_id')
    trials = load(folder + '/materials/variant-trials.json')
    identifiers = [case['profile_id'] for case in trials['cases']]
    e.require(profile_id in PROFILE_IDS or profile_id in identifiers, 'invalid_profile')
    import profiles
    profile = load(folder + '/profiles/' + profile_id + '.json')
    profile['runtime']['autostart'] = False
    profiles.validate(profile)
    if profile_id in identifiers:
        target = profiles.trial_target(profile)
        case = next(case for case in trials['cases'] if case['profile_id'] == profile_id)
        e.require(target == {'variant': case['variant'], 'operator': case['operator']}, 'invalid_profile')
    return profile


def validate_legacy_target(profile, facts, action, folder):
    import profiles
    target = profiles.trial_target(profile)
    if target is None:
        # Generic historic profiles must not bypass exact trial identities or
        # the two extra native-image gates on newly exposed variants.
        e.require(facts.get('variant') in ('SQN100-3', 'SQC100-2', 'SQW100-4'),
                  'trial_exact_profile_required')
        return
    cases = load(folder + '/materials/variant-trials.json')['cases']
    case = next(item for item in cases if item['profile_id'] == profile['id'])
    e.require(facts.get('variant') == target['variant'], 'trial_exact_variant_required')
    e.require(action == 'legacy-inspect' or case['route'] == 'manual_candidate',
              'trial_read_only_lifecycle_pending')


def legacy_command(action, request, folder, stage=None):
    import native as n
    payload = {'action': action, 'profile_id': request['profile_id'], 'stage': stage,
               'backup_location': request.get('backup_location', 'internal'),
               'operation_id': request['operation_id']}
    import base64
    raw = n.command(['/usr/bin/python3.2', folder + '/runtime/legacy_entry.py',
                     base64.b64encode(e.canonical(payload)).decode('ascii')], 480)
    value = e.json_bytes(raw)
    e.require(isinstance(value, dict), 'invalid_legacy_response')
    e.require(value.get('ok') is True, value.get('error_code', 'legacy_operation_failed'))
    return value


def run_operation(job):
    action, request, folder = job['action'], job['request'], job['bundle']
    e.private_directory(folder)
    e.read_bundle(folder)
    m = engine()
    if action == 'compatibility':
        report = compatibility_report(folder)
        path = export_blobs({'compatibility.json': e.canonical(report)}, request.get('backup_location', 'internal'), job['id'])
        return {'exported': True, 'path': path}
    if action == 'export' and request.get('export_kind', 'diagnostics') == 'diagnostics':
        report = compatibility_report(folder)
        state = inspect(request, folder)
        # Explicit display fields only: no jobs, root journals, SIM digests or
        # raw modem logs are included in a shareable report.
        report['status'] = {'state': state['state'], 'details': state['details']}
        path = export_blobs({'diagnostics.json': e.canonical(report)}, request.get('backup_location', 'internal'), job['id'])
        return {'exported': True, 'path': path}
    if action == 'export':
        e.require(request.get('export_kind') == 'backup', 'invalid_export_kind')
        progress(job, 'verifying_original_backup')
        with m.management_lock():
            path = backup_originals(request)
        return {'exported': True, 'path': path}
    if action.startswith('legacy-'):
        profile = profile_for(request, folder)
        with m.management_lock():
            e.require(not os.path.lexists(m.BASE + '/payload.json'), 'unified_installation_present')
            stage = stage_payload(folder, job['id'], True, profile) if action in ('legacy-install', 'legacy-update') else None
            progress(job, 'legacy_installing' if action == 'legacy-install' else action)
            return legacy_command(action, request, folder, stage)
    if action == 'install':
        progress(job, 'checking_and_preparing')
        stage = stage_payload(folder, job['id'])
        with m.management_lock():
            # An activation can commit immediately before power loss. Consult
            # its durable receipt before ever trying to prepare a second time.
            activation = m.BASE + '/activation.json'
            if (os.path.isfile(activation) and os.path.isfile(m.BASE + '/payload.json')
                    and not os.path.isfile(m.BASE + '/uninstalled.json')
                    and not os.path.isfile(m.BASE + '/install-pending.json')):
                return m.manage('activate', operation_id=job['id'])
            prepared = m.manage('prepare', stage=stage, operation_id=job['id'])
            progress(job, 'exporting_original_backup')
            path = backup_originals(request, prepared)
            progress(job, 'activating')
            result = m.manage('activate', operation_id=job['id'])
        result['path'] = path
        return result
    if action == 'update':
        progress(job, 'verifying_update')
        candidate = job.get('candidate')
        if not candidate:
            path = request.get('package_path')
            if path:
                e.require(isinstance(path, str) and len(path) <= 1024 and path.startswith('/accounts/1000/'),
                          'choose_update_package')
                bundle = e.read_archive(path)
                e.require(e.numeric_version(bundle[0]['version']) > e.numeric_version(load(folder + '/manifest.json')['version']),
                          'update_version_not_newer')
                candidate = e.snapshot(bundle)
            else:
                # A newer BAR already contains a verified engine bundle; it can
                # upgrade that engine without a second download or file picker.
                candidate = folder
            progress(job, 'update_verified', candidate=candidate)
        e.trusted_python(candidate)
        # A candidate can change the management code. Execute only its signed,
        # root-private entry in a fresh process, never mix imported versions.
        import native as n
        import base64
        message = {'action': 'engine-update', 'operation_id': job['id']}
        transition = ROOT + '/update-transition.json'
        prior = load(transition) if os.path.isfile(transition) else None
        if prior and prior.get('operation_id') == job['id']:
            e.require(prior['after_bundle'] == candidate, 'update_candidate_changed')
        else:
            prior = {'operation_id': job['id'], 'before_bundle': folder, 'after_bundle': candidate}
            save(transition, prior)
        progress(job, 'updating_payload')
        output = n.command(['/usr/bin/python3.2', candidate + '/runtime/job_entry.py',
                            base64.b64encode(e.canonical(message)).decode('ascii')], 600)
        result = e.json_bytes(output)
        if result.get('ok') is not True:
            job['resumable_failure'] = os.path.isfile(m.BASE + '/update-pending.json')
        e.require(result.get('ok') is True, result.get('error_code', 'update_failed'))
        if result.get('updated'):
            save(ROOT + '/last-update.json', dict(prior, engine_result=result))
            save(ROOT + '/active.json', {'manifest_sha256': os.path.basename(candidate),
                 'for_bundle': getattr(e, 'FALLBACK_MANIFEST_SHA', os.path.basename(folder))})
        return result
    if action == 'rollback':
        progress(job, action)
        pointer = ROOT + '/last-update.json'
        previous = load(pointer) if os.path.isfile(pointer) else None
        try:
            if previous and previous['before_bundle'] != previous['after_bundle']:
                e.read_bundle(previous['before_bundle'])
                result = ({'rolled_back': True, 'runtime_only': True} if previous['engine_result'].get('runtime_only')
                          else m.manage('rollback', operation_id=job['id']))
                if result.get('rolled_back'):
                    save(ROOT + '/active.json', {'manifest_sha256': os.path.basename(previous['before_bundle']),
                         'for_bundle': getattr(e, 'FALLBACK_MANIFEST_SHA', os.path.basename(folder))})
                return result
            return m.manage('rollback', operation_id=job['id'])
        except Exception:
            job['resumable_failure'] = os.path.isfile(m.BASE + '/rollback-pending.json')
            raise
    if action in ('enable', 'disable', 'uninstall'):
        progress(job, action)
        before_enabled = os.path.isfile(m.BASE + '/enabled')
        try:
            result = m.manage(action, operation_id=job['id'])
        except Exception:
            job['resumable_failure'] = ((os.path.isfile(m.BASE + '/uninstall-pending.json') or
                os.path.isfile(m.BASE + '/uninstalled.json')) if action == 'uninstall' else
                before_enabled != os.path.isfile(m.BASE + '/enabled'))
            raise
        if action == 'disable' and result.get('restoration_pending'):
            progress(job, 'restoring')
            deadline = time.time() + 180
            while time.time() < deadline:
                state = m.manage('status')
                if not state.get('manager_alive'):
                    journal = load(m.s.JOURNAL) if os.path.isfile(m.s.JOURNAL) else {}
                    e.require(not journal or journal.get('restore_completed') is True or
                              journal.get('configuration_restored') is True, 'restore_incomplete')
                    result['restoration_pending'] = False
                    break
                time.sleep(1)
            e.require(result.get('restoration_pending') is False, 'restoration_still_pending')
        return result
    raise e.MobileError('invalid_action')


def run_job(job_id, attempt):
    with job_lock(blocking=True):
        job = load(job_path(job_id))
        if job['state'] != 'queued' or job.get('attempt') != attempt:
            return
        progress(job, job.get('phase', 'checking'), state='running', pid=os.getpid())
        try:
            result = run_operation(job)
            public = dict((key, result[key]) for key in ('path', 'reboot_required', 'uninstalled', 'exported') if key in result)
            progress(job, result.get('phase', 'awaiting_reboot') if result.get('reboot_required') else 'complete',
                     state='waiting_reboot' if result.get('reboot_required') else 'completed',
                     result=result, public_result=public)
        except Exception as error:
            progress(job, job['phase'], state='failed', error_code=safe_error(error))


def spawn(job):
    job_id, attempt = checked_id(job['id']), checked_id(job['attempt'])
    try:
        # setsid alone still inherits BB10's application ID. Use the signed
        # QNX launcher so navigator closing the UI cannot kill its transaction.
        import native as n
        e.trusted_python(job['bundle'])
        output = n.command([job['bundle'] + '/runtime/job-launcher', job_id, attempt], 30)
        e.require(re.match(br'\A[1-9][0-9]{0,11}\s*\Z', output), 'background_launch_failed')
        progress(job, job['phase'], worker_pid=int(output))
    except Exception:
        progress(job, job['phase'], state='interrupted', error_code='background_launch_failed')


def submit(action, request, folder):
    operation = checked_id(request.get('operation_id') or nonce())
    request = dict(request, operation_id=operation)
    with job_lock():
        path = job_path(operation)
        if os.path.isfile(path):
            prior = load(path)
            e.require(prior['action'] == action and prior['request'] == request, 'operation_id_reused')
            return job_response(prior, request)
        current = active_job()
        e.require(current is None or current['state'] in TERMINAL, 'operation_in_progress')
        if action.startswith('legacy-'):
            profile_for(request, folder)
        job = {'schema': 2, 'id': operation, 'action': action, 'request': request, 'bundle': folder,
               'state': 'queued', 'phase': 'checking', 'boot': boot(), 'created': int(time.time()),
               'fallback_manifest_sha': getattr(e, 'FALLBACK_MANIFEST_SHA', os.path.basename(folder)),
               'attempt': nonce()}
        save(path, job)
        save(JOBS + '/active.json', {'id': operation})
        spawn(job)
    return job_response(job, request)


def resume(request):
    with job_lock():
        job = load(job_path(request.get('job_id')))
        e.require(job['action'] in ('install', 'update', 'rollback', 'uninstall', 'enable', 'disable', 'legacy-install'), 'manual_recovery_required')
        e.require(resumable_job(job), 'job_not_resumable')
        if ((job['action'] == 'install' and job['phase'] == 'exporting_original_backup') or
                (job['action'] == 'legacy-install' and job['phase'] == 'legacy_installing')):
            location = request.get('backup_location', job['request'].get('backup_location', 'internal'))
            e.require(location in ('internal', 'sdcard'), 'invalid_backup_location')
            # This explicit retry rechecks the same originals and readback. Only
            # the user-selected export destination may change before activation.
            job['request']['backup_location'] = location
        if job['action'] in ('enable', 'disable') and job['boot'] != boot():
            state = engine().manage('status')
            enabled = job['action'] == 'enable'
            e.require(state.get('enabled') is enabled, 'service_state_changed')
            if not enabled:
                e.require(state.get('manager_alive') is False, 'restoration_still_pending')
            progress(job, 'complete', state='completed')
            return job_response(job, request)
        if job['state'] == 'waiting_reboot':
            e.require(job['boot'] != boot(), 'normal_reboot_required')
            # Successful install/enable/update finishes after a reboot; only
            # uninstall/rollback may have a recorded second transaction phase.
            if job['action'] in ('install', 'update') and job.get('result', {}).get('installed',
                    job.get('result', {}).get('activated', job.get('result', {}).get('updated', False))):
                progress(job, 'complete', state='completed')
                return job_response(job, request)
        progress(job, job['phase'], state='queued', boot=boot(), attempt=nonce())
        spawn(job)
    return job_response(job, request)


def dispatch(action, request, folder):
    e.private_directory(ROOT)
    e.private_directory(JOBS)
    language = request.get('language', 'zh')
    e.require(language in ('zh', 'en'), 'unsupported_language')
    if action == 'resume':
        return resume(request)
    if action == 'poll':
        job = recover_job(load(job_path(request.get('job_id'))))
        return observed_job_response(job, request, folder)
    if action in ('inspect', 'status'):
        job = active_job()
        if job:
            job = recover_job(job)
            if job['state'] not in TERMINAL or resumable_job(job):
                return observed_job_response(job, request, folder)
            if job['state'] == 'completed' and request.get('job_id') == job['id']:
                return observed_job_response(job, request, folder)
        return inspect(request, folder)
    if action == 'confirm-calls':
        with engine().management_lock():
            check_confirmation(request)
        return inspect(request, folder)
    if action == 'compatibility' or (action == 'export' and request.get('export_kind', 'diagnostics') == 'diagnostics'):
        # Reports remain available while another transaction awaits a reboot;
        # they never replace that transaction's active-job pointer.
        operation = checked_id(request.get('operation_id') or nonce())
        report = compatibility_report(folder)
        name = 'compatibility.json'
        if action == 'export':
            state = inspect(request, folder)
            report['status'] = {'state': state['state'], 'details': state['details']}
            name = 'diagnostics.json'
        blobs = {name: e.canonical(report)}
        if os.path.isfile(ROOT + '/last-trial-report.json'):
            trial = load(ROOT + '/last-trial-report.json')
            if trial.get('snapshot') == os.path.basename(folder):
                trial['observation'] = 'last_checked_not_live'
                blobs['last-trial-report.json'] = e.canonical(trial)
        path = export_blobs(blobs, request.get('backup_location', 'internal'), operation)
        return ui('exported', language, details={'path': path, 'identity_data_included': False})
    if action == 'legacy-inspect':
        profile_for(request, folder)
        request = dict(request, operation_id=request.get('operation_id') or nonce())
        report = legacy_command(action, request, folder)
        save(ROOT + '/last-trial-report.json', {'schema': 1, 'snapshot': os.path.basename(folder),
                                               'profile_id': request['profile_id'], 'report': report})
        actions = ['legacy-inspect', 'compatibility']
        for suffix in ('install', 'start', 'stop', 'update', 'uninstall'):
            if report.get('can_' + suffix) is True:
                actions.append('legacy-' + suffix)
        return ui('experimental', language, 'legacy-inspect', report, actions=actions)
    e.require(action in JOB_ACTIONS, 'invalid_action')
    return submit(action, request, folder)
