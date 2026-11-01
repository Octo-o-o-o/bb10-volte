"""Local candidate selection; installation remains in the existing workflow."""
import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import uuid
import device_support
import variant_trials
from feedback_gui import help_row
from i18n import tr
from profile_editor import FONT


class VariantTrialDialog(tk.Toplevel):
    def __init__(self, parent, on_check, variant=''):
        super().__init__(parent)
        self.on_check = on_check
        self.title(tr('候选机型本地试测'))
        self.geometry('740x510')
        self.minsize(620, 460)
        self.variant = tk.StringVar(value=variant)
        self.operator = tk.StringVar()
        body = ttk.Frame(self, padding=24)
        body.pack(fill='both', expand=True)
        help_row(body, self, 'trials')
        ttk.Label(body, text=tr('先检查本机条件，再决定能否试用'), font=(FONT, 16, 'bold')).pack(anchor='w')
        ttk.Label(body, text=tr('手机需已有有效 Root。这里只读检查，不会刷机或自动安装。'), wraplength=650).pack(anchor='w', pady=12)
        row = ttk.Frame(body)
        row.pack(fill='x')
        ttk.Label(row, text=tr('手机型号')).grid(row=0, column=0, sticky='w', padx=(0, 18), pady=8)
        ttk.Combobox(row, textvariable=self.variant, values=list(device_support.catalog()), state='readonly', width=24).grid(row=0, column=1)
        ttk.Label(row, text=tr('计划使用的运营商')).grid(row=1, column=0, sticky='w', padx=(0, 18), pady=8)
        self.operators = {device_support.operator_name(x): x for x in ('mobile', 'unicom', 'telecom')}
        ttk.Combobox(row, textvariable=self.operator, values=list(self.operators), state='readonly', width=24).grid(row=1, column=1)
        self.notice = ttk.Label(body, wraplength=650, justify='left')
        self.notice.pack(fill='both', expand=True, pady=18)
        self.notice.bind('<Configure>', lambda event: self.notice.configure(wraplength=max(1, event.width - 4)))
        footer = ttk.Frame(body)
        footer.pack(fill='x', side='bottom')
        ttk.Button(footer, text=tr('导出试测配置与结果表'), command=self.export).pack(side='left')
        ttk.Button(footer, text=tr('关闭'), command=self.destroy).pack(side='right')
        self.check_button = ttk.Button(footer, text=tr('检查本机条件'), command=self.check)
        self.check_button.pack(side='right', padx=12)
        self.variant.trace_add('write', self.refresh)
        self.operator.trace_add('write', self.refresh)
        self.refresh()

    def decision(self):
        return variant_trials.plan(self.variant.get(), self.operators.get(self.operator.get()))

    def refresh(self, *_):
        decision = self.decision()
        route = decision['route']
        if route == 'operator_required' or not self.variant.get():
            text = tr('请选择手机“关于”中的完整后缀和实际使用的运营商。')
        elif route == 'automatic_supported':
            text = tr('此组合已有自动适配入口，请使用主界面的“三网自动适配”。')
        elif route == 'manual_candidate':
            text = tr('这是未实测的手动候选。检查通过并明确选择实验试用后，可先安装，再单独手动启动；不开启自启动。必须先有可用 LTE 数据，试测不会修复基带入网。完成后使用“停用并恢复”并导出报告。')
        elif route == 'read_only_lifecycle_pending':
            text = tr('此 Passport 后缀先提供检查与报告。原生组件停止及恢复尚未验证，当前不会开放安装；请导出型号、原生文件与网络检查结果，供后续适配。')
        else:
            text = device_support.describe(device_support.assess(self.variant.get(), decision['operator']))
        self.notice.configure(text=text)
        self.check_button.configure(state='normal' if route in ('manual_candidate', 'read_only_lifecycle_pending') else 'disabled')

    def check(self):
        decision = self.decision()
        if decision['route'] not in ('manual_candidate', 'read_only_lifecycle_pending'):
            self.refresh()
            return
        profile = variant_trials.profile(decision['variant'], decision['operator'])
        self.destroy()
        self.on_check(profile)

    def export(self):
        destination = filedialog.askdirectory(parent=self, title=tr('导出试测配置与结果表'))
        if not destination:
            return
        folder = Path(destination) / ('bb10-variant-trials-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
        try:
            variant_trials.export(folder)
            messagebox.showinfo(tr('导出试测配置与结果表'), tr('试测材料已保存：{}。没有连接或修改手机。').format(folder), parent=self)
        except (OSError, ValueError):
            messagebox.showerror(tr('无法保存'), tr('请检查保存路径和写入权限。'), parent=self)
