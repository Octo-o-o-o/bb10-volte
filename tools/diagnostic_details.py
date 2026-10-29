"""Readable, copyable explanations of allowlisted preflight observations."""
import datetime
import re

import compatibility


BASELINE_ITEMS = {
    'voice_policy': ('B01', '语音策略', '核对是否改过语音域或使用过其他 VoLTE 工具。'),
    'crypto_swcr_id': ('B02', '软件加密提供器', '核对是否已有加密提供器加载，或旧服务尚未恢复。'),
    'crypto_support': ('B03', '加密支持状态', '核对加密模块是否仍处于服务使用状态。'),
    'ims_count': ('B04', 'IMS 进程数', '系统 IMS 初始化或其他服务可能仍在运行；待手机稳定后重新检查。'),
    'vpn_count': ('B05', '活动 VPN 会话数', '核对手机 VPN 连接；如为本人主动连接，可先断开再检查。'),
    'native_read_error': ('B06', '底层读取发生错误', '某项底层读取失败；查看标为“读取失败”的项目，重新检查并导出报告。'),
    'clean_configuration': ('B07', '配置符合安装前要求', '查看下面的配置子项，核对具体不符合要求或未能读取的位置。'),
    'ims_override_absent': ('C01', '无 IMS 覆盖文件', '/var/ims/carrier/imsconfig_user.xml'),
    'probe_override_absent': ('C02', '无实验 PPS 目录', '/pps/volte_probe'),
    'cdsc_directory_empty': ('C03', '无数据配置覆盖文件', '/var/radio/cdsc'),
    'voice_override_absent': ('C04', '无语音域覆盖', 'cellular_protocol_configuration / voice_domain_preference_EUTRAN'),
    'ims_profiles_absent': ('C05', '无 IMS 档案覆盖', 'carrier_config/ims/ims / IMS_profilesV2'),
    'ims_networks_absent': ('C06', '无 IMS 网络覆盖', 'carrier_config/ims/ims / supported_networks'),
    'ims_services_absent': ('C07', '无 IMS 服务覆盖', 'carrier_config/ims/ims / IMS_services'),
    'ims_domain_default': ('C08', 'IMS 域为默认状态', 'carrier_config/ims/ims / Home_network_domain_name'),
    'cdsc_selection_default': ('C09', '数据配置选择为默认状态', 'cds/cnice/status_persistent / cdsc_xml'),
}


INCOMING_ITEMS = (
    ('ims_state', 'I01', 'IMS 状态',
     '这是系统 IMS 的状态快照，未据此核实本工具进程或本次注册。'),
    ('ims_ran', 'I02', 'IMS 网络',
     '这是系统 IMS 报告的接入类型，不能证明通话全程保持 4G。'),
    ('allow_volte_provisioning', 'I03', 'VoLTE provisioning',
     '这是设备的配置标志，不能确认运营商业务已开通。'),
    ('engineering_voice_override', 'I04', '工程语音域',
     '工程 override=5 与 DCA=3 属于不同接口的枚举，不能互换或直接作为原生 API 参数。'),
    ('dca_voice_preference', 'I05', 'DCA 语音域',
     'DCA=3 与工程 override=5 属于不同接口的枚举；此处不提供要求值或修改建议。'),
    ('use_preconditions', 'I06', 'IR92 preconditions',
     '这是 IR92 的配置值；关闭 preconditions 不是已证实的通用来电修复。'),
)


def incoming_rows(report):
    """Explain an existing snapshot without I/O, readiness inference or mutation."""
    if not isinstance(report, dict) or 'incoming_diagnostics' not in report:
        return []
    values = compatibility.public_incoming_diagnostics(report.get('incoming_diagnostics'))
    rows = []
    for key, code, title, hint in INCOMING_ITEMS:
        value = values[key]
        actual = '未知' if value is None else str(value)
        detail = '当前：{}。'.format(actual)
        if value is None:
            detail += '报告未提供有效读数；缺失、读取失败或不受支持的值均不能按 0 处理。'
        detail += hint + '仅为只读观察，不能证明来电可用。'
        rows.append({'id': key, 'code': code, 'title': title, 'actual': actual,
                     'state': '未知' if value is None else '只读观察', 'detail': detail})
    return rows


