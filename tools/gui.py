"""bb10-volte: standard-library desktop UI over the fixed workflow."""
import argparse
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from workflow import Client, ROOT, WorkflowError, public_status, registered
from desktop_paths import private_root, prepare_external_programs
from profile_editor import ProfileEditor, presets, profiles, picker_label, FONT
from ui_theme import apply_theme, AutoScrollbar
from connection import matching_alias, saved_connection, resolve_connection, save_connection
from connection_flow import guidance
from mac_help import CONNECTION_HINT, show_guide as show_mac_guide

BG, INK, MUTED = '#F2F5F9', '#18273F', '#62738B'
BLUE, GREEN, AMBER, RED = '#235BD7', '#137860', '#9A610B', '#BA3C42'
NAMES = {'model': '手机型号', 'os': '系统版本', 'root': 'Root 环境', 'native': '原生文件',
         'sim': 'SIM 就绪', 'carrier': '运营商', 'sim_route': 'SIM 路线', 'identity': '身份格式',
         'lte': '4G 网络', 'apn': '数据 APN', 'carrier_config': '原厂数据配置', 'experiment': '实测与试用',
         'installation': '已装服务', 'baseline': '安装前状态', 'saved_profile': '已装配置',
         'provider_lifecycle': '机型恢复验证', 'autostart_policy': '开机启动验证'}
NOTES = {
    'device_identified': '已自动识别型号和硬件变体；实测状态见顶部',
    'passport_provider_lifecycle_unvalidated': 'Passport 有停用后网络栈重启的社区报告；恢复策略验证前暂停安装、启动及自动恢复，实验试用不能绕过。见社区研究说明。',
    'device_identity_unknown': '型号未知或与硬件变体冲突，请导出报告协助适配',
    'os_3216_required': '要求 BB10 OS 10.3.3.3216',
    'root_qnx_arm32_required': '要求 AutoRoot 已就绪、有效 root 和 QNX ARM32',
    'native_hashes_required': '4 个原生文件 SHA-256 必须与验证基线一致',
    'sim_ready': 'SIM 已就绪', 'sim_unavailable': '解锁 SIM 并等待就绪后重试',
    'carrier_matches_profile': '实际 SIM 的 MCC/MNC 与所选配置一致',
    'carrier_not_profiled': 'SIM 与当前配置不一致；请选择或编辑运营商配置',
    'carrier_template_required': '按实际 SIM 匹配原厂配置、数据 APN 和 IMS 结构；失败时需适配',
    'experimental_opt_in': '未实测适配；勾选实验试用后，仍须通过全部技术检查',
    'experimental_manual_start_required': '社区报告自启动可能卡在开机动画；请在“自定义 → 运行选项”关闭自动启动后重新检查。实验组合仅允许手动启动。',
    'recorded_baseline': '有 Q10 SQN100-3 北京联通单机记录；本机仍须验收',
    'saved_profile_matches': '所选配置与手机已装配置一致',
    'profile_update_required': '新安装将保存所选配置；已装配置有变更时先停用恢复，再更新',
    'usim_without_isim': 'USIM，无 ISIM；符合当前实现',
    'sim_route_not_profiled': '此 SIM 类型需要另行适配，不能套用当前配置',
    'identity_layout_matches': '在手机本地核验通过；报告不包含完整标识',
    'identity_layout_unknown': 'SIM 身份格式不符，需提供脱敏预检报告排查',
    'lte_ready': '无线已开启，当前处于 LTE', 'lte_not_ready': '开启移动网络并等待 LTE',
    'data_apn_ready': '所选配置的数据 APN 已连接', 'data_apn_not_ready': '所选数据 APN 未连接；检查数据服务与配置',
    'installation_absent': '未安装，可在全部检查通过后安装',
    'installation_stopped': '文件完整且已停止，可以更新',
    'installation_busy': '已有管理器或锁；更新前先停用并恢复',
    'installation_recovery_required': '恢复记录尚未完成；先停用并恢复',
    'installation_interrupted': '上次安装中断；保留现场，不要重复覆盖',
    'installation_conflict': '目录、文件或所有权不符；需要人工检查',
    'baseline_clean': '原策略、IMS、VPN 与覆盖配置符合安装前条件',
    'baseline_not_clean': '服务运行时属正常现象；更新前需恢复原状态',
}
ERRORS = {
    'provider_lifecycle_needs_adaptation': '此机型的提供器停用策略尚未验证。请保留当前状态并导出报告，参阅“社区研究与适配进展”。',
    'connection_setup_required': '这台电脑还没有可用的连接。打开“连接帮助”，选择原刷机文件夹，或从手机重新授权。',
    'hostname_unresolved': '原连接不可用。打开“连接帮助”恢复材料，或在高级设置核对连接。',
    'ssh_algorithm_mismatch': '手机 SSH 与客户端算法不匹配。请使用更新后的完整应用重新检查。',
    'connection_refused': '手机连接服务尚未启动。请解锁手机，打开“连接帮助”按当前状态处理。',
    'bundled_ssh_mismatch': '内置 SSH 文件校验失败，请重新获取完整 EXE。',
    'invalid_profile': '配置格式或参数不符合要求，请在配置编辑器中检查。',
    'profile_update_required': '所选配置与已装配置不同。先停用恢复，再预检和更新安装。',
    'invalid_host': 'SSH 别名只能使用字母、数字、点、下划线和短横线。',
    'config_missing': '原连接文件可能移动了。打开“连接帮助”，选择原刷机文件夹或恢复授权。',
    'openssh_missing': '找不到 SSH 客户端，请按安装文档准备 ssh 和 scp。',
    'package_mismatch': '安装包与固定清单不一致。请使用完整发布包，不要在客户电脑重新生成清单。',
    'host_key_mismatch': '主机密钥校验失败。核对所选设备和个人 SSH 配置，保留原信任记录。',
    'authentication_failed': '手机未接受这台电脑的授权。打开“连接帮助”，选择原材料或在手机端重新授权。',
    'connection_failed': '无法连接。检查 USB、手机 Root 状态、驱动和 SSH 配置。',
    'connection_timeout_state_unknown': '连接超时，设备状态尚未确认。重新预检并查看状态，不要盲目重复安装。',
    'remote_operation_failed': '设备拒绝了操作。请重新预检并保留现场，必要时采集私有日志。',
    'invalid_device_response': '设备返回不完整。重新连接后预检，确认实际状态。',
    'preflight_blocked': '预检未允许这项操作。请先处理检查表中的待处理项目。',
    'installation_not_verified': '安装回读未通过。保留现场，暂时不要启动或覆盖安装。',
    'installation_needs_inspection': '未发现完整、可管理的安装。请先核对预检结果。',
    'service_needs_attention': '服务未正常运行。先查看状态，再按需要停用并恢复。',
    'restore_pending': '恢复仍未结束。保持连接，稍后查看状态。',
    'restore_needs_inspection': '尚未确认恢复完成。请保留记录并检查，暂时不能更新。',
}
PHASES = {'package': '校验安装包', 'connection': '连接设备', 'transfer': '传输校验文件',
          'preflight': '兼容性预检', 'install': '安装固定版本', 'verify': '回读已装文件',
          'start': '启动服务', 'registration': '验证 IMS 注册', 'restore': '停用并恢复',
          'stage_cleanup': '临时检查文件清理'}
