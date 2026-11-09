"""Guided local prerequisites; destructive flashing requires an explicit choice."""
from i18n import tr
from firmware_policy import baseline_error
import device_support
from pathlib import Path
from feedback import FeedbackQueue
from feedback_gui import help_row
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from connection import matching_alias
from profile_editor import FONT
from root_setup import (SetupError, catalog, local_usb_state, verify_root,
                        prepare_root_kit, flash_root, prepare_driver_kit, install_driver_kit, ensure_ssh,
                        prepared_kit_history, prepared_images, root_lock_path,
                        stock_firmware, import_stock_firmware, download_stock_firmware,
                        firmware_variants, selected_firmware_variant)
from workflow import WorkflowError
from fetch_materials import DownloadError, MaterialImportError, source_urls, source_label
from mac_help import PHONE_STEPS, scrolled_page, show_guide as show_mac_guide
from storage_help import show_storage_help

MESSAGES = {
    'firmware_version_unknown': tr('未读到完整 OS 版本。请先解锁手机并重新检测，确认系统版本后才能刷写 Root。'),
    'firmware_upgrade_required': tr('手机系统低于 10.3.3.3216。请先使用“系统升级”完成升级，再确认 Root 刷写。'),
    'firmware_downgrade_blocked': tr('手机系统高于已适配版本，不能自动降级或直接刷写当前 Root 镜像。'),
    'firmware_model_required': tr('请先检测设备，或按手机“关于”中的硬件型号选择固件。'),
    'firmware_model_unsupported': tr('此硬件型号尚无已校验的固件来源，请核对型号；不会自动改用 Q10 固件。'),
    'firmware_multiple_devices': tr('检测到多台黑莓。请只连接目标手机后重新检测，或断开设备再手动选择型号离线下载。'),
    'firmware_device_unverified': tr('尚未识别连接手机的准确硬件型号，请解锁手机后重新检测。'),
    'firmware_model_mismatch': tr('所选型号与连接手机不符，请重新检测后获取对应固件。'),
    'openssh_missing': tr('本机缺少 SSH 客户端。Windows 源码用户可点击“准备连接组件”，由本项目自动获取。'),
    'root_model_unsupported': tr('此硬件型号尚无自动 Root 配方，请先核对准确型号。'),
    'root_build_failed': tr('Root 镜像构建失败，尚未刷写手机。请保留本机 root-build.log，核对失败原因后再准备。'),
    'windows_root_required': tr('本应用首次 Root 准备仅支持 Windows 和 Mac；其他平台请参考原作者方法。'),
    'root_not_ready': tr('SSH 已连通，但尚未取得有效 Root。请按已有 Root 方法完成启动，再重新检测。'),
    'root_probe_failed': tr('已建立 SSH，但 Root 诊断未完成。请保留现场核对诊断结果，不要因此重新刷写或更改手机安全设置。'),
    'root_platform_mismatch': tr('镜像包与本机平台不符。Mac 原生流程不能直接运行 Windows EXE，请在本机重新准备匹配的个人镜像包。'),
    'usb_source_address_required': tr('尚未确认黑莓 USB 接口使用 169.254.0.2。请先核对 USB 网络；现有授权可能限制这个来源地址。'),
    'native_console_unavailable': tr('未能打开可交互的 Terminal 刷写窗口，已停止。请保留当前阶段，不要重复启动刷写。'),
    'path_unsupported': tr('个人目录路径含当前工具不支持的字符。请保留现有材料，改用不含等号、换行或引号的目录重新准备。'),
    'macos_root_architecture_unsupported': tr('原生 Mac 首次 Root 工具仅提供 Apple Silicon 和 Intel Mac 版本。'),
    'macos_root_version_unsupported': tr('原生首次 Root 工具需要 macOS 14 或更新版本；这不影响已有可用 SSH 的日常连接。'),
    'macos_root_input_missing': tr('离线缓存缺少固定材料。请允许本次准备下载，或提供完整且校验通过的缓存。'),
    'macos_root_runtime_unavailable': tr('Mac 原生 Root 工具未能启动。请核对工具和私有依赖，不要为此降低系统安全设置。'),
    'macos_root_build_failed': tr('原生镜像构建失败，尚未刷写手机。请保留本机 root-build.log，核对失败原因后再准备。'),
    'already_rooted': tr('已检测到可用 Root，已阻止重复刷写。请直接返回主界面检查设备。'),
    'ssh_access_needs_repair': tr('手机已提供 SSH，但未能验证当前密钥。请导入原有个人配置，不要用重新刷写修复密钥问题。'),
    'insufficient_disk': tr('可用磁盘空间不足，请至少预留 15 GB 后重试。'),
    'preparation_busy': tr('另一个窗口或程序正在准备材料，请等待完成后重试，不会另建一份。'),
    'tool_hash_mismatch': tr('工具文件校验失败，已停止。请保留现场并重新获取正确材料。'),
    'image_not_verified': tr('镜像校验未通过，已禁止刷写。'),
    'device_model_not_verified': tr('未能核对唯一连接手机的型号。请解锁手机，只保留这一台 USB 设备后重试。'),
    'flash_state_unknown': tr('刷写状态未确认，自动流程已暂停。请保留镜像与现场，核对手机和刷写窗口结果，不要重复刷写。'),
    'driver_install_incomplete': tr('驱动安装未完成。可能取消了管理员确认，或已有进程需要处理；请查看驱动指南后重试。'),
    'host_key_mismatch': tr('手机主机密钥与当前配置不符。请使用这台设备原来的可信配置，不要关闭主机校验。'),
    'connection_setup_required': tr('尚未找到可用的个人配置。已有 Root 请导入原配置；首次使用请按下方手机步骤准备。'),
    'authentication_failed': tr('个人密钥未获这台手机授权，请导入原来的 SSH 配置。'),
    'connection_failed': tr('尚未连通手机。检查 USB、手机解锁、Root 启动状态后重新检测。'),
    'connection_refused': tr('手机尚未提供 SSH。已有 AutoRoot 可打开一次 BlackBerry World 等待启动；仍不恢复时，从手机电源菜单正常重启后重试。'),
}


