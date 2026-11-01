"""Early model/carrier guidance. Radio overlap never grants runtime permission."""
import json
import sys
from functools import lru_cache
from desktop_paths import resource_root
from i18n import tr
sys.path.insert(0, str(resource_root() / 'device'))
import carrier_policy


@lru_cache(maxsize=1)
def catalog():
    value = json.loads((resource_root() / 'materials/device-support.json').read_text(encoding='utf-8'))
    if value.get('schema') != 1 or not isinstance(value.get('models'), dict):
        raise ValueError('invalid_support_catalog')
    return value['models']


def assess(variant, operator=None):
    row = catalog().get(variant)
    if not variant:
        code = 'model_required'
    elif row is None or row.get('identity_documented') is not True:
        code = 'model_unconfirmed'
    elif (operator and operator not in row['radio_candidate_operators'] or
          not row['radio_candidate_operators']):
        code = 'radio_no_overlap'
    elif variant not in carrier_policy.MODELS:
        code = 'adaptation_pending'
    else:
        code = 'supported'
    return {'variant': variant, 'code': code, 'automatic_volte': code == 'supported',
            'root_recipe_eligible': bool(row and row.get('identity_documented')),
            'candidate_operators': (row or {}).get('radio_candidate_operators')}


def operator_name(operator):
    return {'mobile': tr('中国移动'), 'unicom': tr('中国联通'), 'telecom': tr('中国电信')}.get(operator, '')


def describe(value):
    code, variant = value['code'], value['variant']
    if code == 'model_required':
        return tr('请先检测或选择准确硬件型号。下载、Root 与 VoLTE 的支持范围将分别显示。')
    if code == 'model_unconfirmed':
        return tr('{} 的硬件身份或对应资料尚未核实，暂不提供自动准备和刷写。请核对手机“关于”中的完整型号；不要按固件文件名猜测后缀。').format(variant)
    if code == 'supported':
        return tr('{} 已纳入自动 VoLTE 适配。要求 OS 10.3.3.3216、移动 460-00／联通 460-01／电信 460-11，且为无 ISIM 的 USIM；连接后仍会核对系统、原生文件和 SIM。').format(variant)
    candidates = value.get('candidate_operators') or []
    if code == 'radio_no_overlap':
        note = tr('{} 与所选运营商的已核对 LTE 频段没有交集，不能通过 Root 或更换配置解决；当前开通流程已暂停。').format(variant)
    else:
        note = tr('{} 有 Root 配方，但自动 VoLTE 尚待适配，当前开通流程已暂停。刷写 Root 不会自动补齐此型号的通话支持。').format(variant)
    if candidates:
        note += '\n' + tr('从频段看可继续研究：{}。这只是适配候选，尚未通过实机验收。').format('、'.join(operator_name(x) for x in candidates))
    return note


def preparation_blocker(variant, root_only=False, operator=None):
    value = assess(variant, operator)
    if value['automatic_volte'] or root_only and value['root_recipe_eligible']:
        return None
    return describe(value)


def root_scope_note(variant, platform):
    if platform == 'darwin' and variant == 'SQC100-2':
        return tr('首次 Root：Apple 芯片 Mac／SQC100-2 已有实机记录；Intel 与完整 GUI 首次流程仍待验收。')
    if platform == 'win32' and variant == 'SQW100-4':
        return tr('首次 Root：Windows／SQW100-4 已有实机记录；完整 GUI 首次流程仍待验收。')
    return tr('首次 Root：此电脑平台与硬件后缀尚无完整首刷验收，配方可生成不代表刷机加载器已验证。')


def error_message(code):
    return {
        'os_not_supported': tr('当前 OS 尚未适配。自动 VoLTE 要求 10.3.3.3216；请先查看系统升级说明，不能直接安装或自动降级。'),
        'unsupported_model_or_os': tr('当前硬件后缀或 OS 尚未纳入自动 VoLTE，无法安装。请查看机型支持范围；重新连接或重复刷机不会增加适配。'),
        'hardware_identity_conflict': tr('手机型号与主板身份不一致，已停止自动适配。请核对准确硬件版本。'),
        'unknown_native_image': tr('系统原生文件与已适配版本不一致，已停止安装。需要核对固件与补丁，不能靠更换运营商模板继续。'),
        'carrier_not_validated': tr('这张卡的归属网络尚未适配。当前自动流程仅支持 460-00、460-01、460-11；同一家运营商的其他 MNC 不能直接套用。'),
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
