"""One connection entry point for new users, returning owners and replacement PCs."""
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from connection import matching_alias
from connection_flow import guidance
from connection_materials import scan_materials
from connection_recovery import import_identity, fingerprint, pending_pairings, RecoveryError
from root_setup import local_usb_state, verify_root, SetupError
from workflow import WorkflowError
from mac_help import scrolled_page
from profile_editor import FONT

MATERIAL_MESSAGES = {
    'limited': '文件夹内容较多或层级过深。如果连接材料就在所选文件夹中，可以只检查这一层；也可以选择存放材料的子文件夹。',
    'ambiguous': '找到多组密钥或手机身份。请选择当前手机对应的子文件夹；程序不会按日期猜选。',
    'host_missing': '找到了登录密钥，但缺少可信的手机身份记录。请补充原材料，或从手机重新授权。',
    'identity_missing': '找到了手机身份记录，但没有登录密钥。请取回原电脑上的材料，或从手机重新授权。',
    'putty': '找到了 PuTTY 密钥。请用 PuTTYgen 导出 OpenSSH 格式后重试，或从手机重新授权。',
    'config_only': '找到了配置文件，但缺少可识别的配套材料。可使用高级导入，或选择包含登录密钥的原文件夹。',
    'unreadable': '部分材料无法读取，请检查文件夹权限，或选择可读取的原材料。',
    'empty': '此文件夹没有可识别的连接材料。请选择以前刷机的工作目录，或从手机重新授权。',
}