class SetupWizard(tk.Toplevel):
    def __init__(self, parent, on_ready, auto_check=True, initial_page='connection'):
        super().__init__(parent)
        self.title(tr('首次使用与连接帮助'))
        self.geometry('860x730')
        self.minsize(800, 680)
        self.transient(parent)
        self.on_ready, self.events = on_ready, FeedbackQueue(self, 'root')
        self.busy, self.choice, self.kit, self.usb = False, None, None, {}
        self.host, self.config = 'bb10-root', ''
        self.variant = tk.StringVar()
        self._last_variant = ''
        self.proxy = tk.StringVar()
        self.firmware_path = tk.StringVar()
        self.imported_variant = None
        self.ack = tk.BooleanVar()
        self.mac_flash_ack = tk.BooleanVar()
        self.root_only = tk.BooleanVar(value=False)
        self.operator = tk.StringVar()
        body = ttk.Frame(self, padding=24)
        body.pack(fill='both', expand=True)
        help_row(body, self, lambda: ('connect', 'root', 'drivers')[self.tabs.index(self.tabs.select())])
        ttk.Label(body, text=tr('准备好设备，再继续开通'), font=(FONT, 17, 'bold')).pack(anchor='w')
        self.status = ttk.Label(body, text=tr('已有 Root 的设备可直接检测；首次 Root 需要备份并刷写。'), wraplength=790)
        self.status.pack(anchor='w', pady=(8, 18))
        self.support_notice = ttk.Label(body, wraplength=790, justify='left')
        self.support_notice.pack(fill='x', pady=(0, 12))
        self.support_notice.bind('<Configure>', lambda event: self.support_notice.configure(wraplength=max(1, event.width - 4)))
        self.tabs = ttk.Notebook(body)
        self.tabs.pack(fill='both', expand=True)
        connection_page, connection = scrolled_page(self.tabs, padding=20)
        root_page, root_tab = scrolled_page(self.tabs, padding=20)
        drivers = ttk.Frame(self.tabs, padding=20)
        for frame, title in [(connection_page, tr('连接检查')), (root_page, tr('首次 Root')), (drivers, tr('Windows 驱动'))]:
            self.tabs.add(frame, text=title)
        self.tabs.select({'connection': 0, 'root': 1, 'drivers': 2}.get(initial_page, 0))
        self.device = ttk.Label(connection, text=tr('设备型号与系统将在检测后显示'), font=(FONT, 12, 'bold'))
        self.device.pack(anchor='w', pady=(0, 12))
        self.facts = ttk.Label(connection, text=tr('等待检测 USB、开发模式、SSH 与 Root。'), wraplength=730, justify='left')
        self.facts.pack(anchor='w', pady=(0, 20))
        ttk.Label(connection, text=tr('按手机现状准备连接') if sys.platform == 'darwin' else tr('需要在手机上配合时'),
                  font=(FONT, 12, 'bold')).pack(anchor='w')
        phone_steps = PHONE_STEPS if sys.platform == 'darwin' else (tr('1. 解锁手机，用数据线连接电脑。\n'
                  '2. 首次开发连接：设置 → 安全和隐私 → 开发模式，按手机提示开启。\n'
                  '3. 已有 AutoRoot：必要时打开一次 BlackBerry World，等待 Root / SSH 就绪。商店提示无网络不等于 Root 失败。\n'
                  '4. 已有个人 SSH 配置可直接导入。连接失败不能单独证明手机没有 Root。\n\n'
                  '已有可用 Root SSH 时，开发模式无需为了本应用一直开启。重启后 Root 与 IMS 会先后就绪，请等待注册完成。'))
        self.phone_steps = ttk.Label(connection, text=phone_steps, wraplength=730, justify='left')
        self.phone_steps.pack(anchor='w', pady=(8, 18))
        actions = ttk.Frame(connection)
        actions.pack(fill='x')
        self.detect_button = ttk.Button(actions, text=tr('重新检测'), command=self.detect)
        self.detect_button.pack(side='left')
        self.import_button = ttk.Button(actions, text=tr('导入已有连接'), command=self.import_connection)
        self.import_button.pack(side='left', padx=10)
        self.components_button = ttk.Button(actions, text=tr('准备连接组件'), command=self.components)
        if sys.platform == 'win32':
            self.components_button.pack(side='left')
        self.mac_guide_button = None
        if sys.platform == 'darwin':
            self.mac_guide_button = ttk.Button(actions, text=tr('Mac 连接说明'), command=lambda: show_mac_guide(self))
            self.mac_guide_button.pack(side='left')
        self.continue_button = ttk.Button(connection, text=tr('返回主界面并检查'), style='Accent.TButton', command=self.continue_to_app, state='disabled')
        self.continue_button.pack(anchor='e', pady=(20, 0))
        self.recovery_button = ttk.Button(connection, text=tr('已 Root 但没有连接配置？恢复连接'), command=self.recover_connection)
        self.recovery_button.pack(anchor='w', pady=(10, 0))
        self.upgrade_help_button = ttk.Button(connection, text=tr('系统升级 / 继续升级记录'), command=self.open_firmware)
        self.upgrade_help_button.pack(anchor='w', pady=(8, 0))

        ttk.Label(root_tab, text=tr('自动获取材料 → 生成个人密钥 → 构建校验镜像 → 确认后刷写'), wraplength=740,
                  font=(FONT, 11, 'bold')).pack(anchor='w')
        if sys.platform == 'darwin':
            ttk.Label(root_tab, text=tr('macOS 14+ 原生实验流程：按准确型号准备镜像，确认后打开 Terminal 刷写；Apple 芯片 Mac／Q20 已完成原生首刷验收，其他组合仍待验证。'),
                      wraplength=740).pack(anchor='w', pady=(12, 0))
        if sys.platform != 'win32':
            self.tabs.tab(drivers, state='disabled')
        ttk.Label(root_tab, text=tr('固件按检测到的硬件型号下载，支持 Q10、Classic（Q20）和 Passport（Q30）。\n'
                  '导入原版固件后，点击下方“自动准备 Root 镜像”，生成本机型的个人镜像，再确认刷写。\n'
                  '应用自动测速选择下载节点，中断或持续低速时自动切换并续传。无需另装 Git、7-Zip 或其他 Root 项目。首次准备需要互联网和至少 15 GB 空间。'),
                  wraplength=740, justify='left').pack(anchor='w', pady=(10, 18))
        line = ttk.Frame(root_tab)
        line.pack(fill='x')
        ttk.Label(line, text=tr('手机型号')).pack(side='left', padx=(0, 14))
        self.model_picker = ttk.Combobox(line, textvariable=self.variant, values=firmware_variants(), state='readonly', width=20)
        self.model_picker.pack(side='left')
        carrier_row = ttk.Frame(root_tab)
        carrier_row.pack(fill='x', pady=8)
        ttk.Label(carrier_row, text=tr('计划使用的运营商')).pack(side='left', padx=(0, 12))
        self.operator_options = [tr('连接后核对 SIM'), tr('中国移动'), tr('中国联通'), tr('中国电信')]
        self.operator_picker = ttk.Combobox(carrier_row, textvariable=self.operator,
                                            values=self.operator_options, state='readonly', width=22)
        self.operator_picker.current(0)
        self.operator_picker.pack(side='left')
        self.root_only_check = ttk.Checkbutton(root_tab, variable=self.root_only,
            text=tr('仅准备或恢复系统 / Root，不开通 VoLTE'))
        self.root_only_check.pack(anchor='w', pady=(0, 8))
        self.root_scope = ttk.Label(root_tab, wraplength=730, justify='left')
        self.root_scope.pack(fill='x', pady=(0, 12))
        self.root_scope.bind('<Configure>', lambda event: self.root_scope.configure(wraplength=max(1, event.width - 4)))
        self.history = prepared_kit_history()
        history_row = ttk.Frame(root_tab)
        history_row.pack(fill='x', pady=(12, 0))
        stage_labels = {'prepared': tr('镜像已准备'), 'flashed_waiting_for_root': tr('已刷写，等待验证')}
        self.history_picker = ttk.Combobox(history_row, state='readonly', width=46, values=[
            '{} · {} · {}'.format(item['variant'], stage_labels.get(item['stage'], tr('刷写状态待核对')), Path(item['folder']).name)
            for item in self.history])
        self.history_picker.pack(side='left')
        self.resume_button = ttk.Button(history_row, text=tr('继续上次准备'), command=self.resume_preparation)
        self.resume_button.pack(side='left', padx=(8, 0))
        if not self.history:
            history_row.pack_forget()
        elif len(self.history) == 1:
            self.history_picker.current(0)
        self.download_firmware_button = ttk.Button(root_tab, text=tr('下载对应机型固件'), command=self.download_firmware)
        self.download_firmware_button.pack(anchor='w', pady=(0, 12))
        manual = ttk.LabelFrame(root_tab, text=tr('对应机型固件：浏览器下载或本地导入'), padding=12)
        manual.pack(fill='x', pady=(0, 16))
        self.firmware_label = ttk.Label(manual, wraplength=680, justify='left')
        self.firmware_label.pack(anchor='w')
        self.firmware_urls = []
        source_row = ttk.Frame(manual)
        source_row.pack(fill='x', pady=(8, 0))
        ttk.Label(source_row, text=tr('浏览器下载来源')).pack(side='left', padx=(0, 10))
        self.firmware_source = ttk.Combobox(source_row, state='readonly', width=38,
                                          values=[source_label(url) for url in self.firmware_urls])
        self.firmware_source.pack(side='left', fill='x', expand=True)
        links = ttk.Frame(manual)
        links.pack(fill='x', pady=(8, 12))
        self.browser_download_button = ttk.Button(links, text=tr('在浏览器下载固件'), command=self.open_firmware_download)
        self.browser_download_button.pack(side='left')
        self.copy_download_button = ttk.Button(links, text=tr('复制下载链接'), command=self.copy_firmware_link)
        self.copy_download_button.pack(side='left', padx=(8, 0))
        domestic_links = ttk.Frame(manual)
        domestic_links.pack(fill='x', pady=(0, 8))
        self.domestic_download_button = ttk.Button(domestic_links, text=tr('国内下载（极空间）'), command=self.open_domestic_download)
        self.domestic_download_button.pack(side='left')
        self.copy_domestic_download_button = ttk.Button(domestic_links, text=tr('复制极空间链接'), command=self.copy_domestic_link)
        self.copy_domestic_download_button.pack(side='left', padx=(8, 0))
        self.domestic_download_hint = ttk.Label(domestic_links, wraplength=250)
        self.domestic_download_hint.pack(side='left', padx=(8, 0))
        backup_links = ttk.Frame(manual)
        backup_links.pack(fill='x', pady=(0, 8))
        self.backup_download_button = ttk.Button(backup_links, text=tr('备用下载（百度网盘）'), command=self.open_backup_download)
        self.backup_download_button.pack(side='left')
        self.copy_backup_download_button = ttk.Button(backup_links, text=tr('复制备用链接'), command=self.copy_backup_link)
        self.copy_backup_download_button.pack(side='left', padx=(8, 0))
        self.backup_download_hint = ttk.Label(backup_links, wraplength=250)
        self.backup_download_hint.pack(side='left', padx=(8, 0))
        ttk.Label(manual, text=tr('2. 下载完成后，选择文件或粘贴本地完整路径：'), wraplength=680).pack(anchor='w')
        file_row = ttk.Frame(manual)
        file_row.pack(fill='x', pady=(8, 8))
        self.firmware_entry = ttk.Entry(file_row, textvariable=self.firmware_path)
        self.firmware_entry.pack(side='left', fill='x', expand=True)
        self.browse_firmware_button = ttk.Button(file_row, text=tr('选择文件…'), command=self.browse_firmware)
        self.browse_firmware_button.pack(side='left', padx=(8, 0))
        self.import_firmware_button = ttk.Button(manual, text=tr('校验并导入固件'), command=self.import_firmware)
        self.import_firmware_button.pack(anchor='w')
        ttk.Label(manual, text=tr('保留下载的原文件，不要运行或解压。导入只校验原版固件；Q10、Q20、Q30 均需继续准备 Root 镜像。'),
                  wraplength=680, justify='left').pack(anchor='w', pady=(8, 0))
        self.prepare_button = ttk.Button(root_tab, text=tr('自动准备 Root 镜像'), command=self.prepare_root)
        self.prepare_button.pack(anchor='w', pady=(0, 8))
        self.root_hint = ttk.Label(root_tab, wraplength=730, justify='left')
        self.root_hint.pack(anchor='w', pady=(0, 12))
        self.root_detect_button = ttk.Button(root_tab, text=tr('重新检测连接与机型'), command=self.detect)
        self.root_detect_button.pack(anchor='w', pady=(0, 8))
        self.root_firmware_button = ttk.Button(root_tab, text=tr('系统升级 / 继续升级记录'), command=self.open_firmware)
        self.root_firmware_button.pack(anchor='w', pady=(0, 12))
        self.ack_check = ttk.Checkbutton(root_tab, text=tr('已备份并核对机型，同意清空手机数据'), variable=self.ack)
        self.ack_check.pack(anchor='w')
        self.ack.trace_add('write', lambda *_: self.refresh())
        self.mac_flash_check = None
        if sys.platform == 'darwin':
            self.mac_flash_check = ttk.Checkbutton(root_tab, text=tr('已核对手机尚未 Root，理解实验性刷写的验证范围'),
                                                   variable=self.mac_flash_ack)
            self.mac_flash_check.pack(anchor='w', pady=(6, 0))
            self.mac_flash_ack.trace_add('write', lambda *_: self.refresh())
        self.flash_button = ttk.Button(root_tab, text=tr('开始刷写 Root（清空数据）'), command=self.flash, state='disabled')
        self.flash_button.pack(anchor='w', pady=(12, 14))
        ttk.Label(root_tab, text=tr('刷写后完成手机首次设置，打开一次 BlackBerry World，再到“连接检查”验证 Root。\n'
                  '刷写窗口可能要求输入设备密码；应用不会记录该密码。'), wraplength=740, justify='left').pack(anchor='w')
        network = ttk.Frame(root_tab)
        network.pack(side='bottom', fill='x', pady=(12, 0))
        ttk.Label(network, text=tr('下载代理（可选）')).pack(side='left', padx=(0, 12))
        self.proxy_entry = ttk.Entry(network, textvariable=self.proxy)
        self.proxy_entry.pack(side='left', fill='x', expand=True)

        ttk.Label(drivers, text=tr('只有 Windows 未识别手机或没有 USB 网络时，才需要安装驱动。'),
                  wraplength=740, font=(FONT, 11, 'bold')).pack(anchor='w', pady=(0, 12))
        ttk.Label(drivers, text=tr('应用下载并校验 BlackBerry 驱动，随后通过 Windows 管理员确认完成安装。\n'
                  '请先保存电脑上的工作。安装器不会自动重启；现有程序冲突时会暂停。'),
                  wraplength=740, justify='left').pack(anchor='w')
        self.driver_button = ttk.Button(drivers, text=tr('自动准备并安装驱动'), command=self.drivers)
        self.driver_button.pack(anchor='w', pady=20)
        self.progress = ttk.Progressbar(body, mode='indeterminate')
        self.progress.pack(fill='x', pady=(18, 10))
        ttk.Button(body, text=tr('存储位置与磁盘清理'), command=lambda: show_storage_help(self)).pack(anchor='w')
        ttk.Button(body, text=tr('关闭'), command=self.close).pack(anchor='e')
        self.protocol('WM_DELETE_WINDOW', self.close)
        self._job = self.after(100, self.drain)
        self.grab_set()
        self.variant.trace_add('write', self.model_changed)
        self.root_only.trace_add('write', self.scope_changed)
        self.operator.trace_add('write', self.scope_changed)
        self.refresh()
        if auto_check:
            self.detect()

    def refresh(self):
        for button in (self.detect_button, self.root_detect_button, self.import_button, self.prepare_button, self.driver_button, self.components_button, self.recovery_button, self.resume_button,
                       self.browser_download_button, self.copy_download_button, self.browse_firmware_button, self.import_firmware_button):
            button.configure(state='disabled' if self.busy else 'normal')
        try:
            variant = selected_firmware_variant(self.variant.get(), self.usb)
            item = stock_firmware(variant)
            firmware_text = tr('目标固件（{}）：\n{}').format(variant, item['file'])
        except SetupError as error:
            variant, item = None, None
            firmware_text = MESSAGES[str(error)]
        self.firmware_label.configure(text=firmware_text)
        urls = source_urls(item) if item else []
        if urls != self.firmware_urls:
            self.firmware_urls = urls
            self.firmware_source.configure(values=[source_label(url) for url in urls])
            if urls:
                self.firmware_source.current(0)
            else:
                self.firmware_source.set('')
        blocker = self.support_blocker()
        self.support_notice.configure(text=device_support.describe(device_support.assess(self.support_variant(), self.selected_operator())))
        self.root_scope.configure(text=device_support.root_scope_note(self.support_variant(), sys.platform)
                                  if self.support_variant() else '')
        ready = item is not None and not self.busy and not blocker
        for button in (self.download_firmware_button, self.browser_download_button, self.copy_download_button,
                       self.browse_firmware_button, self.import_firmware_button):
            button.configure(state='normal' if ready else 'disabled')
        domestic_url = item.get('manual_download_url') if item else None
        for button in (self.domestic_download_button, self.copy_domestic_download_button):
            button.configure(state='normal' if ready and domestic_url else 'disabled')
        domestic_code = item.get('manual_download_code') if domestic_url else None
        self.domestic_download_hint.configure(text=tr('极空间提取码：{}').format(domestic_code) if domestic_code else '')
        backup_url = item.get('backup_manual_download_url') if item else None
        for button in (self.backup_download_button, self.copy_backup_download_button):
            button.configure(state='normal' if ready and backup_url else 'disabled')
        backup_code = item.get('backup_manual_download_code') if backup_url else None
        self.backup_download_hint.configure(text=tr('百度网盘提取码：{}').format(backup_code) if backup_code else '')
        self.prepare_button.configure(state='normal' if ready and variant in catalog()['auto_root_variants'] and
                                      sys.platform in ('win32', 'darwin') and not self.choice else 'disabled')
        self.driver_button.configure(state='normal' if not self.busy and sys.platform == 'win32' and not self.usb.get('usb_network') else 'disabled')
        blocker = self.flash_blocker(variant)
        self.flash_button.configure(state='disabled' if blocker else 'normal')
        self.root_hint.configure(text=blocker or tr('{} 的 Root 镜像已准备，可以开始刷写；下一步仍会单独确认清空数据。').format(variant))
        self.continue_button.configure(state='normal' if self.choice and not self.busy else 'disabled')
        detected = self.usb.get('usb_count') == 1 and (self.usb.get('device') or {}).get('ModelName') in firmware_variants()
        self.model_picker.configure(state='disabled' if self.busy or self.kit or detected else 'readonly')
        self.proxy_entry.configure(state='disabled' if self.busy else 'normal')
        self.firmware_entry.configure(state='normal' if ready else 'disabled')
        self.firmware_source.configure(state='readonly' if ready else 'disabled')
        self.history_picker.configure(state='disabled' if self.busy else 'readonly')
        self.ack_check.configure(state='disabled' if self.busy else 'normal')
        self.root_only_check.configure(state='disabled' if self.busy else 'normal')
        self.operator_picker.configure(state='disabled' if self.busy else 'readonly')
        if self.mac_flash_check is not None:
            self.mac_flash_check.configure(state='disabled' if self.busy else 'normal')

    def selected_operator(self):
        return dict(zip(self.operator_options, (None, 'mobile', 'unicom', 'telecom'))).get(self.operator.get())

    def support_variant(self):
        detected = (self.usb.get('device') or {}).get('ModelName')
        return detected if self.usb.get('usb_count') == 1 and detected else self.variant.get()

    def support_blocker(self):
        return device_support.preparation_blocker(self.support_variant(), self.root_only.get(), self.selected_operator())

    def scope_changed(self, *_):
        self.ack.set(False)
        self.mac_flash_ack.set(False)
        self.refresh()

    def model_changed(self, *_):
        variant = self.variant.get()
        if variant != self._last_variant:
            self._last_variant = variant
            self.kit = None
            self.imported_variant = None
            self.firmware_path.set('')
            self.ack.set(False)
            self.mac_flash_ack.set(False)
            self.root_only.set(False)
        self.refresh()

    def flash_blocker(self, variant):
        if self.busy:
            return tr('正在处理，请等待当前步骤完成。')
        prepared_hint = (tr('已保留 {} 的 Root 镜像。请先重新检测连接与机型，核对目标手机后再确认刷写。').format(self.variant.get())
                         if self.kit else None)
        if not variant:
            return prepared_hint or tr('请先确认准确机型，再获取对应固件和准备 Root 镜像。')
        if variant not in catalog()['auto_root_variants']:
            return MESSAGES['root_model_unsupported']
        if self.support_blocker():
            return self.support_blocker()
        if sys.platform not in ('win32', 'darwin'):
            return MESSAGES['windows_root_required']
        if self.choice:
            return MESSAGES['already_rooted']
        if root_lock_path().exists():
            return MESSAGES['flash_state_unknown']
        if self.usb.get('usb_count') == 1:
            version_error = baseline_error(self.usb.get('device'))
            if version_error:
                return MESSAGES[version_error]
        if not self.kit:
            return (tr('{} 的原版固件已导入。下一步：点击“自动准备 Root 镜像”；将复用固件，补齐工具并生成个人镜像。').format(variant)
                    if self.imported_variant == variant else
                    tr('下一步：点击“自动准备 Root 镜像”。可先在上方导入固件，也可由应用自动下载。'))
        if self.usb.get('usb_count') != 1 or (self.usb.get('device') or {}).get('ModelName') != variant:
            return prepared_hint
        if sys.platform == 'darwin' and self.usb.get('usb_address_ready') is not True:
            return MESSAGES['usb_source_address_required']
        if not self.ack.get():
            return tr('{} 的 Root 镜像已准备。请确认已备份并核对机型，再勾选同意清空数据。').format(variant)
        if sys.platform == 'darwin' and not self.mac_flash_ack.get():
            return tr('请再确认手机尚未 Root，并勾选理解实验性刷写的验证范围。')
        return None

    def firmware_target(self):
        try:
            variant = selected_firmware_variant(self.variant.get(), self.usb)
            blocker = self.support_blocker()
            if blocker:
                self.status.configure(text=blocker)
                return None
            return variant
        except SetupError as error:
            self.status.configure(text=MESSAGES[str(error)])
            return None
    def start(self, action, function):
        if self.busy:
            return
        self.events.step = ('connect', 'root', 'drivers')[self.tabs.index(self.tabs.select())]
        self.events.begin(action)
        self.busy = True
        self.refresh()
        self.progress.start()
        self.status.configure(text=tr('正在校验本地固件文件，请稍候…') if action == 'import_firmware' else tr('正在处理，请保持设备连接。'))
        def worker():
            try:
                self.events.put(('result', (action, function(lambda value: self.events.put(('progress', value))))))
            except (DownloadError, MaterialImportError) as error:
                self.events.failure(error)
                self.events.put(('download_error', error.user_message))
            except (SetupError, WorkflowError) as error:
                self.events.failure(error)
                self.events.put(('error', str(error)))
            except Exception as error:
                self.events.failure(error)
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
                elif error in ('authentication_failed', 'host_key_mismatch', 'root_not_ready', 'root_probe_failed'):
                    usb['ssh_port'] = True
            return {'usb': usb, 'choice': choice, 'error': error}
        self.start('detect', work)

    def import_connection(self):
        path = filedialog.askopenfilename(parent=self, title=tr('选择这台手机原来的 SSH 配置'))
        if path:
            self.host, self.config = matching_alias(path, 'bb10-root'), path
            self.detect()

    def recover_connection(self):
        from recovery_gui import RecoveryDialog
        def ready(host, config):
            self.host, self.config = host, config
            self.grab_set()
            self.detect()
        RecoveryDialog(self, ready)

    def prepare_root(self):
        variant, proxy = self.firmware_target(), self.proxy.get().strip() or None
        if not variant:
            return
        if variant not in catalog()['auto_root_variants']:
            self.status.configure(text=MESSAGES['root_model_unsupported'])
            return
        self.kit = None
        self.ack.set(False)
        self.mac_flash_ack.set(False)
        def work(progress):
            selected_firmware_variant(variant, local_usb_state())
            return prepare_root_kit(variant, progress, proxy)
        self.start('prepare', work)

    def download_firmware(self):
        if self.busy:
            return
        variant = self.firmware_target()
        if variant:
            proxy = self.proxy.get().strip() or None
            def work(progress):
                selected_firmware_variant(variant, local_usb_state())
                return download_stock_firmware(variant, progress, proxy)
            self.start('download_firmware', work)

    def open_firmware_download(self, url=None):
        if self.busy or not self.firmware_target():
            return
        try:
            opened = webbrowser.open(url or self.firmware_urls[max(0, self.firmware_source.current())], new=2)
        except (OSError, webbrowser.Error):
            opened = False
        self.status.configure(text=tr('已请求浏览器打开固件下载。下载完成后，选择文件并点击“校验并导入固件”。') if opened else
                              tr('未能自动打开浏览器。请点击“复制下载链接”，粘贴到浏览器或下载工具中。'))
        return opened

    def open_domestic_download(self):
        if self.busy:
            return
        variant = self.firmware_target()
        if not variant:
            return
        item = stock_firmware(variant)
        url = item.get('manual_download_url')
        if not url:
            return
        if self.open_firmware_download(url):
            self.status.configure(text=tr('已打开极空间。进入分享文件夹，点击 {} 右侧“下载”；保存原文件后返回此处校验导入。').format(item['file']))
        else:
            self.status.configure(text=tr('未能自动打开极空间。请点击“复制极空间链接”，在浏览器中手动打开。'))

    def copy_domestic_link(self):
        if self.busy:
            return
        variant = self.firmware_target()
        if not variant:
            return
        item = stock_firmware(variant)
        url = item.get('manual_download_url')
        if not url:
            return
        code = item.get('manual_download_code')
        text = url + ('\n' + tr('极空间提取码：{}').format(code) if code else '')
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status.configure(text=tr('已复制极空间链接。进入分享文件夹下载 {}，保存后返回应用校验导入。').format(item['file']))

    def open_backup_download(self):
        if self.busy:
            return
        variant = self.firmware_target()
        if not variant:
            return
        item = stock_firmware(variant)
        url = item.get('backup_manual_download_url')
        if not url:
            return
        if self.open_firmware_download(url):
            self.status.configure(text=tr('已打开百度网盘。请下载 {}，下载完成后选择文件并校验导入。').format(item['file']))
        else:
            self.status.configure(text=tr('未能自动打开百度网盘。请点击“复制备用链接”，在浏览器中手动打开。'))

    def copy_backup_link(self):
        if self.busy:
            return
        variant = self.firmware_target()
        if not variant:
            return
        item = stock_firmware(variant)
        url = item.get('backup_manual_download_url')
        if not url:
            return
        code = item.get('backup_manual_download_code')
        text = url + ('\n' + tr('百度网盘提取码：{}').format(code) if code else '')
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status.configure(text=tr('已复制百度网盘备用链接。请下载 {}，然后校验并导入。').format(item['file']))

    def copy_firmware_link(self):
        if not self.busy and self.firmware_target():
            self.clipboard_clear()
            self.clipboard_append(self.firmware_urls[max(0, self.firmware_source.current())])
            self.status.configure(text=tr('已复制固件下载链接。可粘贴到浏览器或支持续传的下载工具中。'))

    def browse_firmware(self):
        if self.busy or not self.firmware_target():
            return
        path = filedialog.askopenfilename(parent=self, title=tr('选择对应机型的完整固件文件'),
                                          filetypes=[(tr('固件文件'), '*.7z *.exe'), (tr('所有文件'), '*')])
        if path:
            self.firmware_path.set(path)

    def import_firmware(self):
        if self.busy:
            return
        variant = self.firmware_target()
        if not variant:
            return
        path = self.firmware_path.get().strip()
        if len(path) >= 2 and path[0] == path[-1] == '"':
            path = path[1:-1]  # Windows Explorer's "Copy as path".
        if not path:
            self.status.configure(text=tr('请先选择已下载的完整固件文件，或粘贴本地文件路径。'))
            self.firmware_entry.focus_set()
            return
        self.start('import_firmware', lambda progress: import_stock_firmware(path, progress, variant=variant))

    def resume_preparation(self):
        if self.busy:
            return
        index = self.history_picker.current()
        if index < 0:
            self.status.configure(text=tr('请选择与当前手机对应的准备记录。'))
            return
        item = self.history[index]
        try:
            selected_firmware_variant(item['variant'], self.usb)
        except SetupError as error:
            self.status.configure(text=MESSAGES[str(error)])
            return
        self.kit = None
        self.ack.set(False)
        self.mac_flash_ack.set(False)
        self.refresh()
        if root_lock_path().exists() or item['stage'] not in ('prepared', 'flashed_waiting_for_root'):
            self.status.configure(text=tr('上次刷写状态尚未确认。请保留现场和日志，不要重复刷写。'))
            return
        if item['stage'] == 'flashed_waiting_for_root':
            self.host, self.config = 'bb10-root', str(Path(item['folder']) / 'ssh_config')
            self.tabs.select(0)
            self.detect()
            return
        if item['platform'] != sys.platform:
            self.status.configure(text=MESSAGES['root_platform_mismatch'])
            return
        def work(progress):
            progress(tr('重新校验已准备的镜像，尚不刷写手机…'))
            prepared_images(item['folder'])
            return item['folder']
        self.variant.set(item['variant'])
        self.start('prepare', work)

    def flash(self):
        variant = self.firmware_target()
        if self.flash_blocker(variant):
            return
        if messagebox.askyesno(tr('确认清空并刷写'), tr('此操作会清空 {} 的手机数据，并写入该机型的 Root 系统与无线固件。\n\n'
                              '请只连接这一台手机，确保已备份、电量充足，并保持 USB 稳定。确认开始？').format(variant), parent=self):
            self.start('flash', lambda progress: flash_root(self.kit, True, progress))

    def open_firmware(self):
        if not self.busy:
            from firmware_gui import FirmwareDialog
            FirmwareDialog(self, self.on_ready, self.usb, root_only=self.root_only.get())

    def drivers(self):
        if not messagebox.askokcancel(tr('安装 BlackBerry 驱动'), tr('将下载并校验驱动，然后请求 Windows 管理员确认。请先保存电脑上的工作。'), parent=self):
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
                if kind == 'download_error':
                    self.status.configure(text=value)
                elif kind == 'error':
                    self.status.configure(text=MESSAGES.get(value, tr('准备未完成。请检查网络或材料，保留现场后重试；下载代理可在“首次 Root”页设置。')))
                else:
                    action, result = value
                    if action == 'detect':
                        self.usb, self.choice = result['usb'], result['choice']
                        device = self.usb['device']
                        model = device.get('ModelName') or tr('型号待确认')
                        self.device.configure(text=model + ' · ' + (device.get('PlatformVersion') or tr('系统待确认')))
                        if self.usb.get('usb_count') == 1 and model in firmware_variants():
                            self.variant.set(model)
                        elif self.kit and (self.usb.get('usb_count') != 1 or not device.get('ModelName')):
                            # Missing or ambiguous metadata is not evidence of a
                            # different model. Keep the prepared selection, but
                            # require a new verified connection and confirmation.
                            self.ack.set(False)
                            self.mac_flash_ack.set(False)
                        elif self.usb.get('usb_count') or self.usb.get('usb_present') or device:
                            self.variant.set('')
                        yesno = lambda value: tr('已就绪') if value is True else tr('未就绪') if value is False else tr('待确认')
                        development = device.get('DeveloperModeEnabled')
                        ssh_state = (tr('需核对密钥') if result['error'] in ('authentication_failed', 'host_key_mismatch') else yesno(self.usb['ssh_port']))
                        self.facts.configure(text=tr('USB 设备：{}    USB 网络：{}\n开发模式：{}    SSH 连接：{}\nRoot：{}').format(
                            yesno(self.usb['usb_present']), yesno(self.usb['usb_network']),
                            tr('已开启') if development == '1' else tr('未开启') if development == '0' else tr('待确认'),
                            ssh_state, tr('已验证') if self.choice else tr('未能验证（不等于未 Root）')))
                        if sys.platform == 'darwin' and self.usb.get('network_interfaces'):
                            interfaces = self.usb['network_interfaces']
                            rows = ['{} {}'.format(item['name'], ', '.join(item.get('ipv4', [])) or tr('无 IPv4'))
                                    for item in interfaces if item.get('active')]
                            network = tr('；').join(rows) if rows else tr('关联接口尚未启用')
                            self.facts.configure(text=self.facts.cget('text') + tr('\n电脑 USB 网络：') + network)
                        self.status.configure(text=tr('Root 连接已验证，可以继续。开发模式无需为此保持开启。') if self.choice else
                                              MESSAGES.get(result['error'], tr('请按手机上的准备步骤操作，再重新检测。')))
                        if self.choice:
                            self.host, self.config = self.choice['host'], self.choice['config']
                    elif action == 'prepare':
                        self.kit = result
                        self.status.configure(text=tr('{} 的 Root 镜像与个人连接配置已准备。确认备份并勾选同意清空数据后，可开始刷写。').format(self.variant.get()))
                    elif action == 'flash':
                        self.host, self.config = result['host'], result['config']
                        self.kit = None
                        self.ack.set(False)
                        self.tabs.select(0)
                        self.status.configure(text=tr('刷写已结束。请完成手机首次设置，打开一次 BlackBerry World，再重新检测 Root。'))
                    elif action == 'drivers':
                        self.status.configure(text=tr('驱动安装完成，请按 Windows 提示重启后重新检测。') if result['reboot_required'] else
                                              tr('驱动安装完成，请重新连接手机并检测。'))
                    elif action == 'components':
                        self.status.configure(text=tr('连接组件已就绪，请重新检测。'))
                    elif action == 'import_firmware':
                        self.imported_variant = self.variant.get()
                        self.status.configure(text=tr('固件已导入并通过校验。下一步：点击下方“自动准备 Root 镜像”，为 {} 生成个人镜像；准备完成后才能刷写。').format(self.variant.get()))
                    elif action == 'download_firmware':
                        self.firmware_path.set(result)
                        self.imported_variant = self.variant.get()
                        self.status.configure(text=tr('对应机型固件已下载并通过校验。下一步：点击“自动准备 Root 镜像”。\n{}').format(result))
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
            messagebox.showinfo(tr('准备进行中'), tr('请等待当前步骤结束。刷写期间不要断开 USB 或关闭刷写窗口。'), parent=self)
            return
        self.after_cancel(self._job)
        self.destroy()
        if isinstance(self.master, tk.Toplevel) and self.master.winfo_exists():
            self.master.grab_set()
