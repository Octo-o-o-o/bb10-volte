"""Shared Windows/macOS recovery UI for devices that already have Root."""
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from connection_recovery import (RecoveryError, read_host_key, fingerprint, import_identity,
                                 prepare_pairing, read_pairing_result, finish_pairing,
                                 pending_pairings, save_pairing_step, complete_pairing)
from root_setup import verify_root, SetupError
from workflow import WorkflowError
from profile_editor import FONT
from mac_help import TRANSFER_HINT, scrolled_page, show_guide as show_mac_guide

MESSAGES = {
    'pairing_export_conflict': '目标位置已有同名但内容不同的文件。请更换保存位置，原文件没有覆盖。',
    'keygen_missing': '缺少密钥工具。Windows 源码用户请先准备连接组件；Mac 使用系统 OpenSSH。',
    'key_unreadable': '私钥无法读取或带有口令。请用原 SSH 工具解锁并导出可用的 RSA 私钥，或改用“没有连接文件”重新授权。',
    'login_key_required': '请选择登录私钥（如 id_rsa、id_rsa4x），不能选择 .pub 或 ssh_host 开头的手机主机密钥。',
    'putty_conversion_required': '这是 PuTTY 的 PPK 文件。请用 PuTTYgen 导出 OpenSSH 私钥后导入，或改用手机重新授权。',
    'rsa_key_required': '此旧版手机连接流程需要 RSA 私钥，可改用“没有连接文件”生成兼容密钥。',
    'host_key_invalid': '请选择这台手机的 RSA 主机公钥 ssh_host_rsa_key.pub，或包含 USB 地址记录的 known_hosts。',
    'pairing_result_invalid': '授权结果与本电脑生成的文件不匹配。请导入本次手机生成的 result.json；不要换用另一台电脑的结果。',
    'host_key_changed': '这次结果与此前保存的手机身份不同，已保留原记录。请核对手机与授权文件。',
    'authentication_failed': '手机没有接受这把登录密钥。可改用“没有连接文件”，通过手机已有 Root 终端授权本电脑。',
    'host_key_mismatch': '手机身份与导入的公钥不符。请重新从这台手机获取授权结果，不要关闭校验。',
    'connection_refused': '手机的 SSH 尚未开启。新授权文件可在手机上输入 START 临时开启 USB SSH；已有 Root 工具也可开启。',
    'connection_failed': '尚未连通手机。检查 USB 网络、手机解锁与 SSH 是否已启动，再点击验证。',
    'connection_timeout_state_unknown': '连接超时。请核对 USB 网络与手机 SSH 状态后重新验证。',
    'root_not_ready': 'SSH 已连接，但不是有效 Root。请先用原 Root 工具完成启动，再验证。',
    'root_probe_failed': '已建立 SSH，但 Root 诊断未完成。请保留连接材料检查诊断结果，不要因此重新刷写或更改手机安全设置。',
}