class ConnectionDialog(tk.Toplevel):
    def __init__(self, parent, on_ready, host='bb10-root', config='', auto_check=True):
        super().__init__(parent)
        self.title('连接手机')
        self.geometry('790x650')
        self.minsize(700, 580)
        self.transient(parent)
        self.on_ready, self.host, self.config = on_ready, host, config
        self.events, self.busy, self.choice = queue.Queue(), False, None
        self.usb, self.error, self.materials = {}, None, None
        body = ttk.Frame(self, padding=22)
        body.pack(fill='both', expand=True)
        self.title_label = ttk.Label(body, font=(FONT, 18, 'bold'), wraplength=690)
        self.title_label.pack(fill='x')
        self.detail = ttk.Label(body, wraplength=690, justify='left')
        self.detail.pack(fill='x', pady=(10, 12))
        self.facts = ttk.Label(body, wraplength=690, justify='left')
        self.facts.pack(fill='x', pady=(0, 12))
        # Footer remains reachable even with large system fonts or long help text.
        footer = ttk.Frame(body)
        footer.pack(side='bottom', fill='x', pady=(12, 0))
        self.retry_button = ttk.Button(footer, text='重新检测', command=self.detect)
        self.retry_button.pack(side='left')
        self.back_button = ttk.Button(footer, text='返回连接选项', command=self.show_guidance)
        self.back_button.pack(side='left', padx=8)
        self.close_button = ttk.Button(footer, text='关闭', command=self.close)
        self.close_button.pack(side='right')
        self.continue_button = ttk.Button(footer, text='继续检查 VoLTE', command=self.finish)
        self.continue_button.pack(side='right', padx=10)
        self.progress = ttk.Progressbar(body, mode='indeterminate')
        self.status = ttk.Label(body, wraplength=690, justify='left')
        self.status.pack(side='bottom', fill='x', pady=(8, 12))
        for label in (self.title_label, self.detail, self.facts, self.status):
            label.bind('<Configure>', lambda event, target=label: target.configure(wraplength=max(1, event.width - 4)))
        page, self.options = scrolled_page(body, padding=0)
        page.pack(fill='both', expand=True)
        self.option_buttons = []
        self.protocol('WM_DELETE_WINDOW', self.close)
        self._job = self.after(100, self.drain)
        self.grab_set()
        self.show_guidance()
        if auto_check:
            self.detect()

    def clear_options(self):
        for widget in self.options.winfo_children():
            widget.destroy()
        self.option_buttons = []

    def option(self, title, command, detail=''):
        button = ttk.Button(self.options, text=title, command=command)
        button.pack(anchor='w', pady=(8, 0))
        self.option_buttons.append(button)
        if detail:
            ttk.Label(self.options, text=detail, wraplength=640, justify='left').pack(anchor='w', pady=(3, 5))
        return button

    def show_guidance(self):
        view = guidance(self.usb, self.error, bool(self.choice))
        self.title_label.configure(text=view.title)
        self.detail.configure(text=view.detail)
        self.clear_options()
        if view.state == 'ready':
            self.status.configure(text='已保存验证成功的连接。下次打开应用会重新检查实际状态。')
            self.facts.configure(text='最近检查：手机身份与有效 Root 权限均已验证。')
        elif view.action == 'usb':
            self.option('查看 USB 连接指引', self.usb_help)
        elif view.action == 'components':
            self.option('查看连接组件', lambda: self.open_setup('connection'))
        else:
            self.material_options()
        if view.state != 'ready':
            self.option('手机尚未 Root，或不确定', self.root_options)
            self.option('其他连接方式', self.show_materials)
        else:
            self.option('换一台手机，重新查找本机连接', self.rediscover)
        self.refresh()

    def material_options(self):
        if self.config:
            self.option('重新查找本机已有连接', self.rediscover)
        self.option('选择以前刷机的文件夹', self.select_folder, '选择整个文件夹，程序识别登录材料并为本机建立连接。')
        self.option('没有旧文件，从手机重新授权', self.pair, '适用于手机已有可用 Root 终端的情况。')
        if pending_pairings():
            self.option('继续上次未完成的手机授权', lambda: self.recover('pair'))

    def rediscover(self):
        self.host, self.config = 'bb10-root', ''
        self.detect()

    def show_materials(self):
        self.clear_options()
        self.title_label.configure(text='使用已有材料或重新授权')
        self.detail.configure(text='先选择你手边的材料。找不到文件不代表手机没有 Root。')
        self.material_options()
        self.option('高级：手动选择密钥与手机身份', lambda: self.recover('key'))
        self.option('高级：选择 SSH 配置文件', self.import_config)
        self.refresh()

    def root_options(self):
        self.clear_options()
        self.title_label.configure(text='按手机实际情况继续')
        self.detail.configure(text='应用首次使用、没有连接文件、开发模式关闭，都不能证明手机尚未 Root。')
        self.option('以前 Root 过，恢复连接', self.show_materials)
        self.option('不确定，先检查连接', self.detect)
        self.option('确认尚未 Root，查看首次准备', self.first_root,
                    '首次 Root 与恢复连接是独立流程；刷写会清空手机数据。')

    def first_root(self):
        if messagebox.askokcancel('核对手机状态', '请确认手机尚未 Root。接下来仅打开首次准备说明；实际刷写仍需备份、机型核对和单独确认。\n\n连接失败或找不到文件时，请先尝试恢复已有访问。', parent=self):
            self.open_setup('root')

    def pair(self):
        self.clear_options()
        self.title_label.configure(text='先确认手机可以授权')
        self.detail.configure(text='手机需要已有可用的 Root 终端，例如原 Root 工具提供的 Term49。只有图标或开发模式还不够，授权脚本会检查实际权限。')
        self.option('有可用的 Root 终端，开始授权', lambda: self.recover('pair'))
        self.option('不清楚如何确认', self.root_help)
        self.option('没有 Root 终端，也没有旧文件', self.unavailable)

    def root_help(self):
        self.clear_options()
        self.title_label.configure(text='在手机上检查 Root 权限')
        self.detail.configure(text='在原 Root 工具提供的终端中，按该工具说明进入 Root 环境，再执行 id，核对有效用户身份为 root（有效 UID 0）。\n\n如果命令或 Root helper 不存在，请先按原工具说明恢复访问。授权脚本仍会检查实际权限。')
        self.option('已确认有效 Root，继续授权', lambda: self.recover('pair'))
        self.option('无法取得 Root 权限', self.unavailable)

    def unavailable(self):
        self.clear_options()
        self.title_label.configure(text='需要先恢复手机访问')
        self.detail.configure(text='请取回原电脑上的个人连接材料，或通过原 Root 工具恢复手机上的有效 Root 终端。\n\n既没有登录材料，也没有有效 Root 终端时，电脑无法直接建立授权。请保留手机现有数据。')
        self.option('我找到了原文件夹', self.select_folder)

    def usb_help(self):
        self.clear_options()
        self.title_label.configure(text='先建立 USB 网络连接')
        self.detail.configure(text=('解锁手机，使用支持数据传输的数据线，直接连接电脑 USB 接口。\n'
                                    'Mac：手机“设置 → 存储和访问 → USB 连接”选择“连接至 Mac”，再检查 USB 网络接口。'
                                    if sys.platform == 'darwin' else
                                    '解锁手机，使用支持数据传输的数据线，直接连接电脑 USB 接口。\nWindows：仅在未识别黑莓 USB 设备或网络时检查、安装黑莓驱动。'))
        if sys.platform == 'win32':
            self.option('查看 Windows 驱动', lambda: self.open_setup('drivers'))
        self.option('已处理，重新检测', self.detect)

    def open_setup(self, page):
        from setup_wizard import SetupWizard
        SetupWizard(self, self.adopt, auto_check=False, initial_page=page)

    def recover(self, mode):
        from recovery_gui import RecoveryDialog
        RecoveryDialog(self, self.adopt, mode=mode)

    def adopt(self, host, config):
        self.host, self.config = host, config
        self.grab_set()
        self.detect()

    def import_config(self):
        path = filedialog.askopenfilename(parent=self, title='选择可信的个人 SSH 配置（保留原路径）')
        if path:
            self.host, self.config = matching_alias(path, 'bb10-root'), path
            self.detect()

    def select_folder(self):
        path = filedialog.askdirectory(parent=self, title='选择以前刷机或保存个人连接材料的文件夹')
        if path:
            self.start('materials', lambda: scan_materials(path))

    def use_materials(self):
        if not self.materials or self.materials['state'] != 'ready' or self.busy:
            return
        identity = self.materials['identities'][0]
        host_key, _ = self.materials['hosts'][0]
        if not messagebox.askokcancel('确认材料来自当前手机',
                '请确认所选文件夹是你为当前手机保存的原材料。\n\n手机身份：' + fingerprint(host_key) +
                '\n\n验证时将为本机复制所需材料到应用个人目录，原文件保留。', parent=self):
            return
        def work():
            choice = import_identity(identity, host_key, confirmed=True)
            self.events.put(('candidate', choice))
            return verify_root(choice['host'], choice['config'])
        self.start('verified', work)

    def scan_current_folder(self):
        if self.materials and not self.busy:
            folder = self.materials['folder']
            self.start('materials', lambda: scan_materials(folder, recursive=False))

    def detect(self):
        def work():
            usb = local_usb_state()
            if (usb.get('usb_count') or 0) > 1:
                return {'usb': usb, 'choice': None, 'error': None}
            try:
                choice = verify_root(self.host, self.config)
                return {'usb': usb, 'choice': choice, 'error': None}
            except (WorkflowError, SetupError) as error:
                return {'usb': usb, 'choice': None, 'error': str(error)}
        self.start('detect', work)

    def start(self, action, work):
        if self.busy:
            return
        self.busy, self.choice = True, None
        self.status.configure(text='正在识别所选文件夹…' if action == 'materials' else '正在检查连接和权限，请稍候…')
        self.refresh()
        self.progress.pack(side='bottom', fill='x', before=self.status)
        self.progress.start(12)
        def worker():
            try:
                self.events.put((action, work()))
            except Exception as error:
                self.events.put(('error', str(error) if isinstance(error, (WorkflowError, SetupError, RecoveryError)) else 'connection_check_failed'))
        threading.Thread(target=worker, daemon=True).start()

    def drain(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'candidate':
                    self.host, self.config = value['host'], value['config']
                    continue
                self.busy = False
                self.progress.stop()
                self.progress.pack_forget()
                self.status.configure(text='')
                if kind == 'detect':
                    self.usb, self.choice, self.error = value['usb'], value['choice'], value['error']
                    device = self.usb.get('device', {})
                    yesno = lambda item: '已识别' if item is True else '未就绪' if item is False else '待确认'
                    self.facts.configure(text='{} · USB 设备：{} · USB 网络：{}\nRoot：{}'.format(
                        device.get('ModelName') or '手机型号待确认', yesno(self.usb.get('usb_present')),
                        yesno(self.usb.get('usb_network')), '已验证' if self.choice else '待验证（不等于未 Root）'))
                    self.show_guidance()
                elif kind == 'verified':
                    self.choice, self.error = value, None
                    self.show_guidance()
                elif kind == 'materials':
                    self.materials = value
                    self.clear_options()
                    self.title_label.configure(text='已识别连接材料' if value['state'] == 'ready' else '还需要补充连接材料')
                    self.detail.configure(text='找到一组登录密钥和手机身份记录。确认来源后，程序会建立本机配置并验证实际连接。' if value['state'] == 'ready' else MATERIAL_MESSAGES[value['state']])
                    self.status.configure(text='检查范围：' + str(value['folder']) +
                                          ('（包含子文件夹）' if value.get('recursive', True) else '（仅当前文件夹）'))
                    if value['state'] == 'ready':
                        self.option('确认来源并验证连接', self.use_materials)
                    elif value['state'] in ('limited', 'ambiguous', 'unreadable') and value.get('recursive', True):
                        self.option('只检查当前文件夹', self.scan_current_folder, '不查找子文件夹；仍需完整材料、来源确认和实际连接验证。')
                    self.option('重新选择文件夹', self.select_folder)
                    self.option('没有完整材料，从手机授权', self.pair)
                    self.option('高级：选择 SSH 配置文件', self.import_config)
                elif kind == 'error':
                    self.error = value
                    self.show_guidance()
                    from recovery_gui import MESSAGES
                    self.status.configure(text=MESSAGES.get(value, '检查未完成，请核对材料后重试。'))
                if self.choice:
                    self.host, self.config = self.choice['host'], self.choice['config']
                self.refresh()
        except queue.Empty:
            pass
        self._job = self.after(100, self.drain)

    def refresh(self):
        for button in self.option_buttons + [self.retry_button, self.back_button]:
            button.configure(state='disabled' if self.busy else 'normal')
        self.continue_button.configure(state='normal' if self.choice and not self.busy else 'disabled')

    def finish(self):
        if self.choice and not self.busy:
            choice = self.choice
            self.close()
            self.on_ready(choice['host'], choice['config'])

    def close(self):
        if self.busy:
            messagebox.showinfo('检查进行中', '请等待当前有界检查结束。', parent=self)
            return
        self.after_cancel(self._job)
        self.destroy()
        if isinstance(self.master, tk.Toplevel) and self.master.winfo_exists():
            self.master.grab_set()
