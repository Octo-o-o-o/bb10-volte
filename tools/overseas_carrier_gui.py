"""Modal dialog for explicit overseas / custom carrier trial configuration."""
import json
from pathlib import Path
import queue
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from connection_flow import guidance
from i18n import tr
import device_support
from mac_help import scrolled_page
import overseas_carrier
import profiles
from profile_editor import FONT

CONNECTION_ERROR_CODES = (
    'connection_setup_required', 'hostname_unresolved', 'config_missing',
    'authentication_failed', 'host_key_mismatch', 'connection_refused',
    'connection_failed', 'connection_timeout_state_unknown',
    'openssh_missing', 'bundled_ssh_mismatch', 'ssh_algorithm_mismatch',
)


def should_show_overseas_banner(report):
    """Show the overseas banner ONLY for non-460 SIMs or an active overseas trial.

    Mainland China (460-*) users without an active experimental override never
    see this banner, preserving the 1-click zero-clutter workflow.
    """
    if not isinstance(report, dict) or report.get('scope_error'):
        return False
    if report.get('exp_trial_active') is True:
        return True
    plmn = report.get('sim_plmn')
    if isinstance(plmn, str) and '-' in plmn:
        return not plmn.startswith('460-')
    return False


def overseas_banner_text(report):
    plmn = (report or {}).get('sim_plmn') or ''
    if report and report.get('exp_trial_active') is True:
        summary = report.get('exp_trial_summary') or {}
        plmns = ', '.join(summary.get('plmns') or ()) or plmn or '—'
        return tr('已启用海外 / 自定义试测配置（{}）。可调整参数或清除配置。').format(plmns)
    matched = overseas_carrier.lookup_plmn_code(plmn) if plmn else None
    if matched is not None:
        return tr('检测到海外 SIM（{} · {}），可套用离线参考参数或自定义 APN / ISIM 进行实验试测（尚未在 BB10 实机验收）。').format(
            plmn, matched.get('name', ''))
    if plmn:
        return tr('检测到海外 / 其他运营商 SIM（{}），可配置自定义 APN / ISIM / 0.xml 参数进行实验试测（尚未在 BB10 实机验收）。').format(plmn)
    return tr('当前 SIM 未命中自动模板，可配置海外 / 自定义实验参数后重新检查。')


def _friendly_validation_error(exc):
    text = str(exc)
    if text.startswith('Invalid experimental trial field:'):
        field = text.split(':', 1)[1].strip()
        return tr('配置字段无效：{}。请核对 MCC（3 位数字）、MNC（2–3 位，排除 460-15）与 APN 格式。').format(field)
    return text