class RecoveryDialog(tk.Toplevel):
    def __init__(self, parent, on_ready, mode='pair'):
        super().__init__(parent)
        self.title('恢复已 Root 手机的连接')
        self.geometry('880x720')
        self.minsize(820, 690)
        self.transient(parent)
        self.on_ready = on_ready
        self.events = queue.Queue()
        self.busy, self.choice, self.verified = False, None, False
        self.pair_script, self.pair_step = None, 1
        self.identity, self.host_key = tk.StringVar(), tk.StringVar()
        body = ttk.Frame(self, padding=22)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='让这台电脑连接手机', font=(FONT, 16, 'bold')).pack(anchor='w')
        ttk.Label(body, text='手机授权需要已有有效 Root 终端。完成后验证手机身份和实际 Root 权限。',
                  wraplength=800).pack(anchor='w', pady=(8, 14))
        self.tabs = ttk.Notebook(body)
        self.tabs.pack(fill='both', expand=True)
        existing = ttk.Frame(self.tabs, padding=18)
        self.tabs.add(existing, text='高级：手动导入密钥')
        if sys.platform == 'darwin':
            missing_page, missing = scrolled_page(self.tabs)
            self.tabs.add(missing_page, text='从手机授权 / 继续上次')
        else:
            missing = ttk.Frame(self.tabs, padding=18)
            self.tabs.add(missing, text='从手机授权 / 继续上次')
        ttk.Label(existing, text='用于原刷机包提供了登录私钥，但没有 ssh_config 的情况。', wraplength=750).pack(anchor='w')
        self.buttons = []
        for title, variable, callback in [('登录私钥', self.identity, self.select_identity),
                                          ('手机主机公钥', self.host_key, self.select_host_key)]:
            row = ttk.Frame(existing)
            row.pack(fill='x', pady=(12, 0))
            ttk.Label(row, text=title, width=14).pack(side='left')
            ttk.Entry(row, textvariable=variable, state='readonly').pack(side='left', fill='x', expand=True)
            button = ttk.Button(row, text='选择文件', command=callback)
            button.pack(side='right', padx=(8, 0))
            self.buttons.append(button)
        ttk.Label(existing, text='登录私钥常见名称：id_rsa、id_rsa4x。手机主机公钥通常叫 ssh_host_rsa_key.pub。\n'
                  '没有手机主机公钥时，请使用“没有连接文件”路径，从手机导出可信结果。\n'
                  '已有完整 ssh_config 可回到“首次使用 → 导入已有连接”。',
                  wraplength=740, justify='left').pack(anchor='w', pady=18)
        button = ttk.Button(existing, text='补建配置并验证', command=self.import_key)
        button.pack(anchor='w')
        self.buttons.append(button)
        self.pending = pending_pairings()
        resume = ttk.Frame(missing)
        resume.pack(fill='x', pady=(0, 10))
        self.resume_picker = ttk.Combobox(resume, state='readonly', width=34,
            values=[item['script'].stem + ' · 第 ' + str(item['step']) + ' 步' for item in self.pending])
        self.resume_picker.pack(side='left')
        resume_button = ttk.Button(resume, text='继续选中的授权', command=self.resume_pairing)
        resume_button.pack(side='left', padx=8)
        self.buttons.append(resume_button)
        if not self.pending:
            resume.pack_forget()
        self.step_label = ttk.Label(missing, font=(FONT, 12, 'bold'))
        self.step_label.pack(anchor='w')
        self.missing_steps = ttk.Label(missing, wraplength=740, justify='left')
        self.missing_steps.pack(anchor='w', pady=(8, 0))
        row = ttk.Frame(missing)
        row.pack(fill='x', pady=12)
        self.generate_button = ttk.Button(row, text='保存授权文件', command=self.generate)
        self.result_button = ttk.Button(row, text='选择手机授权结果', command=self.import_result)
        self.step_back = ttk.Button(row, text='上一步', command=lambda: self.set_step(self.pair_step - 1))
        self.step_next = ttk.Button(row, command=lambda: self.set_step(self.pair_step + 1))
        self.buttons.extend([self.generate_button, self.result_button, self.step_back, self.step_next])
        self.commands = tk.Text(missing, height=5, wrap='word', font=(FONT, 10))
        self.pair_hint = ttk.Label(missing, wraplength=740, justify='left')
        self.pair_hint.pack(anchor='w', pady=(12, 0))
        self.mac_transfer_help = None
        if sys.platform == 'darwin':
            self.mac_transfer_help = ttk.Label(missing, text=TRANSFER_HINT, wraplength=740, justify='left')
            self.mac_transfer_help.pack(anchor='w', pady=(10, 0))
        self.status = ttk.Label(body, text='请选择适合当前情况的路径。', wraplength=800)
        self.status.pack(fill='x', pady=14)
        bottom = ttk.Frame(body)
        bottom.pack(fill='x')
        self.verify_button = ttk.Button(bottom, text='重新验证连接', command=self.verify, state='disabled')
        self.verify_button.pack(side='left')
        self.continue_button = ttk.Button(bottom, text='使用此连接', command=self.finish, state='disabled')
        self.continue_button.pack(side='right')
        ttk.Button(bottom, text='关闭', command=self.close).pack(side='right', padx=10)
        if sys.platform == 'darwin':
            ttk.Button(bottom, text='Mac 连接说明', command=lambda: show_mac_guide(self)).pack(side='left', padx=10)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self._job = self.after(100, self.drain)
        self.grab_set()
        self.tabs.select(0 if mode == 'key' else 1)
        if len(self.pending) == 1:
            self.resume_picker.current(0)
            self.resume_pairing()
        else:
            self.set_step(1, persist=False)
        self.refresh()

    def resume_pairing(self):
        if self.busy:
            return
        index = self.resume_picker.current()
        if index < 0:
            self.status.configure(text='有多次未完成授权，请按手机上的文件编号选择对应记录。')
            return
        item = self.pending[index]
        self.pair_script = item['script']
        self.set_step(item['step'], persist=False)
        self.status.configure(text='继续 ' + self.pair_script.name + '，使用原来的本机密钥。')

    def set_step(self, step, persist=True):
        if self.busy or step not in (1, 2, 3) or step > 1 and not self.pair_script:
            return
        if persist and self.pair_script:
            try:
                save_pairing_step(self.pair_script, step)
            except (OSError, ValueError):
                self.status.configure(text='暂时无法保存进度。请检查应用个人目录的写入权限。')
                return
        self.pair_step = step
        titles = {1: '把授权文件放到手机', 2: '在手机上允许这台电脑连接', 3: '取回手机授权结果'}
        self.step_label.configure(text='第 {} / 3 步 · {}'.format(step, titles[step]))
        descriptions = {
            1: '保存本次授权文件，并复制到手机内部存储 Downloads。电脑私钥保留在本机。\n如果已经拿到结果，也可以直接选择手机授权结果。',
            2: '在手机已有 Root 终端按下方命令执行。脚本核验权限后，输入 PAIR 才会追加这台电脑的授权。\n只有脚本提示需要启动连接服务时，才另行输入 START。',
            3: '将手机内部 Downloads 中同编号的 result.json 复制回本电脑，再选择它并确认来源。\n应用会核对请求编号、本机密钥、手机身份与实际 Root 权限。',
        }
        self.missing_steps.configure(text=descriptions[step])
        for button in (self.generate_button, self.result_button, self.step_back, self.step_next):
            button.pack_forget()
        if step == 1:
            self.generate_button.pack(side='left', padx=(0, 10))
        self.result_button.pack(side='left', padx=(0, 10))
        if step > 1:
            self.step_back.pack(side='left', padx=(0, 10))
        if step < 3:
            self.step_next.configure(text='已复制到手机，下一步' if step == 1 else '手机已生成结果，下一步')
            self.step_next.pack(side='left')
        self.commands.pack_forget()
        if step == 2 and self.pair_script:
            phone_path = '/accounts/1000/shared/downloads/' + self.pair_script.name
            self.set_commands('__root\n/proc/boot/pathtrust !' + phone_path + '\n/usr/bin/python3.2 ' + phone_path)
            self.commands.pack(fill='x', before=self.pair_hint)
        self.pair_hint.configure(text=('当前文件：' + self.pair_script.name if self.pair_script else '还没有生成本次授权文件。') +
                                 '\n关闭应用后可继续本次授权，无需重新生成密钥。')
        self.refresh()

    def set_commands(self, text):
        self.commands.configure(state='normal')
        self.commands.delete('1.0', 'end')
        self.commands.insert('1.0', text)
        self.commands.configure(state='disabled')

    def select_identity(self):
        path = filedialog.askopenfilename(parent=self, title='选择原手机的登录私钥')
        if path:
            self.identity.set(path)

    def select_host_key(self):
        path = filedialog.askopenfilename(parent=self, title='选择手机主机公钥或可信 known_hosts')
        if path:
            self.host_key.set(path)

    def confirm_host(self, key):
        return messagebox.askokcancel('核对手机身份', '手机主机公钥指纹：\n' + fingerprint(key) +
                                     '\n\n请确认此公钥或结果来自当前这台手机，或你信任的原始连接材料。确认后会固定校验此身份。', parent=self)

    def show_error(self, error):
        self.verified = False
        self.status.configure(text=MESSAGES.get(str(error), '未完成。请检查所选材料和文件权限；现有手机配置不会被覆盖。'))
        self.refresh()

    def import_key(self):
        if not self.identity.get() or not self.host_key.get():
            self.status.configure(text='请先选择登录私钥和这台手机的主机公钥。')
            return
        try:
            key = read_host_key(self.host_key.get())
            if not self.confirm_host(key):
                return
            identity = self.identity.get()
            self.start('config', lambda: import_identity(identity, key, confirmed=True))
        except (OSError, ValueError) as error:
            self.show_error(error)

    def generate(self):
        folder = filedialog.askdirectory(parent=self, title='选择公开授权脚本的导出目录')
        if not folder:
            return
        existing_script = self.pair_script
        def work():
            script = existing_script or prepare_pairing()
            self.events.put(('prepared_script', script))
            target = Path(folder) / script.name
            # Exclusive creation avoids overwriting another exported request.
            if target.exists():
                if target.read_bytes() != script.read_bytes():
                    raise RecoveryError('pairing_export_conflict')
            else:
                with target.open('xb') as output:
                    output.write(script.read_bytes())
            return script
        self.start('script', work)

    def import_result(self):
        path = filedialog.askopenfilename(parent=self, title='选择手机生成的 bb10-pair-编号-result.json', filetypes=[('授权结果', '*.json')])
        if not path:
            return
        try:
            _, key, _ = read_pairing_result(path)
            if not self.confirm_host(key):
                return
            self.choice = finish_pairing(path, confirmed=True)
            self.verify()
        except (OSError, ValueError) as error:
            self.show_error(error)

    def verify(self):
        if self.choice:
            choice = dict(self.choice)
            self.start('verify', lambda: verify_root(choice['host'], choice['config']))

    def start(self, action, work):
        if self.busy:
            return
        self.busy, self.verified = True, False
        self.refresh()
        self.status.configure(text='正在准备本机文件…' if action != 'verify' else '正在验证手机身份与 Root 权限…')
        def worker():
            try:
                self.events.put((action, work()))
            except Exception as error:
                self.events.put(('error', str(error) if isinstance(error, (RecoveryError, WorkflowError, SetupError)) else 'recovery_failed'))
        threading.Thread(target=worker, daemon=True).start()

    def drain(self):
        try:
            while True:
                action, result = self.events.get_nowait()
                if action == 'prepared_script':
                    self.pair_script = result
                    continue
                self.busy = False
                if action == 'error':
                    self.show_error(result)
                elif action == 'script':
                    self.pair_script = result
                    self.set_step(1)
                    self.status.configure(text='已保存 ' + result.name + '。复制到手机内部 Downloads 后点击下一步。')
                elif action == 'config':
                    self.choice = result
                    self.verify()
                elif action == 'verify':
                    self.choice, self.verified = result, True
                    try:
                        complete_pairing(result['config'])
                    except OSError:
                        pass
                    self.status.configure(text='手机身份与 Root 连接已验证并保存，可使用此连接继续检查设备。')
                self.refresh()
        except queue.Empty:
            pass
        self._job = self.after(100, self.drain)

    def refresh(self):
        for button in self.buttons:
            button.configure(state='disabled' if self.busy else 'normal')
        self.verify_button.configure(state='normal' if self.choice and not self.busy else 'disabled')
        self.continue_button.configure(state='normal' if self.verified and not self.busy else 'disabled')
        self.step_next.configure(state='normal' if self.pair_script and not self.busy else 'disabled')
        self.resume_picker.configure(state='disabled' if self.busy else 'readonly')

    def finish(self):
        if self.verified and not self.busy:
            choice = self.choice
            self.close()
            self.on_ready(choice['host'], choice['config'])

    def close(self):
        if self.busy:
            messagebox.showinfo('正在处理', '请等待当前文件准备或连接验证结束。', parent=self)
            return
        self.after_cancel(self._job)
        self.destroy()
        if isinstance(self.master, tk.Toplevel) and self.master.winfo_exists():
            self.master.grab_set()
