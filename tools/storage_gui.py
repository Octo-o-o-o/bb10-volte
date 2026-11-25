"""Non-modal storage window. Choosing a folder never grabs the rest of the application."""
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from i18n import tr
from storage_location import (
    collect_inventory, delete_items, format_bytes, free_bytes, location_status,
    measure_tree, private_root, set_work_root,
)


_OPEN = {}


def open_storage(parent, scope_kit=None, stable=None):
    """Show the storage window and return immediately. Does not grab the parent."""
    key = str(getattr(parent, '_w', id(parent)))
    current = _OPEN.get(key)
    try:
        if current is not None and current.winfo_exists():
            if scope_kit:
                current.scope_kit = str(scope_kit)
                current.reload()
            current.deiconify()
            current.lift()
            return current
    except tk.TclError:
        pass
    window = StorageWindow(parent, scope_kit=scope_kit, stable=stable)
    _OPEN[key] = window
    return window


class StorageWindow(tk.Toplevel):
    def __init__(self, parent, scope_kit=None, stable=None):
        super().__init__(parent)
        self.stable = stable if stable is not None else private_root()
        self.scope_kit = str(scope_kit) if scope_kit else None
        self.generation = 0
        self.items = []
        self.checked = {}
        self.checks = {}
        self.labels = {}
        self.size_vars = {}
        self.title(tr('要清理这次的临时文件吗？') if self.scope_kit else tr('存储位置与磁盘清理'))
        self.geometry('760x640')
        self.minsize(640, 480)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Escape>', lambda _event: self.close())
        self.canvas = None

        summary = ttk.Frame(self, padding=(16, 12, 16, 0))
        summary.grid(row=0, column=0, sticky='ew')
        summary.columnconfigure(0, weight=1)
        self.location = ttk.Label(summary, justify='left', wraplength=700)
        self.location.grid(row=0, column=0, sticky='ew')
        self.notice = ttk.Label(summary, justify='left', wraplength=700)
        self.notice.grid(row=1, column=0, sticky='ew', pady=(6, 0))
        ttk.Label(summary, justify='left', wraplength=700, text=tr(
            '更改只影响之后开始的下载和准备。正在进行的操作不会被打断，已有文件不会搬走，不选择也能继续使用。'
        )).grid(row=2, column=0, sticky='ew', pady=(6, 0))

        actions = ttk.Frame(self, padding=(16, 8))
        actions.grid(row=1, column=0, sticky='ew')
        ttk.Button(actions, text=tr('选择文件夹'), command=self.choose).pack(side='left')
        ttk.Button(actions, text=tr('打开文件夹'), command=self.open_folder).pack(side='left', padx=(8, 0))
        ttk.Button(actions, text=tr('恢复默认位置'), command=self.restore).pack(side='left', padx=(8, 0))

        holder = ttk.Frame(self, padding=(16, 0))
        holder.grid(row=2, column=0, sticky='nsew')
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(holder, highlightthickness=0)
        scroll = ttk.Scrollbar(holder, orient='vertical', command=self.canvas.yview)
        self.rows = ttk.Frame(self.canvas)
        self.rows.bind('<Configure>', lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.rows, anchor='nw')
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(self.canvas_window, width=event.width))
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        scroll.grid(row=0, column=1, sticky='ns')
        self.canvas.bind('<MouseWheel>', self._wheel)

        footer = ttk.Frame(self, padding=16)
        footer.grid(row=3, column=0, sticky='ew')
        self.clean_button = ttk.Button(footer, text=tr('清理所选'), command=self.clean, state='disabled')
        self.clean_button.pack(side='left')
        close_text = tr('不清理') if self.scope_kit else tr('关闭')
        self.close_button = ttk.Button(footer, text=close_text, command=self.close)
        self.close_button.pack(side='right')
        self.close_button.focus_set()
        self.reload()

    def close(self):
        self.destroy()

    def destroy(self):
        self.generation += 1
        super().destroy()

    def _wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), 'units')

    def reload(self):
        self.generation += 1
        generation = self.generation
        status = location_status(self.stable)
        self._show_status(status)
        self.items = collect_inventory(self.stable, self.scope_kit)
        self.checked = {}
        self.checks = {}
        self.labels = {}
        self.size_vars = {}
        for child in self.rows.winfo_children():
            child.destroy()
        if not self.items:
            ttk.Label(self.rows, text=tr('没有可清理的下载、解包文件或成品镜像。')).grid(sticky='w')
        self.rows.columnconfigure(0, weight=1)
        for index, item in enumerate(self.items):
            variable = tk.BooleanVar(value=False)
            self.checked[item['path']] = variable
            variable.trace_add('write', lambda *_args: self._refresh_clean())
            row = ttk.Frame(self.rows)
            row.grid(row=index, column=0, sticky='ew', pady=(0, 8))
            row.columnconfigure(1, weight=1)
            check = ttk.Checkbutton(row, variable=variable, state='normal' if item['enabled'] else 'disabled')
            check.grid(row=0, column=0, sticky='nw')
            self.checks[item['path']] = check
            label = ttk.Label(row, text=self._item_text(item), wraplength=520, justify='left')
            label.grid(row=0, column=1, sticky='ew', padx=(8, 12))
            self.labels[item['path']] = label
            size = tk.StringVar(value=format_bytes(item['bytes']) if item['bytes'] is not None else tr('正在计算…'))
            self.size_vars[item['path']] = size
            ttk.Label(row, textvariable=size).grid(row=0, column=2, sticky='ne')
        self._refresh_clean()
        trees = [item for item in self.items if item['kind'] == 'tree']
        if trees:
            threading.Thread(target=self._measure, args=(generation, trees), daemon=True).start()

    def _item_text(self, item):
        text = item['purpose']
        if item['reason']:
            text += '\n' + item['reason']
        return text + '\n' + item['path']

    def _show_status(self, status):
        download = status['download']
        free = free_bytes(download)
        free_text = format_bytes(free) if free is not None else tr('暂时读不到')
        if status['problem'] == 'download_link':
            self.location.configure(text=tr('之后的准备使用：{}\n下载仍使用原来的位置：{}\n剩余空间：{}').format(
                status['effective'], download, free_text))
        elif status['configured'] and not status['problem']:
            self.location.configure(text=tr('之后的下载和准备使用：{}\n下载目录：{}\n剩余空间：{}').format(
                status['effective'], download, free_text))
        else:
            self.location.configure(text=tr('当前仍使用原来的位置：{}\n下载目录：{}\n剩余空间：{}').format(
                status['effective'], download, free_text))
        problem = status['problem']
        if problem == 'missing':
            note = tr('上次选的文件夹现在不存在。下载和准备仍使用原来的位置，其他功能不受影响。')
        elif problem == 'link':
            note = tr('上次选的位置是符号链接或目录联接，已忽略。下载和准备仍使用原来的位置。')
        elif problem == 'unwritable':
            note = tr('上次选的文件夹现在不能写入。下载和准备仍使用原来的位置。')
        elif problem == 'download_link':
            note = tr('所选文件夹里的 downloads 是符号链接或目录联接。下载仍使用原来的位置，准备仍使用所选文件夹。')
        elif problem:
            note = tr('上次选的位置目前不能使用。下载和准备仍使用原来的位置，其他功能不受影响。')
        elif self.scope_kit:
            note = tr('默认不清理。可以勾选要删除的项；不勾选就什么都不会删。')
        else:
            note = ''
        self.notice.configure(text=note)

    def _measure(self, generation, trees):
        updates = []
        for item in trees:
            if generation != self.generation:
                return
            size = measure_tree(item['path'])
            updates.append((item['path'], size))
        try:
            self.after(0, lambda generation=generation, updates=updates: self._apply_sizes(generation, updates))
        except tk.TclError:
            return

    def _apply_sizes(self, generation, updates):
        try:
            if not self.winfo_exists() or generation != self.generation:
                return
        except tk.TclError:
            return
        by_path = {item['path']: item for item in self.items}
        for path, size in updates:
            item = by_path.get(path)
            variable = self.size_vars.get(path)
            if item is None or variable is None:
                continue
            if size is None:
                item['enabled'] = False
                item['bytes'] = None
                item['reason'] = tr('目录里含有链接，已跳过。')
                checked = self.checked.get(path)
                if checked is not None:
                    checked.set(False)
                widget = self.checks.get(path)
                if widget is not None:
                    widget.configure(state='disabled')
                label = self.labels.get(path)
                if label is not None:
                    label.configure(text=self._item_text(item))
                variable.set(tr('已跳过'))
            else:
                item['bytes'] = size
                variable.set(format_bytes(size))

    def _refresh_clean(self):
        selected = False
        for item in self.items:
            variable = self.checked.get(item['path'])
            if item['enabled'] and variable is not None and variable.get():
                selected = True
                break
        self.clean_button.configure(state='normal' if selected else 'disabled')

    def choose(self):
        selected = filedialog.askdirectory(parent=self, title=tr('选择大文件目录'), mustexist=True)
        if not selected:
            return
        self._apply_choice(set_work_root(self.stable, selected))

    def restore(self):
        self._apply_choice(set_work_root(self.stable, None))

    def _apply_choice(self, result):
        if result == 'saved':
            note = tr('之后开始的下载和准备会使用这个文件夹。正在进行的操作不会被打断，已有文件不会搬走。')
        elif result == 'default':
            note = tr('已恢复默认位置。已有文件仍留在原地，当前使用不会被打断。')
        elif result == 'link':
            note = tr('不能使用符号链接或目录联接。请选择真实文件夹。')
        elif result == 'bundle':
            note = tr('不能选在程序自身目录里。请选择其他磁盘上的文件夹。')
        elif result == 'inside_private':
            note = tr('请选择个人材料目录以外的文件夹。原来的位置不用再选一次。')
        elif result == 'downloads':
            note = tr('下载缓存不能当作大文件目录。请选择一个单独的文件夹。')
        elif result == 'nested':
            note = tr('不能选在已有的准备目录里面。请换一个文件夹。')
        elif result == 'unwritable':
            note = tr('这个文件夹现在不能写入。请检查权限或换一个文件夹。')
        elif result == 'missing':
            note = tr('所选文件夹不存在。请另选一个已有文件夹；当前使用仍走原来的位置。')
        else:
            note = tr('这个位置没有改成新的目录。当前使用仍走原来的位置。')
        self.reload()
        self.notice.configure(text=note)

    def open_folder(self):
        status = location_status(self.stable)
        path = status['download'] if status['configured'] and not status['problem'] else status['effective']
        target = Path(path)
        if not target.exists():
            target = target.parent
        if not target.is_dir():
            self.notice.configure(text=tr('文件夹暂时打不开。当前使用不受影响。'))
            return
        try:
            if sys.platform == 'win32':
                os.startfile(target)  # noqa: S606 — user asked to view the chosen folder
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(target)])
            else:
                subprocess.Popen(['xdg-open', str(target)])
        except OSError:
            self.notice.configure(text=tr('文件夹暂时打不开。当前使用不受影响。'))

    def clean(self):
        selected = [item for item in self.items
                    if item['enabled'] and self.checked.get(item['path']) is not None and self.checked[item['path']].get()]
        if not selected:
            return
        total = sum(item['bytes'] or 0 for item in selected)
        if not messagebox.askyesno(
                tr('清理所选文件'),
                tr('将删除 {} 项，合计 {}。密钥、连接和刷写记录不会删除。').format(len(selected), format_bytes(total)),
                parent=self, default='no'):
            return
        deleted, failed = delete_items(selected, self.stable)
        self.reload()
        if failed:
            self.notice.configure(text=tr('已删除 {} 项。还有 {} 项没有删除，可以稍后再试。').format(len(deleted), len(failed)))
        else:
            self.notice.configure(text=tr('已删除 {} 项。').format(len(deleted)))
