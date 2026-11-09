"""One-time graphical provisioning of the native phone app; no service activation."""
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from connection import resolve_connection
from connection_flow import guidance
from feedback import FeedbackQueue
from i18n import tr
from mobile_app_install import MobileAppInstaller, release, verify_bar, bundled_bar
from ui_theme import BG


def presentation(report):
    state = report.get('state')
    if state == 'installed':
        return (tr('手机应用已安装，文件校验通过'),
                tr('现在可以拔掉 USB。在手机上打开 BB10 VoLTE，正常确认权限，按首页提示备份并启用服务。自动服务启用后会随手机开机启动；需要查看状态或管理时再打开应用，并先等 Root 成功提示。未完成的任务仍须按提示继续。'))
    if state == 'absent':
        return tr('可以安装手机应用'), tr('已内置本次发行的 BAR。确认手机后点“安装到手机”，无需输入终端命令。')
    if state == 'upgrade_available':
        return tr('可以更新手机应用'), tr('先关闭手机上的 BB10 VoLTE，再点“安装到手机”。已内置匹配的 BAR；后台服务仍由手机界面管理。')
    if state == 'newer_installed':
        return tr('手机已安装较新版本'), tr('当前桌面不会降级手机应用。请使用与手机版本对应的新版桌面。')
    if state == 'pending':
        return tr('正在核对同一安装任务'), tr('已保留任务与安装文件。连接恢复后会查询原任务，不会重复安装；暂时不要重新提交或删除安装文件。')
    if state in ('failed', 'conflict'):
        return tr('安装结果需要检查'), tr('已保留安装回执。请保留手机当前状态，不要重复覆盖或降级；可以重新检查连接并导出已有诊断。')
    code = report.get('error')
    if code == 'pending_release_differs':
        return tr('先核对上次安装任务'), tr('手机保留着另一版本的安装任务。请使用对应的桌面发行包查询原任务，不能用当前版本覆盖。')
    if code in ('app_install_unresolved', 'app_install_busy', 'orphaned_install_records'):
        return tr('已有安装任务需要核对'), tr('请保持同一台手机连接并检查原任务。程序不会开始第二次安装，也不需要重新 Root。')
    if code == 'newer_app_installed':
        return presentation({'state': 'newer_installed'})
    if code in ('root_qnx_required', 'installer_unverified', 'os_not_supported'):
        return tr('当前安装入口尚未验证'), tr('此入口需要已授权的原生 Root 连接、受验证的 AutoRoot v4 安装器和 OS 10.3.3.3216。已有其他本机 BAR 安装器时，可使用对应的手机安装路径。')
    if code == 'device_changed':
        return tr('连接的手机已变化'), tr('请重新检查当前手机，核对型号后再确认安装。')
    if code == 'mobile_app_bar_mismatch':
        return tr('安装包不属于本次发行'), tr('请选择窗口中所示版本的完整 BAR 文件。文件大小、完整摘要或应用身份不匹配时不会安装。')
    if code == 'mobile_app_release_invalid':
        return tr('桌面安装资源校验失败'), tr('请重新获取完整的桌面发行包，不要自行替换校验清单。')
    if code == 'mobile_app_result_unconfirmed':
        return tr('连接中断，安装结果待确认'), tr('请恢复同一台手机的连接，再点“检查手机”。程序会读取原任务，不能把连接超时当作安装失败而重新提交。')
    if code == 'app_install_check_failed':
        return tr('安装结果需要检查'), tr('已保留安装回执。请保留手机当前状态，不要重复覆盖或降级；可以重新检查连接并导出已有诊断。')
    view = guidance(error=code)
    return view.title, view.detail


