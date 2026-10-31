"""bb10-volte: standard-library desktop UI over the fixed workflow."""
from i18n import document_path, tr
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
from diagnostic_details import baseline_rows, baseline_summary, has_read_failure, incoming_rows, network_rows, support_summary
from ui_theme import apply_theme, AutoScrollbar
from connection import matching_alias, saved_connection, resolve_connection, save_connection
from connection_flow import guidance
from mac_help import CONNECTION_HINT, show_guide as show_mac_guide
from auto_carrier_view import status_view as unified_status_view, restart_guidance as unified_restart_guidance

BG, INK, MUTED = '#F2F5F9', '#18273F', '#62738B'
BLUE, GREEN, AMBER, RED = '#235BD7', '#137860', '#9A610B', '#BA3C42'
NAMES = {'model': tr('手机型号'), 'os': tr('系统版本'), 'root': tr('Root 环境'), 'native': tr('原生文件'),
         'sim': tr('SIM 就绪'), 'carrier': tr('运营商'), 'sim_route': tr('SIM 路线'), 'identity': tr('身份格式'),
         'lte': tr('4G 网络'), 'apn': tr('数据 APN'), 'carrier_config': tr('原厂数据配置'), 'experiment': tr('实测与试用'),
         'installation': tr('已装服务'), 'baseline': tr('安装前状态'), 'saved_profile': tr('已装配置'),
         'provider_lifecycle': tr('机型恢复验证'), 'autostart_policy': tr('开机启动验证')}
