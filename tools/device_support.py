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


def error_message(code):
    return {
        'operator_not_supported': tr('请更新手机服务：当前版本已开放所有目录型号的三网入口。'),
        'os_not_supported': tr('当前 OS 尚未适配。自动 VoLTE 要求 10.3.3.3216；请先查看系统升级说明，不能直接安装或自动降级。'),
        'unsupported_model_or_os': tr('当前硬件后缀或 OS 尚未纳入自动 VoLTE，无法安装。请查看机型支持范围；重新连接或重复刷机不会增加适配。'),
        'hardware_identity_conflict': tr('手机型号与主板身份不一致，已停止自动适配。请核对准确硬件版本。'),
        'unknown_native_image': tr('系统原生文件与已适配版本不一致，已停止安装。需要核对固件与补丁，不能靠更换运营商模板继续。'),
        'carrier_not_validated': tr('当前卡的归属网络尚无自动配置模板；已开放型号不因实测状态或频段说明而限制。'),
        'sim_route_unsupported': tr('当前 SIM 类型尚未适配。自动流程只支持无 ISIM 的 USIM；请保留现有系统，补充脱敏检查报告。'),
        'sim_not_ready': tr('SIM 尚未就绪。请解锁 SIM 并等待入网，再检查；暂不安装自动适配。'),
        'sim_identity_unavailable': tr('尚未核对 SIM 归属网络，暂不安装。请等待手机读卡完成后重新检查。'),
        'unified_preflight_blocked': tr('安装条件未通过。请先重新检查设备并处理显示的阻断原因。'),
    }.get(code)


def report_note(report):
    if report.get('scope_error'):
        return error_message(report['scope_error']) or describe(assess(report.get('variant')))
    if report.get('sim_supported') is False:
        return error_message(report.get('sim_reason')) or tr('当前 SIM 或原厂运营商模板未通过检查，暂不安装自动适配。')
    return ''
