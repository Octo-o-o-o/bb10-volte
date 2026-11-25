"""One installation workflow for the Windows and Mac front ends."""
from feedback import FeedbackQueue
from feedback_gui import help_row
import queue
import threading
import tkinter as tk
from tkinter import ttk
from auto_carrier import AutoClient
from connection import resolve_connection
from connection_flow import guidance
from completion_dialog import CompletionDialog
from i18n import tr
from auto_carrier_view import status_view, restart_guidance, retry_available, operator_trial_note
from overseas_carrier_gui import OverseasCarrierDialog, should_show_overseas_banner, overseas_banner_text
from ui_theme import AutoScrollbar
import device_support


def status_text(result):
    view = status_view(result)
    return view['title'], view['details']


class AutoCarrierWindow:
    def __init__(self, parent, host, config, auto_probe=False):
        self.host, self.config = host, config
        self.window = tk.Toplevel(parent)
        self.window.title(tr('三网自动适配'))
        self.window.geometry('780x700')
        self.window.minsize(740, 640)
        self.window.transient(parent)
        self.window.grab_set()
        self.events, self.busy = FeedbackQueue(self.window, 'install'), False
        self.client, self.report = None, None
        self.completion_pending = False
        self.completion_dialog = None
        self.reconnect_pending, self.status_button_override = False, None
        box = ttk.Frame(self.window, padding=20)
        box.pack(fill='both', expand=True)
        help_row(box, self.window, lambda: 'acceptance' if status_view((self.report or {}).get('status', {}))['ready']
                 else 'restart' if (self.report or {}).get('installed') else 'install')
        heading = ttk.Frame(box)
        heading.pack(fill='x')
        self.connect_button = ttk.Button(heading, text=tr('手机连接选项'), command=self.connect)
        self.connect_button.pack(side='right')
        ttk.Label(heading, text=tr('Q10 · Q20 · Passport · P’9983'), font=('', 19, 'bold')).pack(side='left')
        ttk.Label(box, text=tr('首次安装后，关机换卡再开机即可按当前 SIM 归属网络自动选择运营商。\n'
            '支持 Q10、Q20 Classic、Passport 与 P’9983 全 16 个目录型号（OS 10.3.3.3216，无 ISIM 的普通 4G USIM）。\n'
            '支持中国移动（460-00/02/04/07/08）、中国联通（460-01/06/09）、中国电信（460-03/05/11/12），含原厂回落 0.xml 的号段。\n'
            '携转号码按当前 SIM 卡归属网络识别；Passport 在联通与移动／电信之间切换入网策略时需再正常重启一次。'),
            wraplength=700, justify='left').pack(anchor='w', pady=(10, 6))
        ttk.Label(box, text=tr('电信短信说明：r46 及以上版本已内置发信状态回执清理，不再长卡“发送中”；若旧版曾卡住，更新重启一次即可自动恢复。'),
                  wraplength=700, justify='left').pack(anchor='w', pady=(0, 6))
        self.status = ttk.Label(box, text=tr('请连接已完成 Root 的手机，程序将检查完整型号、系统和当前 SIM 的适配范围。'),
                                wraplength=700, justify='left')
        self.status.pack(anchor='w', pady=(6, 8))
        self.overseas_bar = ttk.Frame(box)
        self.overseas_label = ttk.Label(self.overseas_bar, text='', wraplength=520, justify='left', foreground='#9A610B')
        self.overseas_label.pack(side='left', fill='x', expand=True, padx=(0, 8))
        self.overseas_button = ttk.Button(self.overseas_bar, text=tr('配置海外运营商…'), command=self.open_overseas_dialog)
        self.overseas_button.pack(side='right')
        self.window._feedback_status_labels = [self.status]
        self.action_row = ttk.Frame(box)
        self.action_row.pack(fill='x', pady=(4, 6))
        row = self.action_row
        self.buttons = {}
        for action, title in (('probe', '检查设备'), ('install', '备份并安装自动适配'),
                              ('status', '刷新状态'), ('enable', '启用自动适配'), ('disable', '停用自动适配')):
            if action == 'enable':
                row = ttk.Frame(box)
                row.pack(fill='x', pady=(0, 4))
            button = ttk.Button(row, text=tr(title), command=lambda a=action: self.run(a))
            button.pack(side='left', padx=(0, 8))
            self.buttons[action] = button
        self.completion_button = ttk.Button(row, text=tr('完成与支持'), command=self.show_completion, state='disabled')
        self.completion_button.pack(side='left', padx=(0, 8))
        details_frame = ttk.Frame(box)
        details_frame.pack(fill='both', expand=True, pady=(8, 0))
        self.details = tk.Text(details_frame, height=8, wrap='word', state='disabled')
        details_scroll = AutoScrollbar(details_frame, orient='vertical', command=self.details.yview)
        self.details.configure(yscrollcommand=details_scroll.set)
        details_scroll.pack(side='right', fill='y')
        self.details.pack(side='left', fill='both', expand=True)
        self.window._feedback_status_labels = [self.status, self.details]
        self.refresh()
        self.poll_job = self.window.after(150, self.poll)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        if auto_probe:
            self.window.after_idle(lambda: self.run('probe'))

    def close(self):
        if not self.busy:
            self.window.after_cancel(self.poll_job)
            self.window.destroy()

    def refresh(self):
        report = self.report or {}
        ready = status_view(report.get('status', {}))['ready']
        self.completion_button.configure(state='normal' if ready and not self.busy else 'disabled')
        self.connect_button.configure(state='disabled' if self.busy else 'normal')
        for action, button in self.buttons.items():
            allowed = (not self.busy and (action == 'probe' or
                action == 'install' and (report.get('can_install') and report.get('sim_supported') is True or
                    report.get('can_prepare_mobile_network') and
                    (not report.get('installed') or report.get('installation_pending')) or report.get('can_update')) or
                action in ('status', 'enable', 'disable') and report.get('installed') and
                    not report.get('installation_pending') and not report.get('update_pending')))
            if report.get('scope_error') and action != 'probe':
                allowed = False
            enabled = report.get('status', {}).get('enabled')
            retry = retry_available(report.get('status', {}))
            if action == 'enable' and enabled is not False and not retry or action == 'disable' and enabled is False:
                allowed = False
            if action == 'enable' and report.get('status', {}).get('manager_alive'):
                allowed = False
            button.configure(state='normal' if allowed else 'disabled')
        self.buttons['install'].configure(text=tr('更新自动适配') if report.get('update_available') else tr('备份并安装自动适配'))
        self.buttons['status'].configure(text=self.status_button_override or status_view(report.get('status', {}))['status_button'])
        self.buttons['probe'].configure(text=tr('重新检查连接') if self.reconnect_pending else tr('检查设备'))
        self.buttons['enable'].configure(text=tr('重试连接') if retry_available(report.get('status', {})) else tr('启用自动适配'))
        if should_show_overseas_banner(report):
            self.overseas_label.configure(text=overseas_banner_text(report))
            self.overseas_button.configure(state='disabled' if self.busy else 'normal')
            if not self.overseas_bar.winfo_manager():
                self.overseas_bar.pack(fill='x', before=self.action_row, pady=(0, 8))
        elif self.overseas_bar.winfo_manager():
            self.overseas_bar.pack_forget()

    def _ensure_client(self):
        if self.client is None:
            transport, unused = resolve_connection(self.host, self.config)
            self.client = AutoClient(transport)
        return self.client

    def open_overseas_dialog(self):
        if self.busy:
            return
        self.window.grab_release()
        def saved(res):
            if self.window.winfo_exists():
                self.window.grab_set()
                if isinstance(res, dict) and isinstance(res.get('probe'), dict):
                    self.events.put(('probe', res['probe'], None))
                else:
                    self.run('probe')
        dialog = OverseasCarrierDialog(self.window, self._ensure_client, self.report, on_saved=saved)
        def restore_grab(event):
            if event.widget is dialog and self.window.winfo_exists() and not self.busy:
                self.window.grab_set()
        dialog.bind('<Destroy>', restore_grab, add='+')

    def run(self, action):
        if self.busy:
            return
        self.events.begin(action)
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
                if action == 'install':
                    try:
                        result['status'] = self.client.action('status')
                    except Exception:
                        # Installation and verified backups succeeded. A lost
                        # connection must not suggest reinstalling the payload.
                        result['status'] = {}
                self.events.put((action, result, None))
            except Exception as error:
                self.events.failure(error)
                self.events.put((action, None, getattr(error, 'code', type(error).__name__)))
        threading.Thread(target=work, daemon=True).start()

    def update_completion(self, action, error=None):
        # An explicit setup can complete after USB reconnect and both Passport
        # reboots. A read-only probe offers the manual entry, never a popup.
        if action == 'disable':
            self.completion_pending = False
        if not error and action in ('install', 'enable'):
            self.completion_pending = True
        ready = status_view((self.report or {}).get('status', {}))['ready']
        if not ready and self.completion_dialog and self.completion_dialog.winfo_exists():
            self.completion_dialog.destroy()
        if not error and ready and self.completion_pending and action in ('status', 'probe'):
            self.completion_pending = False
            self.show_completion()

    def show_completion(self):
        if self.busy or not status_view((self.report or {}).get('status', {}))['ready']:
            return
        if self.completion_dialog and self.completion_dialog.winfo_exists():
            self.completion_dialog.lift()
            return
        self.window.grab_release()
        self.completion_dialog = CompletionDialog(self.window)
        def restore_grab(event):
            if event.widget is self.completion_dialog and self.window.winfo_exists():
                self.window.grab_set()
        self.completion_dialog.bind('<Destroy>', restore_grab, add='+')

    def connect(self):
        if self.busy:
            return
        from connection_dialog import ConnectionDialog
        self.window.grab_release()
        def ready(host, config):
            self.host, self.config, self.client = host, config, None
            self.report = None
            if self.window.winfo_exists():
                self.window.grab_set()
                self.run('probe')
        dialog = ConnectionDialog(self.window, ready, self.host, self.config)
        def restore_grab(event):
            if event.widget is dialog and self.window.winfo_exists() and not self.busy:
                self.window.grab_set()
        dialog.bind('<Destroy>', restore_grab, add='+')

    def poll(self):
        try:
            while True:
                action, result, error = self.events.get_nowait()
                self.busy = False
                if error:
                    self.client, self.report = None, None
                    scope_error = device_support.error_message(error)
                    self.reconnect_pending, self.status_button_override = not bool(scope_error), None
                    connection_codes = ('connection_setup_required', 'hostname_unresolved', 'config_missing',
                                        'authentication_failed', 'host_key_mismatch', 'connection_refused',
                                        'connection_failed', 'connection_timeout_state_unknown',
                                        'openssh_missing', 'bundled_ssh_mismatch', 'ssh_algorithm_mismatch')
                    if scope_error:
                        self.status.configure(text=scope_error)
                        details = scope_error
                    elif error in connection_codes:
                        view = guidance(error=error)
                        self.status.configure(text=view.title)
                        details = view.detail
                        if error in ('connection_refused', 'connection_failed', 'connection_timeout_state_unknown'):
                            details += '\n\n' + tr('若刚重启手机，请解锁并等待约 3–5 分钟，保持 USB 连接，再点击“重新检查连接”。\n'
                                                   '连接恢复后将重新读取手机状态。若安装或更新中断，先检查设备，不要重复覆盖安装。')
                        else:
                            details += '\n\n' + tr('在“手机连接选项”中恢复旧连接或为这台电脑授权。')
                    else:
                        self.status.configure(text=tr('本次检查或操作未完成，请重新检查连接。') + '\n' + error)
                        details = tr('若刚重启手机，请解锁并等待约 3–5 分钟，保持 USB 连接，再点击“重新检查连接”。\n'
                                     '连接恢复后将重新读取手机状态。若安装或更新中断，先检查设备，不要重复覆盖安装。')
                else:
                    self.reconnect_pending, self.status_button_override = False, None
                    if action == 'probe':
                        self.report = result
                        self.status.configure(text=result['variant'] + ' · ' + result.get('operator', tr('SIM 未就绪')))
                        details = tr('安装会保存原始配置并接替现有适配。首次安装及后续换卡需要正常重启。')
                        if result.get('can_prepare_mobile_network'):
                            details += '\n\n' + tr('继续安装或启用 VoLTE 时，将自动打开移动网络，确认开启后重新核对 SIM 和适配条件。')
                        if result.get('installed') and result.get('status'):
                            title, details = status_text(result['status'])
                            self.status.configure(text=title)
                        if result.get('update_available'):
                            details += '\n\n' + (tr('可更新自动适配，更新前版本会保留备份。') if result.get('can_update') else
                                                tr('有适配更新。请先停用，待恢复后正常重启，再检查并更新。'))
                        scope_note = device_support.report_note(result)
                        if scope_note:
                            status_phase = (result.get('status') or {}).get('phase')
                            preserve_status = (result.get('installed') and not result.get('scope_error') and
                                               status_phase in ('error', 'error_restored', 'cleanup_required',
                                                                'reboot_required', 'carrier_reboot_required'))
                            if preserve_status:
                                details += '\n\n' + scope_note
                            else:
                                self.status.configure(text=scope_note)
                                details = device_support.describe(device_support.assess(result.get('variant'))) + '\n\n' + scope_note
                        if result.get('operator_trial') is True and (scope_note or not (result.get('status') or {}).get('operator_trial')):
                            details += '\n\n' + operator_trial_note()
                        if result.get('sim_has_isim') is True and result.get('radio_lte') is False:
                            details += '\n\n' + tr('系统未接入 LTE。请先在系统设置或向运营商确认入网；SIM 的 ISIM 限制需另行验证。')
                        if result.get('lte_bands_disabled') is True:
                            details += '\n\n' + tr('只读诊断：无线已开启且当前未接入 LTE，且基带报告的 LTE 频段能力位图为 0。工具不会自动改写基带，请核对手机移动网络模式（确保允许 4G/LTE）或联系运营商。')
                    elif action == 'install':
                        self.report = dict(self.report or {}, installed=True, can_install=False, can_update=False,
                                           installation_pending=False, update_pending=False, update_available=False,
                                           status=result.get('status') or {})
                        enabled = self.report['status'].get('enabled')
                        if enabled is True and result.get('reboot_required') is False:
                            title, details = status_text(self.report['status'])
                            self.status_button_override = None
                        elif enabled is True:
                            title = (tr('自动适配已更新，旧版本已备份。请正常重启。') if result.get('updated') else
                                     tr('原始配置已备份，自动适配已安装。请用手机电源菜单正常重启，再刷新状态。'))
                            details = restart_guidance()
                            self.status_button_override = tr('已重启，重新检查')
                        elif enabled is False:
                            title = tr('文件已安装并备份，请先启用自动适配')
                            details = tr('当前自动启动处于关闭状态。点击“启用自动适配”，再按提示正常重启。')
                        else:
                            title = tr('文件已安装并备份，启用状态待检查')
                            details = tr('请刷新状态，确认是否需要先启用自动适配，再正常重启。无需重复安装。')
                        self.status.configure(text=title)
                        details += '\n\n' + tr('电脑备份位置：') + result['desktop_backup']
                    elif action == 'disable':
                        self.report = dict(self.report or {}, status={'enabled': False,
                            'manager_alive': result.get('restoration_pending') is True})
                        self.status.configure(text=tr('已关闭自动启动。请等待恢复完成，再正常重启。'))
                        details = tr('原始备份和旧版本文件仍保留，可用于恢复。')
                    elif action == 'enable':
                        self.report = dict(self.report or {}, status={'enabled': True})
                        if result.get('reboot_required') is False:
                            self.status.configure(text=tr('正在等待本次开机的自动适配结果。请保持当前 SIM，稍后刷新状态；注册成功后再验收通话。'))
                            details = tr('上次在启动 IMS 前停止，配置已恢复。保持当前 SIM，点击“重试连接”。')
                            self.status_button_override = None
                        else:
                            self.status.configure(text=tr('已启用自动适配，请正常重启。'))
                            details = restart_guidance()
                            self.status_button_override = tr('已重启，重新检查')
                    else:
                        self.report = dict(self.report or {}, status=result)
                        title, details = status_text(result)
                        self.status.configure(text=title)
                self.update_completion(action, error)
                self.details.configure(state='normal')
                self.details.delete('1.0', 'end')
                self.details.insert('end', details)
                self.details.configure(state='disabled')
                self.refresh()
        except queue.Empty:
            pass
        if self.window.winfo_exists():
            self.poll_job = self.window.after(150, self.poll)
