"""Shared Windows/Mac guidance derived from the phone's current boot status."""
from i18n import tr
from workflow import registered


PHASES = {
    'waiting_for_sim': '等待 SIM 就绪', 'waiting_for_lte_and_usim': '等待 SIM 和正常 LTE 数据服务',
    'registering': '正在注册 IMS', 'running': 'IMS 已连接，请验收双向通话',
    'reboot_required': '请使用手机电源菜单正常重启',
    'carrier_reboot_required': '运营商入网策略已保存，请再正常重启一次',
    'not_started_this_boot': '等待开机服务启动', 'error': '适配未完成，请保留现场并导出报告',
    'stopped': '服务已停止', 'native_exited': '原生 IMS 已退出，请正常重启',
    'unsupported_sim': '当前 SIM 不在支持范围内，未启动自动适配',
    'error_restored': '适配未完成，运行配置已恢复，请导出报告',
    'cleanup_required': '恢复尚未完成，请保留现场并导出报告',
    'not_started': '等待开机服务启动',
    'waiting_for_native_ims': '等待系统 IMS 初始化结束',
    'waiting_for_phone_idle': '等待手机和通话服务空闲',
    'waiting_for_ims_apn': '等待 IMS 专用网络',
    'configuring': '准备运营商配置',
}


def registration_ready(state):
    return (state.get('enabled') is True and state.get('status_from_current_boot') is True
            and state.get('selected_this_boot') is True and registered(state))


def restart_guidance():
    return tr('用手机电源菜单正常重启，开机后解锁并等待约 3–5 分钟，再点击“已重启，重新检查”。\n'
              'Passport 改变电信入网策略时可能还需一次正常重启，程序会根据手机状态提示。\n'
              '以后不连电脑换卡：先关机换卡再开机；Passport 进入或离开电信时，等待约 5 分钟后再正常重启一次。')


def status_view(state):
    """No desktop step counter: reconnecting/reopening resumes from phone facts."""
    ready = registration_ready(state)
    phase = state.get('phase')
    button = tr('刷新状态')
    code = 'unified_waiting'
    if phase in ('cleanup_required', 'error', 'error_restored', 'unsupported_sim'):
        title = tr(PHASES[phase])
        guidance = tr('适配尚未完成。请保留当前状态，在主窗口导出报告后处理。')
    elif state.get('enabled') is False:
        ready = False
        if state.get('manager_alive'):
            title = tr('自动适配正在停用并恢复设置')
            guidance = tr('请保持当前状态，等待恢复完成后再正常重启或启用。')
            button = tr('检查恢复进度')
        else:
            title = tr('自动适配已停用')
            guidance = tr('若要使用自动适配，请点击“启用自动适配”，然后正常重启。升级前请先正常重启，再检查设备。')
    elif state.get('status_from_current_boot') is not True:
        ready = False
        title = tr('等待本次开机状态')
        guidance = tr('尚未取得本次开机的注册结果。刚安装或启用后请先正常重启；已重启则解锁并等待约 3–5 分钟，再刷新状态。')
    elif phase == 'carrier_reboot_required':
        title = tr('还需一次正常重启，适配尚未完成')
        guidance = tr('当前 SIM 的入网策略已保存。Passport 的基带需要再正常重启一次才能采用它；此时 4G 图标不代表通话已就绪。\n'
                      '保持当前 SIM，用手机电源菜单正常重启，开机后解锁并等待约 3–5 分钟，再点击“已重启，重新检查”。\n'
                      '重新检查会确认本次开机的运营商、IMS 注册和 LTE。无需重新安装，飞行模式不能代替重启。')
        button = tr('已重启，重新检查')
        code = 'unified_carrier_reboot_required'
    elif phase in ('reboot_required', 'native_exited'):
        title = tr(PHASES[phase])
        guidance = restart_guidance()
        button = tr('已重启，重新检查')
        code = 'unified_reboot_required'
    elif ready:
        title = tr('本次开机注册成功，请验收通话')
        guidance = tr('当前 SIM 已自动选择，IMS 注册与 LTE 已确认。请断开 USB，用系统拨号器检查呼出、呼入和双向声音。')
        code = 'unified_running'
    else:
        if phase == 'running':
            phase = 'registering' if state.get('manager_alive') else 'stopped'
        title = tr(PHASES.get(phase, '等待状态更新'))
        guidance = tr('正在等待本次开机的自动适配结果。请保持当前 SIM，稍后刷新状态；注册成功后再验收通话。')
    current = state.get('current') or {}
    details = tr('IMS 注册：{}\n无线网络：{}\n运营商：{}').format(
        current.get('register_status') if ready else tr('未确认'),
        current.get('ran') or '/'.join(current.get('radio') or []) or '—',
        state.get('selected_operator') if state.get('selected_this_boot') else '—')
    return {'ready': ready, 'title': title, 'guidance': guidance,
            'details': guidance + '\n\n' + details, 'status_button': button, 'check_code': code}
