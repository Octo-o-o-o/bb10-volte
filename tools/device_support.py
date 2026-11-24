"""Early model/carrier guidance. Radio overlap never grants runtime permission."""
import json
import sys
from functools import lru_cache
from desktop_paths import resource_root
from i18n import tr
import i18n
sys.path.insert(0, str(resource_root() / 'device'))
import carrier_policy
import profiles


@lru_cache(maxsize=1)
def catalog():
    value = json.loads((resource_root() / 'materials/device-support.json').read_text(encoding='utf-8'))
    if value.get('schema') != 1 or not isinstance(value.get('models'), dict):
        raise ValueError('invalid_support_catalog')
    return value['models']


@lru_cache(maxsize=1)
def evidence_catalog():
    return json.loads((resource_root() / 'materials/compatibility-matrix.json').read_text(encoding='utf-8'))['models']


def assess(variant, operator=None):
    row = catalog().get(variant)
    admitted = carrier_policy.ADMITTED_MNCS.get(variant, ())
    operators = sorted({carrier_policy.CARRIERS[mnc][0] for mnc in admitted})
    code = ('model_required' if not variant else 'model_unconfirmed' if variant not in carrier_policy.MODELS
            else 'operator_required' if operator and operator not in operators else 'supported')
    evidence = evidence_catalog().get(variant, {})
    return {'variant': variant, 'code': code, 'automatic_volte': code == 'supported',
            'owner_trial_pending_manual_acceptance': any(s == 'untested' for s in evidence.get('status', {}).values()),
            'root_recipe_eligible': bool(row and row.get('identity_documented')
                                         and row.get('root_recipe_verified') is not False),
            'candidate_operators': operators, 'admitted_home_plmns': ['460-' + mnc for mnc in admitted],
            'validated_home_plmns': ['460-' + mnc for mnc in admitted],
            'validated_operators': operators, 'evidence_status': evidence.get('status', {}),
            'radio_overlap_note_only': bool(row and operator and operator not in (row['radio_candidate_operators'] or []))}


def operator_name(operator):
    return {'mobile': tr('中国移动'), 'unicom': tr('中国联通'), 'telecom': tr('中国电信')}.get(operator, '')


def describe(value):
    variant = value['variant']
    if value['code'] == 'supported':
        return evidence_catalog()[variant]['summary'][i18n.LANGUAGE]
    if not variant:
        return tr('请先检测或选择准确硬件型号。下载、Root 与 VoLTE 的支持范围将分别显示。')
    return tr('请核对完整型号与实际运营商。')


def preparation_blocker(variant, root_only=False, operator=None):
    value = assess(variant, operator)
    if value['automatic_volte'] or root_only and value['root_recipe_eligible']:
        return None
    return describe(value)


def root_scope_note(variant, platform):
    if platform == 'win32' and variant == 'SQC100-4':
        return tr('首次 Root：Windows／SQC100-4 已完成原版升级、OS/radio 刷写和有效 UID 0 核验；完整 GUI 首次流程仍待验收。')
    if platform == 'darwin' and variant == 'SQC100-2':
        return tr('首次 Root：Apple 芯片 Mac／SQC100-2 已有实机记录；Intel 与完整 GUI 首次流程仍待验收。')
    if platform == 'win32' and variant == 'SQW100-4':
        return tr('首次 Root：Windows／SQW100-4 已有实机记录；完整 GUI 首次流程仍待验收。')
    return tr('首次 Root：此电脑平台与硬件后缀尚无完整首刷验收，配方可生成不代表刷机加载器已验证。')


