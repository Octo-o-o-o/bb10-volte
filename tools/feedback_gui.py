"""A support entry that stays available during and after each operation."""
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import webbrowser

from feedback import journal_for, write_bundle
from i18n import tr, LANGUAGE


def help_row(parent, owner, step):
    row = ttk.Frame(parent)
    row.pack(side='bottom', fill='x', pady=(8, 0))
    current = lambda: step() if callable(step) else step
    ttk.Button(row, text=tr('遇到问题 / 反馈'), command=lambda: FeedbackDialog(owner, current())).pack(side='left')
    ttk.Button(row, text=tr('查看本步图文教程'), command=lambda: webbrowser.open(
        'https://bb10-volte.octoooo.com/' + ('en/' if LANGUAGE == 'en' else '') +
        'guide.html#walkthrough-' + current())).pack(side='left', padx=8)
    return row


class FeedbackDialog(tk.Toplevel):
    def __init__(self, parent, step):
        super().__init__(parent)
        self.title(tr('保存问题反馈'))
        self.geometry('820x700')
        self.minsize(680, 560)
        self.transient(parent)
        self.previous_grab = self.grab_current()
        self.grab_set()
        self.journal, self.step = journal_for(parent), step
        # Capture only explicitly named status labels, never entries, clipboard,
        # password fields or the whole screen. Scrubbing happens before storage.
        labels = getattr(parent, '_feedback_status_labels', None)
        if labels is None:
            labels = [getattr(parent, name, None) for name in ('status', 'root_hint', 'facts', 'device')]
        visible = []
        for label in labels:
            if label is not None:
                try:
                    visible.append(str(label.cget('text')))
                except (tk.TclError, AttributeError):
                    pass
        self.journal.record(step, 'open_feedback', 'observed', message='\n'.join(visible))
        self.payload = None
        body = ttk.Frame(self, padding=20)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=tr('把卡住的步骤和此前记录一起保存'), font=('', 16, 'bold')).pack(anchor='w')
        ttk.Label(body, text=tr('只保存在你的电脑，不会自动上传。保存后检查 ZIP 内容，再通过原联系渠道发给开发者。'),
                  wraplength=740).pack(anchor='w', pady=(8, 6))
        ttk.Label(body, text=tr('包含：当前步骤、版本、近期操作、失败代码和允许的检查结果。\n'
            '不包含：私钥、密码、手机号、手机备份或原始通信日志。'), wraplength=740).pack(anchor='w')
        footer = ttk.Frame(body)
        footer.pack(side='bottom', fill='x', pady=(12, 0))
        self.save_button = ttk.Button(footer, text=tr('保存反馈包…'), command=self.save)
        self.save_button.pack(side='left')
        ttk.Button(footer, text=tr('复制反馈摘要'), command=self.copy_summary).pack(side='left', padx=8)
        ttk.Button(footer, text=tr('关闭'), command=self.close).pack(side='right')
        self.status = ttk.Label(body, wraplength=740)
        self.status.pack(side='bottom', fill='x', pady=(8, 0))
        ttk.Label(body, text=tr('补充说明（可选）：做到了哪一步，原本希望看到什么？请勿填写密码或号码。'),
                  wraplength=740).pack(anchor='w', pady=(14, 4))
        self.note = tk.Text(body, height=3, wrap='word')
        self.note.pack(fill='x')
        toolbar = ttk.Frame(body)
        toolbar.pack(fill='x', pady=(10, 4))
        ttk.Label(toolbar, text=tr('将要保存的内容（已脱敏）')).pack(side='left')
        ttk.Button(toolbar, text=tr('刷新预览'), command=self.preview).pack(side='right')
        panel = ttk.Frame(body)
        panel.pack(fill='both', expand=True)
        self.content = tk.Text(panel, wrap='word', state='disabled', height=12)
        scroll = ttk.Scrollbar(panel, orient='vertical', command=self.content.yview)
        self.content.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.content.pack(fill='both', expand=True)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.preview()

    def preview(self):
        old_id = (self.payload or {}).get('feedback_id')
        self.payload = self.journal.bundle(self.step, self.note.get('1.0', 'end-1c')[:1600])
        if old_id:
            self.payload['feedback_id'] = old_id
        self.content.configure(state='normal')
        self.content.delete('1.0', 'end')
        self.content.insert('1.0', json.dumps(self.payload, ensure_ascii=False, indent=2))
        self.content.configure(state='disabled')
        count = sum(len(item['events']) for item in self.payload['sessions'])
        self.status.configure(text=tr('已包含 {} 条近期记录。只覆盖启用此功能后的最近 5 次启动，每次最多 400 条。').format(count)
            if self.journal.persistence_ok else tr('本机历史写入失败；仍可保存本次运行的内存记录。'))

    def save(self):
        self.preview()
        path = filedialog.asksaveasfilename(parent=self, title=tr('保存脱敏反馈包'),
            initialfile='bb10-feedback-' + self.payload['feedback_id'] + '.zip',
            defaultextension='.zip', filetypes=[('ZIP', '*.zip')])
        if not path:
            return
        try:
            write_bundle(path, self.payload)
            self.status.configure(text=tr('反馈包已保存，尚未发送。请检查内容后，将 ZIP 发给开发者：octoooo@octoooo.com。'))
        except (OSError, ValueError):
            messagebox.showerror(tr('无法保存'), tr('请检查保存路径和写入权限。'), parent=self)

    def copy_summary(self):
        self.preview()
        errors = [event for session in self.payload['sessions'] for event in session['events']
                  if event['outcome'] in ('failed', 'needs_attention')]
        summary = 'BB10 VoLTE ' + self.payload['app_version'] + '\nID: ' + self.payload['feedback_id'] + '\n'
        summary += 'Step: ' + self.step + '\n' + self.payload['note'] + '\n'
        summary += '\n'.join(event['action'] + ': ' + event.get('message', event['outcome']) for event in errors[-5:])
        try:
            self.clipboard_clear()
            self.clipboard_append(summary)
            self.status.configure(text=tr('摘要已复制。完整过程请另存反馈包，一并发送。'))
        except tk.TclError:
            self.status.configure(text=tr('剪贴板暂不可用，请使用“保存反馈包”。'))

    def close(self):
        self.destroy()
        if self.previous_grab is not None and self.previous_grab.winfo_exists():
            self.previous_grab.grab_set()
