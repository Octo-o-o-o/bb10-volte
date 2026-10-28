"""Shared Windows/macOS recovery UI for devices that already have Root."""
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from connection_recovery import (RecoveryError, read_host_key, fingerprint, import_identity,
                                 prepare_pairing, read_pairing_result, finish_pairing)
from root_setup import verify_root, SetupError
from workflow import WorkflowError
from profile_editor import FONT

MESSAGES = {
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
}


class RecoveryDialog(tk.Toplevel):
    def __init__(self, parent, on_ready):
        super().__init__(parent)
        self.title('恢复已 Root 手机的连接')
        self.geometry('880x720')
        self.minsize(820, 690)
        self.transient(parent)
        self.on_ready = on_ready
        self.events = queue.Queue()
        self.busy, self.choice, self.verified = False, None, False
        self.identity, self.host_key = tk.StringVar(), tk.StringVar()
        body = ttk.Frame(self, padding=22)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='手机已 Root，重新建立电脑连接', font=(FONT, 16, 'bold')).pack(anchor='w')
        ttk.Label(body, text='先按已有材料选择路径。此向导不刷机；只有验证 Root 连接成功后才保存并继续。',
                  wraplength=800).pack(anchor='w', pady=(8, 14))
        self.tabs = ttk.Notebook(body)
        self.tabs.pack(fill='both', expand=True)
        existing, missing = ttk.Frame(self.tabs, padding=18), ttk.Frame(self.tabs, padding=18)
        self.tabs.add(existing, text='有登录私钥')
        self.tabs.add(missing, text='没有连接文件')
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
        ttk.Label(missing, text='需要手机已有可用的 Root 终端（如 Term49 + __root）。只有图标、开发模式或 Root 提示还不够。\n'
                  '1. 生成并导出授权脚本，只把此 .py 文件复制到手机 Downloads；私钥保留在电脑。\n'
                  '2. 在手机终端执行下方命令；脚本确认有效 Root 后，输入 PAIR 授权这台电脑。\n'
                  '3. 若 SSH 未开启，可按脚本提示输入 START 临时启动；已有会话无需重复启动。\n'
                  '4. 将手机 Downloads 中同编号的 result.json 复制回电脑，导入并验证。',
                  wraplength=740, justify='left').pack(anchor='w')
        row = ttk.Frame(missing)
        row.pack(fill='x', pady=12)
        for title, callback in [('生成并导出授权文件', self.generate), ('导入手机授权结果', self.import_result)]:
            button = ttk.Button(row, text=title, command=callback)
            button.pack(side='left', padx=(0, 10))
            self.buttons.append(button)
        self.commands = tk.Text(missing, height=5, wrap='word', font=(FONT, 10))
        self.commands.pack(fill='x')
        self.set_commands('生成文件后，这里会显示对应的手机命令。')
        ttk.Label(missing, text='脚本保留原授权并备份，不改 Root 固件。临时启动 SSH 不保证重启后仍开启。\n'
                  '若 __root / u_root 不存在或仍无 Root 权限，请先在手机原有 Root 工具中恢复权限；电脑端无法越过这一步。',
                  wraplength=740, justify='left').pack(anchor='w', pady=(12, 0))
        self.status = ttk.Label(body, text='请选择适合当前情况的路径。', wraplength=800)
        self.status.pack(fill='x', pady=14)
        bottom = ttk.Frame(body)
        bottom.pack(fill='x')
        self.verify_button = ttk.Button(bottom, text='重新验证连接', command=self.verify, state='disabled')
        self.verify_button.pack(side='left')
        self.continue_button = ttk.Button(bottom, text='使用此连接', command=self.finish, state='disabled')
        self.continue_button.pack(side='right')
        ttk.Button(bottom, text='关闭', command=self.close).pack(side='right', padx=10)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self._job = self.after(100, self.drain)
        self.grab_set()

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
        def work():
            script = prepare_pairing()
            target = Path(folder) / script.name
            # Exclusive creation avoids overwriting another exported request.
            with target.open('xb') as output:
                output.write(script.read_bytes())
            return target
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
                self.busy = False
                if action == 'error':
                    self.show_error(result)
                elif action == 'script':
                    phone_path = '/accounts/1000/shared/downloads/' + result.name
                    self.set_commands('__root\nid -u\n/proc/boot/pathtrust !' + phone_path + '\n/usr/bin/python3.2 ' + phone_path)
                    self.status.configure(text='已导出 ' + result.name + '。复制到手机 Downloads，再按上面的步骤授权；此时尚未建立连接。')
                elif action == 'config':
                    self.choice = result
                    self.verify()
                elif action == 'verify':
                    self.choice, self.verified = result, True
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