class MobileAppInstallWindow:
    def __init__(self, parent, host, config):
        self.host, self.config = host, config
        self.pin = release()
        self.window = tk.Toplevel(parent)
        self.window.title(tr('安装手机应用'))
        self.window.geometry('760x570')
        self.window.minsize(680, 500)
        self.window.transient(parent)
        self.window.grab_set()
        self.events = FeedbackQueue(self.window, 'install')
        self.busy, self.report, self.installer = False, {}, None
        self.bar, self.recheck_job, self.connection_dialog = str(bundled_bar(self.pin)), None, None
        box = ttk.Frame(self.window, padding=24)
        box.pack(fill='both', expand=True)
        # Reserve all actions/status first. Long translated explanations scroll
        # above them instead of clipping buttons at the minimum window size.
        footer = ttk.Frame(box)
        footer.pack(side='bottom', fill='x', pady=(12, 0))
        viewport = ttk.Frame(box)
        viewport.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(viewport, highlightthickness=0, background=BG, takefocus=True)
        scrollbar = ttk.Scrollbar(viewport, orient='vertical', command=self.canvas.yview)
        scrollbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.body = ttk.Frame(self.canvas)
        self.body_item = self.canvas.create_window(0, 0, anchor='nw', window=self.body)
        self.body.bind('<Configure>', lambda event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', self.reflow)
        self.window.bind('<MouseWheel>', self.scroll)
        self.canvas.bind('<Prior>', lambda event: self.canvas.yview_scroll(-1, 'pages'))
        self.canvas.bind('<Next>', lambda event: self.canvas.yview_scroll(1, 'pages'))
        self.canvas.bind('<Up>', lambda event: self.canvas.yview_scroll(-1, 'units'))
        self.canvas.bind('<Down>', lambda event: self.canvas.yview_scroll(1, 'units'))
        self.window.bind('<Button-4>', lambda event: self.canvas.yview_scroll(-1, 'units'))
        self.window.bind('<Button-5>', lambda event: self.canvas.yview_scroll(1, 'units'))
        heading = ttk.Label(self.body, text=tr('把 BB10 VoLTE 装到手机'), font=('', 20, 'bold'))
        heading.pack(anchor='w')
        ttk.Label(self.body, text=tr('目标应用版本：{}').format(self.pin['version'])).pack(anchor='w', pady=(10, 0))
        self.device = ttk.Label(self.body, text=tr('等待检查已 Root 的手机'))
        self.device.pack(anchor='w', pady=(5, 14))
        self.title = ttk.Label(self.body, text=tr('安装包已就绪，先检查手机'), font=('', 15, 'bold'), wraplength=680)
        self.title.pack(fill='x')
        self.detail = ttk.Label(self.body, wraplength=680, justify='left')
        self.detail.pack(fill='x', pady=(8, 16))
        introduction = ttk.Label(self.body, text=tr('没有本机 BAR 安装器时，用电脑引导安装一次；以后在手机里点击管理。此步骤安装应用图标，VoLTE 的配置和启用在手机上完成。'),
                                 wraplength=680, justify='left')
        introduction.pack(fill='x', pady=(0, 6))
        self.file = ttk.Label(footer, text=tr('已内置并核对安装包：{}').format(self.pin['filename']), wraplength=680)
        self.file.pack(fill='x', pady=(0, 10))
        row = ttk.Frame(footer)
        row.pack(fill='x')
        self.check_button = ttk.Button(row, text=tr('检查手机'), command=lambda: self.run('inspect'))
        self.check_button.pack(side='left', padx=(0, 8))
        self.choose_button = ttk.Button(row, text=tr('选择 BAR 安装包'), command=self.choose)
        self.choose_button.pack(side='left', padx=(0, 8))
        self.install_button = ttk.Button(row, text=tr('安装到手机'), command=self.install)
        self.install_button.pack(side='left')
        self.connect_button = ttk.Button(footer, text=tr('恢复或选择手机连接'), command=self.connect)
        self.connect_button.pack(anchor='w', pady=(10, 8))
        self.progress = ttk.Progressbar(footer, mode='indeterminate')
        self.status = ttk.Label(footer, wraplength=680, justify='left')
        self.status.pack(fill='x')
        self.wrapped_labels = (heading, introduction, self.title, self.detail)
        footer.bind('<Configure>', lambda event: [label.configure(wraplength=max(180, event.width - 4))
                                                for label in (self.file, self.status)])
        self.window._feedback_status_labels = [self.title, self.detail, self.status]
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_job = self.window.after(100, self.poll)
        self.refresh()

    def reflow(self, event):
        self.canvas.itemconfigure(self.body_item, width=event.width)
        for label in self.wrapped_labels:
            label.configure(wraplength=max(180, event.width - 4))

    def scroll(self, event):
        if event.delta:
            units = -int(event.delta / 120) or (-1 if event.delta > 0 else 1)
            self.canvas.yview_scroll(units, 'units')
        return 'break'

    def refresh(self):
        for button in (self.check_button, self.choose_button, self.connect_button):
            button.configure(state='disabled' if self.busy else 'normal')
        self.install_button.configure(state='normal' if not self.busy and self.bar and
                                      self.report.get('can_install') is True else 'disabled')

    def choose(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self.window, title=tr('选择本次发行的原生 BAR'),
                                         filetypes=[('BlackBerry BAR', '*.bar')])
        if not path:
            return
        try:
            verify_bar(path, self.pin)
            self.bar = path
            self.file.configure(text=tr('安装包已核对：{}').format(self.pin['filename']))
        except Exception as error:
            self.bar = None
            title, detail = presentation({'error': getattr(error, 'code', 'mobile_app_bar_mismatch')})
            self.title.configure(text=title)
            self.detail.configure(text=detail)
        self.refresh()

    def install(self):
        if self.busy or not self.bar or self.report.get('can_install') is not True:
            return
        text = tr('将为 {} 安装 BB10 VoLTE {}。请先关闭手机上的该应用，并保持 USB 连接；后台通话服务由手机应用另行管理。').format(
            self.report.get('variant', ''), self.pin['version'])
        if messagebox.askokcancel(tr('安装手机应用'), text, parent=self.window):
            self.run('install')

    def run(self, action):
        if self.busy:
            return
        if self.recheck_job:
            self.window.after_cancel(self.recheck_job)
            self.recheck_job = None
        self.busy = True
        self.refresh()
        self.progress.pack(fill='x', pady=(0, 8), before=self.status)
        self.progress.start()
        self.status.configure(text=tr('正在核验连接和安装任务，请稍候。'))
        expected_device = self.report.get('device_id')
        self.events.begin(action)
        def work():
            try:
                if self.installer is None:
                    client, choice = resolve_connection(self.host, self.config)
                    self.host, self.config = choice['host'], choice['config']
                    self.installer = MobileAppInstaller(client)
                result = (self.installer.inspect() if action == 'inspect' else
                          self.installer.install(self.bar, expected_device))
                self.events.put(('result', (action, result)))
            except Exception as error:
                self.events.failure(error)
                self.events.put(('error', getattr(error, 'code', 'mobile_app_result_unconfirmed')))
        threading.Thread(target=work, daemon=True).start()

    def connect(self):
        if self.busy:
            return
        if self.recheck_job:
            self.window.after_cancel(self.recheck_job)
            self.recheck_job = None
        from connection_dialog import ConnectionDialog
        self.window.grab_release()
        def ready(host, config):
            self.host, self.config, self.installer = host, config, None
            self.report = {}
            self.window.grab_set()
            self.run('inspect')
        self.connection_dialog = ConnectionDialog(self.window, ready, self.host, self.config)

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                previous_state = (self.report.get('state'), self.report.get('error'))
                self.busy = False
                self.progress.stop()
                self.progress.pack_forget()
                if kind == 'error':
                    self.installer = None
                    self.report = {'state': 'error', 'error': value}
                else:
                    unused_action, self.report = value
                title, detail = presentation(self.report)
                self.title.configure(text=title)
                self.detail.configure(text=detail)
                self.device.configure(text=self.report.get('variant') or tr('等待检查已 Root 的手机'))
                self.status.configure(text=tr('无需在手机终端输入命令。'))
                if previous_state != (self.report.get('state'), self.report.get('error')):
                    self.canvas.yview_moveto(0)
                self.refresh()
                if self.report.get('state') == 'pending':
                    self.recheck_job = self.window.after(5000, lambda: self.run('inspect'))
        except queue.Empty:
            pass
        self.poll_job = self.window.after(100, self.poll)

    def close(self):
        if self.busy:
            self.status.configure(text=tr('正在处理，请等待本次返回；连接中断时会保留任务供下次核对。'))
            return
        self.window.after_cancel(self.poll_job)
        if self.recheck_job:
            self.window.after_cancel(self.recheck_job)
        self.window.destroy()