def error_message(code, sim_plmn=None):
    if code == 'carrier_not_validated' and sim_plmn == '460-20':
        return tr('当前 SIM 归属网为中国铁通（460-20）。现有中国移动公众 VoLTE 模板不适用于该网络。')
    if code == 'carrier_not_validated' and isinstance(sim_plmn, str) and profiles.match(r'[0-9]{3}-[0-9]{2,3}', sim_plmn):
        return tr('当前卡的归属网络尚无自动配置模板（{}）；已开放型号不因实测状态或频段说明而限制。').format(sim_plmn)
    return {
        'operator_not_supported': tr('请更新手机服务：当前版本已开放所有目录型号的三网入口。'),
        'os_not_supported': tr('当前 OS 尚未适配。自动 VoLTE 要求 10.3.3.3216；请先查看系统升级说明，不能直接安装或自动降级。'),
        'unsupported_model_or_os': tr('当前硬件后缀或 OS 尚未纳入自动 VoLTE，无法安装。请查看机型支持范围；重新连接或重复刷机不会增加适配。'),
        'hardware_identity_conflict': tr('手机型号与主板身份不一致，已停止自动适配。请核对准确硬件版本。'),
        'unknown_native_image': tr('系统原生文件与已适配版本不一致，已停止安装。需要核对固件与补丁，不能靠更换运营商模板继续。'),
        'china_broadnet_unsupported': tr('检测到中国广电（460-15）SIM。黑莓 10 全系硬件不支持广电主力 700 MHz（Band 28）频段且归属网非三大运营商，暂不支持开通 VoLTE。'),
        'downloaded_carrier_config_present': tr('检测到手机上存在已下载的运营商配置文件（OTA 覆盖），为保护现有设置未自动改写。请保留现场并导出脱敏检查报告。'),
        'experimental_stock_template_unavailable': tr('未实测运营商的原厂配置缺少可用的互联网或 IMS 服务，当前无法生成自动激活配置。'),
        'carrier_not_validated': tr('当前卡的归属网络尚无自动配置模板；已开放型号不因实测状态或频段说明而限制。'),
        'sim_route_unsupported': tr('当前 SIM 类型尚未适配。自动流程只支持无 ISIM 的 USIM（部分新版 5G USIM 内置 ISIM 应用暂未适配）；请换用普通 4G USIM，或保留现有系统补充脱敏检查报告。'),
        'sim_not_ready': tr('SIM 尚未就绪。请解锁 SIM 并等待入网，再检查；暂不安装自动适配。'),
        'sim_identity_unavailable': tr('尚未核对 SIM 归属网络，暂不安装。请等待手机读卡完成后重新检查。'),
        'unified_preflight_blocked': tr('安装条件未通过。请先重新检查设备并处理显示的阻断原因。'),
        'unified_retry_blocked': tr('手机状态已变化，请重新检查后按提示操作。'),
        'mobile_network_off': tr('手机移动网络已关闭。请在手机设置中打开移动网络（若飞行模式开启请先关闭），然后重新检查设备。'),
        'mobile_network_rejected': tr('系统拒绝自动打开移动网络。请检查飞行模式和移动网络设置，然后重新检查设备。'),
        'mobile_network_reply_timeout': tr('未收到打开移动网络的确认。请检查手机移动网络开关，然后重新检查设备。'),
        'mobile_network_enable_unconfirmed': tr('未确认移动网络已开启。请检查手机移动网络开关，然后重新检查设备。'),
        'mobile_network_state_unknown': tr('移动网络状态不明确。请检查手机系统设置，然后重新检查设备。'),
        'mobile_network_enable_blocked': tr('当前状态不允许自动打开移动网络。请重新检查设备并按提示处理。'),
        'mobile_network_write_failed': tr('打开移动网络的请求未完整提交。请检查手机系统开关，然后重新检查设备。'),
        'unified_backup_not_verified': tr('原始配置电脑备份未完成读回校验，本次安装已停止。请检查磁盘空间和权限后重试。'),
        'unified_update_needs_stop_and_reboot': tr('有适配更新。请先停用，待恢复后正常重启，再检查并更新。'),
        'unified_already_installed': tr('手机已安装三网自动适配。请点击“检查设备”读取当前状态。'),
        'unified_package_mismatch': tr('手机自动适配版本与程序不匹配。请保留当前安装并导出报告。'),
        'restore_pending': tr('停用恢复仍在处理中。请稍候点击“检查设备”或“刷新状态”，待恢复完成后再正常重启。'),
        'call_active': tr('检测到通话中或暂时无法确认通话空闲。请结束通话后再执行操作。'),
        'root_scheme_not_supported': tr('当前手机 Root 启动入口不在已支持方案内（要求 AutoRoot v4，或 SQC100-2 已校验 AutoRoot v2）。'),
        'root_boot_script_changed': tr('手机 Root 启动脚本与已知原版散列不一致，为安全起见已停止安装。请保留现场并导出报告。'),
        'root_addon_directory_changed': tr('手机 Root 启动附加目录状态异常（非正常目录或包含符号链接），已暂停安装。请保留现场并导出报告。'),
        'legacy_install_interrupted': tr('检测到旧版 VoLTE 安装曾中断（残留安装事务记录），已暂停自动迁移。请保留现场并导出报告。'),
        'unvalidated_legacy_installation': tr('检测到旧版 VoLTE 目录（如 /var/rootdata/q10_volte）无法安全自动迁移：可能是安装清单缺失、属于其他机型的历史独立目录，或同时存在多套旧目录。标准且文件完整的旧版会自动迁移；当前情况请勿重复覆盖，请保留现场并导出诊断报告以便核对。'),
        'legacy_payload_changed': tr('检测到旧版 VoLTE 安装文件与原始清单不一致，已暂停自动迁移。请保留现场并导出报告。'),
        'legacy_directory_changed': tr('检测到旧版 VoLTE 目录状态异常，已暂停自动迁移。请保留现场并导出报告。'),
        'unknown_legacy_owner': tr('检测到来源不明的旧版 VoLTE 目录，已暂停自动迁移。请保留现场并导出报告。'),
        'unfinished_nas_trial': tr('检测到旧版尚未结束的实验恢复记录，已暂停自动迁移。请先完成恢复并正常重启。'),
    }.get(code)


def report_note(report):
    if report.get('scope_error'):
        return error_message(report['scope_error']) or describe(assess(report.get('variant')))
    if report.get('sim_supported') is False:
        return (error_message(report.get('sim_reason'), report.get('sim_plmn')) or
                tr('当前 SIM 或原厂运营商模板未通过检查，暂不安装自动适配。'))
    return ''
