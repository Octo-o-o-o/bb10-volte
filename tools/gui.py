"""Q10 VoLTE Desk: standard-library desktop UI over the fixed workflow."""
import argparse
import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from workflow import Client, ROOT, WorkflowError

BG, INK, MUTED = '#F2F5F9', '#18273F', '#62738B'
BLUE, GREEN, AMBER, RED = '#235BD7', '#137860', '#9A610B', '#BA3C42'
NAMES = {'model': '手机型号', 'os': '系统版本', 'root': 'Root 环境', 'native': '原生文件',
         'sim': 'SIM 就绪', 'carrier': '运营商', 'sim_route': 'SIM 路线', 'identity': '身份格式',
         'lte': '4G 网络', 'apn': '数据 APN', 'installation': '已装服务', 'baseline': '安装前状态'}
NOTES = {
    'q10_sqn100_3_required': '要求 Q10 · SQN100-3', 'os_3216_required': '要求 BB10 OS 10.3.3.3216',
    'root_qnx_arm32_required': '要求 AutoRoot 已就绪、有效 root 和 QNX ARM32',
    'native_hashes_required': '4 个原生文件 SHA-256 必须与验证基线一致',
    'sim_ready': 'SIM 已就绪', 'sim_unavailable': '解锁 SIM 并等待就绪后重试',
    'unicom_46001': '中国联通 460-01；归属省份不作为自动判据',
    'carrier_not_profiled': '此 MCC/MNC 未适配；移动、电信及其他联通 MNC 暂不能安装',
    'usim_without_isim': 'USIM，无 ISIM；符合当前实现',
    'sim_route_not_profiled': '此 SIM 类型需要另行适配，不能套用当前配置',
    'identity_layout_matches': '在手机本地核验通过；报告不包含完整标识',
    'identity_layout_unknown': 'SIM 身份格式不符，需提供脱敏预检报告排查',
    'lte_ready': '无线已开启，当前处于 LTE', 'lte_not_ready': '开启移动网络并等待 LTE',
    'data_apn_ready': '3gnet 已连接', 'data_apn_not_ready': '要求 3gnet 已连接；检查数据服务与 APN',
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
    'invalid_host': 'SSH 别名只能使用字母、数字、点、下划线和短横线。',
    'config_missing': '找不到 SSH 配置文件，请重新选择。',
    'openssh_missing': '缺少 Windows OpenSSH 客户端，请按安装文档准备 ssh 和 scp。',
    'package_mismatch': '安装包与固定清单不一致。请使用完整发布包，不要在客户电脑重新生成清单。',
    'host_key_mismatch': '主机密钥校验失败。核对所选设备和个人 SSH 配置，保留原信任记录。',
    'authentication_failed': 'SSH 身份验证失败。请使用为这台手机准备的个人密钥配置。',
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


class App:
    def __init__(self, root, host='q10-root', config=''):
        self.root, self.events = root, queue.Queue()
        self.busy, self.report, self.last_result = False, None, None
        self.report_connection = None
        self.host = tk.StringVar(value=host)
        default = ROOT / 'private/root-kit/ssh_config'
        self.config = tk.StringVar(value=config or (str(default) if default.is_file() else ''))
        self.ack = tk.BooleanVar()
        root.title('Q10 VoLTE Desk')
        root.geometry('1160x820')
        root.minsize(1030, 760)
        root.configure(bg=BG)
        root.option_add('*Font', ('Microsoft YaHei UI', 10))
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TButton', font=('Microsoft YaHei UI', 10), padding=(12, 9),
                        background='white', foreground=INK, borderwidth=0)
        style.map('TButton', background=[('active', '#E9EFFA'), ('disabled', '#E9EDF3')],
                  foreground=[('disabled', '#98A3B4')])
        style.configure('Accent.TButton', background=BLUE, foreground='white')
        style.map('Accent.TButton', background=[('active', '#194BB7'), ('disabled', '#CCD7ED')],
                  foreground=[('disabled', '#7C8BA7')])
        style.configure('TEntry', padding=8, fieldbackground='white')
        style.configure('TCheckbutton', background=BG, foreground=INK)
        style.configure('Treeview', font=('Microsoft YaHei UI', 9), rowheight=27,
                        background='white', fieldbackground='white', foreground=INK, borderwidth=0)
        style.configure('Treeview.Heading', font=('Microsoft YaHei UI', 9, 'bold'),
                        background='#EDF1F7', foreground=MUTED, padding=7, relief='flat')
        style.map('Treeview', background=[('selected', '#E4EDFF')], foreground=[('selected', INK)])
        style.configure('Horizontal.TProgressbar', background=BLUE, troughcolor='#E2E8F2', borderwidth=0)
        self.build()
        self.host.trace_add('write', self.connection_changed)
        self.config.trace_add('write', self.connection_changed)
        self.ack.trace_add('write', lambda *_: self.refresh_buttons())
        self.root.after(100, self.drain)

    def label(self, parent, text, size=10, fg=INK, bg=None, bold=False, **kwargs):
        return tk.Label(parent, text=text, font=('Microsoft YaHei UI', size, 'bold' if bold else 'normal'),
                        fg=fg, bg=bg or parent.cget('bg'), **kwargs)

    def build(self):
        sidebar = tk.Frame(self.root, bg='#172740', width=178)
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)
        self.label(sidebar, 'Q10', 31, 'white', bold=True).pack(anchor='w', padx=25, pady=(30, 0))
        self.label(sidebar, 'VoLTE DESK', 10, '#AFC6EA', bold=True).pack(anchor='w', padx=27)
        self.label(sidebar, '设备服务工具', 10, '#9BAFCD').pack(anchor='w', padx=27, pady=(8, 35))
        for number, title, detail in [('01', '连接与预检', '确认设备适用条件'),
                                      ('02', '安装与验证', '固定版本 · 回读检查'),
                                      ('03', '通话验收', '手机拨号器实测')]:
            self.label(sidebar, number + '  ' + title, 11, 'white', bold=True).pack(anchor='w', padx=23, pady=(15, 4))
            self.label(sidebar, detail, 9, '#9BAFCD').pack(anchor='w', padx=23)
        footer = tk.Frame(sidebar, bg='#172740')
        footer.pack(side='bottom', fill='x', padx=20, pady=24)
        tk.Button(footer, text='使用与恢复指南  ↗', bg='#223956', fg='white', relief='flat',
                  activebackground='#30496B', activeforeground='white', bd=0, pady=9, command=self.guide).pack(fill='x')
        version = json.loads((ROOT / 'project.json').read_text(encoding='utf-8'))['version']
        self.label(footer, 'v' + version + ' · 实验版本', 9, '#9BAFCD').pack(anchor='w', pady=(17, 5))
        self.label(footer, '单机验证 · 逐台验收', 9, '#9BAFCD').pack(anchor='w')

        main = tk.Frame(self.root, bg=BG)
        main.pack(side='left', fill='both', expand=True, padx=28, pady=22)
        header = tk.Frame(main, bg=BG)
        header.pack(fill='x')
        self.label(header, '让每一步都可核验', 21, bold=True).pack(side='left')
        self.export_button = ttk.Button(header, text='导出脱敏报告', command=self.export, state='disabled')
        self.export_button.pack(side='right')
        self.label(main, 'Q10 SQN100-3  /  BB10 10.3.3.3216  /  联通 460-01 USIM', 9, MUTED).pack(anchor='w', pady=(4, 17))

        summary = tk.Frame(main, bg='white', padx=18, pady=13)
        summary.pack(fill='x')
        self.summary = self.label(summary, '先连接设备，运行兼容性预检', 14, bold=True)
        self.summary.pack(anchor='w')
        self.detail = self.label(summary, '预检不会修改通话配置。初次 Root 请先按指南完成备份和刷写。', 9, MUTED,
                                 wraplength=800, justify='left')
        self.detail.pack(anchor='w', pady=(5, 0))

        connection = tk.Frame(main, bg=BG)
        connection.pack(fill='x', pady=(15, 12))
        connection.columnconfigure(1, weight=1)
        self.label(connection, 'SSH 配置', 9, MUTED).grid(row=0, column=0, sticky='w', padx=(0, 10))
        self.config_entry = ttk.Entry(connection, textvariable=self.config)
        self.config_entry.grid(row=0, column=1, sticky='ew')
        self.browse_button = ttk.Button(connection, text='选择文件', command=self.browse)
        self.browse_button.grid(row=0, column=2, padx=(8, 12))
        self.label(connection, '别名', 9, MUTED).grid(row=0, column=3, padx=(0, 8))
        self.host_entry = ttk.Entry(connection, textvariable=self.host, width=13)
        self.host_entry.grid(row=0, column=4)

        table_frame = tk.Frame(main, bg='white')
        table_frame.pack(fill='both', expand=True)
        self.table = ttk.Treeview(table_frame, columns=('item', 'state', 'detail'), show='headings', selectmode='browse', height=12)
        for col, label, width in [('item', '检查项目', 116), ('state', '结果', 76), ('detail', '说明与下一步（双击查看）', 590)]:
            self.table.heading(col, text=label, anchor='w')
            self.table.column(col, width=width, minwidth=width if col != 'detail' else 300, stretch=col == 'detail')
        scroll = ttk.Scrollbar(table_frame, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.table.pack(fill='both', expand=True)
        for tag, color in [('pass', GREEN), ('wait', AMBER), ('adapt', AMBER), ('block', RED), ('idle', MUTED)]:
            self.table.tag_configure(tag, foreground=color)
        for key, name in NAMES.items():
            self.table.insert('', 'end', iid=key, values=(name, '待检查', '连接后自动读取'), tags=('idle',))
        self.table.bind('<Double-1>', self.explain_row)

        ttk.Checkbutton(main, text='已备份，已确认此卡开通 VoLTE，当前没有通话', variable=self.ack).pack(anchor='w', pady=(13, 8))
        toolbar = tk.Frame(main, bg=BG)
        toolbar.pack(fill='x')
        self.buttons = {}
        for key, text, style in [('preflight', '运行预检', 'TButton'), ('install', '安装并验证', 'Accent.TButton'),
                                 ('start', '启动验证', 'TButton'), ('status', '查看状态', 'TButton'),
                                 ('disable', '停用并恢复', 'TButton')]:
            button = ttk.Button(toolbar, text=text, style=style, command=lambda k=key: self.run(k))
            button.pack(side='left', padx=(0, 8))
            self.buttons[key] = button
        self.progress = ttk.Progressbar(main, mode='indeterminate', length=300)
        self.progress.pack(fill='x', pady=(14, 7))
        self.activity = self.label(main, '就绪 · 仅有北京联通单机实测，其他地区仍需逐台通话验收', 9, MUTED,
                                   wraplength=830, justify='left', anchor='w')
        self.activity.pack(fill='x')
        self.refresh_buttons()

    def connection_changed(self, *_):
        self.report, self.report_connection, self.last_result = None, None, None
        self.summary.configure(text='连接信息已更新，请重新预检', fg=INK)
        self.detail.configure(text='安装按钮将在新连接的检查通过后启用。')
        for row in self.table.get_children():
            self.table.item(row, values=(NAMES[row], '待检查', '连接信息已更新'), tags=('idle',))
        self.refresh_buttons()

    def refresh_buttons(self):
        if not hasattr(self, 'buttons'):
            return
        r = self.report or {}
        owned = r.get('installation', {}).get('state') in ('busy', 'stopped', 'recovery_required')
        allowed = {'preflight': True, 'install': (r.get('can_install') or r.get('can_update')) and self.ack.get(),
                   'start': r.get('can_start') and self.ack.get(), 'status': owned, 'disable': owned and self.ack.get()}
        self.buttons['install'].configure(text='更新并验证' if r.get('can_update') else '安装并验证')
        for key, button in self.buttons.items():
            button.configure(state='normal' if not self.busy and allowed[key] else 'disabled')
        for widget in (self.config_entry, self.host_entry, self.browse_button):
            widget.configure(state='disabled' if self.busy else 'normal')
        self.export_button.configure(state='normal' if self.last_result and not self.busy else 'disabled')

    def browse(self):
        path = filedialog.askopenfilename(title='选择这台手机的 SSH 配置', initialdir=str(ROOT / 'private'), filetypes=[('SSH config', '*')])
        if path:
            self.config.set(path)

    def render_report(self, report):
        self.report = report
        self.report_connection = (self.host.get(), self.config.get())
        for row in self.table.get_children():
            self.table.item(row, values=(NAMES[row], '待检查', '当前无法确认'), tags=('idle',))
        labels = {'pass': '通过', 'wait': '待处理', 'adapt': '需适配', 'block': '不支持'}
        for check in report['checks']:
            key, state = check['id'], check['status']
            if key in NAMES:
                self.table.item(key, values=(NAMES[key], labels[state], NOTES.get(check['code'], check['code'])), tags=(state,))
        outcome = report['outcome']
        title, color = {'compatible': ('符合当前适配条件', GREEN), 'not_ready': ('有条件尚未就绪', AMBER),
                        'needs_adaptation': ('此 SIM 或运营商需要适配', AMBER), 'unsupported': ('不在当前支持范围', RED)}[outcome]
        state = report['installation']['state']
        if state == 'busy':
            detail = '已有服务正在运行或持有锁。更新前请先停用并恢复；本次不会覆盖安装。'
        elif report.get('can_install') or report.get('can_update'):
            detail = '可进入安装流程。运营商开通情况和双向通话效果仍需真实通话确认。'
        elif state in ('conflict', 'interrupted', 'recovery_required'):
            detail = '安装或恢复状态需要处理。请保留现场，按检查表处理后重新预检。'
        else:
            detail = '请处理待处理项目后重试。其他省份尚未实测，预检通过不代表通话验收完成。'
        self.summary.configure(text=title, fg=color)
        self.detail.configure(text=detail)

    def run(self, action):
        if self.busy:
            return
        if action in ('install', 'start', 'disable'):
            if not self.ack.get() or self.report_connection != (self.host.get(), self.config.get()):
                return
            message = ('将停止本项目服务、恢复其修改并关闭自动启动。' if action == 'disable' else
                       '将使用固定版本并重新预检，启用自动启动和 IMS 验证。首次启动可能短暂重载无线网络。')
            if not messagebox.askokcancel('确认设备操作', message + '\n\n请保持 USB 连接，操作期间不要换卡或拨打电话。', parent=self.root):
                return
        mode = 'update' if (self.report or {}).get('can_update') else 'install'
        host, config = self.host.get().strip(), self.config.get().strip()
        self.busy = True
        self.last_result = None
        self.refresh_buttons()
        self.progress.start(12)
        self.summary.configure(text='正在执行，请保持设备连接', fg=BLUE)
        self.detail.configure(text='按固定步骤检查和执行。发生连接中断时会保留实际状态，等待核对。')

        def work():
            try:
                client = Client(host, config or None, lambda phase, state: self.events.put(('progress', (phase, state))))
                result = (client.preflight() if action == 'preflight' else
                          client.install(mode, start=True) if action == 'install' else client.action(action))
                self.events.put(('result', (action, result)))
            except WorkflowError as error:
                self.events.put(('error', (error.code, error.report)))
            except Exception:
                # Do not expose unfiltered errors or SSH output in exported reports.
                self.events.put(('error', ('unexpected_error', None)))
        threading.Thread(target=work, daemon=True).start()

    def drain(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == 'progress':
                    phase, state = payload
                    self.activity.configure(text=PHASES.get(phase, phase) + ' · ' + {'working': '进行中', 'done': '完成', 'pending': '待确认'}[state])
                    continue
                self.busy = False
                self.progress.stop()
                if kind == 'error':
                    code, report = payload
                    if report and 'checks' in report:
                        self.render_report(report)
                    else:
                        self.report, self.report_connection = None, None
                    self.last_result = {'error': code, 'preflight': report if report and 'checks' in report else None}
                    self.summary.configure(text='操作未完成，需要核对', fg=RED)
                    self.detail.configure(text=ERRORS.get(code, '发生异常。请重新预检并保留现场；不要重复覆盖安装。'))
                    self.activity.configure(text='已停止后续步骤 · ' + code)
                else:
                    action, result = payload
                    self.last_result = result
                    report = result if 'checks' in result else result.get('preflight')
                    if report:
                        self.render_report(report)
                    if action != 'preflight':
                        # Every device action invalidates previously enabled mutation buttons.
                        self.report, self.report_connection = None, None
                    if result.get('restored'):
                        self.summary.configure(text='已停用并确认恢复', fg=GREEN)
                        self.detail.configure(text='恢复检查通过。再次安装或更新前，请重新预检。')
                    elif result.get('registration') == 'verified' or result.get('registered'):
                        self.summary.configure(text='IMS 注册通过，待通话验收', fg=GREEN)
                        self.detail.configure(text='请用系统拨号器验证呼入、呼出、双向声音和全程 4G，再完成重启后复测。')
                    elif action in ('install', 'start'):
                        self.summary.configure(text='服务已启动，注册仍待确认', fg=AMBER)
                        self.detail.configure(text='等待窗口已结束。稍后重新预检并查看状态；尚不能判断为安装通话成功。')
                    elif action == 'status':
                        self.summary.configure(text='当前状态：' + result.get('status', {}).get('phase', 'unknown'), fg=INK)
                        self.detail.configure(text='注册判断同时要求管理器、原生进程存活，以及当前 LTE 和 IMS 连接。')
                    self.activity.configure(text='本次操作已结束 · ' + time.strftime('%H:%M:%S') + ' · 报告不含完整 SIM 或设备标识')
                self.refresh_buttons()
        except queue.Empty:
            pass
        self.root.after(100, self.drain)

    def explain_row(self, _):
        rows = self.table.selection()
        if rows:
            item, state, detail = self.table.item(rows[0], 'values')
            messagebox.showinfo(item + ' · ' + state, detail, parent=self.root)

    def export(self):
        if not self.last_result:
            return
        path = filedialog.asksaveasfilename(title='保存脱敏检查报告', defaultextension='.json', initialfile='q10-preflight.json', filetypes=[('JSON', '*.json')])
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as file:
                    json.dump(self.last_result, file, ensure_ascii=False, indent=2)
                self.activity.configure(text='脱敏报告已保存 · 分享前仍请自行核对内容')
            except OSError:
                messagebox.showerror('无法保存', '请检查保存路径和写入权限。', parent=self.root)

    def guide(self):
        popup = tk.Toplevel(self.root)
        popup.title('使用与恢复指南')
        popup.geometry('760x580')
        text = tk.Text(popup, wrap='word', font=('Microsoft YaHei UI', 11), padx=24, pady=20,
                       bg='white', fg=INK, relief='flat')
        bar = ttk.Scrollbar(popup, command=text.yview)
        bar.pack(side='right', fill='y')
        text.configure(yscrollcommand=bar.set)
        text.pack(fill='both', expand=True)
        text.insert('1.0', (ROOT / 'docs/GUI.md').read_text(encoding='utf-8'))
        text.configure(state='disabled')

    def close(self):
        if self.busy:
            messagebox.showinfo('操作进行中', '请等待本次有界操作结束。强行退出不能撤销已经写入手机的步骤。', parent=self.root)
            return
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='q10-root')
    parser.add_argument('--ssh-config', default='')
    args = parser.parse_args()
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
    App(root, args.host, args.ssh_config)
    root.mainloop()


if __name__ == '__main__':
    main()