class OverseasCarrierDialog(tk.Toplevel):
    def __init__(self, parent, client_factory, probe_report=None, on_saved=None):
        super().__init__(parent)
        self.title(tr('海外 / 自定义运营商设置（实验试测）'))
        self.geometry('880x680')
        self.minsize(860, 600)
        self.transient(parent)
        self.client_factory = client_factory
        self.probe_report = dict(probe_report or {})
        self.on_saved = on_saved
        self.events = queue.Queue()
        self.busy = False
        self._extra_carriers = []
        self._form_widgets = []
        self._readonly_widgets = []
        self._service_running = bool((self.probe_report.get('status') or {}).get('manager_alive'))
        self._update_needed = bool(self.probe_report.get('update_available'))
        self.catalog = overseas_carrier.load_catalog()
        self.filtered_catalog = list(self.catalog)

        self.search_var = tk.StringVar()
        self.preset_var = tk.StringVar()
        self.label_var = tk.StringVar()
        self.mcc_var = tk.StringVar()
        self.mncs_var = tk.StringVar()
        self.data_apns_var = tk.StringVar(value='auto')
        self.ims_apn_var = tk.StringVar(value='ims')
        self.ip_family_var = tk.StringVar(value='IPv4v6')
        self.home_domain_var = tk.StringVar(value='auto')
        self.sms_var = tk.BooleanVar(value=True)
        self.allow_isim_var = tk.BooleanVar(value=bool(self.probe_report.get('sim_has_isim')))
        self.allow_0xml_var = tk.BooleanVar(value=True)
        self.always_on_var = tk.BooleanVar(value=True)
        self.sig_pco_var = tk.BooleanVar(value=False)
        self.disable_dad_var = tk.BooleanVar(value=False)
        self.stock_config_var = tk.StringVar(value='auto')
        self.ue_usage_var = tk.StringVar(value='auto')
        self.use_precond_var = tk.StringVar(value='')
        self.sms_format_var = tk.StringVar(value='')
        self.amr_var = tk.StringVar()
        self.amrwb_var = tk.StringVar()
        self.silent_redial_var = tk.StringVar(value='')
        self.sip_csfb_var = tk.StringVar()
        self.ipsec_var = tk.StringVar(value='')
        self.sip_transport_var = tk.StringVar(value='')
        self.reg_exp_var = tk.StringVar()

        body = ttk.Frame(self, padding=16)
        body.pack(fill='both', expand=True)

        # Reserve bottom controls and status BEFORE expanding notebook tabs so
        # buttons are never clipped at the minimum window size in zh or en.
        btn_row = ttk.Frame(body)
        btn_row.pack(side='bottom', fill='x')
        self.import_btn = ttk.Button(btn_row, text=tr('导入 JSON…'), command=self._import_json)
        self.import_btn.pack(side='left', padx=(0, 6))
        self.export_btn = ttk.Button(btn_row, text=tr('导出 JSON…'), command=self._export_json)
        self.export_btn.pack(side='left', padx=(0, 6))
        self.clear_btn = ttk.Button(btn_row, text=tr('清除手机端海外配置'), command=self._clear_on_phone)
        self.clear_btn.pack(side='left', padx=(0, 6))
        self.close_btn = ttk.Button(btn_row, text=tr('关闭'), command=self._close)
        self.close_btn.pack(side='right')
        self.save_btn = ttk.Button(btn_row, text=tr('保存并重新检查'), style='Accent.TButton', command=self._save_to_phone)
        self.save_btn.pack(side='right', padx=(0, 8))

        self.status_label = ttk.Label(body, text='', wraplength=800, justify='left')
        self.status_label.pack(side='bottom', anchor='w', fill='x', pady=(6, 8))

        ttk.Label(body, text=tr('海外 / 自定义运营商设置（实验试测）'), font=(FONT, 15, 'bold')).pack(anchor='w')
        ttk.Label(
            body,
            text=tr('参考参数来自公开 Apache-2.0 运营商列表，尚未在 BB10 实机验收，不保证在所有网络可用。写入手机前会先经过严格校验与管理锁保护。'),
            wraplength=800, justify='left',
        ).pack(anchor='w', pady=(4, 6))

        self.sim_info = ttk.Label(body, text=self._format_sim_summary(), wraplength=800, justify='left')
        self.sim_info.pack(anchor='w', pady=(0, 6))

        self.extra_carriers_label = ttk.Label(body, text='', wraplength=800, justify='left', foreground='#9A610B')

        # Offline Apache-2.0 catalog picker
        preset_frame = ttk.LabelFrame(body, text=tr('离线海外运营商参考库（Apache-2.0，共 {} 项）').format(len(self.catalog)), padding=8)
        preset_frame.pack(fill='x', pady=(0, 8))
        search_row = ttk.Frame(preset_frame)
        search_row.pack(fill='x', pady=(0, 6))
        ttk.Label(search_row, text=tr('搜索国家 / 运营商 / PLMN')).pack(side='left', padx=(0, 8))
        self.search_entry = ttk.Entry(search_row, textvariable=self.search_var)
        self.search_entry.pack(side='left', fill='x', expand=True)
        self._form_widgets.append(self.search_entry)
        self.search_var.trace_add('write', self._filter_catalog)

        pick_row = ttk.Frame(preset_frame)
        pick_row.pack(fill='x')
        self.preset_combo = ttk.Combobox(pick_row, textvariable=self.preset_var, state='readonly')
        self.preset_combo.pack(side='left', fill='x', expand=True, padx=(0, 8))
        self._readonly_widgets.append(self.preset_combo)
        self.apply_preset_btn = ttk.Button(pick_row, text=tr('套用参考参数'), command=self._apply_selected_preset)
        self.apply_preset_btn.pack(side='right')

        tabs = ttk.Notebook(body)
        tabs.pack(fill='both', expand=True, pady=(0, 4))
        basic_page, basic = scrolled_page(tabs, padding=12)
        adv_page, advanced = scrolled_page(tabs, padding=12)
        tabs.add(basic_page, text=tr('基本参数'))
        tabs.add(adv_page, text=tr('高级参数（可选）'))

        basic.columnconfigure(1, weight=1)
        row = 0
        for label_text, var in (
            (tr('配置名称（可选）'), self.label_var),
            (tr('MCC（3 位）'), self.mcc_var),
            (tr('MNC（逗号分隔，保留前导 0）'), self.mncs_var),
            (tr('数据 APN（逗号分隔，可写 auto）'), self.data_apns_var),
            (tr('IMS APN'), self.ims_apn_var),
        ):
            ttk.Label(basic, text=label_text).grid(row=row, column=0, sticky='w', pady=4, padx=(0, 10))
            entry_w = ttk.Entry(basic, textvariable=var)
            entry_w.grid(row=row, column=1, sticky='ew', pady=4)
            self._form_widgets.append(entry_w)
            row += 1
        ttk.Label(basic, text=tr('IMS IP 类型')).grid(row=row, column=0, sticky='w', pady=4, padx=(0, 10))
        ip_combo = ttk.Combobox(basic, textvariable=self.ip_family_var, values=('IPv4v6', 'IPv4', 'IPv6'),
                                state='readonly', width=14)
        ip_combo.grid(row=row, column=1, sticky='w', pady=4)
        self._readonly_widgets.append(ip_combo)
        row += 1
        for text_lbl, var in (
            (tr('向网络声明 IMS 短信能力'), self.sms_var),
            (tr('允许 ISIM 卡实验试测（仅限当前配置 PLMN）'), self.allow_isim_var),
            (tr('允许回落原厂 0.xml 模板（缺少专用 XML 或仅旧配置时）'), self.allow_0xml_var),
        ):
            chk = ttk.Checkbutton(basic, text=text_lbl, variable=var)
            chk.grid(row=row, column=0, columnspan=2, sticky='w', pady=3)
            self._form_widgets.append(chk)
            row += 1

        advanced.columnconfigure(1, weight=1)
        arow = 0
        for text_lbl, var in (
            (tr('IMS 归属域（auto 自动推导）'), self.home_domain_var),
            (tr('原厂配置模板（auto / 0 / 数字 ID）'), self.stock_config_var),
        ):
            ttk.Label(advanced, text=text_lbl).grid(row=arow, column=0, sticky='w', pady=3, padx=(0, 10))
            ew = ttk.Entry(advanced, textvariable=var)
            ew.grid(row=arow, column=1, sticky='ew', pady=3)
            self._form_widgets.append(ew)
            arow += 1
        ttk.Label(advanced, text=tr('UE 用途模式（默认 auto 不修改）')).grid(row=arow, column=0, sticky='w', pady=3, padx=(0, 10))
        ue_combo = ttk.Combobox(advanced, textvariable=self.ue_usage_var, values=('auto', 'voice_centric', 'data_centric'),
                                state='readonly', width=18)
        ue_combo.grid(row=arow, column=1, sticky='w', pady=3)
        self._readonly_widgets.append(ue_combo)
        arow += 1
        for text_lbl, var in (
            (tr('IMS 承载 AlwaysOn（关闭时不阻塞等待 IMS APN）'), self.always_on_var),
            (tr('通过 PCO 请求信令承载（RequestSignallingBearerViaPCO）'), self.sig_pco_var),
            (tr('禁用 IPv6 重复地址检测（DisableDAD）'), self.disable_dad_var),
        ):
            chk = ttk.Checkbutton(advanced, text=text_lbl, variable=var)
            chk.grid(row=arow, column=0, columnspan=2, sticky='w', pady=2)
            self._form_widgets.append(chk)
            arow += 1
        for text_lbl, var, vals in (
            (tr('IR.92 UsePreconditions（留空不改）'), self.use_precond_var, ('', 'false', 'true')),
            (tr('IR.92 SMS_Format（留空不改）'), self.sms_format_var, ('', '3GPP', '3GPP2')),
        ):
            ttk.Label(advanced, text=text_lbl).grid(row=arow, column=0, sticky='w', pady=3, padx=(0, 10))
            cb = ttk.Combobox(advanced, textvariable=var, values=vals, state='readonly', width=12)
            cb.grid(row=arow, column=1, sticky='w', pady=3)
            self._readonly_widgets.append(cb)
            arow += 1
        for text_lbl, var in (
            (tr('IR.92 AMR Modeset（留空不改，如 0,2,4,7）'), self.amr_var),
            (tr('IR.92 AMR-WB Modeset（留空不改，如 0,1,2）'), self.amrwb_var),
        ):
            ttk.Label(advanced, text=text_lbl).grid(row=arow, column=0, sticky='w', pady=3, padx=(0, 10))
            ew = ttk.Entry(advanced, textvariable=var)
            ew.grid(row=arow, column=1, sticky='ew', pady=3)
            self._form_widgets.append(ew)
            arow += 1
        for text_lbl, var, vals in (
            (tr('IMS SilentRedial（留空不改）'), self.silent_redial_var, ('', 'true', 'false')),
            (tr('IMS IPsec（留空不改）'), self.ipsec_var, ('', 'true', 'false')),
            (tr('IMS SIP_transport（留空不改）'), self.sip_transport_var, ('', 'UDP', 'TCP', 'TLS')),
        ):
            ttk.Label(advanced, text=text_lbl).grid(row=arow, column=0, sticky='w', pady=3, padx=(0, 10))
            cb = ttk.Combobox(advanced, textvariable=var, values=vals, state='readonly', width=12)
            cb.grid(row=arow, column=1, sticky='w', pady=3)
            self._readonly_widgets.append(cb)
            arow += 1
        for text_lbl, var in (
            (tr('IMS SIP_Timer_CSFB（秒，0–120，留空不改）'), self.sip_csfb_var),
            (tr('IMS RegExpiration（秒，60–86400，留空不改）'), self.reg_exp_var),
        ):
            ttk.Label(advanced, text=text_lbl).grid(row=arow, column=0, sticky='w', pady=3, padx=(0, 10))
            ew = ttk.Entry(advanced, textvariable=var)
            ew.grid(row=arow, column=1, sticky='ew', pady=3)
            self._form_widgets.append(ew)
            arow += 1

        self._prefill_from_probe()
        self._filter_catalog()
        self._refresh_action_states()
        if self._service_running:
            self.status_label.configure(
                text=tr('VoLTE 后台服务正在运行。请先停用自动适配并等待恢复完成，再保存或清除海外运营商配置。'))
        elif self._update_needed:
            self.status_label.configure(
                text=tr('检测到手机端 VoLTE 后台可更新。保存海外配置后请按提示更新自动适配并重启。'))
        self.protocol('WM_DELETE_WINDOW', self._close)
        self._poll_job = self.after(120, self._poll)
        self.grab_set()
        if self.probe_report.get('exp_trial_active') is not False or not self.probe_report.get('sim_plmn'):
            self._load_existing_from_phone()

    def _format_sim_summary(self):
        plmn = self.probe_report.get('sim_plmn') or tr('未知')
        isim = tr('是') if self.probe_report.get('sim_has_isim') is True else tr('否') if self.probe_report.get('sim_has_isim') is False else tr('未知')
        xml_name = self.probe_report.get('preloaded_carrier_config') or tr('无 / 0.xml')
        raw_apn = self.probe_report.get('observed_data_apn') or ''
        apn = tr('其他 APN') if raw_apn == 'other' else (tr('未读到') if raw_apn in ('', 'unknown') else raw_apn)
        summary = tr('当前手机检测：SIM PLMN={} · ISIM={} · 原厂模板={} · 实测数据 APN={}').format(plmn, isim, xml_name, apn)
        if self.probe_report.get('lte_bands_disabled') is True:
            summary += ' · ' + tr('LTE 频段能力位图为 0')
        elif self.probe_report.get('radio_lte') is False:
            summary += ' · ' + tr('当前非 LTE')
        return summary

    def _update_extra_carriers_indicator(self):
        if self._extra_carriers:
            plmns = [item.get('mcc', '') + '-' + mnc
                     for item in self._extra_carriers for mnc in (item.get('mncs') or ())]
            self.extra_carriers_label.configure(
                text=tr('保存时将一并保留其他 {} 项海外配置：{}').format(len(self._extra_carriers), ', '.join(plmns[:8])))
            if not self.extra_carriers_label.winfo_manager():
                self.extra_carriers_label.pack(anchor='w', after=self.sim_info, pady=(0, 6))
        elif self.extra_carriers_label.winfo_manager():
            self.extra_carriers_label.pack_forget()

    def _prefill_from_probe(self):
        plmn = self.probe_report.get('sim_plmn') or ''
        matched = overseas_carrier.lookup_plmn_code(plmn) if plmn else None
        if matched is not None:
            cfg = overseas_carrier.preset_to_trial_config(
                matched,
                allow_isim=bool(self.probe_report.get('sim_has_isim')),
                allow_stock_default_xml=True,
                observed_apn=self.probe_report.get('observed_data_apn'),
            )
            self._load_config_into_form(cfg)
            return
        if '-' in plmn and not plmn.startswith('460-'):
            mcc, mnc = plmn.split('-', 1)
            self.mcc_var.set(mcc)
            self.mncs_var.set(mnc)
            apns = ['auto']
            obs = overseas_carrier.usable_observed_apn(self.probe_report.get('observed_data_apn'))
            if obs:
                apns.append(obs)
            self.data_apns_var.set(', '.join(apns))

    def _filter_catalog(self, *_):
        self.filtered_catalog = overseas_carrier.search_catalog(self.search_var.get())
        labels = [overseas_carrier.format_catalog_entry(item) for item in self.filtered_catalog]
        self.preset_combo.configure(values=labels)
        plmn = self.probe_report.get('sim_plmn') or ''
        selected_idx = 0
        for idx, item in enumerate(self.filtered_catalog):
            if item.get('plmn') == plmn:
                selected_idx = idx
                break
        if labels:
            self.preset_combo.current(selected_idx)
        else:
            self.preset_var.set('')

    def _apply_selected_preset(self):
        idx = self.preset_combo.current()
        if idx < 0 or idx >= len(self.filtered_catalog):
            return
        entry = self.filtered_catalog[idx]
        sim_plmn = self.probe_report.get('sim_plmn') or ''
        observed = self.probe_report.get('observed_data_apn') if entry.get('plmn') == sim_plmn else None
        cfg = overseas_carrier.preset_to_trial_config(
            entry,
            allow_isim=bool(self.allow_isim_var.get()),
            allow_stock_default_xml=bool(self.allow_0xml_var.get()),
            observed_apn=observed,
        )
        # Preserve non-overlapping extra carriers from multi-carrier configs.
        preserved = []
        target_pair = (entry.get('mcc'), entry.get('mnc'))
        for extra in self._extra_carriers:
            mncs = [m for m in (extra.get('mncs') or ()) if (extra.get('mcc'), m) != target_pair]
            if mncs:
                item = dict(extra)
                item['mncs'] = mncs
                preserved.append(item)
        self._load_config_into_form(cfg, preserve_extra=preserved)
        self.status_label.configure(text=tr('已套用 {} 参考参数；请核对后点击“保存并重新检查”。').format(entry.get('plmn', '')))

    def _load_config_into_form(self, cfg, preserve_extra=None):
        entries = profiles.exp_trial_entries(cfg)
        if not entries:
            return
        sim_plmn = self.probe_report.get('sim_plmn') or ''
        pick_idx = 0
        if '-' in sim_plmn:
            sim_mcc, sim_mnc = sim_plmn.split('-', 1)
            for idx, item in enumerate(entries):
                if item.get('mcc') == sim_mcc and sim_mnc in (item.get('mncs') or ()):
                    pick_idx = idx
                    break
        if preserve_extra is not None:
            self._extra_carriers = list(preserve_extra)
        else:
            self._extra_carriers = [dict(item) for i, item in enumerate(entries) if i != pick_idx]
        self._update_extra_carriers_indicator()
        first = entries[pick_idx]
        self.label_var.set(first.get('label', ''))
        self.mcc_var.set(first.get('mcc', ''))
        self.mncs_var.set(', '.join(first.get('mncs') or ()))
        self.data_apns_var.set(', '.join(first.get('data_apns') or ('auto',)))
        ims = first.get('ims') or {}
        self.ims_apn_var.set(ims.get('apn', 'ims'))
        self.ip_family_var.set(ims.get('ip_family', 'IPv4v6'))
        self.home_domain_var.set(ims.get('home_domain', 'auto'))
        self.sms_var.set(bool(ims.get('sms', True)))
        self.allow_isim_var.set(bool(first.get('allow_isim', False)))
        self.allow_0xml_var.set(bool(first.get('allow_stock_default_xml', True)))
        self.stock_config_var.set(first.get('stock_config', 'auto'))
        self.ue_usage_var.set(first.get('ue_usage', 'auto'))
        self.always_on_var.set(bool(ims.get('always_on', True)))
        self.sig_pco_var.set(bool(ims.get('request_signalling_bearer_via_pco', False)))
        self.disable_dad_var.set(bool(ims.get('disable_dad', False)))
        ir92 = ims.get('ir92') or {}
        if 'UsePreconditions' not in ir92:
            self.use_precond_var.set('')
        else:
            self.use_precond_var.set('true' if bool(ir92['UsePreconditions']) else 'false')
        self.sms_format_var.set(ir92.get('SMS_Format', ''))
        self.amr_var.set(ir92.get('amr_modeset_list', ''))
        self.amrwb_var.set(ir92.get('amrwb_modeset_list', ''))
        ims_pps = ims.get('ims_pps') or {}
        self.silent_redial_var.set('' if 'SilentRedial' not in ims_pps else ('true' if ims_pps['SilentRedial'] else 'false'))
        self.sip_csfb_var.set('' if 'SIP_Timer_CSFB' not in ims_pps else str(ims_pps['SIP_Timer_CSFB']))
        self.ipsec_var.set('' if 'IPsec' not in ims_pps else ('true' if ims_pps['IPsec'] else 'false'))
        self.sip_transport_var.set(ims_pps.get('SIP_transport', ''))
        self.reg_exp_var.set('' if 'RegExpiration' not in ims_pps else str(ims_pps['RegExpiration']))

    def build_config_from_form(self):
        mncs = [item.strip() for item in re.split(r'[,，]', self.mncs_var.get()) if item.strip()]
        apns = [item.strip() for item in re.split(r'[,，]', self.data_apns_var.get()) if item.strip()]
        ir92 = {}
        precond = self.use_precond_var.get().strip().lower()
        if precond in ('false', 'true', '0', '1'):
            ir92['UsePreconditions'] = precond in ('true', '1')
        if self.sms_format_var.get() in ('3GPP', '3GPP2'):
            ir92['SMS_Format'] = self.sms_format_var.get()
        if self.amr_var.get().strip():
            ir92['amr_modeset_list'] = self.amr_var.get().replace('，', ',').strip()
        if self.amrwb_var.get().strip():
            ir92['amrwb_modeset_list'] = self.amrwb_var.get().replace('，', ',').strip()
        ims_pps = {}
        if self.silent_redial_var.get() in ('true', 'false'):
            ims_pps['SilentRedial'] = self.silent_redial_var.get() == 'true'
        if self.sip_csfb_var.get().strip():
            try:
                ims_pps['SIP_Timer_CSFB'] = int(self.sip_csfb_var.get().strip())
            except ValueError:
                raise ValueError(tr('SIP_Timer_CSFB 必须为整数（秒，0–120）。')) from None
        if self.ipsec_var.get() in ('true', 'false'):
            ims_pps['IPsec'] = self.ipsec_var.get() == 'true'
        if self.sip_transport_var.get() in ('UDP', 'TCP', 'TLS'):
            ims_pps['SIP_transport'] = self.sip_transport_var.get()
        if self.reg_exp_var.get().strip():
            try:
                ims_pps['RegExpiration'] = int(self.reg_exp_var.get().strip())
            except ValueError:
                raise ValueError(tr('RegExpiration 必须为整数（秒，60–86400）。')) from None
        primary = overseas_carrier.build_trial_config(
            mcc=self.mcc_var.get().strip(),
            mncs=mncs,
            data_apns=apns or ['auto'],
            ims_apn=self.ims_apn_var.get().strip() or 'ims',
            ip_family=self.ip_family_var.get() or 'IPv4v6',
            home_domain=self.home_domain_var.get().strip() or 'auto',
            sms=bool(self.sms_var.get()),
            allow_isim=bool(self.allow_isim_var.get()),
            allow_stock_default_xml=bool(self.allow_0xml_var.get()),
            label=self.label_var.get().strip(),
            stock_config=self.stock_config_var.get().strip() or 'auto',
            ue_usage=self.ue_usage_var.get() or 'auto',
            always_on=bool(self.always_on_var.get()),
            request_signalling_bearer_via_pco=bool(self.sig_pco_var.get()),
            disable_dad=bool(self.disable_dad_var.get()),
            ir92=ir92 or None,
            ims_pps=ims_pps or None,
            enabled=True,
        )
        if self._extra_carriers:
            primary_entry = {k: v for k, v in primary.items() if k not in ('schema', 'enabled')}
            return profiles.validate_exp_trial({
                'schema': 2,
                'enabled': True,
                'carriers': [primary_entry] + list(self._extra_carriers),
            })
        return primary

    def _import_json(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self, title=tr('导入海外运营商 JSON 配置'),
                                          filetypes=[(tr('JSON 文件'), '*.json'), (tr('所有文件'), '*.*')])
        if not path:
            return
        try:
            raw = json.loads(Path(path).read_text(encoding='utf-8'))
            validated = profiles.validate_exp_trial(raw)
            self._load_config_into_form(validated)
            self.status_label.configure(text=tr('已导入并通过格式校验；点击“保存并重新检查”写入手机。'))
        except Exception as exc:
            messagebox.showerror(tr('配置未通过校验'), _friendly_validation_error(exc), parent=self)

    def _export_json(self):
        if self.busy:
            return
        try:
            cfg = self.build_config_from_form()
        except Exception as exc:
            messagebox.showerror(tr('配置未通过校验'), _friendly_validation_error(exc), parent=self)
            return
        path = filedialog.asksaveasfilename(parent=self, title=tr('导出海外运营商 JSON 配置'),
                                            defaultextension='.json',
                                            filetypes=[(tr('JSON 文件'), '*.json')])
        if path:
            try:
                Path(path).write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                self.status_label.configure(text=tr('已导出海外试测配置文件。'))
            except OSError:
                messagebox.showerror(tr('无法保存'), tr('请检查保存路径和写入权限。'), parent=self)

    def _refresh_action_states(self):
        state = 'disabled' if self.busy else 'normal'
        ro_state = 'disabled' if self.busy else 'readonly'
        for w in self._form_widgets:
            w.configure(state=state)
        for w in self._readonly_widgets:
            w.configure(state=ro_state)
        for btn in (self.apply_preset_btn, self.import_btn, self.export_btn, self.close_btn):
            btn.configure(state=state)
        write_state = 'disabled' if (self.busy or self._service_running) else 'normal'
        self.save_btn.configure(state=write_state)
        self.clear_btn.configure(state=write_state)

    def _set_busy(self, busy, message=''):
        self.busy = busy
        self._refresh_action_states()
        if message:
            self.status_label.configure(text=message)

    def _load_existing_from_phone(self):
        if self.busy:
            return
        self._set_busy(True, tr('正在读取手机当前海外试测配置…'))
        def work():
            try:
                auto = self.client_factory()
                res = auto.get_exp_trial()
                self.events.put(('load', res, None))
            except Exception as exc:
                self.events.put(('load', None, getattr(exc, 'code', None) or str(exc) or type(exc).__name__))
        threading.Thread(target=work, daemon=True).start()

    def _save_to_phone(self):
        if self.busy or self._service_running:
            return
        try:
            cfg = self.build_config_from_form()
        except Exception as exc:
            messagebox.showerror(tr('配置未通过校验'), _friendly_validation_error(exc), parent=self)
            return
        self._set_busy(True, tr('正在校验并写入手机端海外试测配置…'))
        def work():
            try:
                auto = self.client_factory()
                res = auto.set_exp_trial(cfg)
                self.events.put(('save', res, None))
            except Exception as exc:
                self.events.put(('save', None, getattr(exc, 'code', None) or str(exc) or type(exc).__name__))
        threading.Thread(target=work, daemon=True).start()

    def _clear_on_phone(self):
        if self.busy or self._service_running:
            return
        if not messagebox.askyesno(
            tr('清除手机端海外配置'),
            tr('确定要删除手机上的海外 / 自定义试测配置文件吗？（不会卸载已安装的 VoLTE 服务）'),
            parent=self,
        ):
            return
        self._set_busy(True, tr('正在清除手机端海外试测配置…'))
        def work():
            try:
                auto = self.client_factory()
                res = auto.clear_exp_trial()
                self.events.put(('clear', res, None))
            except Exception as exc:
                self.events.put(('clear', None, getattr(exc, 'code', None) or str(exc) or type(exc).__name__))
        threading.Thread(target=work, daemon=True).start()

    def _format_error(self, err):
        msg = device_support.error_message(err)
        if msg:
            return msg
        if err in CONNECTION_ERROR_CODES:
            return guidance(error=err).title
        return str(err)

    def _poll(self):
        try:
            while True:
                action, res, err = self.events.get_nowait()
                self._set_busy(False)
                if err:
                    self.status_label.configure(text=tr('操作未完成：{}').format(self._format_error(err)))
                elif action == 'load':
                    loaded = isinstance(res, dict) and isinstance(res.get('config'), dict)
                    if loaded:
                        self._load_config_into_form(res['config'])
                    if self._service_running:
                        self.status_label.configure(
                            text=tr('VoLTE 后台服务正在运行。请先停用自动适配并等待恢复完成，再保存或清除海外运营商配置。'))
                    elif self._update_needed:
                        self.status_label.configure(
                            text=tr('检测到手机端 VoLTE 后台可更新。保存海外配置后请按提示更新自动适配并重启。'))
                    elif loaded:
                        self.status_label.configure(text=tr('已载入手机当前海外试测配置。'))
                    else:
                        self.status_label.configure(text=tr('手机当前未配置海外试测文件。'))
                elif action in ('save', 'clear'):
                    if isinstance(res, dict) and isinstance(res.get('probe'), dict):
                        self.probe_report = res['probe']
                        self._service_running = bool((self.probe_report.get('status') or {}).get('manager_alive'))
                        self.sim_info.configure(text=self._format_sim_summary())
                    try:
                        if self.on_saved is not None:
                            self.on_saved(res)
                    finally:
                        self._close()
                    return
        except queue.Empty:
            pass
        if self.winfo_exists():
            self._poll_job = self.after(120, self._poll)

    def _close(self):
        if not self.busy:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
            if self.winfo_exists():
                self.destroy()