NAMES.update(telecom_attach=tr('电信入网前置流程'), carrier_selection=tr('运营商配置选择'))
NOTES = {
    'unified_payload_verified': tr('三网自动适配文件及原始备份回执已核验。'),
    'unified_running': tr('本次开机自动选择的运营商已注册；双向通话仍需实机确认。'),
    'unified_waiting': tr('自动适配尚未完成注册。请按当前阶段的提示处理，再检查状态。'),
    'unified_carrier_reboot_required': tr('入网策略已保存，还需一次正常重启；重启后重新检查注册。'),
    'unified_reboot_required': tr('需要正常重启手机，开机解锁后重新检查注册。'),
    'telecom_attach_manual_port': tr('Q10 电信手动移植待验收：先备份原始配置，再恢复正常 LTE 数据，最后配置 IMS。'),
    'telecom_attach_owned': tr('当前入网参数由本工具管理，原始配置及电脑备份回执均已核验。'),
    'telecom_recorded_acceptance': tr('这台 Q10、当前配置和 SIM 已有双向声音、LTE、正常重启及拔 USB 通话验收，关键运行文件散列一致。'),
    'telecom_attach_needs_adaptation': tr('电信入网前置流程仅开放散列和原始配置一致的 Q10 SQN100-3 手动试用；Q20 使用已验收的独立适配，Q30 仍待适配。'),
    'q20_root_v2_verified': tr('已验证现有 Q20 旧 Root 适配，无需更换 Root 方案。'),
    'q20_adapter_verified': tr('现有 Q20 适配的全部固定文件校验通过；App 可查询、手动启动或停用恢复。'),
    'q20_boot_accepted': tr('Q20 开机入口已核验；请参照当前运营商的实机验收记录。'),
    'q20_boot_hook_changed': tr('Q20 开机入口与已验收版本不同，自动恢复需要复核；请保留当前配置并导出报告。'),
    'carrier_selection_conflict': tr('配置选择路径与当前服务的文件不一致。保留现场，核对 XML 内容与运营商，避免套用其他运营商数据配置。'),
    'device_identified': tr('已自动识别型号和硬件变体；实测状态见顶部'),
    'passport_provider_lifecycle_unvalidated': tr('Passport 有停用后网络栈重启的社区报告；恢复策略验证前暂停安装、启动及自动恢复，实验试用不能绕过。见社区研究说明。'),
    'device_identity_unknown': tr('型号未知或与硬件变体冲突，请导出报告协助适配'),
    'os_3216_required': tr('要求 BB10 OS 10.3.3.3216'),
    'root_qnx_arm32_required': tr('要求 AutoRoot 已就绪、有效 root 和 QNX ARM32'),
    'native_hashes_required': tr('4 个原生文件 SHA-256 必须与验证基线一致'),
    'sim_ready': tr('SIM 已就绪'), 'sim_unavailable': tr('解锁 SIM 并等待就绪后重试'),
    'carrier_matches_profile': tr('实际 SIM 的 MCC/MNC 与所选配置一致'),
    'carrier_not_profiled': tr('SIM 与当前配置不一致；请选择或编辑运营商配置'),
    'carrier_template_required': tr('按实际 SIM 匹配原厂配置、数据 APN 和 IMS 结构；失败时需适配'),
    'experimental_opt_in': tr('未实测适配；勾选实验试用后，仍须通过全部技术检查'),
    'experimental_manual_start_required': tr('社区报告自启动可能卡在开机动画；请在“自定义 → 运行选项”关闭自动启动后重新检查。实验组合仅允许手动启动。'),
    'recorded_baseline': tr('有 Q10 SQN100-3 北京联通单机记录；本机仍须验收'),
    'saved_profile_matches': tr('所选配置与手机已装配置一致'),
    'profile_update_required': tr('新安装将保存所选配置；已装配置有变更时先停用恢复，再更新'),
    'usim_without_isim': tr('USIM，无 ISIM；符合当前实现'),
    'sim_route_not_profiled': tr('此 SIM 类型需要另行适配，不能套用当前配置'),
    'identity_layout_matches': tr('在手机本地核验通过；报告不包含完整标识'),
    'identity_layout_unknown': tr('SIM 身份格式不符，需提供脱敏预检报告排查'),
    'lte_ready': tr('本次快照报告 LTE；不代表已完成网络注册、能上网或已确认频段'), 'lte_not_ready': tr('开启移动网络并等待 LTE'),
    'lte_emergency_only': tr('手机仍报告紧急服务标志；即使其他项目显示已连接，也不能认定正常入网。'),
    'lte_service_unknown': tr('未取得有效的无线网络服务位图；显示 LTE 或数据已连接仍不足以确认就绪。'),
    'lte_data_unavailable': tr('无线层未报告正常 LTE 数据服务；请先排查入网，能力标志不能代替数据服务。'),
    'data_services_off': tr('手机报告数据服务状态或设置为 OFF；检查详情可区分两者，不能仅凭状态认定手动关闭，也不能据此判断频段不支持。'),
    'data_internet_inactive': tr('系统未提供可用的 internet 服务；缺少 APN/connected 字段不等于 APN 填错，请先检查数据服务与入网状态。'),
    'data_network_emergency_only': tr('手机报告仅紧急服务，当前不能将数据连接判为就绪；请先排查正常入网。'),
    'data_network_service_unknown': tr('无线网络服务状态未知，不能仅凭 APN connected=true 放行；请导出报告。'),
    'data_network_unavailable': tr('数据层与无线层状态不一致：无线层未报告正常 LTE 数据服务，暂不放行安装。'),
    'data_apn_ready': tr('所选配置的数据 APN 已连接'), 'data_apn_not_ready': tr('所选数据 APN 未连接；检查数据服务与配置'),
    'data_apn_profile_mismatch': tr('手机报告的 APN 不在所选配置中；请核对实际 APN 与运营商模板。连接状态见检查详情。'),
    'data_apn_disconnected': tr('APN 与配置匹配，但手机报告数据未连接；请先确认手机能使用移动数据上网。'),
    'data_apn_state_unknown': tr('未取得完整网络或 APN 状态；请导出报告，不能据此判断频段不支持。'),
    'installation_absent': tr('未安装，可在全部检查通过后安装'),
    'installation_stopped': tr('文件完整且已停止，可以更新'),
    'installation_busy': tr('已有管理器或锁；更新前先停用并恢复'),
    'installation_recovery_required': tr('恢复记录尚未完成；先停用并恢复'),
    'installation_interrupted': tr('上次安装中断；保留现场，不要重复覆盖'),
    'installation_conflict': tr('目录、文件或所有权不符；需要人工检查'),
    'baseline_clean': tr('原策略、IMS、VPN 与覆盖配置符合安装前条件'),
    'baseline_not_clean': tr('配置或服务状态不符合安装前条件，具体项目见检查详情。尚未安装本工具时，需先核实已有配置来源。'),
}
ERRORS = {
    'unified_update_needs_stop_and_reboot': tr('有适配更新。请先停用，待恢复后正常重启，再检查并更新。'),
    'unified_already_installed': tr('手机已安装三网自动适配。请使用“三网自动适配”管理现有服务。'),
    'unified_package_mismatch': tr('手机自动适配版本与程序不匹配。请保留当前安装并导出报告。'),
    'telecom_backup_not_verified': tr('原始电信配置尚未完成电脑备份和散列核验，未允许入网修改。请保留现场并重新检查。'),
    'q20_managed_existing_only': tr('这台 Q20 使用已验收的独立适配；请管理现有服务，通用安装器不会覆盖它。'),
    'provider_lifecycle_needs_adaptation': tr('此机型的提供器停用策略尚未验证。请保留当前状态并导出报告，参阅“社区研究与适配进展”。'),
    'connection_setup_required': tr('这台电脑还没有可用的连接。打开“连接帮助”，选择原刷机文件夹，或从手机重新授权。'),
    'hostname_unresolved': tr('原连接不可用。打开“连接帮助”恢复材料，或在高级设置核对连接。'),
    'ssh_algorithm_mismatch': tr('手机 SSH 与客户端算法不匹配。请使用更新后的完整应用重新检查。'),
    'connection_refused': tr('手机连接服务尚未启动。请解锁手机，打开“连接帮助”按当前状态处理。'),
    'bundled_ssh_mismatch': tr('内置 SSH 文件校验失败，请重新获取完整 EXE。'),
    'invalid_profile': tr('配置格式或参数不符合要求，请在配置编辑器中检查。'),
    'profile_update_required': tr('所选配置与已装配置不同。先停用恢复，再预检和更新安装。'),
    'invalid_host': tr('SSH 别名只能使用字母、数字、点、下划线和短横线。'),
    'config_missing': tr('原连接文件可能移动了。打开“连接帮助”，选择原刷机文件夹或恢复授权。'),
    'openssh_missing': tr('找不到 SSH 客户端，请按安装文档准备 ssh 和 scp。'),
    'package_mismatch': tr('安装包与固定清单不一致。请使用完整发布包，不要在客户电脑重新生成清单。'),
    'host_key_mismatch': tr('主机密钥校验失败。核对所选设备和个人 SSH 配置，保留原信任记录。'),
    'authentication_failed': tr('手机未接受这台电脑的授权。打开“连接帮助”，选择原材料或在手机端重新授权。'),
    'connection_failed': tr('无法连接。检查 USB、手机 Root 状态、驱动和 SSH 配置。'),
    'connection_timeout_state_unknown': tr('连接超时，设备状态尚未确认。重新预检并查看状态，不要盲目重复安装。'),
    'remote_operation_failed': tr('设备拒绝了操作。请重新预检并保留现场，必要时采集私有日志。'),
    'invalid_device_response': tr('设备返回不完整。重新连接后预检，确认实际状态。'),
    'preflight_blocked': tr('预检未允许这项操作。请先处理检查表中的待处理项目。'),
    'installation_not_verified': tr('安装回读未通过。保留现场，暂时不要启动或覆盖安装。'),
    'installation_needs_inspection': tr('未发现完整、可管理的安装。请先核对预检结果。'),
    'service_needs_attention': tr('服务未正常运行。先查看状态，再按需要停用并恢复。'),
    'restore_pending': tr('恢复仍未结束。保持连接，稍后查看状态。'),
    'restore_needs_inspection': tr('尚未确认恢复完成。请保留记录并检查，暂时不能更新。'),
}
PHASES = {'package': tr('校验安装包'), 'connection': tr('连接设备'), 'transfer': tr('传输校验文件'),
          'preflight': tr('兼容性预检'), 'install': tr('安装固定版本'), 'verify': tr('回读已装文件'),
          'start': tr('启动服务'), 'registration': tr('验证 IMS 注册'), 'restore': tr('停用并恢复'),
          'stage_cleanup': tr('临时检查文件清理')}
