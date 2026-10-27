"""Local JSON profile editor; all changes pass the same device-side validator."""
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from workflow import ROOT, profiles


def presets():
    return [profiles.default()] + [profiles.validate(profiles.read_json(str(path)))
                                  for path in sorted((ROOT / 'profiles').glob('*.json'))]


class ProfileEditor(tk.Toplevel):
    def __init__(self, parent, profile, on_apply):
        super().__init__(parent)
        self.title('运营商与运行配置')
        self.geometry('820x800')
        self.minsize(780, 760)
        self.transient(parent)
        self.on_apply = on_apply
        self.fields = {}
        body = ttk.Frame(self, padding=22)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='配置保存在本机；应用后必须重新预检。', font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w')
        ttk.Label(body, text='修改已装配置：先停用恢复 → 更新配置并预检 → 更新安装 → 通话验收。').pack(anchor='w', pady=(8, 15))
        tabs = ttk.Notebook(body)
        tabs.pack(fill='both', expand=True)
        sections = [
            ('运营商', [('id', '档案 ID', None), ('label', '显示名称', None),
                       ('carrier.mcc', 'MCC（3 位）', None), ('carrier.mncs', 'MNC（逗号分隔，保留前导 0）', None),
                       ('carrier.data_apns', '数据 APN（逗号分隔）', None),
                       ('carrier.stock_config', '原厂配置 ID（auto 自动识别）', None),
                       ('carrier.stock_sha256', '原厂配置 SHA-256（可留空）', None)]),
            ('IMS', [('ims.apn', 'IMS APN', None), ('ims.ip_family', 'IP 类型', ['IPv4v6', 'IPv4', 'IPv6']),
                     ('ims.home_domain', 'IMS 域名（auto 从实际 SIM 推导）', None),
                     ('ims.sms', '向网络声明 SMS 能力（需单独实测）', 'bool')]),
            ('运行选项', [('runtime.sim_wait_seconds', 'SIM / LTE 等待（30–900 秒）', None),
                          ('runtime.ims_apn_wait_seconds', 'IMS APN 等待（10–180 秒）', None),
                          ('runtime.existing_ims_wait_seconds', '原生 IMS 退出等待（10–600 秒）', None),
                          ('runtime.registration_wait_seconds', '桌面注册验证等待（30–900 秒）', None),
                          ('runtime.poll_seconds', '检查间隔（1–10 秒）', None),
                          ('runtime.autostart', '安装后随手机开机自动启动', 'bool')])]
        for title, fields in sections:
            frame = ttk.Frame(tabs, padding=18)
            tabs.add(frame, text=title)
            frame.columnconfigure(1, weight=1)
            for row, (key, label, kind) in enumerate(fields):
                variable = tk.BooleanVar() if kind == 'bool' else tk.StringVar()
                self.fields[key] = variable
                if kind == 'bool':
                    ttk.Checkbutton(frame, text=label, variable=variable).grid(row=row, column=0, columnspan=2, sticky='w', pady=12)
                else:
                    ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', padx=(0, 12), pady=10)
                    widget = (ttk.Combobox(frame, textvariable=variable, values=kind, state='readonly') if kind else
                              ttk.Entry(frame, textvariable=variable))
                    widget.grid(row=row, column=1, sticky='ew', pady=8)
        note = ttk.Label(body, text='P-CSCF 由网络 PCO 下发；身份从手机本地 SIM 读取。当前仅支持无 ISIM 的 USIM。\n'
                  '系统版本、ARM32 和原生文件校验始终生效。实验试用不代表已验证通话。',
                  wraplength=710, justify='left')
        note.pack(anchor='w', pady=16)
        footer = ttk.Frame(body)
        footer.pack(fill='x')
        ttk.Button(footer, text='导入 JSON', command=self.import_json).pack(side='left')
        ttk.Button(footer, text='导出 JSON', command=self.export_json).pack(side='left', padx=10)
        ttk.Button(footer, text='应用配置', style='Accent.TButton', command=self.apply).pack(side='right')
        ttk.Button(footer, text='取消', command=self.destroy).pack(side='right', padx=10)
        # Reserve the action row before allocating the expanding notebook.
        tabs.pack_forget()
        footer.pack_configure(side='bottom')
        note.pack_configure(side='bottom')
        tabs.pack(fill='both', expand=True)
        self.populate(profile)
        self.grab_set()

    def populate(self, profile):
        p = profiles.validate(profile)
        for key, variable in self.fields.items():
            section, _, field = key.partition('.')
            value = p[section][field] if field else p[section]
            variable.set(', '.join(value) if isinstance(value, list) else value)

    def value(self):
        p = profiles.default()
        for key, variable in self.fields.items():
            section, _, field = key.partition('.')
            value = variable.get()
            if isinstance(value, str):
                value = value.strip()
            if key in ('carrier.mncs', 'carrier.data_apns'):
                value = [item.strip() for item in value.split(',')]
            elif section == 'runtime' and field != 'autostart':
                value = int(value)
            if field:
                p[section][field] = value
            else:
                p[section] = value
        return profiles.validate(p)

    def checked_value(self):
        try:
            return self.value()
        except (ValueError, TypeError) as error:
            messagebox.showerror('配置未通过校验', str(error), parent=self)
            return None

    def apply(self):
        p = self.checked_value()
        if p is not None:
            self.on_apply(p)
            self.destroy()

    def import_json(self):
        path = filedialog.askopenfilename(parent=self, title='导入运营商配置', filetypes=[('JSON', '*.json')])
        if path:
            try:
                self.populate(profiles.read_json(path))
            except (OSError, ValueError, TypeError) as error:
                messagebox.showerror('无法导入', str(error), parent=self)

    def export_json(self):
        p = self.checked_value()
        if p is None:
            return
        path = filedialog.asksaveasfilename(parent=self, title='保存运营商配置', defaultextension='.json',
                                          initialfile=p['id'] + '.json', filetypes=[('JSON', '*.json')])
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as output:
                    json.dump(p, output, ensure_ascii=False, indent=2)
                    output.write('\n')
            except OSError as error:
                messagebox.showerror('无法保存', str(error), parent=self)
