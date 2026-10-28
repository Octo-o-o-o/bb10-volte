"""Guided local prerequisites; destructive flashing requires an explicit choice."""
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from connection import matching_alias
from profile_editor import FONT
from root_setup import (SetupError, catalog, local_usb_state, verify_root,
                        prepare_root_kit, flash_root, prepare_driver_kit, install_driver_kit, ensure_ssh)
from workflow import WorkflowError

MESSAGES = {
    'openssh_missing': '本机缺少 SSH 客户端。Windows 源码用户可点击“准备连接组件”，由本项目自动获取。',
    'root_model_unsupported': '当前自动 Root 配方仅支持 Q10。Q20 / Q30 必须使用各自的固件，不能套用 Q10 镜像。',
    'windows_root_required': '首次 Root 刷写目前需要 Windows。此 Mac 应用可连接已 Root 的设备；请先在 Windows 完成首次准备。',
    'root_not_ready': 'SSH 已连通，但尚未取得有效 Root。请按已有 Root 方法完成启动，再重新检测。',
    'already_rooted': '已检测到可用 Root，已阻止重复刷写。请直接返回主界面检查设备。',
    'ssh_access_needs_repair': '手机已提供 SSH，但未能验证当前密钥。请导入原有个人配置，不要用重新刷写修复密钥问题。',
    'insufficient_disk': '可用磁盘空间不足，请至少预留 15 GB 后重试。',
    'tool_hash_mismatch': '工具文件校验失败，已停止。请保留现场并重新获取正确材料。',
    'image_not_verified': '镜像校验未通过，已禁止刷写。',
    'device_model_not_verified': '未能核对唯一连接手机的型号。请解锁手机，只保留这一台 USB 设备后重试。',
    'flash_state_unknown': '刷写状态未确认，自动流程已暂停。请保留镜像与现场，核对手机和刷写窗口结果，不要重复刷写。',
    'driver_install_incomplete': '驱动安装未完成。可能取消了管理员确认，或已有进程需要处理；请查看驱动指南后重试。',
    'host_key_mismatch': '手机主机密钥与当前配置不符。请使用这台设备原来的可信配置，不要关闭主机校验。',
    'connection_setup_required': '尚未找到可用的个人配置。已有 Root 请导入原配置；首次使用请按下方手机步骤准备。',
    'authentication_failed': '个人密钥未获这台手机授权，请导入原来的 SSH 配置。',
    'connection_failed': '尚未连通手机。检查 USB、手机解锁、Root 启动状态后重新检测。',
    'connection_refused': '手机尚未提供 SSH。已有 AutoRoot 可打开一次 BlackBerry World 等待启动；仍不恢复时，从手机电源菜单正常重启后重试。',
}