def baseline_rows(report, running=False):
    baseline_check = next((c for c in report.get('checks', []) if c['id'] == 'baseline'), None)
    if not baseline_check and not report.get('baseline') and not report.get('configuration_diagnostics'):
        return []
    values = dict(report.get('baseline') or {})
    values['native_read_status'] = report.get('native_read_status', {})
    values['configuration_diagnostics'] = report.get('configuration_diagnostics', {})
    observations = compatibility.baseline_diagnostics(values)
    installation = report.get('installation', {}).get('state')
    if report.get('can_restore') is False:
        next_step = '此机型的自动恢复尚未验证，请保留当前状态并提供排查摘要。'
    elif installation == 'absent':
        next_step = '未检测到本工具安装；请核对已有设置的来源，并提供排查摘要。'
    elif installation in ('busy', 'stopped', 'recovery_required'):
        next_step = '确认没有通话后，可使用“更多 → 停用并恢复”，再重新检查。'
    else:
        next_step = '安装状态尚未确认，请保留现场并导出报告。'
    rows = []
    for observation in observations:
        key, status = observation['id'], observation['status']
        code, title, hint = BASELINE_ITEMS[key]
        actual, expected = observation['actual'], observation['expected']
        def show(value):
            return '未知' if value is None else '是' if value is True else '否' if value is False else str(value)
        detail = '当前：{}；安装前要求：{}。'.format(show(actual), show(expected))
        # Older reports can pass the aggregate without containing the new subitems.
        legacy_unknown = status == 'unknown' and baseline_check and baseline_check['status'] == 'pass'
        state = '符合' if status == 'pass' else '需核实' if status == 'wait' else '未知'
        problem = status != 'pass' and not legacy_unknown
        if status == 'unknown':
            state = {'read_failed': '读取失败', 'not_checked': '未执行'}.get(observation['reason'], '未知')
            detail += ('Root 或原生文件条件未通过，本次未执行此项读取。' if state == '未执行' else
                       '本次未取得有效读数；未知不等于正常，也不能据此认定手机损坏。')
            detail += '请重新检查；仍未知时导出报告。'
        elif status == 'wait':
            if running and key != 'native_read_error':
                state, problem = '运行中需复查', False
                detail += '已确认本工具管理器运行，使用中的状态可能偏离安装前要求；停用后需重新核验。'
            if key in compatibility.CONFIGURATION_FLAGS:
                detail += '该项不符合本工具基线；来源可能是原厂差异、手动设置或其他工具。'
            else:
                detail += hint
            detail += next_step
        else:
            detail += '此项符合安装前要求。'
        if key in compatibility.CONFIGURATION_FLAGS:
            detail += '\n检查位置：' + hint + '。仅记录是否符合要求，不收集配置原文。'
        rows.append({'id': key, 'code': code, 'title': title, 'state': state,
                     'actual': show(actual), 'expected': show(expected), 'detail': detail,
                     'problem': bool(problem), 'status': status})
    return rows


def baseline_summary(report, running=False):
    rows = [row for row in baseline_rows(report, running) if row['problem']]
    if not rows:
        return '安装前状态的具体读数见“检查详情”；设备操作后请重新检查。'
    known = [row for row in rows if row['status'] == 'wait' and row['id'] != 'clean_configuration']
    chosen = known or rows
    summary = '；'.join('{}：{}'.format(row['title'], row['actual'] if row['status'] == 'wait' else row['state'])
                       for row in chosen[:3])
    if len(chosen) > 3:
        summary += '等 {} 项'.format(len(chosen))
    return summary + '。打开“检查详情”查看要求值和排查建议。'


def has_read_failure(report):
    baseline = report.get('baseline') or {}
    configuration = report.get('configuration_diagnostics') or {}
    return (baseline.get('native_read_error') is True or
            'failed' in (report.get('native_read_status') or {}).values() or
            any(value is None for value in configuration.values()) or
            bool(baseline) and any(row['status'] == 'unknown' for row in baseline_rows(report)
                                  if row['id'] not in compatibility.CONFIGURATION_FLAGS))


def support_summary(report, names, note_for, version, running=False):
    """Select public observations explicitly; never serialize the report wholesale."""
    lines = ['BB10 VoLTE 排查摘要 · ' + version]
    device = report.get('device', {})
    identifiers = []
    for key in ('variant', 'os_version'):
        value = device.get(key)
        if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9.\-]{1,32}', value):
            identifiers.append(value)
    if identifiers:
        lines.append('设备 / 系统：' + ' / '.join(identifiers))
    checked = report.get('checked_at')
    if type(checked) is int and 0 <= checked <= 4102444800:
        lines.append('检查时间：' + datetime.datetime.fromtimestamp(checked, datetime.timezone.utc).isoformat())
    states = {'absent': '未安装', 'stopped': '已安装，已停止', 'busy': '管理器或锁存在',
              'conflict': '安装冲突', 'interrupted': '安装中断', 'recovery_required': '待恢复'}
    lines.append('安装状态：' + states.get(report.get('installation', {}).get('state'), '未知'))
    lines.append('操作许可：安装={}，更新={}，启动={}'.format(
        *('是' if report.get(key) is True else '否' for key in ('can_install', 'can_update', 'can_start'))))
    lines.append('待处理检查：')
    issues = [check for check in report.get('checks', []) if check['status'] != 'pass']
    for check in issues:
        lines.append('- ' + names.get(check['id'], '其他检查') + '：' + note_for(check))
    if not issues:
        lines.append('- 无；检查通过仍需实际通话验收。')
    rows = baseline_rows(report, running)
    if rows:
        lines.append('安装前状态明细（编号供维护者定位）：')
        for row in rows:
            lines.append('- [{}] {} · {}\n  {}'.format(row['code'], row['title'], row['state'], row['detail']))
    network = report.get('network_diagnostics', {})
    if network:
        apn = network.get('observed_data_apn')
        lines.append('数据 APN：' + (apn if apn in compatibility.PUBLIC_APNS else '其他或未知（不含原文）'))
        for key, title in (('apn_matches', 'APN 匹配'), ('data_connected', '数据已连接')):
            value = network.get(key)
            lines.append(title + '：' + ('是' if value is True else '否' if value is False else '未知'))
    observations = incoming_rows(report)
    if observations:
        lines.append('IMS 与来电配置观察（不作为通过条件；通话尚未由此验收）：')
        for row in observations:
            lines.append('- [{}] {} · {}\n  {}'.format(row['code'], row['title'], row['state'], row['detail']))
    lines.append('以上为检查快照；设备操作后请重新检查。配置观察不能代替通话验收。')
    return '\n'.join(lines)
