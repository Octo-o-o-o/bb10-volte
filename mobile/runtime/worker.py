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
SAFE_JOB_GUARD = 'safe_job_outcome_v1'
SELECTION_GUARD = 'active_selection_guard_v1'
PRELOCK_UPDATE_GUARD = 'prelock_update_busy_v1'


def supports_job_guard(manifest):
    capabilities = manifest.get('capabilities') if isinstance(manifest, dict) else None
    return isinstance(capabilities, list) and SAFE_JOB_GUARD in capabilities


def supports_selection_guard(manifest):
    capabilities = manifest.get('capabilities') if isinstance(manifest, dict) else None
    return isinstance(capabilities, list) and SELECTION_GUARD in capabilities

# Text is selected by state, never by a free-form native exception or modem log.
MESSAGES = {
    'ready_to_install': ('准备开启 VoLTE', '已通过当前设备检查。会先保存并校验原始备份，再配置自动服务。', '开启 VoLTE',
                         'Ready to enable VoLTE', 'Device checks passed. Original files will be backed up and verified first.', 'Enable VoLTE'),
    'mobile_network_off': ('移动网络已关闭', '请在系统设置中打开移动网络；若飞行模式开启，请先关闭。然后返回应用重新检查。', '重新检查',
                           'Mobile network is off', 'Turn on Mobile Network in system settings. If Airplane Mode is on, turn it off first. Then return and check again.', 'Check again'),
    'task_mobile_network_off': ('上次操作时移动网络关闭', '请在系统设置中打开移动网络；若飞行模式开启，请先关闭。然后返回应用继续原任务。', '继续当前任务',
                                'Mobile network was off', 'Turn on Mobile Network in system settings and turn off Airplane Mode if needed. Then return to continue the original task.', 'Continue task'),
    'working': ('正在处理', '可以离开此应用；任务在手机后台继续。请保持电量充足。', '查看进度',
                'Working', 'The task continues on the phone if you leave this app. Keep the battery charged.', 'Check progress'),
    'reboot_required': ('请正常重启手机', '使用电源菜单重启并解锁。已启用的自动服务会随开机启动，网络可能需要约 3–5 分钟。需要查看状态或继续未完成的任务时，先等 Root 成功提示，再打开应用检查；图标无反应时不要连续点击。', '立即检查',
                        'Restart your phone normally', 'Restart from the power menu and unlock. An enabled automatic service starts with the phone; the network may take 3–5 minutes. To check the status or continue an unfinished task, wait for the Root success notification before opening the app. Do not repeatedly tap an unresponsive icon.', 'Check now'),
    'carrier_reboot_required': ('运营商配置已保存，请再重启一次', 'Passport 网络策略已变化，还需正常重启。已启用的自动服务会随开机启动。需要查看状态或继续任务时，先等 Root 成功提示，再打开应用检查；图标无反应时不要连续点击。', '立即检查',
                                'Carrier settings saved; restart again', 'The Passport network policy changed and needs another normal restart. An enabled automatic service starts with the phone. To check the status or continue a task, wait for the Root success notification before opening the app. Do not repeatedly tap an unresponsive icon.', 'Check now'),
    'registered': ('VoLTE 服务已连接', '可直接用系统拨号器接打电话。重启后已启用的自动服务会启动；查看状态或管理时再打开应用。通话检查可选，注册不代表通话已验证。', '刷新状态',
                   'VoLTE service connected', 'Use the system dialer for calls. The enabled automatic service starts after a restart; open the app when you need status or management. Call checks are optional; registration does not verify calls.', 'Refresh'),
    'verified': ('当前 SIM 已完成通话验收', '本次开机、当前 SIM 和当前版本的双向通话已由你确认。短信能力请另外实测。', '刷新状态',
                 'Calls verified for this SIM', 'You confirmed calls for this boot, SIM and version. Test text messages separately.', 'Refresh'),
    'disabled': ('VoLTE 自动服务已停用', '需要使用时可重新启用，按任务提示正常重启，再检查 IMS 和通话。', '启用自动服务',
                 'Automatic service disabled', 'Enable the service when needed, restart when the task asks, then check IMS and calls.', 'Enable service'),
    'update_ready': ('手机服务可以更新', '现有服务已完成停用与恢复。使用应用内置版本更新，原始备份会保留，完成后按提示正常重启。', '更新手机服务',
                     'Phone service update ready', 'The existing service is stopped and restored. Apply the bundled update, keep the originals, then restart normally when prompted.', 'Update phone service'),
    'waiting': ('等待手机网络就绪', '请保持移动网络和正常 LTE 数据可用。稍后可点“立即检查”更新状态；若长时间未就绪，可以导出不含身份信息的报告。', '立即检查',
                'Waiting for the network', 'Keep cellular and LTE data available. Select Check now later to update the status; export a report if this persists.', 'Check now'),
    'waiting_ims': ('等待 IMS 通话注册', '通话注册与浏览器上网是不同的连接。稍后可点“立即检查”更新状态；若持续等待，请导出诊断报告，不用重新启用。', '立即检查',
                    'Waiting for IMS voice registration', 'Voice registration is separate from web access. Select Check now later to update the status; export a report if it keeps waiting. Re-enabling is unnecessary.', 'Check now'),
    'waiting_ims_apn': ('等待通话专用网络', '正在等待运营商的 IMS 专用连接。浏览器能够上网仍不代表此连接已就绪；稍后可点“立即检查”更新状态。', '立即检查',
                        'Waiting for the IMS connection', 'Waiting for the carrier connection used by IMS. Web access alone does not confirm this connection is ready. Select Check now later to update the status.', 'Check now'),
    'update_requires_stop': ('先停用旧版服务，再更新', '手机已有旧版服务。先停用并恢复配置，按提示正常重启后，首页会提供“更新手机服务”；原始备份会保留。', '停用旧版服务',
                             'Stop the old service before updating', 'An older service is installed. Stop it and restore its settings, then restart normally when prompted. The home page will offer Update phone service. Original backups are retained.', 'Stop old service'),
    'unsupported': ('需要进一步适配', '可以导出兼容性报告。检测到机型不代表已经验证可用；高级页面保留已有的实验路线。', '导出兼容性报告',
                    'Further adaptation needed', 'Export a compatibility report. Recognizing a model does not establish support. Existing experimental routes are in Advanced.', 'Export compatibility'),
    'sim_unsupported': ('当前 SIM 尚未通过检查', '请检查 SIM、LTE 数据服务及运营商 VoLTE 开通状态，换卡请关机后操作。', '重新检查',
                        'SIM checks incomplete', 'Check the SIM, LTE data and carrier VoLTE provisioning. Power off before changing SIMs.', 'Check again'),
    'waiting_sim': ('等待 SIM 就绪', '手机正在读取 SIM 和运营商信息，稍后可点“立即检查”更新状态。如系统要求 SIM 密码，请先解锁；持续等待时请检查系统的移动网络设置。', '立即检查',
                    'Waiting for SIM readiness', 'The phone is reading the SIM and carrier details. Select Check now later to update the status. Unlock the SIM if prompted; if waiting persists, check the system mobile network settings.', 'Check now'),
    'recovery_required': ('需要检查上次操作', '请检查原任务；如已有原件备份，请保留。不要重复提交操作或删除文件。', '继续检查',
                          'Previous operation needs attention', 'Check the original task and keep any existing backups. Do not resubmit the operation or delete files.', 'Check recovery'),
    'uninstall_recovery_required': ('卸载尚未完成', '检测到未完成的卸载记录。请在“管理与恢复”中选择“完整停用并卸载”并确认，已有原件备份请保留。', '重新检查',
                                    'Uninstall is incomplete', 'An unfinished uninstall record was found. In Manage & restore, select Restore & uninstall and confirm. Keep any existing original backups.', 'Check again'),
    'reboot_unconfirmed': ('无法确认重启状态', '请按系统电源菜单正常重启，再检查原任务；如仍无法确认，请导出诊断报告。', '检查任务',
                           'Restart state could not be confirmed', 'Restart normally from the system power menu, then check the original task. Export diagnostics if it remains unconfirmed.', 'Check task'),
    'task_status_unavailable': ('暂时无法核对原任务', '请稍后检查同一任务，不要重复提交或再次重启。', '查看任务进度',
                                'Task status is temporarily unavailable', 'Check the same task again later. Do not resubmit it or restart again.', 'Check task progress'),
    'task_service_busy': ('手机服务正在处理', '暂时无法核对原任务，请稍后查看任务进度；不要重新提交或再次重启。', '查看任务进度',
                          'Phone service is busy', 'The original task cannot be checked yet. Check its progress later; do not resubmit or restart again.', 'Check task progress'),
    'task_service_busy_radio_off': ('手机服务正在处理，移动网络已关闭', '请在系统设置中打开移动网络；如开启了飞行模式请先关闭，然后回来查看原任务进度。', '查看任务进度',
                                    'Phone service is busy; mobile network is off', 'Turn on Mobile Network in system settings and disable Airplane Mode if needed. Then return to check the original task.', 'Check task progress'),
    'service_busy': ('手机服务正在处理', '暂时无法检查当前状态，请稍后再检查。', '重新检查',
                     'Phone service is busy', 'The current status cannot be checked yet. Check again later.', 'Check again'),
    'service_busy_radio_off': ('手机服务正在处理，移动网络已关闭', '请在系统设置中打开移动网络；如开启了飞行模式请先关闭，然后回来重新检查。', '重新检查',
                               'Phone service is busy; mobile network is off', 'Turn on Mobile Network in system settings and disable Airplane Mode if needed. Then return and check again.', 'Check again'),
    'task_complete_status_unchecked': ('上次任务已完成', '当前手机状态尚未检查。请检查手机状态，再进行其他操作。', '检查手机状态',
                                       'Previous task completed', 'The current phone status has not been checked. Check it before another action.', 'Check phone status'),
    'continue_after_reboot': ('检测到开机状态变化', '如果刚才已使用系统电源菜单正常重启，请继续上次任务；否则请先正常重启。', '继续当前任务',
                              'Startup state changed', 'If you restarted normally from the system power menu, continue the previous task. Otherwise restart normally first.', 'Continue task'),
    'job_outcome_unknown': ('上次操作结果尚未确认', '目前无法自动确认结果。请保留现状，导出诊断报告寻求帮助；无需反复检查或重新提交。', '导出诊断报告',
                            'Previous operation outcome is unknown', 'The result cannot currently be confirmed automatically. Keep the current state and export diagnostics for help; do not repeatedly check or resubmit.', 'Export diagnostics'),
    'export_interrupted': ('备份导出未确认', '请检查手机上的原件备份和导出目录；如有需要，可重新导出备份。', '检查手机状态',
                           'Backup export not confirmed', 'Check the original backup on the phone and the export folder. Export the backup again if needed.', 'Check phone status'),
    'policy_restart_once': ('网络策略待确认，请正常重启一次', '已核验联通策略提交后的恢复状态，尚未确认策略生效。请用电源菜单重启一次，解锁并等 Root 成功后再检查；若仍失败，请导出报告，不要重复重启。', '检查状态',
                            'Restart once to check the network policy', 'The restored state after submitting the Unicom policy was verified, but the policy is not yet confirmed. Restart once from the power menu, unlock and wait for Root. If it still fails, export a report instead of restarting repeatedly.', 'Check status'),
    'policy_restart_unconfirmed': ('重启后仍未确认网络策略', '已保留原件和记录。请导出诊断报告，不要继续重复重启或重新安装。', '检查状态',
                                   'Network policy still unconfirmed after restart', 'Originals and records are retained. Export a diagnostic report; do not keep restarting or reinstalling.', 'Check status'),
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


def task_observation_unavailable(job, request, error):
    code = safe_error(error)
    if code == 'management_busy':
        state = 'task_service_busy_radio_off' if mobile_radio_state() == 'OFF' else 'task_service_busy'
    else:
        state = 'task_status_unavailable'
    return ui(state, request.get('language'), 'poll', {'error_code': code},
              actions=['poll', 'compatibility'], job_id=job['id'], job=public_job(job))


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
    # Inspection and confirmation share the same lock for the entire
    # read/create operation. A delayed inspection must not overwrite a call
    # confirmation that another process has already saved. The engine lock
    # is reentrant in the process that already holds it during confirmation.
    with engine().management_lock():
        return locked_call_context(create)


def locked_call_context(create=True):
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


def inspection_details(folder):
    return {'device': sanitized_identity(), 'version': load(folder + '/manifest.json')['version'],
            'support': 'new_mobile_workflow_pending_hardware_acceptance'}


def mobile_radio_state():
    """Return ON/OFF only for one unambiguous public PPS value, else None."""
    try:
        import native as n
        blob = n.read('/pps/services/cellular/radioctrl/status_public')
        if not isinstance(blob, bytes) or len(blob) > 65536 or not blob.endswith(b'\n'):
            return None
        rows = []
        for line in blob.decode('ascii').splitlines():
            line = re.sub(r'^\[[^]]*\]', '', line)
            if line.startswith(('-@', '#@', '*@')) or re.match(r'\A-power_status(?:[:\s]|\Z)', line):
                return None
            if re.match(r'\Apower_status(?:[:\s]|\Z)', line):
                rows.append(line)
        if len(rows) != 1:
            return None
        if rows[0] == 'power_status::OFF':
            return 'OFF'
        if rows[0] == 'power_status::ON':
            return 'ON'
    except (OSError, ValueError, TypeError, UnicodeError, ImportError, AttributeError):
        pass
    return None


def inspect(request, folder):
    details = {}
    try:
        details = inspection_details(folder)
        # Desktop writers use this same lock without taking the mobile job
        # lock. Keep the probe and derived display in one coherent snapshot.
        with engine().management_lock():
            result = engine().manage('probe')
            return inspection_response(request, result, details)
    except Exception as error:
        details['error_code'] = safe_error(error)
        # A failed probe does not establish that the device is unsupported.
        if details['error_code'] == 'management_busy':
            off = mobile_radio_state() == 'OFF'
            if off:
                details['mobile_network_off'] = True
            result = ui('service_busy_radio_off' if off else 'service_busy', request.get('language', 'zh'),
                        'status', details, ok=False, actions=['status', 'compatibility'],
                        error={'code': 'management_busy'})
            # Older native clients accept a completed job's observation
            # failure only with state=error; keep the localized busy text.
            result['state'] = 'error'
            return result
        return ui('error', request.get('language', 'zh'), 'status', details, ok=False,
                  actions=['status', 'compatibility'], error={'code': details['error_code']})


def inspection_response(request, result, details, confirmed_context=None):
    # A confirmation renders the same observation that authorized its save.
    # A second full probe after committing can lose or misreport a completed
    # save when the native client's request deadline expires.
    language = request.get('language', 'zh')
    details['carrier'] = result.get('operator', 'unknown')
    details['installed'] = bool(result.get('installed'))
    details['service_state'] = 'unknown'
    if not result.get('scope_error'):
        if result.get('installed_stage') == 'pending' or result.get('installation_pending') or result.get('update_pending'):
            details['service_state'] = 'pending'
        elif result.get('installed') is True:
            details['service_state'] = 'installed'
        elif result.get('legacy_detected') is True:
            details['service_state'] = 'legacy'
        elif result.get('installed_stage') == 'uninstalled' or result.get('legacy_detected') is False:
            details['service_state'] = 'absent'
    if result.get('scope_error'):
        details['error_code'] = result['scope_error']
        return ui('unsupported', language, 'compatibility', details,
                  actions=['status', 'compatibility', 'legacy-inspect'])
    if result.get('installed_stage') == 'pending' and result.get('phase') in (
            'stop_requested', 'awaiting_reboot', 'awaiting_final_reboot', 'removing_hook', 'removing_payload'):
        details['phase'] = result['phase']
        if result.get('reboot_required'):
            return ui('reboot_required', language, 'status', details, actions=['status', 'compatibility'])
        return ui('uninstall_recovery_required', language, 'status', details,
                  actions=['uninstall', 'compatibility', 'status'])
    if not result.get('installed'):
        if result.get('installed_stage') == 'uninstalled':
            if result.get('can_install'):
                if mobile_radio_state() == 'OFF':
                    return ui('mobile_network_off', language, 'status', details, actions=['status', 'export', 'compatibility'])
                return ui('ready_after_uninstall', language, 'install', details, actions=['install', 'export', 'compatibility', 'status'])
            return ui('uninstalled', language, details=details, actions=['export', 'compatibility', 'status'])
        if not result.get('sim_supported'):
            if result.get('sim_reason') in ('sim_not_ready', 'sim_identity_unavailable') and mobile_radio_state() == 'OFF':
                return ui('mobile_network_off', language, 'status', details, actions=['status', 'compatibility'])
            state = 'waiting_sim' if result.get('sim_reason') in ('sim_not_ready', 'sim_identity_unavailable') else 'sim_unsupported'
            return ui(state, language, details=details)
        if result.get('can_install'):
            if mobile_radio_state() == 'OFF':
                return ui('mobile_network_off', language, 'status', details, actions=['status', 'compatibility'])
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
        temporary = result.get('sim_reason') in ('sim_not_ready', 'sim_identity_unavailable')
        # A transient SIM read must not obscure a previously established
        # reboot or restoration failure: neither can heal through polling.
        if temporary and status.get('enabled'):
            if status.get('current_sim_matches') is False or status.get('phase') in (
                    'reboot_required', 'carrier_reboot_required', 'native_exited'):
                state = 'carrier_reboot_required' if status.get('phase') == 'carrier_reboot_required' else 'reboot_required'
                return ui(state, language, details=details, actions=actions)
            if status.get('phase') in ('error', 'error_restored', 'cleanup_required'):
                return ui('recovery_required', language, details=details, actions=actions)
        if (temporary and not result.get('can_update') and status.get('phase') not in
                ('error', 'error_restored', 'cleanup_required', 'reboot_required', 'carrier_reboot_required') and
                mobile_radio_state() == 'OFF'):
            return ui('mobile_network_off', language, 'status', details, actions=actions)
        state = 'waiting_sim' if temporary else 'sim_unsupported'
        return ui(state, language, details=details, actions=actions)
    if not status.get('enabled'):
        actions = ['enable', 'update', 'export', 'compatibility', 'uninstall', 'status']
        if rollback_available:
            actions.append('rollback')
        if result.get('can_update'):
            return ui('update_ready', language, 'update', details, actions=actions)
        if status.get('phase') not in ('error', 'error_restored', 'cleanup_required', 'reboot_required', 'carrier_reboot_required') and mobile_radio_state() == 'OFF':
            return ui('mobile_network_off', language, 'status', details,
                      actions=['status', 'export', 'compatibility', 'uninstall'])
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
        context = confirmed_context if confirmed_context is not None else call_context()
        if result.get('family') == 'passport' and result.get('operator') == 'unicom':
            import policy_hint
            policy_hint.resolve(result, context, engine(), ROOT)
        state = 'verified' if context['calls_verified'] else 'registered'
        return ui(state, language, 'status', details,
                  actions=actions + ['confirm-calls'], call_context=context['context'])
    if status.get('phase') in ('error', 'error_restored', 'cleanup_required'):
        if (status.get('phase') == 'error_restored' and result.get('family') == 'passport' and
                result.get('operator') == 'unicom'):
            import policy_hint
            hint = policy_hint.suggestion(result, engine(), ROOT)
            if hint:
                details['policy_restart_suggestion_used'] = True
                return ui(hint, language, details=details, actions=['status', 'export', 'compatibility'])
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
    return result, context


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


def unknown_job_outcome(job):
    # Historical workers could fail after changing the device without a
    # corresponding result or pending marker. A missing classification does
    # not establish that a write was avoided. Export jobs only create copies
    # or reports and must not block subsequent device operations.
    action = job.get('action', '')
    device_write = action in ('install', 'enable', 'disable', 'update', 'rollback', 'uninstall') or action.startswith('legacy-')
    if job.get('state') not in ('failed', 'interrupted') or not device_write:
        return False
    return (job.get('worker_safety') != SAFE_JOB_GUARD or
            job.get('commit_outcome_unknown') is not False or
            (isinstance(job.get('result'), dict) and bool(job['result'])))


def protected_job(job):
    return resumable_job(job) or unknown_job_outcome(job)


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


def diagnostic_job_summary(expected_job=None):
    # A report describes only a bounded snapshot, never an authorization to
    # infer completion or repeat a device operation. Do not export identifiers,
    # requests, paths, raw messages, SIM bindings or detailed journals.
    if expected_job is None:
        # A general report must not accidentally describe another client's
        # active task when the UI has no identity to match.
        return {'availability': 'not_requested'}
    try:
        with job_lock():
            job = active_job()
            if job is None:
                return {'availability': 'unavailable'}
            checked_id(expected_job)
            if job.get('id') != expected_job:
                return {'availability': 'different_active_task'}
            action = job.get('action')
            state = job.get('state')
            if action not in JOB_ACTIONS or state not in ('queued', 'running', 'waiting_reboot', 'interrupted', 'failed', 'completed'):
                return {'availability': 'unavailable'}
            summary = {'availability': 'matching_snapshot_only', 'action': action, 'state': state}
            phases = ('checking', 'verifying_original_backup', 'legacy_installing', 'checking_and_preparing',
                      'exporting_original_backup', 'activating', 'verifying_update', 'update_verified',
                      'updating_payload', 'rollback', 'enable', 'disable', 'uninstall', 'restoring',
                      'complete', 'awaiting_reboot', 'awaiting_final_reboot', 'removing_hook',
                      'removing_payload', 'stop_requested', 'legacy-start', 'legacy-stop',
                      'legacy-update', 'legacy-uninstall')
            errors = ('worker_interrupted', 'background_launch_failed', 'legacy_job_requires_review',
                      'call_active', 'operation_in_progress', 'state_persistence_unconfirmed',
                      'update_version_mismatch', 'package_changed', 'rollback_component_too_old', 'backup_location_unavailable',
                      'backup_readback_failed', 'preflight_or_recovery_check_failed')
            if job.get('phase') is not None:
                summary['phase'] = job['phase'] if job['phase'] in phases else 'other'
            if job.get('error_code'):
                summary['error_code'] = job['error_code'] if job['error_code'] in errors else 'other'
            return summary
    except Exception:
        return {'availability': 'unavailable'}


def boot():
    import unified_service
    return unified_service.boot_token()


def recover_job(job, folder=None):
    if job['state'] in ('queued', 'running'):
        # Success is never inferred from a vanished PID. A different boot or a
        # lock acquired by this caller proves no owned worker is still active.
        try:
            with job_lock():
                job = load(job_path(job['id']))
                # A newly forked child may not have taken the lock yet. Its
                # unique attempt is invalidated before an interrupted retry.
                age = time.time() - job.get('updated', job['created'])
                recent_queue = (job['state'] == 'queued' and job.get('boot') == boot()
                                and 0 <= age < 10)
                if job['state'] in ('queued', 'running') and not recent_queue:
                    if folder is not None:
                        require_current_selection(folder)
                    # A vanished worker that had already begun an operation
                    # may have committed before its result could be saved.
                    # Queued work, by contrast, has not entered run_operation.
                    action = job.get('action', '')
                    device_write = action in ('install', 'enable', 'disable', 'update', 'rollback', 'uninstall') or action.startswith('legacy-')
                    progress(job, job['phase'], state='interrupted', error_code='worker_interrupted',
                             commit_outcome_unknown=job['state'] == 'running' and device_write)
        except e.MobileError as error:
            if str(error) != 'operation_in_progress':
                raise
    return job


def job_response(job, request):
    if unknown_job_outcome(job):
        return ui('job_outcome_unknown', request.get('language'), 'export',
                  actions=['poll', 'export', 'compatibility'], job_id=job['id'], job=public_job(job))
    if job['state'] == 'interrupted' and job['action'] in ('export', 'compatibility'):
        return ui('export_interrupted', request.get('language'), 'status',
                  actions=['status', 'compatibility'], job_id=job['id'], job=public_job(job))
    state = ('working' if job['state'] in ('queued', 'running') else
             'reboot_required' if job['state'] == 'waiting_reboot' else
             'recovery_required' if job['state'] == 'interrupted' else
             'error' if job['state'] == 'failed' else
             'exported' if job['action'] in ('export', 'compatibility') else
             'uninstalled' if job.get('result', {}).get('uninstalled') else 'task_complete_status_unchecked')
    resume = resumable_job(job)
    if resume and job['state'] == 'failed':
        state = 'recovery_required'
    action = 'poll' if job['state'] in ('queued', 'running', 'waiting_reboot') else 'resume' if resume else 'status'
    display_state = 'task_mobile_network_off' if resume and job['state'] == 'failed' and job.get('error_code') == 'mobile_network_off' else state
    result = ui(display_state, request.get('language'), action, job.get('public_result', {}),
                ok=job['state'] != 'failed', actions=[action, 'export', 'compatibility'],
                job_id=job['id'], job=public_job(job))
    # Preserve the existing recovery protocol state for older clients, while
    # supplying bilingual instructions even where their local label is absent.
    result['state'] = state
    return result


def valid_boot(value):
    return (isinstance(value, list) and len(value) == 2 and
            isinstance(value[0], str) and bool(value[0]) and
            isinstance(value[1], str) and re.match(r'\A[a-f0-9]{48}\Z', value[1]) is not None)


def observed_job_response(job, request, folder):
    """Observe a committed reboot boundary, never retry a device operation."""
    def response(current, locked=False):
        if current['state'] == 'completed' and current['action'] in ('install', 'update', 'enable', 'disable'):
            if not locked:
                try:
                    with job_lock():
                        latest = load(job_path(current['id']))
                        e.require(latest.get('id') == current['id'], 'operation_id_reused')
                        return response(latest, True)
                except e.MobileError as error:
                    if str(error) != 'operation_in_progress':
                        raise
                    # A busy writer prevents a live observation, but does not
                    # undo this matching completed journal's own result.
                    return job_response(current, request)
            active = active_job()
            if active is not None and active['id'] != current['id'] and (active['state'] not in TERMINAL or protected_job(active)):
                # Return this terminal identity first. The client then obtains
                # the unrelated active task in a separate status observation.
                return job_response(current, request)
            try:
                result = inspect(request, folder)
            except Exception as error:
                # Rendering a current observation can itself need the
                # management lock. Failure there cannot erase a committed job.
                code = safe_error(error)
                result = ui('error', request.get('language'), 'status', {'error_code': code},
                            ok=False, actions=['status', 'compatibility'], error={'code': code})
            result.update(job_id=current['id'], job=public_job(current), live_status=True)
            return result
        return job_response(current, request)

    if job['state'] == 'completed':
        return response(job)
    if job['state'] != 'waiting_reboot':
        return response(job)
    try:
        with job_lock():
            # Another client may have completed this job and submitted a new
            # one while we waited. Never write our earlier copy over its state.
            current = active_job()
            if current is None or current['id'] != job['id']:
                # The pointer can be absent between journal and pointer writes,
                # or another client can have moved it. Never substitute that
                # other job, or offer to resume a non-active transaction.
                try:
                    latest = load(job_path(job['id']))
                    if latest.get('id') == job['id'] and latest.get('state') == 'completed':
                        return job_response(latest, request)
                except Exception:
                    pass
                return ui('recovery_required', request.get('language'), 'poll',
                          actions=['poll', 'compatibility'], job_id=job['id'], job=public_job(job))
            if current['state'] != 'waiting_reboot':
                return response(current, True)
            old_boot = current.get('boot')
            if not valid_boot(old_boot):
                return ui('reboot_unconfirmed', request.get('language'), 'poll',
                          actions=['poll', 'compatibility'], job_id=current['id'], job=public_job(current))
            # A disabled boot hook does not create the volatile boot marker.
            # The existing engine creates it on the first observation; this
            # changes only its shmem nonce, never modem or service settings.
            try:
                new_boot = boot()
            except Exception:
                new_boot = None
            if not valid_boot(new_boot) or old_boot[0] != new_boot[0]:
                return ui('reboot_unconfirmed', request.get('language'), 'poll',
                          actions=['poll', 'compatibility'], job_id=current['id'], job=public_job(current))
            if old_boot == new_boot:
                return response(current, True)
            action = current['action']
            if action not in ('install', 'update', 'enable', 'disable'):
                if resumable_job(current):
                    if current.get('worker_safety') != SAFE_JOB_GUARD:
                        return ui('job_outcome_unknown', request.get('language'), 'export',
                                  actions=['poll', 'export', 'compatibility'], job_id=current['id'], job=public_job(current))
                    return ui('continue_after_reboot', request.get('language'), 'resume',
                              actions=['resume', 'compatibility', 'poll'], job_id=current['id'], job=public_job(current))
                return response(current)
            def unavailable(error):
                return task_observation_unavailable(current, request, error)
            entered = False
            try:
                # Desktop writers take this lock without the mobile job lock.
                # Hold both in the established order through verification and
                # the journal update; inspection re-enters the manager lock.
                with engine().management_lock():
                    entered = True
                    if action in ('enable', 'disable'):
                        try:
                            state = engine().manage('status')
                        except Exception as error:
                            return unavailable(error)
                        if state.get('enabled') is not (action == 'enable'):
                            return unavailable(e.MobileError('service_state_changed'))
                        if action == 'disable' and state.get('manager_alive') is not False:
                            return unavailable(e.MobileError('restoration_still_pending'))
                    else:
                        committed = current.get('result') or {}
                        keys = ('installed', 'activated') if action == 'install' else ('updated',)
                        if not any(committed.get(key) is True for key in keys):
                            return unavailable(e.MobileError('operation_unknown'))
                    require_current_selection(folder)
                    progress(current, 'complete', state='completed')
                    return response(current, True)
            except Exception as error:
                if not entered:
                    return unavailable(error)
                raise
    except e.MobileError as error:
        if str(error) != 'operation_in_progress':
            raise
        # The snapshot predates the busy writer: it may already be resuming
        # or completing the task. Do not tell the owner to reboot again.
        return task_observation_unavailable(job, request, error)


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
    if action == 'enable':
        # The same journal identity is retained on failure. This check is
        # before service writes, including when resuming a prepared install.
        e.require(mobile_radio_state() != 'OFF', 'mobile_network_off')
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
            job['commit_outcome_unknown'] = True
            return legacy_command(action, request, folder, stage)
    if action == 'install':
        with m.management_lock():
            # An activation can commit immediately before power loss. Consult
            # its durable receipt before ever trying to prepare a second time.
            activation = m.BASE + '/activation.json'
            if (os.path.isfile(activation) and os.path.isfile(m.BASE + '/payload.json')
                    and not os.path.isfile(m.BASE + '/uninstalled.json')
                    and not os.path.isfile(m.BASE + '/install-pending.json')):
                job['commit_outcome_unknown'] = True
                return m.manage('activate', operation_id=job['id'])
            e.require(mobile_radio_state() != 'OFF', 'mobile_network_off')
            progress(job, 'checking_and_preparing')
            stage = stage_payload(folder, job['id'])
            job['commit_outcome_unknown'] = True
            prepared = m.manage('prepare', stage=stage, operation_id=job['id'])
            # The prepared transaction has returned a verified receipt. A
            # backup-export failure can safely resume this same preparation.
            job['commit_outcome_unknown'] = False
            progress(job, 'exporting_original_backup')
            path = backup_originals(request, prepared)
            # Preparation and export can take time. Preserve their verified
            # receipt and this job if the owner turned the radio off meanwhile.
            e.require(mobile_radio_state() != 'OFF', 'mobile_network_off')
            progress(job, 'activating')
            job['commit_outcome_unknown'] = True
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
                expected_version = request.get('expected_version')
                expected_hash = request.get('expected_sha256')
                if expected_version is not None or expected_hash is not None:
                    e.require(isinstance(expected_version, str) and isinstance(expected_hash, str),
                              'invalid_update_expectation')
                    e.numeric_version(expected_version)
                    bundle = e.read_archive(path, expected_sha256=expected_hash)
                    e.require(bundle[0]['version'] == expected_version, 'update_version_mismatch')
                else:
                    bundle = e.read_archive(path)
                e.require(e.numeric_version(bundle[0]['version']) > e.numeric_version(load(folder + '/manifest.json')['version']),
                          'update_version_not_newer')
                candidate = e.snapshot(bundle)
            else:
                # A newer BAR already contains a verified engine bundle; it can
                # upgrade that engine without a second download or file picker.
                candidate = folder
            progress(job, 'update_verified', candidate=candidate)
        candidate_manifest = e.trusted_python(candidate)
        if not isinstance(candidate_manifest, dict):
            # Older verified entry implementations return no manifest from
            # trusted_python; re-read and verify rather than trust a file name.
            candidate_manifest = e.read_bundle(candidate)[0]
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
        job['commit_outcome_unknown'] = True
        try:
            output = n.command(['/usr/bin/python3.2', candidate + '/runtime/job_entry.py',
                                base64.b64encode(e.canonical(message)).decode('ascii')], 600)
            result = e.json_bytes(output)
            e.require(isinstance(result, dict), 'invalid_update_response')
        except Exception:
            # The child may have committed before its reply was lost or timed
            # out. A later user action must inspect, never blindly rerun it.
            job['commit_outcome_unknown'] = True
            raise
        if result.get('ok') is not True:
            capabilities = candidate_manifest.get('capabilities') if isinstance(candidate_manifest, dict) else None
            safely_not_dispatched = (isinstance(capabilities, list) and PRELOCK_UPDATE_GUARD in capabilities and
                set(result) == {'ok', 'error_code', 'operation_id', 'not_dispatched'} and
                result.get('ok') is False and result.get('error_code') == 'management_busy' and
                result.get('operation_id') == job['id'] and result.get('not_dispatched') is True)
            if safely_not_dispatched:
                job['commit_outcome_unknown'] = False
                job['resumable_failure'] = True
            else:
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
                previous_bundle = e.read_bundle(previous['before_bundle'])
                guarded_previous = supports_job_guard(previous_bundle[0]) and supports_selection_guard(previous_bundle[0])
                if previous['engine_result'].get('runtime_only'):
                    e.require(guarded_previous, 'rollback_component_too_old')
                if previous['engine_result'].get('runtime_only'):
                    job['commit_outcome_unknown'] = True
                    result = {'rolled_back': True, 'runtime_only': True}
                else:
                    with m.management_lock():
                        job['commit_outcome_unknown'] = True
                        result = m.manage('rollback', operation_id=job['id'])
                if result.get('rolled_back') and guarded_previous:
                    save(ROOT + '/active.json', {'manifest_sha256': os.path.basename(previous['before_bundle']),
                         'for_bundle': getattr(e, 'FALLBACK_MANIFEST_SHA', os.path.basename(folder))})
                elif result.get('rolled_back'):
                    result['management_component_retained'] = True
                return result
            with m.management_lock():
                job['commit_outcome_unknown'] = True
                return m.manage('rollback', operation_id=job['id'])
        except Exception as error:
            job['resumable_failure'] = ((str(error) == 'management_busy' and job.get('commit_outcome_unknown') is not True) or
                                        os.path.isfile(m.BASE + '/rollback-pending.json'))
            raise
    if action in ('enable', 'disable', 'uninstall'):
        progress(job, action)
        if action in ('enable', 'disable'):
            # Check before entering the service transaction so the common
            # in-call rejection is known to have made no service changes.
            # The service still performs its own check under its lock.
            e.require(m.s.phone_idle(), 'call_active')
        with m.management_lock():
            before_enabled = os.path.isfile(m.BASE + '/enabled')
            try:
                job['commit_outcome_unknown'] = True
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
        except Exception as error:
            uncertain = str(error) == 'state_persistence_unconfirmed' or job.get('commit_outcome_unknown') is True
            progress(job, job['phase'], state='interrupted' if uncertain else 'failed',
                     error_code=safe_error(error), commit_outcome_unknown=uncertain)
            return
        public = dict((key, result[key]) for key in ('path', 'reboot_required', 'uninstalled', 'exported') if key in result)
        # If this final save is uncertain, do not overwrite an already
        # committed result with a retryable failure. A remaining running
        # journal is recovered as an unknown outcome, never blindly retried.
        progress(job, result.get('phase', 'awaiting_reboot') if result.get('reboot_required') else 'complete',
                 state='waiting_reboot' if result.get('reboot_required') else 'completed',
                 result=result, public_result=public, commit_outcome_unknown=False)


def spawn(job):
    job_id, attempt = checked_id(job['id']), checked_id(job['attempt'])
    try:
        # setsid alone still inherits BB10's application ID. Use the signed
        # QNX launcher so navigator closing the UI cannot kill its transaction.
        import native as n
        manifest = e.read_bundle(job['bundle'])[0]
        e.require(job.get('worker_safety') == SAFE_JOB_GUARD and supports_job_guard(manifest),
                  'legacy_job_requires_review')
        e.trusted_python(job['bundle'])
        output = n.command([job['bundle'] + '/runtime/job-launcher', job_id, attempt], 30)
        e.require(re.match(br'\A[1-9][0-9]{0,11}\s*\Z', output), 'background_launch_failed')
        progress(job, job['phase'], worker_pid=int(output))
    except Exception as error:
        if str(error) == 'legacy_job_requires_review':
            progress(job, job['phase'], state='interrupted', error_code='legacy_job_requires_review',
                     commit_outcome_unknown=True)
        else:
            progress(job, job['phase'], state='interrupted', error_code='background_launch_failed')


def require_current_selection(folder):
    # Called only while the existing job lock is held. A concurrent update may
    # have switched active.json between entry selection and this transaction.
    observation = getattr(e, 'FOREGROUND_ACTIVE_POINTER', None)
    if observation is not None:
        e.require(e.active_pointer_observation() == observation, 'runtime_selection_changed')
        return
    # Older entry versions cannot capture the pointer. Recompute their choice
    # under this same lock, without weakening their full signature validation.
    fallback = getattr(e, 'FALLBACK_MANIFEST_SHA', None)
    e.require(isinstance(fallback, str) and re.match(r'\A[a-f0-9]{64}\Z', fallback),
              'runtime_selection_changed')
    e.require(e.active_bundle(ROOT + '/snapshots/' + fallback) == folder, 'runtime_selection_changed')


def submit(action, request, folder):
    operation = checked_id(request.get('operation_id') or nonce())
    request = dict(request, operation_id=operation)
    with job_lock():
        path = job_path(operation)
        if os.path.isfile(path):
            prior = load(path)
            e.require(prior['action'] == action and prior['request'] == request, 'operation_id_reused')
            return job_response(prior, request)
        require_current_selection(folder)
        current = active_job()
        # A failed or interrupted task may still own a recoverable device
        # transaction. Never replace its pointer with a different operation.
        e.require(current is None or (current['state'] in TERMINAL and not protected_job(current)),
                  'operation_in_progress')
        if action.startswith('legacy-'):
            profile_for(request, folder)
        job = {'schema': 2, 'id': operation, 'action': action, 'request': request, 'bundle': folder,
               'state': 'queued', 'phase': 'checking', 'boot': boot(), 'created': int(time.time()),
               'fallback_manifest_sha': getattr(e, 'FALLBACK_MANIFEST_SHA', os.path.basename(folder)),
               'attempt': nonce(), 'commit_outcome_unknown': False, 'worker_safety': SAFE_JOB_GUARD}
        save(path, job)
        save(JOBS + '/active.json', {'id': operation})
        spawn(job)
    return job_response(job, request)


def resume(request, folder=None):
    with job_lock():
        if folder is not None:
            require_current_selection(folder)
        requested_id = checked_id(request.get('job_id'))
        job = load(job_path(requested_id))
        e.require(job.get('id') == requested_id, 'operation_id_reused')
        current = active_job()
        e.require(current is not None and current['id'] == job['id'], 'operation_in_progress')
        e.require(not unknown_job_outcome(job), 'operation_unknown')
        e.require(job['action'] in ('install', 'update', 'rollback', 'uninstall', 'enable', 'disable', 'legacy-install'), 'manual_recovery_required')
        e.require(resumable_job(job), 'job_not_resumable')
        if job['state'] == 'waiting_reboot':
            old_boot = job.get('boot')
            e.require(valid_boot(old_boot), 'reboot_state_unconfirmed')
            try:
                new_boot = boot()
            except Exception:
                new_boot = None
            e.require(valid_boot(new_boot) and old_boot[0] == new_boot[0], 'reboot_state_unconfirmed')
            e.require(old_boot != new_boot, 'normal_reboot_required')
            if job['action'] in ('enable', 'disable'):
                entered = False
                try:
                    with engine().management_lock():
                        entered = True
                        try:
                            state = engine().manage('status')
                            enabled = job['action'] == 'enable'
                            e.require(state.get('enabled') is enabled, 'service_state_changed')
                            if not enabled:
                                e.require(state.get('manager_alive') is False, 'restoration_still_pending')
                        except Exception as error:
                            return task_observation_unavailable(job, request, error)
                        progress(job, 'complete', state='completed')
                        return job_response(job, request)
                except Exception as error:
                    if not entered:
                        return task_observation_unavailable(job, request, error)
                    raise
            # Successful install/update finishes after reboot; other actions
            # may still have a recorded second transaction phase.
            if job['action'] in ('install', 'update'):
                result = job.get('result') or {}
                keys = ('installed', 'activated') if job['action'] == 'install' else ('updated',)
                e.require(any(result.get(key) is True for key in keys), 'operation_unknown')
                progress(job, 'complete', state='completed')
                return job_response(job, request)
        # Already committed single-phase reboot jobs were settled above.
        # Any path that can spawn must use a signed, guarded job snapshot.
        e.require(job.get('worker_safety') == SAFE_JOB_GUARD, 'legacy_job_requires_review')
        e.require(supports_job_guard(e.read_bundle(job['bundle'])[0]), 'legacy_job_requires_review')
        if ((job['action'] == 'install' and job['phase'] == 'exporting_original_backup') or
                (job['action'] == 'legacy-install' and job['phase'] == 'legacy_installing')):
            location = request.get('backup_location', job['request'].get('backup_location', 'internal'))
            e.require(location in ('internal', 'sdcard'), 'invalid_backup_location')
            # This explicit retry rechecks the same originals and readback. Only
            # the user-selected export destination may change before activation.
            job['request']['backup_location'] = location
        job.pop('result', None)
        job.pop('public_result', None)
        job.pop('resumable_failure', None)
        job['commit_outcome_unknown'] = False
        progress(job, job['phase'], state='queued', boot=boot(), attempt=nonce())
        spawn(job)
    return job_response(job, request)


def dispatch(action, request, folder):
    e.private_directory(ROOT)
    e.private_directory(JOBS)
    language = request.get('language', 'zh')
    e.require(language in ('zh', 'en'), 'unsupported_language')
    if action == 'resume':
        return resume(request, folder)
    if action == 'poll' or (action in ('inspect', 'status') and request.get('job_id')):
        # An explicit identity addresses its own durable journal, even if the
        # active pointer now names another operation. Missing is still unknown:
        # a delayed original submit may not have written its journal yet.
        job_id = checked_id(request.get('job_id'))
        if request.get('operation_id'):
            e.require(checked_id(request['operation_id']) == job_id, 'operation_id_reused')
        path = job_path(job_id)
        if not os.path.isfile(path):
            return ui('recovery_required', language, 'status', actions=['status', 'compatibility'])
        job = load(path)
        e.require(job.get('id') == job_id, 'operation_id_reused')
        return observed_job_response(recover_job(job, folder), request, folder)
    if action in ('inspect', 'status'):
        job = active_job()
        if job:
            job = recover_job(job, folder)
            if job['state'] not in TERMINAL or protected_job(job):
                return observed_job_response(job, request, folder)
            if job['state'] == 'completed' and request.get('job_id') == job['id']:
                return observed_job_response(job, request, folder)
        return inspect(request, folder)
    if action == 'confirm-calls':
        # The UI may be showing a cached observation or may have lost its
        # local pending record. Protect the active transaction at the Root
        # boundary, using the existing job -> management lock order.
        with job_lock():
            require_current_selection(folder)
            current = active_job()
            e.require(current is None or (current['state'] in TERMINAL and not protected_job(current)),
                      'operation_in_progress')
            with engine().management_lock():
                details = inspection_details(folder)
                result, context = check_confirmation(request)
                return inspection_response(request, result, details, context)
    if action == 'compatibility' or (action == 'export' and request.get('export_kind', 'diagnostics') == 'diagnostics'):
        # Reports remain available while another transaction awaits a reboot;
        # they never replace that transaction's active-job pointer.
        operation = checked_id(request.get('operation_id') or nonce())
        report = compatibility_report(folder)
        name = 'compatibility.json'
        if action == 'export':
            state = inspect(request, folder)
            report['status'] = {'state': state['state'], 'details': state['details']}
            report['task'] = diagnostic_job_summary(request.get('job_id'))
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