SERVICE_PHASES = {'waiting_for_native_ims': '等待系统 IMS 初始化结束',
                  'configuring': '准备运营商配置', 'waiting_for_ims_apn': '等待 IMS 专用网络',
                  'not_started_this_boot': '本次开机尚未启动', 'not_started': '尚未启动',
                  'running': '运行中', 'registering': '等待 IMS 注册', 'stopped': '已停止'}


class App:
    def __init__(self, root, host='bb10-root', config='', auto_connect=False):
        self.root, self.events = root, queue.Queue()
        self.busy, self.report, self.last_result = False, None, None
        self.report_connection = None
        self.display_report, self.device_info = None, {}
        self.running_baseline_expected = False
        self.connection_options_visible = False
        self.connection_dialog = None
        self._startup_job = None
        self.presets = presets()
        self.profile = profiles.default()
        self.profile_name = tk.StringVar(value=picker_label(self.profile['label']))
        self.experimental = tk.BooleanVar(value=False)
        saved = saved_connection(require_files=False) if not config and host == 'bb10-root' else None
        # An unverified default kit must not bypass discovery of the kit that
        # actually matches the connected phone. Check device fills it on success.
        selected_config = config or (saved['config'] if saved else '')
        selected_host = saved['host'] if saved else matching_alias(selected_config, host) if selected_config else host
        self.host = tk.StringVar(value=selected_host)
        self.config = tk.StringVar(value=selected_config)
        self.ack = tk.BooleanVar()
        root.title('bb10-volte')
        if os.name == 'nt' and (ROOT / 'assets/app.ico').is_file():
            root.iconbitmap(str(ROOT / 'assets/app.ico'))
        self.icon = None
        if (ROOT / 'assets/icon.png').is_file():
            self.icon = tk.PhotoImage(file=str(ROOT / 'assets/icon.png'))
            root.iconphoto(True, self.icon)
        width = min(1080, max(960, root.winfo_screenwidth() - 48))
        height = min(780, max(700, root.winfo_screenheight() - 80))
        root.geometry('{}x{}'.format(width, height))
        root.minsize(960, 700)
        root.configure(bg=BG)
        root.option_add('*Font', (FONT, 11))
        root.protocol('WM_DELETE_WINDOW', self.close)
        apply_theme(root, FONT)
        self.build()
        self.host.trace_add('write', self.connection_changed)
        self.config.trace_add('write', self.connection_changed)
        self.experimental.trace_add('write', lambda *_: self.connection_changed(preserve_device=True))
        self.ack.trace_add('write', lambda *_: self.refresh_buttons())
        self._drain_job = self.root.after(100, self.drain)
        self.connection_status.configure(text='已记住上次连接 · 待重新验证' if saved else '尚未连接')
        if saved:
            self.detail.configure(text='已记住上次成功的连接。重新检查后显示手机当前状态，不会自动安装或刷写。')
        if auto_connect and saved:
            self._startup_job = self.root.after(350, self.resume_last_connection)

    def resume_last_connection(self):
        self._startup_job = None
        if not self.busy and not (self.connection_dialog and self.connection_dialog.winfo_exists()):
            self.run('preflight')

    def label(self, parent, text, size=10, fg=INK, bg=None, bold=False, **kwargs):
        return tk.Label(parent, text=text, font=(FONT, max(size, 11), 'bold' if bold else 'normal'),
                        fg=fg, bg=bg or parent.cget('bg'), **kwargs)

    def build(self):
        main = tk.Frame(self.root, bg=BG)
        main.pack(fill='both', expand=True, padx=30, pady=24)
        header = tk.Frame(main, bg=BG)
        header.pack(fill='x')
        self.label(header, 'BB10 VoLTE', 22, bold=True).pack(side='left')
        self.more_button = ttk.Menubutton(header, text='更多')
        self.more_button.pack(side='right')
        self.menu = tk.Menu(self.more_button, tearoff=False, font=(FONT, 11))
        self.more_button.configure(menu=self.menu)
        self.menu_actions = {}
        for action, title in [('install', '安装 / 更新并验证'), ('status', '查看服务状态'), ('disable', '停用并恢复')]:
            self.menu_actions[action] = self.menu.index('end') + 1 if self.menu.index('end') is not None else 0
            self.menu.add_command(label=title, command=lambda k=action: self.run(k))
        self.menu.add_separator()
        self.export_index = self.menu.index('end') + 1
        self.menu.add_command(label='导出检查报告', command=self.export)
        self.menu.add_command(label='高级连接设置', command=self.toggle_connection_options)
        self.menu.add_separator()
        self.menu.add_command(label='使用与恢复指南', command=self.guide)
        self.menu.add_command(label='社区研究与适配进展', command=lambda: self.show_document(
            '社区研究与适配进展', ROOT / 'docs/COMMUNITY-RESEARCH.md'))
        self.menu.add_command(label='关于与开源许可', command=self.licenses)
        self.device_label = self.label(main, 'BlackBerry 10 设备 · 等待连接', 11, MUTED, anchor='w')
        self.device_label.pack(fill='x', pady=(5, 22))

        self.connection_card = tk.Frame(main, bg='white', padx=20, pady=16)
        self.connection_card.pack(fill='x', pady=(0, 18))
        self.connection_status = self.label(self.connection_card, '尚未连接', 12, MUTED)
        self.connection_status.pack(anchor='w')

        settings = tk.Frame(self.connection_card, bg='white')
        settings.pack(fill='x', pady=(12, 0))
        settings.columnconfigure(1, weight=1)
        self.label(settings, '运营商', 11, MUTED).grid(row=0, column=0, sticky='w', padx=(0, 30))
        self.profile_picker = ttk.Combobox(settings, textvariable=self.profile_name,
                                          values=[picker_label(p['label']) for p in self.presets], state='readonly', width=47)
        self.profile_picker.grid(row=0, column=1, sticky='ew')
        self.profile_picker.bind('<<ComboboxSelected>>', self.select_profile)
        self.edit_button = ttk.Button(settings, text='自定义', command=self.edit_profile)
        self.edit_button.grid(row=0, column=2, padx=(10, 0))
        self.mac_connection_help = None
        self.mac_guide_button = None
        if sys.platform == 'darwin':
            self.mac_connection_help = tk.Frame(self.connection_card, bg='white')
            self.mac_connection_help.pack(fill='x', pady=(12, 0))
            self.mac_guide_button = ttk.Button(self.mac_connection_help, text='Mac 连接说明',
                                               command=lambda: show_mac_guide(self.root))
            self.mac_guide_button.pack(side='right', padx=(12, 0))
            hint = self.label(self.mac_connection_help, CONNECTION_HINT, 11, MUTED,
                              wraplength=650, justify='left', anchor='w')
            hint.pack(side='left', fill='x', expand=True)
            hint.bind('<Configure>', lambda event: hint.configure(wraplength=max(1, event.width - 4)))
        self.connection_options = tk.Frame(self.connection_card, bg='white')
        self.connection_options.columnconfigure(1, weight=1)
        self.label(self.connection_options, 'SSH 配置', 11, MUTED).grid(row=0, column=0, sticky='w', padx=(0, 14))
        self.config_entry = ttk.Entry(self.connection_options, textvariable=self.config)
        self.config_entry.grid(row=0, column=1, sticky='ew')
        self.browse_button = ttk.Button(self.connection_options, text='手动选择', command=self.browse)
        self.browse_button.grid(row=0, column=2, padx=(10, 0))
        self.label(self.connection_options, 'SSH 别名', 11, MUTED).grid(row=1, column=0, sticky='w', pady=(8, 0))
        self.host_entry = ttk.Entry(self.connection_options, textvariable=self.host, width=20)
        self.host_entry.grid(row=1, column=1, sticky='w', pady=(8, 0))
        self.experiment_check = ttk.Checkbutton(self.connection_card, text='允许未实测设备或运营商实验试用',
                                                variable=self.experimental)

        # Reserve the action area before giving the results card spare height.
        footer = tk.Frame(main, bg=BG)
        footer.pack(side='bottom', fill='x', pady=(16, 0))
        self.ack_check = ttk.Checkbutton(footer, text='已备份、SIM 已开通 VoLTE，当前没有通话', variable=self.ack)
        toolbar = tk.Frame(footer, bg=BG)
        toolbar.pack(side='bottom', fill='x')
        self.primary_action = 'install'
        self.primary_button = ttk.Button(toolbar, text='安装并验证', style='Accent.TButton',
                                          command=lambda: self.run(self.primary_action))
        self.primary_button.pack(side='right')
        self.check_button = ttk.Button(toolbar, text='连接手机', command=self.connect_phone)
        self.check_button.pack(side='right', padx=(0, 10))
        self.setup_button = ttk.Button(toolbar, text='连接帮助', command=self.setup)
        self.setup_button.pack(side='left', padx=(0, 16))
        self.activity = self.label(toolbar, '准备就绪', 11, MUTED, anchor='w')
        self.activity.pack(side='left', fill='x', expand=True, padx=(0, 16))
        self.buttons = {'preflight': self.check_button, 'primary': self.primary_button}
        self.progress = ttk.Progressbar(footer, mode='indeterminate')

        summary = tk.Frame(main, bg='white', padx=20, pady=18)
        summary.pack(fill='both', expand=True)
        heading = tk.Frame(summary, bg='white')
        heading.pack(fill='x')
        self.summary = self.label(heading, '连接你的黑莓手机', 18, bold=True)
        self.summary.pack(side='left')
        self.details_button = ttk.Button(heading, text='检查详情', command=self.show_checks, state='disabled')
        self.details_button.pack(side='right')
        self.detail = self.label(summary, '用数据线连接并解锁手机，再点击“连接手机”。程序会查找已有连接；需要授权或首次 Root 时，打开“连接帮助”。', 11, MUTED,
                                 wraplength=850, justify='left', anchor='w')
        self.detail.pack(fill='x', pady=(10, 12))
        self.detail.bind('<Configure>', lambda event: self.detail.configure(wraplength=max(1, event.width - 4)))
        self.check_count = self.label(summary, '系统、SIM 和安装条件将在连接后自动检查', 11, MUTED, anchor='w')
        self.check_count.pack(fill='x', pady=(0, 10))
        self.table_frame = tk.Frame(summary, bg='white')
        self.table = ttk.Treeview(self.table_frame, columns=('item', 'state', 'detail'), show='headings', selectmode='browse', height=1)
        for col, label, width in [('item', '待处理项目', 135), ('state', '结果', 95), ('detail', '处理方法', 480)]:
            self.table.heading(col, text=label, anchor='w')
            self.table.column(col, width=width, minwidth=width if col != 'detail' else 300, stretch=col == 'detail')
        scroll = AutoScrollbar(self.table_frame, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.table.pack(fill='both', expand=True)
        for tag, color in [('pass', GREEN), ('wait', AMBER), ('adapt', AMBER), ('block', RED), ('idle', MUTED)]:
            self.table.tag_configure(tag, foreground=color)
        self.table.bind('<Double-1>', self.explain_row)
        self.refresh_buttons()

    def connection_changed(self, *_, preserve_device=False):
        self.report, self.report_connection, self.last_result = None, None, None
        self.display_report = None
        self.running_baseline_expected = False
        if not preserve_device:
            self.device_info = {}
            self.device_label.configure(text='BlackBerry 10 设备 · 等待连接')
        self.ack.set(False)
        self.connection_status.configure(text='连接或选项已改变 · 请重新检查')
        self.summary.configure(text='配置已更新，请检查设备', fg=INK)
        self.detail.configure(text='检查通过后即可继续安装或管理服务。')
        self.check_count.configure(text='等待重新检查')
        self.table_frame.pack_forget()
        self.table.delete(*self.table.get_children())
        self.refresh_buttons()

    def selection(self):
        return (self.host.get(), self.config.get(), profiles.fingerprint(profiles.request(self.profile, self.experimental.get())))

    def set_profile(self, profile):
        self.profile = profiles.validate(profile)
        self.profile_name.set(picker_label(self.profile['label']))
        self.connection_changed(preserve_device=True)

    def select_profile(self, _=None):
        index = self.profile_picker.current()
        if index >= 0:
            self.set_profile(self.presets[index])

    def edit_profile(self):
        if not self.busy:
            ProfileEditor(self.root, self.profile, self.set_profile)

    def allowed_actions(self):
        r = self.report or {}
        owned = r.get('installation', {}).get('state') in ('busy', 'stopped', 'recovery_required')
        current = self.report_connection == self.selection()
        allowed = {'preflight': True,
                   'install': current and (r.get('can_install') or r.get('can_update')) and self.ack.get(),
                   'start': current and r.get('can_start') and self.ack.get(),
                   'status': current and owned,
                   'disable': current and owned and r.get('can_restore', True) and self.ack.get()}
        return {key: bool(value) and not self.busy for key, value in allowed.items()}

    def refresh_buttons(self):
        if not hasattr(self, 'buttons'):
            return
        r = self.report or {}
        allowed = self.allowed_actions()
        owned = r.get('installation', {}).get('state') in ('busy', 'stopped', 'recovery_required')
        self.primary_action = ('start' if r.get('can_start') else 'install' if r.get('can_install') or r.get('can_update')
                               else 'status' if owned else None)
        self.primary_button.configure(text='启动并验证' if self.primary_action == 'start' else
                                      '查看状态' if self.primary_action == 'status' else
                                      '更新并验证' if r.get('can_update') else '安装并验证',
                                      state='normal' if allowed.get(self.primary_action) else 'disabled')
        if self.primary_action:
            self.primary_button.pack(side='right', before=self.check_button)
        else:
            self.primary_button.pack_forget()
        self.check_button.configure(text='重新检查' if self.display_report or self.last_result else '连接手机',
                                    style='TButton' if self.primary_action else 'Accent.TButton',
                                    state='normal' if allowed['preflight'] else 'disabled')
        for action, index in self.menu_actions.items():
            self.menu.entryconfigure(index, state='normal' if allowed[action] else 'disabled')
        for widget in (self.config_entry, self.host_entry, self.browse_button, self.edit_button,
                       self.experiment_check, self.ack_check, self.setup_button):
            widget.configure(state='disabled' if self.busy else 'normal')
        self.profile_picker.configure(state='disabled' if self.busy else 'readonly')
        self.menu.entryconfigure(self.export_index, state='normal' if self.last_result and not self.busy else 'disabled')
        self.details_button.configure(state='normal' if self.display_report and not self.busy else 'disabled')
        needs_ack = any(r.get(key) for key in ('can_install', 'can_update', 'can_start')) or r.get('installation', {}).get('state') in ('busy', 'stopped', 'recovery_required')
        if needs_ack:
            self.ack_check.pack(anchor='w', pady=(0, 12))
        else:
            self.ack_check.pack_forget()
        experimental = (self.experimental.get() or not profiles.baseline_parameters(self.profile) or
                        bool(self.device_info) and not self.device_info.get('hardware_tested'))
        if experimental:
            self.experiment_check.pack(anchor='w', pady=(12, 0))
        else:
            self.experiment_check.pack_forget()

    def toggle_connection_options(self):
        self.connection_options_visible = not self.connection_options_visible
        if self.connection_options_visible:
            self.connection_options.pack(fill='x', pady=(12, 0))
        else:
            self.connection_options.pack_forget()

    def browse(self):
        initial = private_root() if private_root().is_dir() else Path.home()
        path = filedialog.askopenfilename(title='选择这台手机的 SSH 配置', initialdir=str(initial), filetypes=[('SSH config', '*')])
        if path:
            self.config.set(path)
            self.host.set(matching_alias(path, self.host.get()))

    def render_report(self, report, service_status=None):
        self.report = report
        self.report_connection = self.selection()
        device = report.get('device', {})
        self.display_report, self.device_info = report, device
        root_verified = any(item['id'] == 'root' and item['status'] == 'pass' for item in report['checks'])
        self.connection_status.configure(text='最近检查：已连接 · Root 已验证' if root_verified else '最近检查：手机已响应 · Root 权限待核验')
        self.running_baseline_expected = (report.get('installation', {}).get('state') == 'busy' and
                                          bool((service_status or {}).get('manager_alive')))
        badge = 'Q10 已有实测记录' if device.get('hardware_tested') else '未实测 · 可实验试用'
        if not device.get('recognized'):
            badge = '机型待识别'
        elif any(c['code'] == 'passport_provider_lifecycle_unvalidated' for c in report['checks']):
            badge = 'Passport 恢复策略待验证'
        self.device_label.configure(text='{}  /  {}  /  OS {}  ·  {}'.format(
            device.get('display_name', '未知设备'), device.get('variant', '?'), device.get('os_version', '?'), badge))
        self.table.delete(*self.table.get_children())
        labels = {'pass': '通过', 'wait': '待处理', 'adapt': '需适配', 'block': '不支持'}
        problems = []
        for check in report['checks']:
            key, state = check['id'], check['status']
            expected = self.running_baseline_expected and key == 'baseline' and check['code'] == 'baseline_not_clean'
            if key in NAMES and state != 'pass' and not expected:
                problems.append(check)
                self.table.insert('', 'end', iid=key,
                                  values=(NAMES[key], labels[state], NOTES.get(check['code'], '请导出报告协助检查')),
                                  tags=(state,))
        expected_count = sum(self.running_baseline_expected and check['id'] == 'baseline' and
                             check['code'] == 'baseline_not_clean' for check in report['checks'])
        self.check_count.configure(text='已检查 {} 项 · {} 项通过{}{}'.format(
            len(report['checks']), sum(check['status'] == 'pass' for check in report['checks']),
            ' · {} 项为服务运行状态'.format(expected_count) if expected_count else '',
            ' · {} 项待处理'.format(len(problems)) if problems else ''))
        if problems:
            self.table_frame.pack(fill='both', expand=True)
        else:
            self.table_frame.pack_forget()
        outcome = report['outcome']
        title, color = {'compatible': ('符合当前适配条件', GREEN), 'not_ready': ('有条件尚未就绪', AMBER),
                        'experimental': ('未实测适配 · 可实验试用', AMBER),
                        'needs_adaptation': ('设备或运营商配置需要适配', AMBER), 'unsupported': ('关键技术条件未通过', RED)}[outcome]
        state = report['installation']['state']
        if report.get('can_restore') is False:
            detail = '此机型的自动操作暂缓。请保留当前状态、导出报告，并查看“社区研究与适配进展”。'
        elif state == 'busy':
            detail = '已有服务正在运行或持有锁。更新前请先停用并恢复；本次不会覆盖安装。'
        elif report.get('can_install') or report.get('can_update'):
            detail = '可进入安装流程。运营商开通情况和双向通话效果仍需真实通话确认。'
        elif state in ('conflict', 'interrupted', 'recovery_required'):
            detail = '安装或恢复状态需要处理。请保留现场，按检查表处理后重新预检。'
        else:
            detail = '请按下方提示处理后重新检查。'
        research = report.get('community_research', {})
        if research.get('records'):
            detail += ' 有相同硬件与运营商的社区研究记录，尚不代表本工具已验收；可在“更多”查看。'
        self.summary.configure(text=title, fg=color)
        self.detail.configure(text=detail)
        self.refresh_buttons()

    def run(self, action):
        if not self.allowed_actions().get(action):
            return
        if self._startup_job is not None:
            self.root.after_cancel(self._startup_job)
            self._startup_job = None
        if action in ('install', 'start', 'disable'):
            if not self.ack.get() or self.report_connection != self.selection():
                return
            message = ('将停止本项目服务、恢复其修改并关闭自动启动。' if action == 'disable' else
                       '将按所选配置安装或启动并进行 IMS 验证。自动启动：' +
                       ('开启' if self.profile['runtime']['autostart'] else '关闭') + '。首次启动可能短暂重载无线网络。')
            if not messagebox.askokcancel('确认设备操作', message + '\n\n请保持 USB 连接，操作期间不要换卡或拨打电话。', parent=self.root):
                return
        mode = 'update' if (self.report or {}).get('can_update') else 'install'
        host, config = self.host.get().strip(), self.config.get().strip()
        profile, experimental = profiles.validate(self.profile), self.experimental.get()
        self.busy = True
        self.connection_status.configure(text='正在连接并检查手机…')
        self.last_result = None
        self.refresh_buttons()
        self.progress.pack(fill='x', pady=(0, 10), before=self.activity.master)
        self.progress.start(12)
        self.summary.configure(text='正在执行，请保持设备连接', fg=BLUE)
        self.detail.configure(text='请保持 USB 连接，不要换卡或拨打电话。')

        def work():
            try:
                client, choice = resolve_connection(host, config,
                    progress=lambda phase, state: self.events.put(('progress', (phase, state))),
                    profile=profile, allow_experimental=experimental)
                self.events.put(('connection', choice))
                if action == 'preflight':
                    report = client.preflight()
                    result = {'preflight': report}
                    if report['installation']['state'] in ('busy', 'stopped', 'recovery_required'):
                        try:
                            state = public_status(client.service('status'))
                            result.update(status=state, registered=registered(state))
                        except WorkflowError as error:
                            result['status_error'] = error.code
                else:
                    result = client.install(mode, start=True) if action == 'install' else client.action(action)
                self.events.put(('result', (action, result)))
            except WorkflowError as error:
                self.events.put(('error', (error.code, error.report)))
            except Exception:
                # Do not expose unfiltered errors or SSH output in exported reports.
                self.events.put(('error', ('unexpected_error', None)))
        threading.Thread(target=work, daemon=True).start()

    def connect_phone(self):
        if not self.busy:
            if not self.config.get() and self.host.get() in ('bb10-root', 'q10-root') and not self.display_report:
                self.setup()
            else:
                self.run('preflight')

    def drain(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == 'connection':
                    if self.host.get() != payload['host']:
                        self.host.set(payload['host'])
                    if self.config.get() != payload['config']:
                        self.config.set(payload['config'])
                    continue
                if kind == 'progress':
                    phase, state = payload
                    self.activity.configure(text=PHASES.get(phase, '处理设备') + ' · ' + {'working': '进行中', 'done': '完成', 'pending': '待确认'}[state])
                    continue
                self.busy = False
                self.progress.stop()
                self.progress.pack_forget()
                if kind == 'error':
                    code, report = payload
                    if report and 'checks' in report:
                        self.render_report(report)
                    else:
                        self.report, self.report_connection = None, None
                        self.display_report = None
                        self.check_count.configure(text='检查未完成')
                        self.table_frame.pack_forget()
                    self.last_result = {'error': code, 'preflight': report if report and 'checks' in report else None}
                    self.summary.configure(text='操作未完成，需要核对', fg=RED)
                    self.detail.configure(text=ERRORS.get(code, '发生异常。请重新预检并保留现场；不要重复覆盖安装。'))
                    if code in ERRORS and code in ('connection_setup_required', 'hostname_unresolved', 'config_missing',
                            'authentication_failed', 'host_key_mismatch', 'connection_refused', 'connection_failed',
                            'connection_timeout_state_unknown', 'openssh_missing', 'bundled_ssh_mismatch', 'ssh_algorithm_mismatch'):
                        view = guidance(error=code)
                        self.summary.configure(text=view.title, fg=AMBER)
                        self.connection_status.configure(text='连接尚未验证 · 已保存材料保留')
                    self.activity.configure(text='操作已停止，请查看上方提示')
                else:
                    action, result = payload
                    self.last_result = result
                    report = result if 'checks' in result else result.get('preflight')
                    remember_failed = False
                    if report and any(item['id'] == 'root' and item['status'] == 'pass' for item in report.get('checks', [])):
                        try:
                            save_connection(self.host.get(), self.config.get())
                        except OSError:
                            remember_failed = True
                    if report:
                        self.render_report(report, result.get('status'))
                    if remember_failed:
                        self.connection_status.configure(text='连接可用 · 本次未能保存，请检查个人目录权限')
                    if action != 'preflight':
                        # Every device action invalidates previously enabled mutation buttons.
                        self.report, self.report_connection = None, None
                    if result.get('restored'):
                        self.summary.configure(text='已停用并确认恢复', fg=GREEN)
                        self.detail.configure(text='恢复检查通过。再次安装或更新前，请重新预检。')
                    elif result.get('registration') == 'verified' or result.get('registered'):
                        self.summary.configure(text='4G 通话服务已启用' if action == 'preflight' else '服务注册正常，待通话验收', fg=GREEN)
                        self.detail.configure(text='已检测到安装的服务，当前 IMS 注册与 LTE 正常。' if action == 'preflight' else
                                              '请在手机上验证呼入、呼出、双向声音和全程 4G。重启后等待服务注册，再复测通话。')
                    elif action == 'preflight' and result.get('status'):
                        state = result['status']
                        phase = state.get('phase', 'unknown')
                        if state.get('manager_alive') and phase in ('waiting_for_native_ims', 'configuring', 'waiting_for_ims_apn', 'running', 'registering'):
                            self.summary.configure(text='服务已安装，正在准备通话', fg=AMBER)
                            self.detail.configure(text=SERVICE_PHASES.get(phase, '等待注册') + '。请稍后重新检查，等待注册通过后再测试通话。')
                        elif phase == 'stopped':
                            self.summary.configure(text='服务已安装，当前未启动', fg=INK)
                            self.detail.configure(text='确认下方事项后，可以启动并验证服务。' if report.get('can_start') else
                                                  '当前条件未允许启动。请按检查表处理；机型适配限制不能用实验试用绕过。')
                        else:
                            self.summary.configure(text='已检测到安装，服务状态需核对', fg=AMBER)
                            self.detail.configure(text='请查看检查详情或导出报告，再按实际状态处理。')
                    elif action in ('install', 'start'):
                        self.summary.configure(text='服务已启动，注册仍待确认', fg=AMBER)
                        self.detail.configure(text='等待窗口已结束。稍后重新预检并查看状态；尚不能判断为安装通话成功。')
                    elif action == 'status':
                        status = result.get('status', {})
                        phase = status.get('phase', 'unknown')
                        self.summary.configure(text='当前状态：' + SERVICE_PHASES.get(phase, '待确认'), fg=INK)
                        detail = ('系统状态可能来自原厂 IMS；当前服务尚未完成注册。' if status.get('ims_observation_scope') == 'system_status_only'
                                  else '服务尚未完成注册，请稍后重新检查。')
                        wait = status.get('startup_wait', {})
                        if phase == 'waiting_for_ims_apn' and wait.get('attempt'):
                            detail = '第 {}/{} 轮等待，每轮最多 {} 秒。请保持 SIM 和 LTE 就绪。'.format(
                                wait['attempt'], wait.get('max_attempts', 3), wait.get('seconds_per_attempt', 45))
                        self.detail.configure(text=detail)
                    self.activity.configure(text='操作完成 · ' + time.strftime('%H:%M:%S'))
                self.refresh_buttons()
        except queue.Empty:
            pass
        self._drain_job = self.root.after(100, self.drain)

    def explain_row(self, _):
        rows = self.table.selection()
        if rows:
            item, state, detail = self.table.item(rows[0], 'values')
            messagebox.showinfo(item + ' · ' + state, detail, parent=self.root)

    def show_checks(self):
        if not self.display_report or self.busy:
            return
        popup = tk.Toplevel(self.root)
        popup.title('检查详情')
        popup.geometry('900x570')
        popup.minsize(780, 450)
        popup.transient(self.root)
        body = tk.Frame(popup, bg='white', padx=20, pady=20)
        body.pack(fill='both', expand=True)
        self.label(body, '完整检查结果', 16, bold=True).pack(anchor='w')
        self.label(body, '此处是最近一次检查的快照；设备操作后需重新检查。', 11, MUTED).pack(anchor='w', pady=(6, 16))
        table = ttk.Treeview(body, columns=('item', 'state', 'detail'), show='headings', selectmode='browse')
        for key, title, width in [('item', '检查项目', 135), ('state', '结果', 85), ('detail', '说明', 580)]:
            table.heading(key, text=title, anchor='w')
            table.column(key, width=width, minwidth=85 if key != 'detail' else 200, stretch=key == 'detail')
        scroll = AutoScrollbar(body, orient='vertical', command=table.yview)
        table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        table.pack(fill='both', expand=True)
        labels = {'pass': '通过', 'wait': '待处理', 'adapt': '需适配', 'block': '不支持'}
        for check in self.display_report['checks']:
            expected = self.running_baseline_expected and check['id'] == 'baseline' and check['code'] == 'baseline_not_clean'
            table.insert('', 'end', values=(NAMES.get(check['id'], '其他检查'), '运行中（预期）' if expected else labels[check['status']],
                                           '服务正在使用配置；更新前先停用并恢复。' if expected else
                                           NOTES.get(check['code'], '请导出报告协助检查')))

        diagnostic_names = {'ims_state': 'IMS 状态', 'ims_ran': 'IMS 网络',
                            'allow_volte_provisioning': 'VoLTE provisioning',
                            'engineering_voice_override': '工程语音域',
                            'dca_voice_preference': 'DCA 语音域', 'use_preconditions': 'IR92 preconditions'}
        diagnostics = self.display_report.get('incoming_diagnostics', {})
        for key, title in diagnostic_names.items():
            if key in diagnostics:
                value = diagnostics[key]
                table.insert('', 'end', values=(title, '只读观察',
                    ('未知' if value is None else str(value)) + '；配置快照，不能证明来电可用'))
        levels = {'upstream_local_experiment': '上游作者本地实验',
                  'upstream_contributed_report': '上游收录的贡献者报告',
                  'upstream_local_negative_test': '上游作者失败记录'}
        for entry in self.display_report.get('community_research', {}).get('records', []):
            table.insert('', 'end', values=('社区记录', '参考', entry['id'] + ' · ' +
                levels.get(entry['evidence_level'], '来源待核对') + '；非本工具验收，来源见社区研究说明'))

        def explain(_):
            rows = table.selection()
            if rows:
                item, state, detail = table.item(rows[0], 'values')
                messagebox.showinfo(item + ' · ' + state, detail, parent=popup)
        table.bind('<Double-1>', explain)

    def export(self):
        if not self.last_result:
            return
        path = filedialog.asksaveasfilename(title='保存脱敏检查报告', defaultextension='.json', initialfile='bb10-volte-preflight.json', filetypes=[('JSON', '*.json')])
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as file:
                    json.dump(self.last_result, file, ensure_ascii=False, indent=2)
                self.activity.configure(text='脱敏报告已保存 · 分享前仍请自行核对内容')
            except OSError:
                messagebox.showerror('无法保存', '请检查保存路径和写入权限。', parent=self.root)

    def guide(self):
        self.show_document('使用与恢复指南', ROOT / 'docs/GUI.md')

    def setup(self):
        if not self.busy:
            if self._startup_job is not None:
                self.root.after_cancel(self._startup_job)
                self._startup_job = None
            if self.connection_dialog and self.connection_dialog.winfo_exists():
                self.connection_dialog.lift()
                return
            from connection_dialog import ConnectionDialog
            def ready(host, config):
                self.host.set(host)
                self.config.set(config)
                self.run('preflight')
            self.connection_dialog = ConnectionDialog(self.root, ready, self.host.get(), self.config.get())

    def licenses(self):
        path = ROOT / 'licenses/THIRD-PARTY-NOTICES.txt'
        project = json.loads((ROOT / 'project.json').read_text(encoding='utf-8'))
        intro = ('bb10-volte ' + project['version'] + ' · 桌面修订 ' + str(project.get('desktop_revision', 1)) + '\n\n'
                 '适用于 BlackBerry 10 设备。当前实机记录：Q10 SQN100-3 / BB10 10.3.3.3216 / 北京联通。\n'
                 '其他设备与运营商需逐台验证。\n\n')
        self.show_document('关于与开源许可', path if path.is_file() else ROOT / 'NOTICE.md', intro)

    def show_document(self, title, path, intro=''):
        popup = tk.Toplevel(self.root)
        popup.title(title)
        popup.geometry('760x580')
        text = tk.Text(popup, wrap='word', font=(FONT, 11), padx=24, pady=20,
                       bg='white', fg=INK, relief='flat')
        bar = AutoScrollbar(popup, command=text.yview)
        bar.pack(side='right', fill='y')
        text.configure(yscrollcommand=bar.set)
        text.pack(fill='both', expand=True)
        text.insert('1.0', intro + path.read_text(encoding='utf-8'))
        text.configure(state='disabled')

    def close(self):
        if self.busy:
            messagebox.showinfo('操作进行中', '请等待本次有界操作结束。强行退出不能撤销已经写入手机的步骤。', parent=self.root)
            return
        self.root.after_cancel(self._drain_job)
        if self._startup_job is not None:
            self.root.after_cancel(self._startup_job)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='bb10-root')
    parser.add_argument('--ssh-config', default='')
    parser.add_argument('--self-test', type=Path, help='Write an offline packaging self-test report and exit')
    parser.add_argument('--preflight-report', type=Path, help='Run read-only preflight, write a report and exit')
    parser.add_argument('--flash-stage', choices=('os', 'radio'), help=argparse.SUPPRESS)
    parser.add_argument('--root-kit', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--flash-token', help=argparse.SUPPRESS)
    parser.add_argument('--prepare-root-report', type=Path, help='Prepare and verify Root images only; never contacts or flashes a phone')
    parser.add_argument('--root-variant', help='Explicit Q10 hardware variant for image preparation')
    parser.add_argument('--root-cache', type=Path, help='Optional directory of pinned, already downloaded Root materials')
    parser.add_argument('--root-offline', action='store_true', help='Require cached Root inputs without any Python download')
    parser.add_argument('--download-proxy', help='Optional proxy for missing preparation inputs')
    args = parser.parse_args()
    prepare_external_programs()
    if args.flash_stage:
        if not args.root_kit or not args.flash_token:
            parser.error('A confirmed Root kit is required')
        from root_flash import run_stage
        return run_stage(args.root_kit, args.flash_stage, args.flash_token)
    if args.prepare_root_report:
        if not args.root_variant:
            parser.error('--root-variant is required for image preparation')
        from root_setup import prepare_root_kit, prepared_images
        folder = prepare_root_kit(args.root_variant, lambda *_: None, args.download_proxy, args.root_cache, args.root_offline)
        state, images = prepared_images(folder)
        result = {'prepared': True, 'variant': state['variant'], 'root_kit': folder,
                  'images_verified': len(images), 'offline_inputs_only': args.root_offline,
                  'phone_contacted': False, 'phone_flashed': False}
        args.prepare_root_report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        return 0
    if args.self_test:
        from windows_selftest import run
        return run(args.self_test)
    if args.preflight_report:
        try:
            client, _ = resolve_connection(args.host, args.ssh_config)
            report = client.preflight()
            if report['installation']['state'] in ('busy', 'stopped', 'recovery_required'):
                status = public_status(client.service('status'))
                report.update(status=status, registered=registered(status))
            code = 0 if report['outcome'] in ('compatible', 'experimental') else 2
        except WorkflowError as error:
            report, code = {'error': error.code}, 1
        args.preflight_report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        return code
    if os.name == 'nt':
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    # Keep point fonts and pixel geometry consistent on Windows at 125/150% DPI.
    # The window remains resizable; Tk's default font scaling otherwise clips
    # the fixed-width sidebar and pushes the operation status below the window.
    root.tk.call('tk', 'scaling', min(float(root.tk.call('tk', 'scaling')), 1.6))
    App(root, args.host, args.ssh_config, auto_connect=True)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