SERVICE_PHASES = {'waiting_for_native_ims': tr('等待系统 IMS 初始化结束'),
                  'waiting_for_phone_idle': tr('等待手机和通话服务空闲'),
                  'waiting_for_sim': tr('等待 SIM 就绪'),
                  'waiting_for_lte_and_usim': tr('等待 SIM 和正常 LTE 数据服务'),
                  'reboot_required': tr('请使用手机电源菜单正常重启'),
                  'carrier_reboot_required': tr('运营商入网策略已保存，请再正常重启一次'),
                  'unsupported_sim': tr('当前 SIM 不在支持范围内，未启动自动适配'),
                  'telecom_bootstrap_configuring': tr('准备电信入网策略'),
                  'telecom_waiting_for_lte_data': tr('等待电信 LTE 数据入网'),
                  'configuration_restored_reboot_required': tr('配置已恢复，正常重启完成收尾'),
                  'configuring': tr('准备运营商配置'), 'waiting_for_ims_apn': tr('等待 IMS 专用网络'),
                  'not_started_this_boot': tr('本次开机尚未启动'), 'not_started': tr('尚未启动'),
                  'running': tr('运行中'), 'registering': tr('等待 IMS 注册'), 'stopped': tr('已停止')}


class App:
    def __init__(self, root, host='bb10-root', config='', auto_connect=False, profile=None):
        self.root, self.events = root, queue.Queue()
        self.busy, self.report, self.last_result = False, None, None
        self.report_connection = None
        self.display_report, self.device_info = None, {}
        self.running_baseline_expected = False
        self.connection_options_visible = False
        self.connection_dialog = None
        self._startup_job = None
        self.presets = presets()
        self.profile = profiles.validate(profile) if profile is not None else profiles.default()
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
        self.connection_status.configure(text=tr('已记住上次连接 · 待重新验证') if saved else tr('尚未连接'))
        if saved:
            self.detail.configure(text=tr('已记住上次成功的连接。重新检查后显示手机当前状态，不会自动安装或刷写。'))
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
        self.auto_carrier_button = ttk.Button(header, text=tr('三网自动适配'), command=self.auto_carrier)
        self.auto_carrier_button.pack(side='left', padx=20)
        self.more_button = ttk.Menubutton(header, text=tr('更多'))
        self.more_button.pack(side='right')
        self.menu = tk.Menu(self.more_button, tearoff=False, font=(FONT, 11))
        self.more_button.configure(menu=self.menu)
        self.menu_actions = {}
        for action, title in [('install', tr('安装 / 更新并验证')), ('status', tr('查看服务状态')),
                              ('enable', tr('启用已验收的开机恢复')), ('disable', tr('停用并恢复'))]:
            self.menu_actions[action] = self.menu.index('end') + 1 if self.menu.index('end') is not None else 0
            self.menu.add_command(label=title, command=lambda k=action: self.run(k))
        self.menu.add_separator()
        self.export_index = self.menu.index('end') + 1
        self.menu.add_command(label=tr('导出检查报告'), command=self.export)
        self.menu.add_command(label=tr('高级连接设置'), command=self.toggle_connection_options)
        self.menu.add_separator()
        self.menu.add_command(label=tr('使用与恢复指南'), command=self.guide)
        self.menu.add_command(label=tr('社区研究与适配进展'), command=lambda: self.show_document(
            tr('社区研究与适配进展'), ROOT / 'docs/COMMUNITY-RESEARCH.md'))
        self.menu.add_command(label=tr('关于与开源许可'), command=self.licenses)
        self.device_label = self.label(main, tr('BlackBerry 10 设备 · 等待连接'), 11, MUTED, anchor='w')
        self.device_label.pack(fill='x', pady=(5, 22))

        self.connection_card = tk.Frame(main, bg='white', padx=20, pady=16)
        self.connection_card.pack(fill='x', pady=(0, 18))
        self.connection_status = self.label(self.connection_card, tr('尚未连接'), 12, MUTED)
        self.connection_status.pack(anchor='w')

        settings = tk.Frame(self.connection_card, bg='white')
        settings.pack(fill='x', pady=(12, 0))
        settings.columnconfigure(1, weight=1)
        self.label(settings, tr('运营商'), 11, MUTED).grid(row=0, column=0, sticky='w', padx=(0, 30))
        self.profile_picker = ttk.Combobox(settings, textvariable=self.profile_name,
                                          values=[picker_label(p['label']) for p in self.presets], state='readonly', width=47)
        self.profile_picker.grid(row=0, column=1, sticky='ew')
        self.profile_picker.bind('<<ComboboxSelected>>', self.select_profile)
        self.edit_button = ttk.Button(settings, text=tr('自定义'), command=self.edit_profile)
        self.edit_button.grid(row=0, column=2, padx=(10, 0))
        self.mac_connection_help = None
        self.mac_guide_button = None
        if sys.platform == 'darwin':
            self.mac_connection_help = tk.Frame(self.connection_card, bg='white')
            self.mac_connection_help.pack(fill='x', pady=(12, 0))
            self.mac_guide_button = ttk.Button(self.mac_connection_help, text=tr('Mac 连接说明'),
                                               command=lambda: show_mac_guide(self.root))
            self.mac_guide_button.pack(side='right', padx=(12, 0))
            hint = self.label(self.mac_connection_help, CONNECTION_HINT, 11, MUTED,
                              wraplength=650, justify='left', anchor='w')
            hint.pack(side='left', fill='x', expand=True)
            hint.bind('<Configure>', lambda event: hint.configure(wraplength=max(1, event.width - 4)))
        self.connection_options = tk.Frame(self.connection_card, bg='white')
        self.connection_options.columnconfigure(1, weight=1)
        self.label(self.connection_options, tr('SSH 配置'), 11, MUTED).grid(row=0, column=0, sticky='w', padx=(0, 14))
        self.config_entry = ttk.Entry(self.connection_options, textvariable=self.config)
        self.config_entry.grid(row=0, column=1, sticky='ew')
        self.browse_button = ttk.Button(self.connection_options, text=tr('手动选择'), command=self.browse)
        self.browse_button.grid(row=0, column=2, padx=(10, 0))
        self.label(self.connection_options, tr('SSH 别名'), 11, MUTED).grid(row=1, column=0, sticky='w', pady=(8, 0))
        self.host_entry = ttk.Entry(self.connection_options, textvariable=self.host, width=20)
        self.host_entry.grid(row=1, column=1, sticky='w', pady=(8, 0))
        self.experiment_check = ttk.Checkbutton(self.connection_card, text=tr('允许未实测设备或运营商实验试用'),
                                                variable=self.experimental)

        # Reserve the action area before giving the results card spare height.
        footer = tk.Frame(main, bg=BG)
        footer.pack(side='bottom', fill='x', pady=(16, 0))
        self.ack_check = ttk.Checkbutton(footer, text=tr('已备份、SIM 已开通 VoLTE，当前没有通话'), variable=self.ack)
        toolbar = tk.Frame(footer, bg=BG)
        toolbar.pack(side='bottom', fill='x')
        self.primary_action = 'install'
        self.primary_button = ttk.Button(toolbar, text=tr('安装并验证'), style='Accent.TButton',
                                          command=lambda: self.run(self.primary_action))
        self.primary_button.pack(side='right')
        self.check_button = ttk.Button(toolbar, text=tr('连接手机'), command=self.connect_phone)
        self.check_button.pack(side='right', padx=(0, 10))
        self.setup_button = ttk.Button(toolbar, text=tr('连接帮助'), command=self.setup)
        self.setup_button.pack(side='left', padx=(0, 16))
        self.activity = self.label(toolbar, tr('准备就绪'), 11, MUTED, anchor='w')
        self.activity.pack(side='left', fill='x', expand=True, padx=(0, 16))
        self.buttons = {'preflight': self.check_button, 'primary': self.primary_button}
        self.progress = ttk.Progressbar(footer, mode='indeterminate')

        summary = tk.Frame(main, bg='white', padx=20, pady=18)
        summary.pack(fill='both', expand=True)
        heading = tk.Frame(summary, bg='white')
        heading.pack(fill='x')
        self.summary = self.label(heading, tr('连接你的黑莓手机'), 18, bold=True)
        self.summary.pack(side='left')
        self.details_button = ttk.Button(heading, text=tr('检查详情'), command=self.show_checks, state='disabled')
        self.details_button.pack(side='right')
        self.detail = self.label(summary, tr('用数据线连接并解锁手机，再点击“连接手机”。程序会查找已有连接；需要授权或首次 Root 时，打开“连接帮助”。'), 11, MUTED,
                                 wraplength=850, justify='left', anchor='w')
        self.detail.pack(fill='x', pady=(10, 12))
        self.detail.bind('<Configure>', lambda event: self.detail.configure(wraplength=max(1, event.width - 4)))
        self.check_count = self.label(summary, tr('系统、SIM 和安装条件将在连接后自动检查'), 11, MUTED, anchor='w')
        self.check_count.pack(fill='x', pady=(0, 10))
        self.table_frame = tk.Frame(summary, bg='white')
        self.table = ttk.Treeview(self.table_frame, columns=('item', 'state', 'detail'), show='headings', selectmode='browse', height=1)
        for col, label, width in [('item', tr('待处理项目'), 135), ('state', tr('结果'), 95), ('detail', tr('处理方法'), 480)]:
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
            self.device_label.configure(text=tr('BlackBerry 10 设备 · 等待连接'))
        self.ack.set(False)
        self.connection_status.configure(text=tr('连接或选项已改变 · 请重新检查'))
        self.summary.configure(text=tr('配置已更新，请检查设备'), fg=INK)
        self.detail.configure(text=tr('检查通过后即可继续安装或管理服务。'))
        self.check_count.configure(text=tr('等待重新检查'))
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
                   'enable': current and r.get('can_enable') and not r.get('installation', {}).get('enabled') and self.ack.get(),
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
        self.primary_button.configure(text=tr('启动并验证') if self.primary_action == 'start' else
                                      tr('查看状态') if self.primary_action == 'status' else
                                      tr('更新并验证') if r.get('can_update') else tr('安装并验证'),
                                      state='normal' if allowed.get(self.primary_action) else 'disabled')
        if self.primary_action:
            self.primary_button.pack(side='right', before=self.check_button)
        else:
            self.primary_button.pack_forget()
        self.check_button.configure(text=tr('重新检查') if self.display_report or self.last_result else tr('连接手机'),
                                    style='TButton' if self.primary_action else 'Accent.TButton',
                                    state='normal' if allowed['preflight'] else 'disabled')
        for action, index in self.menu_actions.items():
            self.menu.entryconfigure(index, state='normal' if allowed[action] else 'disabled')
        for widget in (self.config_entry, self.host_entry, self.browse_button, self.edit_button,
                       self.experiment_check, self.ack_check, self.setup_button):
            widget.configure(state='disabled' if self.busy else 'normal')
        managed = r.get('managed_adapter') in ('q20_root_v2', 'unified_carriers')
        self.menu.entryconfigure(self.menu_actions['enable'], label=tr('启用自动适配')
            if r.get('managed_adapter') == 'unified_carriers' else tr('启用已验收的开机恢复'))
        self.auto_carrier_button.configure(state='disabled' if self.busy else 'normal')
        accepted_telecom = r.get('hardware_validation') == 'q10_telecom_per_sim_accepted'
        self.profile_picker.configure(state='disabled' if self.busy or managed else 'readonly')
        self.edit_button.configure(state='disabled' if self.busy or managed else 'normal')
        self.experiment_check.configure(state='disabled' if self.busy or managed or accepted_telecom else 'normal')
        self.menu.entryconfigure(self.export_index, state='normal' if self.last_result and not self.busy else 'disabled')
        self.details_button.configure(state='normal' if self.display_report and not self.busy else 'disabled')
        needs_ack = any(r.get(key) for key in ('can_install', 'can_update', 'can_start')) or r.get('installation', {}).get('state') in ('busy', 'stopped', 'recovery_required')
        if needs_ack:
            self.ack_check.pack(anchor='w', pady=(0, 12))
        else:
            self.ack_check.pack_forget()
        experimental = (self.experimental.get() or not profiles.baseline_parameters(self.profile) or
                        bool(self.device_info) and not self.device_info.get('hardware_tested'))
        if experimental and not managed and not accepted_telecom:
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
        path = filedialog.askopenfilename(title=tr('选择这台手机的 SSH 配置'), initialdir=str(initial), filetypes=[('SSH config', '*')])
        if path:
            self.config.set(path)
            self.host.set(matching_alias(path, self.host.get()))

    def render_report(self, report, service_status=None):
        self.report = report
        self.report_connection = self.selection()
        device = report.get('device', {})
        self.display_report, self.device_info = report, device
        root_verified = any(item['id'] == 'root' and item['status'] == 'pass' for item in report['checks'])
        self.connection_status.configure(text=tr('最近检查：已连接 · Root 已验证') if root_verified else tr('最近检查：手机已响应 · Root 权限待核验'))
        self.running_baseline_expected = (report.get('installation', {}).get('state') == 'busy' and
                                          bool((service_status or {}).get('manager_alive')) and
                                          not has_read_failure(report))
        badge = tr('Q10 已有实测记录') if device.get('hardware_tested') else tr('未实测 · 可实验试用')
        if not device.get('recognized'):
            badge = tr('机型待识别')
        elif any(c['code'] == 'passport_provider_lifecycle_unvalidated' for c in report['checks']):
            badge = tr('Passport 恢复策略待验证')
        elif report.get('managed_adapter') == 'q20_root_v2':
            badge = tr('Q20 运营商适配')
        elif report.get('managed_adapter') == 'unified_carriers':
            badge = tr('三网自动适配 · 实机验收版')
        elif report.get('hardware_validation') == 'q10_telecom_per_sim_accepted':
            badge = tr('Q10 电信：本机与当前 SIM 已验收')
        display_name = device.get('display_name', tr('未知设备'))
        if display_name == 'Unrecognized BB10 device':
            display_name = tr('未识别的 BB10 设备')
        carrier = (tr('  ·  运营商：中国电信') if report.get('operator_display', {}).get('name') == '中国电信' else '')
        self.device_label.configure(text='{}  /  {}  /  OS {}  ·  {}{}'.format(
            display_name, device.get('variant', '?'), device.get('os_version', '?'), badge, carrier))
        self.table.delete(*self.table.get_children())
        labels = {'pass': tr('通过'), 'wait': tr('待处理'), 'adapt': tr('需适配'), 'block': tr('不支持')}
        problems = []
        for check in report['checks']:
            key, state = check['id'], check['status']
            expected = self.running_baseline_expected and key == 'baseline' and check['code'] == 'baseline_not_clean'
            if key in NAMES and state != 'pass' and not expected:
                problems.append(check)
                self.table.insert('', 'end', iid=key,
                                  values=(NAMES[key], labels[state], self.check_note(check, report)),
                                  tags=(state,))
        expected_count = sum(self.running_baseline_expected and check['id'] == 'baseline' and
                             check['code'] == 'baseline_not_clean' for check in report['checks'])
        self.check_count.configure(text=tr('已检查 {} 项 · {} 项通过{}{}').format(
            len(report['checks']), sum(check['status'] == 'pass' for check in report['checks']),
            tr(' · {} 项为服务运行状态').format(expected_count) if expected_count else '',
            tr(' · {} 项待处理').format(len(problems)) if problems else ''))
        if problems:
            self.table_frame.pack(fill='both', expand=True)
        else:
            self.table_frame.pack_forget()
        outcome = report['outcome']
        title, color = {'compatible': (tr('符合当前适配条件'), GREEN), 'not_ready': (tr('有条件尚未就绪'), AMBER),
                        'experimental': (tr('未实测适配 · 可实验试用'), AMBER),
                        'needs_adaptation': (tr('设备或运营商配置需要适配'), AMBER), 'unsupported': (tr('关键技术条件未通过'), RED)}[outcome]
        state = report['installation']['state']
        baseline_blocked = any(c['id'] == 'baseline' and c['status'] != 'pass' for c in problems)
        if baseline_blocked and outcome in ('compatible', 'experimental'):
            title, color = tr('安装前状态需处理'), AMBER
        if report.get('managed_adapter') == 'unified_carriers':
            view = unified_status_view(service_status or report.get('status', {}))
            title, color = view['title'], GREEN if view['ready'] else AMBER
            detail = view['guidance']
        elif report.get('can_restore') is False:
            detail = tr('此机型的自动操作暂缓。请保留当前状态、导出报告，并查看“社区研究与适配进展”。')
        elif state == 'busy':
            detail = tr('已有服务正在运行或持有锁。更新前请先停用并恢复；本次不会覆盖安装。')
        elif report.get('can_install') or report.get('can_update'):
            detail = tr('可进入安装流程。运营商开通情况和双向通话效果仍需真实通话确认。')
            if report.get('lte_bootstrap_pending'):
                detail = tr('电信当前尚未正常入网。手动试用会先保存并核验原始备份，再尝试入网；LTE 数据未就绪时不会配置 IMS。')
        elif state in ('conflict', 'interrupted', 'recovery_required'):
            detail = tr('安装或恢复状态需要处理。请保留现场，按检查表处理后重新预检。')
        elif baseline_blocked:
            detail = baseline_summary(report)
        else:
            detail = tr('请按下方提示处理后重新检查。')
        research = report.get('community_research', {})
        if research.get('records'):
            detail += tr(' 有相同硬件与运营商的社区研究记录，尚不代表本工具已验收；可在“更多”查看。')
        self.summary.configure(text=title, fg=color)
        self.detail.configure(text=detail)
        self.refresh_buttons()

    def auto_carrier(self):
        if self.busy:
            return
        from auto_carrier_gui import AutoCarrierWindow
        AutoCarrierWindow(self.root, self.host.get().strip(), self.config.get().strip())

    def run(self, action):
        if not self.allowed_actions().get(action):
            return
        if self._startup_job is not None:
            self.root.after_cancel(self._startup_job)
            self._startup_job = None
        if action in ('install', 'start', 'enable', 'disable'):
            if not self.ack.get() or self.report_connection != self.selection():
                return
            message = (tr('将停止本项目服务、恢复其修改并关闭自动启动。') if action == 'disable' else
                       tr('将按所选配置安装或启动并进行 IMS 验证。自动启动：') +
                       (tr('开启') if self.profile['runtime']['autostart'] else tr('已关闭')) + tr('。首次启动可能短暂重载无线网络。'))
            if action == 'disable' and (self.report or {}).get('managed_adapter') == 'q20_root_v2':
                message += tr(' Q20 会保留软件提供器至正常重启；请在恢复完成后用电源菜单重启。')
            if action == 'enable':
                message = tr('将按当前设备、配置和 SIM 的实机验收记录启用开机恢复。')
            if (self.report or {}).get('managed_adapter') == 'unified_carriers':
                message = (tr('将停用自动适配并恢复其配置，恢复后请正常重启。') if action == 'disable' else
                           tr('将启用自动适配；请正常重启，由手机识别当前 SIM。'))
            if not messagebox.askokcancel(tr('确认设备操作'), message + tr('\n\n请保持 USB 连接，操作期间不要换卡或拨打电话。'), parent=self.root):
                return
        mode = 'update' if (self.report or {}).get('can_update') else 'install'
        host, config = self.host.get().strip(), self.config.get().strip()
        profile, experimental = profiles.validate(self.profile), self.experimental.get()
        self.busy = True
        self.connection_status.configure(text=tr('正在连接并检查手机…'))
        self.last_result = None
        self.refresh_buttons()
        self.progress.pack(fill='x', pady=(0, 10), before=self.activity.master)
        self.progress.start(12)
        self.summary.configure(text=tr('正在执行，请保持设备连接'), fg=BLUE)
        self.detail.configure(text=tr('请保持 USB 连接，不要换卡或拨打电话。'))

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
                            unified = report.get('managed_adapter') == 'unified_carriers'
                            state = public_status(report['status'] if unified else client.service('status'))
                            ready = unified_status_view(state)['ready'] if unified else registered(state)
                            result.update(status=state, registered=ready)
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
                    self.activity.configure(text=PHASES.get(phase, tr('处理设备')) + ' · ' + {'working': tr('进行中'), 'done': tr('完成'), 'pending': tr('待确认')}[state])
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
                        self.check_count.configure(text=tr('检查未完成'))
                        self.table_frame.pack_forget()
                    self.last_result = {'error': code, 'preflight': report if report and 'checks' in report else None}
                    self.summary.configure(text=tr('操作未完成，需要核对'), fg=RED)
                    self.detail.configure(text=ERRORS.get(code, tr('发生异常。请重新预检并保留现场；不要重复覆盖安装。')))
                    if code in ERRORS and code in ('connection_setup_required', 'hostname_unresolved', 'config_missing',
                            'authentication_failed', 'host_key_mismatch', 'connection_refused', 'connection_failed',
                            'connection_timeout_state_unknown', 'openssh_missing', 'bundled_ssh_mismatch', 'ssh_algorithm_mismatch'):
                        view = guidance(error=code)
                        self.summary.configure(text=view.title, fg=AMBER)
                        self.connection_status.configure(text=tr('连接尚未验证 · 已保存材料保留'))
                    self.activity.configure(text=tr('操作已停止，请查看上方提示'))
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
                        if report.get('use_installed_profile'):
                            self.profile = profiles.validate(report['profile_parameters'])
                            self.profile_name.set(picker_label(self.profile['label']))
                            self.experimental.set(True)
                        self.render_report(report, result.get('status'))
                    if remember_failed:
                        self.connection_status.configure(text=tr('连接可用 · 本次未能保存，请检查个人目录权限'))
                    if action != 'preflight':
                        # Every device action invalidates previously enabled mutation buttons.
                        self.report, self.report_connection = None, None
                    if result.get('automatic_carrier_selection') and result.get('disabled'):
                        self.summary.configure(text=tr('已关闭自动启动。请等待恢复完成，再正常重启。'), fg=AMBER)
                        self.detail.configure(text=tr('原始备份和旧版本文件仍保留，可用于恢复。'))
                    elif result.get('automatic_carrier_selection') and result.get('enabled'):
                        self.summary.configure(text=tr('已启用自动适配，请正常重启。'), fg=AMBER)
                        self.detail.configure(text=unified_restart_guidance())
                    elif (report or {}).get('managed_adapter') == 'unified_carriers':
                        # Do not overwrite the unified restart/waiting steps with
                        # legacy generic status text or cached registration flags.
                        view = unified_status_view(result.get('status') or report.get('status', {}))
                        self.summary.configure(text=view['title'], fg=GREEN if view['ready'] else AMBER)
                        self.detail.configure(text=view['guidance'])
                    elif result.get('restored'):
                        self.summary.configure(text=tr('已停用并确认恢复'), fg=GREEN)
                        self.detail.configure(text=tr('Q20 配置已恢复，请用电源菜单正常重启，完成提供器收尾。') if result.get('reboot_required') else
                                              tr('恢复检查通过。再次安装或更新前，请重新预检。'))
                    elif result.get('enabled'):
                        self.summary.configure(text=tr('开机恢复已启用'), fg=GREEN)
                        self.detail.configure(text=tr('当前设备、配置、SIM 及关键运行文件已与验收记录核对。正常重启后请等待 IMS 注册。'))
                    elif result.get('registration') == 'verified' or result.get('registered'):
                        self.summary.configure(text=tr('4G 通话服务已启用') if action == 'preflight' else tr('服务注册正常，待通话验收'), fg=GREEN)
                        self.detail.configure(text=tr('已检测到安装的服务，当前 IMS 注册与 LTE 正常。') if action == 'preflight' else
                                              tr('请在手机上验证呼入、呼出、双向声音和全程 4G。重启后等待服务注册，再复测通话。'))
                    elif action == 'preflight' and result.get('status'):
                        state = result['status']
                        phase = state.get('phase', 'unknown')
                        if state.get('manager_alive') and phase in ('waiting_for_native_ims', 'configuring', 'waiting_for_ims_apn', 'running', 'registering'):
                            self.summary.configure(text=tr('服务已安装，正在准备通话'), fg=AMBER)
                            self.detail.configure(text=SERVICE_PHASES.get(phase, tr('等待注册')) + tr('。请稍后重新检查，等待注册通过后再测试通话。'))
                        elif phase == 'stopped':
                            self.summary.configure(text=tr('服务已安装，当前未启动'), fg=INK)
                            self.detail.configure(text=tr('确认下方事项后，可以启动并验证服务。') if report.get('can_start') else
                                                  tr('当前条件未允许启动。请按检查表处理；机型适配限制不能用实验试用绕过。'))
                        else:
                            self.summary.configure(text=tr('已检测到安装，服务状态需核对'), fg=AMBER)
                            self.detail.configure(text=tr('请查看检查详情或导出报告，再按实际状态处理。'))
                    elif action in ('install', 'start'):
                        self.summary.configure(text=tr('服务已启动，注册仍待确认'), fg=AMBER)
                        self.detail.configure(text=tr('等待窗口已结束。稍后重新预检并查看状态；尚不能判断为安装通话成功。'))
                    elif action == 'status':
                        status = result.get('status', {})
                        phase = status.get('phase', 'unknown')
                        self.summary.configure(text=tr('当前状态：') + SERVICE_PHASES.get(phase, tr('待确认')), fg=INK)
                        detail = (tr('系统状态可能来自原厂 IMS；当前服务尚未完成注册。') if status.get('ims_observation_scope') == 'system_status_only'
                                  else tr('服务尚未完成注册，请稍后重新检查。'))
                        wait = status.get('startup_wait', {})
                        if phase == 'waiting_for_ims_apn' and wait.get('attempt'):
                            detail = tr('第 {}/{} 轮等待，每轮最多 {} 秒。请保持 SIM 和 LTE 就绪。').format(
                                wait['attempt'], wait.get('max_attempts', 3), wait.get('seconds_per_attempt', 45))
                        self.detail.configure(text=detail)
                    self.activity.configure(text=tr('操作完成 · ') + time.strftime('%H:%M:%S'))
                self.refresh_buttons()
        except queue.Empty:
            pass
        self._drain_job = self.root.after(100, self.drain)

    def explain_row(self, _):
        rows = self.table.selection()
        if rows:
            if rows[0] == 'baseline':
                self.show_checks()
                return
            item, state, detail = self.table.item(rows[0], 'values')
            messagebox.showinfo(item + ' · ' + state, detail, parent=self.root)

    def check_note(self, check, report=None, running=None):
        report = self.display_report if report is None else report
        running = self.running_baseline_expected if running is None else running
        if check['id'] == 'baseline' and check['status'] != 'pass':
            return (tr('已确认本工具管理器运行；当前读数及停用后的要求见检查详情。') if running else
                    baseline_summary(report))
        passed = {'os': tr('系统版本符合要求。'), 'root': tr('Root 与 QNX ARM32 环境核验通过。'),
                  'native': tr('4 个原生文件的 SHA-256 均与本工具基线一致。'),
                  'autostart_policy': tr('实验组合已关闭自动启动，可在条件通过后手动启动。'),
                  'saved_profile': tr('新安装将保存所选配置。') if report.get('installation', {}).get('state') == 'absent'
                                   else tr('已装配置检查通过。')}
        if check['status'] == 'pass' and check['id'] in passed:
            return passed[check['id']]
        return NOTES.get(check['code'], tr('请导出报告协助检查。'))

    def diagnostic_text(self, report=None, running=None):
        report = self.display_report if report is None else report
        running = self.running_baseline_expected if running is None else running
        project = json.loads((ROOT / 'project.json').read_text(encoding='utf-8'))
        version = tr('{} · 桌面修订 {}').format(project['version'], project.get('desktop_revision', 1))
        return support_summary(report, NAMES, lambda check: self.check_note(check, report, running), version, running)

    def copy_diagnostics(self, report=None, running=None, parent=None):
        if not (report or self.display_report):
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.diagnostic_text(report, running))
            self.activity.configure(text=tr('排查摘要已复制，可粘贴给维护者；完整数据可导出检查报告'))
        except tk.TclError:
            messagebox.showerror(tr('无法复制'), tr('剪贴板暂不可用，请使用“导出检查报告”。'), parent=parent or self.root)

    def show_checks(self):
        if not self.display_report or self.busy:
            return
        popup = tk.Toplevel(self.root)
        popup.title(tr('检查详情'))
        popup.geometry('1040x700')
        popup.minsize(820, 580)
        popup.transient(self.root)
        body = tk.Frame(popup, bg='white', padx=20, pady=20)
        body.pack(fill='both', expand=True)
        self.label(body, tr('完整检查结果'), 16, bold=True).pack(anchor='w')
        self.label(body, tr('待处理项排在前面。选择一项可阅读完整说明；设备操作后需重新检查。'), 11, MUTED).pack(anchor='w', pady=(6, 10))
        report, running = self.display_report, self.running_baseline_expected
        toolbar = tk.Frame(body, bg='white')
        toolbar.pack(fill='x', pady=(0, 10))
        only_problems = tk.BooleanVar(popup, value=False)
        filter_button = ttk.Checkbutton(toolbar, text=tr('仅看待处理'), variable=only_problems)
        filter_button.pack(side='left')
        ttk.Button(toolbar, text=tr('复制排查摘要'), command=lambda: self.copy_diagnostics(report, running, popup)).pack(side='right')
        ttk.Button(toolbar, text=tr('导出检查报告'), command=lambda: self.export(report, running)).pack(side='right', padx=8)
        selected_body = tk.Frame(body, bg=BG)
        selected_body.pack(side='bottom', fill='x', pady=(12, 0))
        selected = tk.Text(selected_body, height=6, wrap='word', font=(FONT, 11), bg=BG, fg=INK,
                           relief='flat', padx=12, pady=10, state='disabled')
        selected_scroll = AutoScrollbar(selected_body, orient='vertical', command=selected.yview)
        selected.configure(yscrollcommand=selected_scroll.set)
        selected_scroll.pack(side='right', fill='y')
        selected.pack(fill='both', expand=True)
        table_body = tk.Frame(body, bg='white')
        table_body.pack(fill='both', expand=True)
        table = ttk.Treeview(table_body, columns=('item', 'state', 'detail'), show='headings', selectmode='browse')
        for key, title, width in [('item', tr('检查项目'), 220), ('state', tr('结果'), 110), ('detail', tr('说明'), 620)]:
            table.heading(key, text=title, anchor='w')
            table.column(key, width=width, minwidth=180 if key == 'item' else 100 if key == 'state' else 200,
                         stretch=key == 'detail')
        scroll = AutoScrollbar(table_body, orient='vertical', command=table.yview)
        table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        table.pack(fill='both', expand=True)
        labels = {'pass': tr('通过'), 'wait': tr('待处理'), 'adapt': tr('需适配'), 'block': tr('不支持')}
        rows = []
        def add(title, state, detail, problem=False):
            rows.append((title, state, detail, problem))
        for check in report['checks']:
            expected = running and check['id'] == 'baseline' and check['code'] == 'baseline_not_clean'
            add(NAMES.get(check['id'], tr('其他检查')), tr('运行中（预期）') if expected else labels[check['status']],
                self.check_note(check, report, running), check['status'] != 'pass' and not expected)
        for row in baseline_rows(report, running):
            add(row['title'], row['state'], '[' + row['code'] + '] ' + row['detail'], row['problem'])

        network = report.get('network_diagnostics', {})
        for key, title in (('apn_matches', tr('APN 与模板匹配')), ('data_connected', tr('数据连接状态'))):
            if key in network:
                value = network[key]
                add(title, tr('只读快照'), tr('是') if value is True else tr('否') if value is False else tr('未知'), value is not True)
        apn = network.get('observed_data_apn')
        if apn is not None:
            add(tr('手机报告的 APN'), tr('只读快照'),
                apn if apn in ('ctnet', 'ctlte', 'cmnet', '3gnet') else
                tr('其他 APN（报告不保存原文）') if apn == 'other' else tr('未知'))

        for row in network_rows(report):
            add(row['title'], row['state'], row['detail'], row['problem'])
        for row in incoming_rows(report):
            add(row['title'], row['state'], '[' + row['code'] + '] ' + row['detail'])
        levels = {'upstream_local_experiment': tr('上游作者本地实验'),
                  'upstream_contributed_report': tr('上游收录的贡献者报告'),
                  'upstream_local_negative_test': tr('上游作者失败记录')}
        for entry in report.get('community_research', {}).get('records', []):
            add(tr('社区记录'), tr('参考'), entry['id'] + ' · ' +
                levels.get(entry['evidence_level'], tr('来源待核对')) + tr('；非本工具验收，来源见社区研究说明'))

        table.tag_configure('problem', foreground=AMBER)
        full_details = {}
        def explain(_=None):
            selection = table.selection()
            text = tr('没有待处理项目；可取消筛选查看全部检查。')
            if selection:
                item, state, detail = full_details[selection[0]]
                text = item + ' · ' + state + '\n' + detail
            selected.configure(state='normal')
            selected.delete('1.0', 'end')
            selected.insert('1.0', text)
            selected.configure(state='disabled')
        def populate():
            table.delete(*table.get_children())
            full_details.clear()
            for title, state, detail, problem in sorted(rows, key=lambda row: not row[3]):
                if not only_problems.get() or problem:
                    row_id = table.insert('', 'end', values=(title, state, detail.replace('\n', ' ')),
                                          tags=('problem',) if problem else ())
                    full_details[row_id] = (title, state, detail)
            if table.get_children():
                table.selection_set(table.get_children()[0])
            explain()
        filter_button.configure(command=populate)
        table.bind('<<TreeviewSelect>>', explain)
        table.bind('<Double-1>', explain)
        populate()

    def export(self, snapshot=None, running=None):
        result = snapshot if snapshot is not None else self.last_result
        if not result:
            return
        path = filedialog.asksaveasfilename(title=tr('保存脱敏检查报告'), defaultextension='.json', initialfile='bb10-volte-preflight.json', filetypes=[('JSON', '*.json')])
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as file:
                    payload = dict(result)
                    report = result if 'checks' in result else result.get('preflight')
                    if report:
                        payload['desktop_diagnostics'] = {'schema': 1, 'summary': self.diagnostic_text(report, running)}
                    json.dump(payload, file, ensure_ascii=False, indent=2)
                self.activity.configure(text=tr('脱敏报告已保存 · 分享前仍请自行核对内容'))
            except OSError:
                messagebox.showerror(tr('无法保存'), tr('请检查保存路径和写入权限。'), parent=self.root)

    def guide(self):
        self.show_document(tr('使用与恢复指南'), ROOT / 'docs/GUI.md')

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
        intro = ('bb10-volte ' + project['version'] + tr(' · 桌面修订 ') + str(project.get('desktop_revision', 1)) + tr('\n\n'
                 '适用于 BlackBerry 10 设备。当前实机记录：Q10 SQN100-3 / BB10 10.3.3.3216 / 北京联通。\n'
                 '其他设备与运营商需逐台验证。\n\n'))
        self.show_document(tr('关于与开源许可'), path if path.is_file() else ROOT / 'NOTICE.md', intro)

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
        text.insert('1.0', intro + document_path(path).read_text(encoding='utf-8'))
        text.configure(state='disabled')

    def close(self):
        if self.busy:
            messagebox.showinfo(tr('操作进行中'), tr('请等待本次有界操作结束。强行退出不能撤销已经写入手机的步骤。'), parent=self.root)
            return
        self.root.after_cancel(self._drain_job)
        if self._startup_job is not None:
            self.root.after_cancel(self._startup_job)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='bb10-root')
    parser.add_argument('--ssh-config', default='')
    parser.add_argument('--profile-id', choices=[p['id'] for p in presets()],
                        help='Select an explicit carrier preset for a device-specific shortcut')
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
    selected_profile = next((p for p in presets() if p['id'] == args.profile_id), None)
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
            client, _ = resolve_connection(args.host, args.ssh_config, profile=selected_profile)
            report = client.preflight()
            if report['installation']['state'] in ('busy', 'stopped', 'recovery_required'):
                unified = report.get('managed_adapter') == 'unified_carriers'
                status = public_status(report['status'] if unified else client.service('status'))
                ready = unified_status_view(status)['ready'] if unified else registered(status)
                report.update(status=status, registered=ready)
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
    App(root, args.host, args.ssh_config, auto_connect=True, profile=selected_profile)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
