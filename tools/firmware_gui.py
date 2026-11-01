"""Firmware preparation, explicit data-loss confirmation, and boot readback."""
from pathlib import Path
from feedback import FeedbackQueue
from feedback_gui import help_row
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from firmware_policy import TARGET_OS, assess_version
import firmware_upgrade as upgrade
import root_setup as root
from fetch_materials import DownloadError, MaterialImportError
from i18n import tr
from mac_help import scrolled_page
from profile_editor import FONT

MESSAGES = {
    'upgrade_insufficient_disk': tr('准备原版系统与 Root 镜像至少需要 24 GB 可用空间。请释放空间后重试。'),
    'firmware_version_unknown': tr('未读到完整 OS 版本。请解锁手机、恢复 USB 网络并重新检测；未知版本不能刷写。'),
    'firmware_upgrade_required': tr('手机系统低于支持版本。请先完成原版系统升级，再单独确认 Root 刷写。'),
    'firmware_downgrade_blocked': tr('手机系统高于已适配基线，程序不会自动降级。请保留当前系统并核对适配方案。'),
    'firmware_already_current': tr('系统已是目标版本，无需重复升级。请继续 Root 或恢复连接。'),
    'firmware_device_changed': tr('确认后的手机系统状态发生变化，请重新检测并核对当前设备。'),
    'firmware_boot_not_verified': tr('尚未确认手机已启动到目标 OS。请等待启动、解锁并重新检测；不会重复刷写。'),
}


