"""Local JSON profile editor; all changes pass the same device-side validator."""
from i18n import tr
import json
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from workflow import ROOT, profiles

FONT = 'PingFang SC' if sys.platform == 'darwin' else 'Microsoft YaHei UI'
LEGACY_BASELINE_LABEL = profiles.default()['label']
BB10_BASELINE_LABEL = tr('中国联通 460-01 / BB10（Q10 已验证）')
ATTACH_MODES = {'standard': tr('保持现有入网策略'),
                'telecom_data_centric_v1': tr('电信 460-11 数据优先（Q10 试用）')}


def display_label(label):
    # Translate only known built-ins; preserve arbitrary user-authored labels.
    return {LEGACY_BASELINE_LABEL: BB10_BASELINE_LABEL,
            'China Unicom 01/09 - untested template': tr('中国联通（试用模板）'),
            'China Mobile - untested template': tr('中国移动（试用模板）'),
            'China Telecom 460-11 / Q10 manual port': tr('中国电信 460-11（Q10 手动移植待验收）'),
            'China Telecom - untested template': tr('中国电信（试用模板）')}.get(label, label)


def picker_label(label):
    return {LEGACY_BASELINE_LABEL: tr('中国联通 460-01'),
            'China Unicom 01/09 - untested template': tr('中国联通（试用模板）'),
            'China Mobile - untested template': tr('中国移动（试用模板）'),
            'China Telecom 460-11 / Q10 manual port': tr('中国电信 460-11（Q10 手动移植待验收）'),
            'China Telecom - untested template': tr('中国电信（试用模板）')}.get(label, display_label(label))


def stored_label(label, original):
    if label == display_label(original):
        return original
    return label


def presets():
    return [profiles.default()] + [profiles.validate(profiles.read_json(str(path)))
                                  for path in sorted((ROOT / 'profiles').glob('*.json'))]


def profile_error_message(error):
    """Present validator errors in the UI language without changing its protocol."""
    message = str(error)
    if message.startswith('Invalid profile field: '):
        return tr('配置字段无效：{}').format(message[len('Invalid profile field: '):])
    if isinstance(error, json.JSONDecodeError):
        return tr('配置不是有效的 JSON 文件。')
    if message.startswith('invalid literal for int()'):
        return tr('请输入有效的整数。')
    if isinstance(error, OSError):
        return tr('请检查文件路径和访问权限。')
    return tr('配置无效，请检查文件和参数。')


