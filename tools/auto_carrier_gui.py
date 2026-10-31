"""One installation workflow for the Windows and Mac front ends."""
import queue
import threading
import tkinter as tk
from tkinter import ttk
from auto_carrier import AutoClient
from connection import resolve_connection
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


def status_text(result):
    ready = registered(result) and result.get('status_from_current_boot') is True
    phase = result.get('phase')
    if phase == 'running' and not ready:
        phase = 'registering' if result.get('manager_alive') else 'stopped'
    current = result.get('current') or {}
    details = tr('IMS 注册：{}\n无线网络：{}\n运营商：{}').format(
        current.get('register_status') if ready else tr('未确认'),
        current.get('ran') or '/'.join(current.get('radio') or []) or '—',
        result.get('selected_operator') if result.get('selected_this_boot') else '—')
    return tr(PHASES.get(phase, '等待状态更新')), details


class AutoCarrierWindow:
    def __init__(self, parent, host, config):
        self.host, self.config = host, config
        self.window = tk.Toplevel(parent)
        self.window.title(tr('三网自动适配'))
        self.window.geometry('680x430')
        self.window.transient(parent)
        self.window.grab_set()
        self.events, self.busy = queue.Queue(), False
        self.client, self.report = None, None
        box = ttk.Frame(self.window, padding=24)
        box.pack(fill='both', expand=True)
        ttk.Label(box, text=tr('Q10 · Q20 · Passport'), font=('', 19, 'bold')).pack(anchor='w')
        ttk.Label(box, text=tr('首次安装后，换卡并正常重启即可在手机上选择运营商。\n'
            '支持当前验证范围：SQN100-3、SQC100-2、SQW100-4 / OS 10.3.3.3216。\n'
            '移动 460-00、联通 460-01、电信 460-11；其他 SIM 类型待适配。\n'
            'Passport 切换电信入网策略时可能需要再重启一次。'),
            wraplength=620, justify='left').pack(anchor='w', pady=(16, 12))
        self.status = ttk.Label(box, text=tr('请连接已完成 Root 的手机。新统一版本仍需实机换卡验收。'),
                                wraplength=620, justify='left')
        self.status.pack(anchor='w', pady=12)
        row = ttk.Frame(box)
        row.pack(fill='x', pady=8)
        self.buttons = {}
        for action, title in (('probe', '检查设备'), ('install', '备份并安装自动适配'),
                              ('status', '刷新状态'), ('enable', '启用自动适配'), ('disable', '停用自动适配')):
            if action == 'enable':
                row = ttk.Frame(box)
                row.pack(fill='x', pady=(0, 4))
            button = ttk.Button(row, text=tr(title), command=lambda a=action: self.run(a))
            button.pack(side='left', padx=(0, 8))
            self.buttons[action] = button
        self.details = tk.Text(box, height=5, wrap='word', state='disabled')
        self.details.pack(fill='both', expand=True, pady=(12, 0))
        self.refresh()
        self.poll_job = self.window.after(150, self.poll)
        self.window.protocol('WM_DELETE_WINDOW', self.close)

    def close(self):
        if not self.busy:
            self.window.after_cancel(self.poll_job)
            self.window.destroy()

    def refresh(self):
        report = self.report or {}
        for action, button in self.buttons.items():
            allowed = (not self.busy and (action == 'probe' or
                action == 'install' and (report.get('can_install') or report.get('can_update')) or
                action in ('status', 'enable', 'disable') and report.get('installed') and
                    not report.get('installation_pending') and not report.get('update_pending')))
            enabled = report.get('status', {}).get('enabled')
            if action == 'enable' and enabled is True or action == 'disable' and enabled is False:
                allowed = False
            if action == 'enable' and report.get('status', {}).get('manager_alive'):
                allowed = False
            button.configure(state='normal' if allowed else 'disabled')
        self.buttons['install'].configure(text=tr('更新自动适配') if report.get('update_available') else tr('备份并安装自动适配'))

    def run(self, action):
        if self.busy:
            return
        self.busy = True
        self.refresh()
        self.status.configure(text=tr('正在处理，请保持 USB 连接，暂勿换卡或拨打电话。'))
        def work():
            try:
                if self.client is None:
                    transport, unused = resolve_connection(self.host, self.config)
                    self.client = AutoClient(transport)
                result = (self.client.probe() if action == 'probe' else self.client.install()
                          if action == 'install' else self.client.action(action))
                self.events.put((action, result, None))
            except Exception as error:
                self.events.put((action, None, getattr(error, 'code', type(error).__name__)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                action, result, error = self.events.get_nowait()
                self.busy = False
                if error:
                    self.status.configure(text=tr('操作未完成。请保持当前状态，重新检查设备。') + '\n' + error)
                else:
                    if action == 'probe':
                        self.report = result
                        self.status.configure(text=result['variant'] + ' · ' + result.get('operator', tr('SIM 未就绪')))
                        details = tr('安装会保存原始配置并接替现有适配。首次安装及后续换卡需要正常重启。')
                        if result.get('update_available'):
                            details = (tr('可更新自动适配，更新前版本会保留备份。') if result.get('can_update') else
                                       tr('有适配更新。请先停用，待恢复后正常重启，再检查并更新。'))
                    elif action == 'install':
                        self.report = dict(self.report or {}, installed=True, can_install=False, can_update=False,
                                           installation_pending=False, update_pending=False, update_available=False)
                        self.status.configure(text=tr('自动适配已更新，旧版本已备份。请正常重启。') if result.get('updated') else
                            tr('原始配置已备份，自动适配已安装。请用手机电源菜单正常重启，再刷新状态。'))
                        details = tr('电脑备份位置：') + result['desktop_backup']
                    elif action == 'disable':
                        self.report = dict(self.report or {}, status={'enabled': False,
                            'manager_alive': result.get('restoration_pending') is True})
                        self.status.configure(text=tr('已关闭自动启动。请等待恢复完成，再正常重启。'))
                        details = tr('原始备份和旧版本文件仍保留，可用于恢复。')
                    elif action == 'enable':
                        self.report = dict(self.report or {}, status={'enabled': True})
                        self.status.configure(text=tr('已启用自动适配，请正常重启。'))
                        details = tr('重启后由手机识别当前 SIM，无需再次连接电脑。')
                    else:
                        self.report = dict(self.report or {}, status=result)
                        title, details = status_text(result)
                        self.status.configure(text=title)
                    self.details.configure(state='normal')
                    self.details.delete('1.0', 'end')
                    self.details.insert('end', details)
                    self.details.configure(state='disabled')
                self.refresh()
        except queue.Empty:
            pass
        if self.window.winfo_exists():
            self.poll_job = self.window.after(150, self.poll)
