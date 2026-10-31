"""Evidence-based connection guidance. Failure never proves a phone is unrooted."""
from i18n import tr
from dataclasses import dataclass


@dataclass(frozen=True)
class Guidance:
    state: str
    title: str
    detail: str
    action: str


def guidance(usb=None, error=None, verified=False):
    usb = usb or {}
    if verified:
        return Guidance('ready', tr('手机连接已验证'), tr('手机身份和有效 Root 权限均已核验，可以继续检查 VoLTE。'), 'continue')
    # Authentication evidence is stronger than a possibly incomplete OS USB inventory.
    if error == 'host_key_mismatch':
        return Guidance('identity', tr('手机身份与保存的记录不同'),
                        tr('请核对是否换了手机或重新刷写。使用这台手机可信的材料，或从手机重新授权；原记录会保留。'), 'materials')
    if error == 'authentication_failed':
        return Guidance('authorization', tr('手机没有接受这台电脑的授权'),
                        tr('可以选择以前刷机的文件夹，或通过手机已有 Root 终端重新授权。无需重新刷机。'), 'materials')
    if error in ('root_not_ready', 'root_probe_failed'):
        return Guidance('root_pending', tr('已连接手机，Root 权限仍需确认'),
                        tr('请通过原 Root 工具恢复有效权限后重试。连接诊断未通过不等于手机没有 Root。'), 'retry')
    if usb.get('usb_count', 0) and usb['usb_count'] > 1:
        return Guidance('multiple', tr('请只连接一台黑莓手机'), tr('暂时断开其他手机，再检查当前手机。'), 'retry')
    if error in ('openssh_missing', 'bundled_ssh_mismatch', 'ssh_algorithm_mismatch'):
        return Guidance('components', tr('电脑连接组件需要处理'),
                        tr('请查看连接组件说明。此问题不能说明手机是否已 Root。'), 'components')
    # Anonymous discovery also proves a reachable device, even if the OS driver query failed.
    if not usb.get('device') and usb.get('usb_present') is False:
        return Guidance('usb', tr('电脑尚未识别手机'), tr('请连接支持数据传输的数据线、解锁手机，再重新检测。'), 'usb')
    if not usb.get('device') and usb.get('usb_network') is False:
        return Guidance('network', tr('手机已接入，USB 网络尚未就绪'),
                        tr('先按当前电脑的 USB 连接指引处理，暂时无需查找连接文件。'), 'usb')
    if error == 'connection_refused':
        return Guidance('service', tr('手机的连接服务尚未启动'),
                        tr('已使用 AutoRoot 的手机可打开一次 BlackBerry World 等待启动；仍不恢复时正常重启后再试。无需重新刷机。'), 'retry')
    if error in ('connection_failed', 'connection_timeout_state_unknown'):
        return Guidance('offline', tr('暂时无法连接手机'),
                        tr('请检查 USB 网络，并等待手机完成启动。已保存的授权仍保留；重试不会安装或刷写手机。'), 'retry')
    if error in ('config_missing', 'hostname_unresolved'):
        return Guidance('missing', tr('原连接材料不可用'),
                        tr('原文件可能移动了。选择以前刷机的整个文件夹，或通过手机已有 Root 终端重新授权。'), 'materials')
    if error == 'connection_setup_required':
        return Guidance('missing', tr('这台电脑还没有可用的连接'),
                        tr('先按你手边的材料继续。没有连接材料不能说明手机尚未 Root。'), 'materials')
    if error:
        return Guidance('unknown', tr('连接检查尚未完成'), tr('请保留现有材料，查看连接帮助并重试。当前不能判断手机是否已 Root。'), 'retry')
    return Guidance('idle', tr('连接你的黑莓手机'), tr('用数据线连接并解锁手机，程序会查找已有连接并检查实际状态。'), 'retry')