class SetupWizard(tk.Toplevel):
    def __init__(self, parent, on_ready, auto_check=True):
        super().__init__(parent)
        self.title('首次使用与连接帮助')
        self.geometry('860x730')
        self.minsize(800, 680)
        self.transient(parent)
        self.on_ready, self.events = on_ready, queue.Queue()
        self.busy, self.choice, self.kit, self.usb = False, None, None, {}
        self.host, self.config = 'bb10-root', ''
        self.variant = tk.StringVar()
        self.proxy = tk.StringVar()
        self.ack = tk.BooleanVar()
        body = ttk.Frame(self, padding=24)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='准备好设备，再继续开通', font=(FONT, 17, 'bold')).pack(anchor='w')
        self.status = ttk.Label(body, text='已有 Root 的设备可直接检测；首次 Root 需要备份并刷写。', wraplength=790)
        self.status.pack(anchor='w', pady=(8, 18))
        self.tabs = ttk.Notebook(body)
        self.tabs.pack(fill='both', expand=True)
        connection = ttk.Frame(self.tabs, padding=20)
        root_tab = ttk.Frame(self.tabs, padding=20)
        drivers = ttk.Frame(self.tabs, padding=20)
        for frame, title in [(connection, '连接检查'), (root_tab, '首次 Root'), (drivers, 'Windows 驱动')]:
            self.tabs.add(frame, text=title)
        self.device = ttk.Label(connection, text='设备型号与系统将在检测后显示', font=(FONT, 12, 'bold'))
        self.device.pack(anchor='w', pady=(0, 12))
        self.facts = ttk.Label(connection, text='等待检测 USB、开发模式、SSH 与 Root。', wraplength=730, justify='left')
        self.facts.pack(anchor='w', pady=(0, 20))
        ttk.Label(connection, text='需要在手机上配合时', font=(FONT, 12, 'bold')).pack(anchor='w')
        ttk.Label(connection, text='1. 解锁手机，用数据线连接电脑。\n'
                  '2. 首次开发连接：设置 → 安全和隐私 → 开发模式，按手机提示开启。\n'
                  '3. 已有 AutoRoot：必要时打开一次 BlackBerry World，等待 Root / SSH 就绪。商店提示无网络不等于 Root 失败。\n'
                  '4. 已有个人 SSH 配置可直接导入。连接失败不能单独证明手机没有 Root。\n\n'
                  '已有可用 Root SSH 时，开发模式无需为了本应用一直开启。重启后 Root 与 IMS 会先后就绪，请等待注册完成。',
                  wraplength=730, justify='left').pack(anchor='w', pady=(8, 18))
        actions = ttk.Frame(connection)
        actions.pack(fill='x')
        self.detect_button = ttk.Button(actions, text='重新检测', command=self.detect)
        self.detect_button.pack(side='left')
        self.import_button = ttk.Button(actions, text='导入已有连接', command=self.import_connection)
        self.import_button.pack(side='left', padx=10)
        self.components_button = ttk.Button(actions, text='准备连接组件', command=self.components)
        if sys.platform == 'win32':
            self.components_button.pack(side='left')
        self.continue_button = ttk.Button(connection, text='返回主界面并检查', style='Accent.TButton', command=self.continue_to_app, state='disabled')
        self.continue_button.pack(anchor='e', pady=(20, 0))

        ttk.Label(root_tab, text='自动获取材料 → 生成个人密钥 → 构建校验镜像 → 确认后刷写', wraplength=740,
                  font=(FONT, 11, 'bold')).pack(anchor='w')
        if sys.platform != 'win32':
            ttk.Label(root_tab, text='本机支持连接已 Root 的 BB10 设备；首次 Root 刷写目前请在 Windows 完成。',
                      wraplength=740).pack(anchor='w', pady=(12, 0))
            self.tabs.tab(drivers, state='disabled')
        ttk.Label(root_tab, text='当前自动配方支持 Q10；首次刷写会清空手机数据。Q20 / Q30 请使用匹配机型的 Root 方法。\n'
                  '应用自动下载固定版本工具和固件，无需另装 Git、7-Zip 或其他 Root 项目。首次准备需要互联网和至少 15 GB 空间。',
                  wraplength=740, justify='left').pack(anchor='w', pady=(10, 18))
        line = ttk.Frame(root_tab)
        line.pack(fill='x')
        ttk.Label(line, text='手机型号').pack(side='left', padx=(0, 14))
        self.model_picker = ttk.Combobox(line, textvariable=self.variant, values=catalog()['auto_root_variants'], state='readonly', width=20)
        self.model_picker.pack(side='left')
        self.prepare_button = ttk.Button(root_tab, text='自动准备 Root 镜像', command=self.prepare_root)
        self.prepare_button.pack(anchor='w', pady=(16, 12))
        self.ack_check = ttk.Checkbutton(root_tab, text='已备份并核对机型，同意清空手机数据', variable=self.ack)
        self.ack_check.pack(anchor='w')
        self.ack.trace_add('write', lambda *_: self.refresh())
        self.flash_button = ttk.Button(root_tab, text='开始刷写 Root（清空数据）', command=self.flash, state='disabled')
        self.flash_button.pack(anchor='w', pady=(12, 14))
        ttk.Label(root_tab, text='刷写后完成手机首次设置，打开一次 BlackBerry World，再到“连接检查”验证 Root。\n'
                  '刷写窗口可能要求输入设备密码；应用不会记录该密码。', wraplength=740, justify='left').pack(anchor='w')
        network = ttk.Frame(root_tab)
        network.pack(side='bottom', fill='x', pady=(12, 0))
        ttk.Label(network, text='下载代理（可选）').pack(side='left', padx=(0, 12))
        self.proxy_entry = ttk.Entry(network, textvariable=self.proxy)
        self.proxy_entry.pack(side='left', fill='x', expand=True)

        ttk.Label(drivers, text='只有 Windows 未识别手机或没有 USB 网络时，才需要安装驱动。',
                  wraplength=740, font=(FONT, 11, 'bold')).pack(anchor='w', pady=(0, 12))
        ttk.Label(drivers, text='应用下载并校验 BlackBerry 驱动，随后通过 Windows 管理员确认完成安装。\n'
                  '请先保存电脑上的工作。安装器不会自动重启；现有程序冲突时会暂停。',
                  wraplength=740, justify='left').pack(anchor='w')
        self.driver_button = ttk.Button(drivers, text='自动准备并安装驱动', command=self.drivers)
        self.driver_button.pack(anchor='w', pady=20)
        self.progress = ttk.Progressbar(body, mode='indeterminate')
        self.progress.pack(fill='x', pady=(18, 10))
        ttk.Button(body, text='关闭', command=self.close).pack(anchor='e')
        self.protocol('WM_DELETE_WINDOW', self.close)
        self._job = self.after(100, self.drain)
        self.grab_set()
        self.refresh()
        if auto_check:
            self.detect()

    def refresh(self):
        for button in (self.detect_button, self.import_button, self.prepare_button, self.driver_button, self.components_button):
            button.configure(state='disabled' if self.busy else 'normal')
        self.prepare_button.configure(state='normal' if not self.busy and sys.platform == 'win32' and not self.choice else 'disabled')
        self.driver_button.configure(state='normal' if not self.busy and sys.platform == 'win32' and not self.usb.get('usb_network') else 'disabled')
        self.flash_button.configure(state='normal' if self.kit and self.ack.get() and not self.busy and not self.choice else 'disabled')
        self.continue_button.configure(state='normal' if self.choice and not self.busy else 'disabled')
        self.model_picker.configure(state='disabled' if self.busy or self.kit else 'readonly')
        self.proxy_entry.configure(state='disabled' if self.busy else 'normal')
        self.ack_check.configure(state='disabled' if self.busy else 'normal')

    def start(self, action, function):
        if self.busy:
            return
        self.busy = True
        self.refresh()
        self.progress.start(12)
        self.status.configure(text='正在处理，请保持设备连接。')
        def worker():
            try:
                self.events.put(('result', (action, function(lambda value: self.events.put(('progress', value))))))
            except (SetupError, WorkflowError) as error:
                self.events.put(('error', str(error)))
            except Exception:
                self.events.put(('error', 'preparation_failed'))
        threading.Thread(target=worker, daemon=True).start()

    def detect(self):
        def work(progress):
            usb = local_usb_state()
            try:
                choice = verify_root(self.host, self.config)
                error = None
                usb['ssh_port'] = True
            except (SetupError, WorkflowError) as exc:
                choice, error = None, str(exc)
                if error == 'connection_refused':
                    usb['ssh_port'] = False
                elif error in ('authentication_failed', 'host_key_mismatch', 'root_not_ready'):
                    usb['ssh_port'] = True
            return {'usb': usb, 'choice': choice, 'error': error}
        self.start('detect', work)

    def import_connection(self):
        path = filedialog.askopenfilename(parent=self, title='选择这台手机原来的 SSH 配置')
        if path:
            self.host, self.config = matching_alias(path, 'bb10-root'), path
            self.detect()

    def prepare_root(self):
        variant, proxy = self.variant.get(), self.proxy.get().strip() or None
        if variant not in catalog()['auto_root_variants']:
            self.status.configure(text='请先检测设备，或按手机“关于”中的硬件型号选择正确的 Q10 变体。')
            return
        self.start('prepare', lambda progress: prepare_root_kit(variant, progress, proxy))

    def flash(self):
        if not self.kit or not self.ack.get() or self.busy:
            return
        if messagebox.askyesno('确认清空并刷写', '此操作会清空手机数据，并写入对应 Q10 的 Root 系统与无线固件。\n\n'
                              '请只连接这一台手机，确保已备份、电量充足，并保持 USB 稳定。确认开始？', parent=self):
            self.start('flash', lambda progress: flash_root(self.kit, True, progress))

    def drivers(self):
        if not messagebox.askokcancel('安装 BlackBerry 驱动', '将下载并校验驱动，然后请求 Windows 管理员确认。请先保存电脑上的工作。', parent=self):
            return
        proxy = self.proxy.get().strip() or None
        self.start('drivers', lambda progress: install_driver_kit(prepare_driver_kit(progress, proxy)))

    def components(self):
        proxy = self.proxy.get().strip() or None
        self.start('components', lambda progress: str(ensure_ssh(progress, proxy)))

    def drain(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'progress':
                    self.status.configure(text=value)
                    continue
                self.busy = False
                self.progress.stop()
                if kind == 'error':
                    self.status.configure(text=MESSAGES.get(value, '准备未完成。请检查网络或材料，保留现场后重试；下载代理可在“首次 Root”页设置。'))
                else:
                    action, result = value
                    if action == 'detect':
                        self.usb, self.choice = result['usb'], result['choice']
                        device = self.usb['device']
                        model = device.get('ModelName', '型号待确认')
                        self.device.configure(text=model + ' · ' + device.get('PlatformVersion', '系统待确认'))
                        if model in catalog()['auto_root_variants'] and not self.kit:
                            self.variant.set(model)
                        yesno = lambda value: '已就绪' if value is True else '未就绪' if value is False else '待确认'
                        development = device.get('DeveloperModeEnabled')
                        ssh_state = ('需核对密钥' if result['error'] in ('authentication_failed', 'host_key_mismatch') else yesno(self.usb['ssh_port']))
                        self.facts.configure(text='USB 设备：{}    USB 网络：{}\n开发模式：{}    SSH 连接：{}\nRoot：{}'.format(
                            yesno(self.usb['usb_present']), yesno(self.usb['usb_network']),
                            '已开启' if development == '1' else '未开启' if development == '0' else '待确认',
                            ssh_state, '已验证' if self.choice else '未能验证（不等于未 Root）'))
                        self.status.configure(text='Root 连接已验证，可以继续。开发模式无需为此保持开启。' if self.choice else
                                              MESSAGES.get(result['error'], '请按手机上的准备步骤操作，再重新检测。'))
                        if self.choice:
                            self.host, self.config = self.choice['host'], self.choice['config']
                    elif action == 'prepare':
                        self.kit = result
                        self.status.configure(text='Root 镜像已构建并校验。确认备份后，才能进入会清空数据的刷写步骤。')
                    elif action == 'flash':
                        self.host, self.config = result['host'], result['config']
                        self.tabs.select(0)
                        self.status.configure(text='刷写已结束。请完成手机首次设置，打开一次 BlackBerry World，再重新检测 Root。')
                    elif action == 'drivers':
                        self.status.configure(text='驱动安装完成，请按 Windows 提示重启后重新检测。' if result['reboot_required'] else
                                              '驱动安装完成，请重新连接手机并检测。')
                    elif action == 'components':
                        self.status.configure(text='连接组件已就绪，请重新检测。')
                self.refresh()
        except queue.Empty:
            pass
        self._job = self.after(100, self.drain)

    def continue_to_app(self):
        if self.choice and not self.busy:
            choice = self.choice
            self.close()
            self.on_ready(choice['host'], choice['config'])

    def close(self):
        if self.busy:
            messagebox.showinfo('准备进行中', '请等待当前步骤结束。刷写期间不要断开 USB 或关闭刷写窗口。', parent=self)
            return
        self.after_cancel(self._job)
        self.destroy()