class FirmwareDialog(tk.Toplevel):
    def __init__(self, parent, on_ready, usb=None, root_only=False):
        super().__init__(parent)
        self.title(tr('手机系统升级'))
        self.geometry('880x730')
        self.minsize(760, 560)
        self.transient(parent)
        self.on_ready, self.usb = on_ready, usb or {}
        self.busy, self.kit, self.stage = False, None, None
        self.events = FeedbackQueue(self, 'firmware')
        self.variant = tk.StringVar(value=(self.usb.get('device') or {}).get('ModelName', ''))
        self.ack = tk.BooleanVar(value=False)
        self.root_only = tk.BooleanVar(value=root_only)
        body = ttk.Frame(self, padding=20)
        body.pack(fill='both', expand=True)
        help_row(body, self, 'firmware')
        ttk.Label(body, text=tr('先升级系统，再验证 Root 与连接'), font=(FONT, 16, 'bold')).pack(anchor='w')
        self.support_notice = ttk.Label(body, wraplength=790, justify='left')
        self.support_notice.pack(fill='x', pady=(8, 0))
        self.support_notice.bind('<Configure>', lambda event: self.support_notice.configure(wraplength=max(1, event.width - 4)))
        page, content = scrolled_page(body, padding=12)
        page.pack(fill='both', expand=True, pady=12)
        self.facts = ttk.Label(content, wraplength=710, justify='left')
        self.facts.pack(anchor='w', pady=(0, 12))
        ttk.Label(content, text=tr('原版系统升级尚待真机验收。请先完成备份，只在可清空的测试手机上使用此候选流程。'),
                  wraplength=710, justify='left').pack(anchor='w', pady=(0, 12))
        ttk.Label(content, text=tr('1. 检测准确机型与 OS，准备对应原版固件和 Root 镜像。\n'
                                  '2. 确认备份后升级原版系统；这会清空数据并移除现有 Root 与授权。\n'
                                  '3. 开机后重新检测 OS，再单独确认 Root 刷写，最后验证连接。'),
                  wraplength=710, justify='left').pack(anchor='w', pady=(0, 12))
        row = ttk.Frame(content)
        row.pack(fill='x')
        ttk.Label(row, text=tr('硬件型号')).pack(side='left')
        self.model = ttk.Combobox(row, textvariable=self.variant, values=root.firmware_variants(), state='readonly', width=20)
        self.model.pack(side='left', padx=10)
        self.model.bind('<<ComboboxSelected>>', self.changed)
        self.detect_button = ttk.Button(row, text=tr('重新检测'), command=self.detect)
        self.detect_button.pack(side='left')
        self.root_only_check = ttk.Checkbutton(content, variable=self.root_only, command=self.scope_changed,
            text=tr('仅准备或恢复系统 / Root，不开通 VoLTE'))
        self.root_only_check.pack(anchor='w', pady=(8, 0))
        self.prepare_button = ttk.Button(content, text=tr('准备升级与 Root 材料'), command=self.prepare)
        self.prepare_button.pack(anchor='w', pady=(12, 8))
        self.download_button = ttk.Button(content, text=tr('固件浏览器下载与离线导入'), command=self.downloads)
        self.download_button.pack(anchor='w')
        self.history = upgrade.pending_upgrades()
        history_row = ttk.Frame(content)
        history_row.pack(fill='x', pady=12)
        self.picker = ttk.Combobox(history_row, state='readonly', width=42,
                                  values=[item['variant'] + ' · ' + Path(item['folder']).name for item in self.history])
        self.picker.pack(side='left')
        self.resume_button = ttk.Button(history_row, text=tr('继续选中的准备记录'), command=self.resume)
        self.resume_button.pack(side='left', padx=8)
        if self.history:
            self.picker.current(0)
        else:
            history_row.pack_forget()
        self.progress_text = ttk.Label(content, wraplength=710, justify='left')
        self.progress_text.pack(anchor='w', pady=12)
        self.gate_label = ttk.Label(content, wraplength=710, justify='left')
        self.gate_label.pack(anchor='w', pady=(0, 8))
        self.ack_check = ttk.Checkbutton(content, variable=self.ack, command=self.refresh,
            text=tr('我已备份，并同意清空这台手机的数据、现有 Root 和登录授权'))
        self.ack_check.pack(anchor='w', pady=8)
        self.upgrade_button = ttk.Button(content, text=tr('升级原版系统（清空数据）'), command=self.flash)
        self.upgrade_button.pack(anchor='w', pady=8)
        self.verify_button = ttk.Button(content, text=tr('手机已开机，验证系统版本'), command=self.verify)
        self.verify_button.pack(anchor='w', pady=8)
        self.root_button = ttk.Button(content, text=tr('系统已验证，继续 Root'), command=self.continue_root)
        self.root_button.pack(anchor='w', pady=8)
        self.progress = ttk.Progressbar(body, mode='indeterminate')
        self.progress.pack(fill='x')
        self.status = ttk.Label(body, text=tr('准备材料不会刷写手机；每次刷写均需单独确认。'), wraplength=800, justify='left')
        self.status.pack(fill='x', pady=12)
        ttk.Button(body, text=tr('关闭'), command=self.close).pack(anchor='e')
        self.protocol('WM_DELETE_WINDOW', self.close)
        self._job = self.after(100, self.drain)
        self.grab_set()
        self.refresh()

    def changed(self, *_):
        self.kit, self.stage = None, None
        self.ack.set(False)
        self.root_only.set(False)
        self.refresh()

    def scope_changed(self):
        self.ack.set(False)
        self.refresh()

    def scope_blocker(self):
        import device_support
        detected = (self.usb.get('device') or {}).get('ModelName')
        variant = detected if self.usb.get('usb_count') == 1 and detected else self.variant.get()
        self.support_notice.configure(text=device_support.describe(device_support.assess(variant)))
        return device_support.preparation_blocker(variant, self.root_only.get())

    def refresh(self):
        version = assess_version((self.usb.get('device') or {}).get('PlatformVersion'))
        model = (self.usb.get('device') or {}).get('ModelName') or tr('型号待确认')
        self.facts.configure(text=tr('已检测型号：{}\n当前 OS：{}　目标 OS：{}').format(model, version.current or tr('待确认'), TARGET_OS))
        stages = {None: tr('尚未准备升级材料。'), 'prepared': tr('材料已校验。确认备份后才可升级。'),
                  'awaiting_reboot': tr('写入阶段已结束，等待开机后的 OS 回读。'),
                  'os_verified': tr('已确认目标 OS，可继续单独确认 Root 刷写。')}
        self.progress_text.configure(text=stages.get(self.stage, tr('上次刷写状态不确定。请保留现场与日志，不要重复刷写。')))
        target_valid = False
        try:
            target_valid = root.selected_firmware_variant(self.variant.get(), self.usb) == self.variant.get()
        except root.SetupError:
            pass
        scope_blocker = self.scope_blocker()
        target_valid = target_valid and not scope_blocker
        def state(button, allowed):
            button.configure(state='normal' if allowed and not self.busy else 'disabled')
        state(self.detect_button, True)
        state(self.prepare_button, target_valid and not self.kit and sys.platform in ('win32', 'darwin') and version.state not in ('newer', 'ready'))
        state(self.download_button, True)
        state(self.resume_button, bool(self.history))
        device_ready = (self.usb.get('usb_count') == 1 and target_valid and version.state == 'upgrade'
                        and (sys.platform != 'darwin' or self.usb.get('usb_address_ready') is True))
        locked = root.root_lock_path().exists()
        state(self.upgrade_button, self.stage == 'prepared' and device_ready and self.ack.get() and not locked)
        state(self.verify_button, self.stage in ('awaiting_reboot', 'os_verified'))
        state(self.root_button, self.stage == 'os_verified')
        self.model.configure(state='disabled' if self.busy or self.kit or self.usb.get('usb_count') else 'readonly')
        self.ack_check.configure(state='normal' if not self.busy and self.stage == 'prepared' else 'disabled')
        self.picker.configure(state='disabled' if self.busy else 'readonly')
        self.root_only_check.configure(state='disabled' if self.busy else 'normal')
        if scope_blocker:
            reason = scope_blocker
        elif version.state in ('newer', 'ready') and not self.kit:
            reason = MESSAGES['firmware_downgrade_blocked' if version.state == 'newer' else 'firmware_already_current']
        elif self.stage == 'prepared' and locked:
            reason = tr('存在未结束的刷写记录。请保留现场与日志，不要重复刷写。')
        elif self.stage == 'prepared' and not device_ready:
            reason = tr('刷写前须只连接一台对应型号的手机，并读到低于目标版本的 OS。请解锁手机并重新检测。')
        elif self.stage == 'prepared' and not self.ack.get():
            reason = tr('请先备份手机，再勾选清空数据确认。')
        else:
            reason = ''
        self.gate_label.configure(text=reason)

    def start(self, action, function):
        if self.busy:
            return
        self.events.begin(action)
        self.busy = True
        self.status.configure(text=tr('正在处理，请保持设备连接。'))
        self.progress.start()
        self.refresh()
        def work():
            try:
                result = function(lambda text: self.events.put(('progress', text)))
                self.events.put((action, result))
            except (DownloadError, MaterialImportError) as error:
                self.events.failure(error)
                self.events.put(('download_error', error.user_message))
            except Exception as error:
                self.events.failure(error)
                self.events.put(('error', str(error)))
        threading.Thread(target=work, daemon=True).start()

    def detect(self):
        self.start('detect', lambda _: root.local_usb_state())

    def prepare(self):
        blocker = self.scope_blocker()
        if blocker:
            self.status.configure(text=blocker)
            return
        try:
            variant = root.selected_firmware_variant(self.variant.get(), self.usb)
        except root.SetupError as error:
            self.show_error(str(error))
            return
        self.ack.set(False)
        self.start('prepared', lambda progress: upgrade.prepare_upgrade(variant, progress))

    def downloads(self):
        from setup_wizard import SetupWizard
        wizard = SetupWizard(self, self.on_ready, auto_check=False, initial_page='root')
        wizard.usb = self.usb
        wizard.variant.set(self.variant.get())
        wizard.root_only.set(self.root_only.get())
        wizard.refresh()

    def resume(self):
        index = self.picker.current()
        if index < 0:
            return
        folder = self.history[index]['folder']
        def load(_):
            state = upgrade.read_state(folder)
            if state['stage'] == 'prepared':
                upgrade.verify_kit(folder)
            return folder, state
        self.ack.set(False)
        self.start('resumed', load)

    def flash(self):
        if self.busy or not self.kit or self.stage != 'prepared' or not self.ack.get():
            return
        blocker = self.scope_blocker()
        if blocker:
            self.status.configure(text=blocker)
            return
        version = assess_version((self.usb.get('device') or {}).get('PlatformVersion'))
        if version.state != 'upgrade':
            self.show_error('firmware_version_unknown')
            return
        message = (tr('原版系统升级尚待真机验收。请先完成备份，只在可清空的测试手机上使用此候选流程。') + '\n\n' +
                   tr('目标手机：{}\n当前 OS：{} → {}\n\n将清空手机数据、现有 Root 和授权。写入后必须回读系统，再单独确认 Root。\n请确认已备份、电量充足，只连接此手机。现在开始？').format(self.variant.get(), version.current, TARGET_OS))
        if messagebox.askyesno(tr('确认清空并升级系统'), message, parent=self):
            folder = self.kit
            self.ack.set(False)
            self.start('flashed', lambda progress: upgrade.upgrade(folder, True, version.current, progress))

    def verify(self):
        if self.kit:
            self.start('verified', lambda _: upgrade.verify_boot(self.kit))

    def continue_root(self):
        if self.busy or not self.kit or self.stage != 'os_verified':
            return
        # Recheck even when a stale button or old successful journal is reused.
        self.start('root_ready', lambda _: (upgrade.verify_boot(self.kit), root.prepared_images(self.kit)))

    def show_error(self, error):
        from setup_wizard import MESSAGES as root_messages
        message = MESSAGES.get(error) or root_messages.get(error)
        self.status.configure(text=message or tr('操作未完成。请保留材料与日志，重新核对设备和下载来源。'))

    def drain(self):
        try:
            while True:
                action, value = self.events.get_nowait()
                if action == 'progress':
                    self.status.configure(text=value)
                    continue
                self.busy = False
                self.progress.stop()
                if action in ('error', 'download_error'):
                    if self.kit:
                        try:
                            self.stage = upgrade.read_state(self.kit)['stage']
                        except (OSError, ValueError, root.SetupError):
                            self.stage = 'uncertain'
                    if action == 'download_error':
                        self.status.configure(text=value)
                    else:
                        self.show_error(value)
                elif action == 'detect':
                    self.usb = value
                    model = (value.get('device') or {}).get('ModelName')
                    if value.get('usb_count') == 1 and model in root.firmware_variants() and not self.kit:
                        self.variant.set(model)
                    self.status.configure(text=tr('检测完成。请核对机型、版本和当前步骤。'))
                elif action in ('prepared', 'flashed'):
                    self.kit = value
                    self.variant.set(upgrade.read_state(value)['variant'])
                    self.stage = upgrade.read_state(value)['stage']
                    self.status.configure(text=tr('准备完成。') if action == 'prepared' else tr('请等待手机开机，然后点击验证系统版本。'))
                elif action == 'resumed':
                    self.kit, state = value
                    self.stage = state['stage']
                    self.variant.set(state['variant'])
                    self.status.configure(text=tr('已恢复记录；不会自动继续刷写。'))
                elif action == 'verified':
                    self.stage = value['stage']
                    self.usb = value['usb']
                    self.status.configure(text=tr('系统版本已验证。下一步仍需单独确认 Root 刷写。'))
                elif action == 'root_ready':
                    from setup_wizard import SetupWizard
                    wizard = SetupWizard(self, self.on_ready, auto_check=False, initial_page='root')
                    wizard.variant.set(self.variant.get())
                    wizard.root_only.set(self.root_only.get())
                    wizard.kit = self.kit
                    wizard.ack.set(False)
                    wizard.refresh()
                    wizard.detect()
                self.refresh()
        except queue.Empty:
            pass
        self._job = self.after(100, self.drain)

    def close(self):
        if self.busy:
            messagebox.showinfo(tr('操作进行中'), tr('请等待本次有界操作结束。强行退出不能撤销已经写入手机的步骤。'), parent=self)
            return
        self.after_cancel(self._job)
        self.destroy()
        if isinstance(self.master, tk.Toplevel) and self.master.winfo_exists():
            self.master.grab_set()