class ProfileEditor(tk.Toplevel):
    def __init__(self, parent, profile, on_apply):
        super().__init__(parent)
        self.title(tr('运营商与运行配置'))
        self.geometry('820x700')
        self.minsize(780, 660)
        self.transient(parent)
        self.on_apply = on_apply
        self.fields = {}
        body = ttk.Frame(self, padding=22)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=tr('自定义配置'), font=(FONT, 14, 'bold')).pack(anchor='w')
        ttk.Label(body, text=tr('应用配置后需重新检查设备。')).pack(anchor='w', pady=(6, 15))
        tabs = ttk.Notebook(body)
        tabs.pack(fill='both', expand=True)
        sections = [
            (tr('运营商'), [('label', tr('显示名称'), None),
                       ('carrier.mcc', tr('MCC（3 位）'), None), ('carrier.mncs', tr('MNC（逗号分隔，保留前导 0）'), None),
                       ('carrier.data_apns', tr('数据 APN（逗号分隔）'), None)]),
            ('IMS', [('ims.apn', 'IMS APN', None), ('ims.ip_family', tr('IP 类型'), ['IPv4v6', 'IPv4', 'IPv6']),
                     ('ims.home_domain', tr('IMS 域名（auto 从实际 SIM 推导）'), None),
                     ('ims.sms', tr('向网络声明 SMS 能力（需单独实测）'), 'bool')]),
            (tr('运行选项'), [('runtime.sim_wait_seconds', tr('SIM / LTE 等待（30–900 秒）'), None),
                          ('lte_attach', tr('电信入网前置流程'), list(ATTACH_MODES.values())),
                          ('runtime.ims_apn_wait_seconds', tr('IMS APN 等待（10–180 秒）'), None),
                          ('runtime.existing_ims_wait_seconds', tr('原生 IMS 退出等待（10–600 秒）'), None),
                          ('runtime.registration_wait_seconds', tr('桌面注册验证等待（30–900 秒）'), None),
                          ('runtime.poll_seconds', tr('检查间隔（1–10 秒）'), None),
                          ('runtime.autostart', tr('安装后随手机开机自动启动'), 'bool')]),
            (tr('高级'), [('id', tr('档案 ID'), None),
                      ('carrier.stock_config', tr('原厂配置 ID（auto 自动识别）'), None),
                      ('carrier.stock_sha256', tr('原厂配置 SHA-256（可留空）'), None)])]
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
        footer = ttk.Frame(body)
        footer.pack(fill='x', pady=(16, 0))
        ttk.Button(footer, text=tr('导入配置'), command=self.import_json).pack(side='left')
        ttk.Button(footer, text=tr('导出配置'), command=self.export_json).pack(side='left', padx=10)
        ttk.Button(footer, text=tr('应用配置'), style='Accent.TButton', command=self.apply).pack(side='right')
        ttk.Button(footer, text=tr('取消'), command=self.destroy).pack(side='right', padx=10)
        # Reserve the action row before allocating the expanding notebook.
        tabs.pack_forget()
        footer.pack_configure(side='bottom')
        tabs.pack(fill='both', expand=True)
        self.populate(profile)
        self.grab_set()

    def populate(self, profile):
        p = profiles.validate(profile)
        self.original_label = p['label']
        for key, variable in self.fields.items():
            section, _, field = key.partition('.')
            value = p[section][field] if field else p.get(section, 'standard') if key == 'lte_attach' else p[section]
            if key == 'label':
                value = display_label(value)
            elif key == 'lte_attach':
                value = ATTACH_MODES[value]
            variable.set(', '.join(value) if isinstance(value, list) else value)

    def value(self):
        p = profiles.default()
        for key, variable in self.fields.items():
            section, _, field = key.partition('.')
            value = variable.get()
            if isinstance(value, str):
                value = value.strip()
            if key == 'label':
                value = stored_label(value, self.original_label)
            elif key == 'lte_attach':
                value = next(k for k, v in ATTACH_MODES.items() if value == v)
            if key in ('carrier.mncs', 'carrier.data_apns'):
                value = [item.strip() for item in value.split(',')]
            elif section == 'runtime' and field != 'autostart':
                value = int(value)
            if field:
                p[section][field] = value
            else:
                p[section] = value
        if p.get('lte_attach') == 'standard':
            del p['lte_attach']
        return profiles.validate(p)

    def checked_value(self):
        try:
            return self.value()
        except (ValueError, TypeError) as error:
            messagebox.showerror(tr('配置未通过校验'), profile_error_message(error), parent=self)
            return None

    def apply(self):
        p = self.checked_value()
        if p is not None:
            self.on_apply(p)
            self.destroy()

    def import_json(self):
        path = filedialog.askopenfilename(parent=self, title=tr('导入运营商配置'), filetypes=[('JSON', '*.json')])
        if path:
            try:
                self.populate(profiles.read_json(path))
            except (OSError, ValueError, TypeError) as error:
                messagebox.showerror(tr('无法导入'), profile_error_message(error), parent=self)

    def export_json(self):
        p = self.checked_value()
        if p is None:
            return
        path = filedialog.asksaveasfilename(parent=self, title=tr('保存运营商配置'), defaultextension='.json',
                                          initialfile=p['id'] + '.json', filetypes=[('JSON', '*.json')])
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as output:
                    json.dump(p, output, ensure_ascii=False, indent=2)
                    output.write('\n')
            except OSError as error:
                messagebox.showerror(tr('无法保存'), profile_error_message(error), parent=self)
