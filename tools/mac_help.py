"""Offline Mac connection guidance for the three supported starting situations."""
import tkinter as tk
from tkinter import ttk

from desktop_paths import resource_root
from profile_editor import FONT

CONNECTION_HINT = (
    '先接数据线并解锁，再点“连接手机”。需要恢复授权、处理 USB 网络或首次 Root 时，打开“连接帮助”。')

PHONE_STEPS = (
    '未 Root：本分支提供 Q10 的实验性 Mac 首刷，须先核对变体并备份；Q30 / Q20 尚缺匹配首刷材料。\n'
    '已 Root、无连接资料：点“恢复连接 → 没有连接文件”，通过手机已有 Root 终端授权本机。\n'
    '已 Root、有连接资料：导入本机可用的个人 SSH 配置；只有登录私钥时，走“恢复连接 → 有登录私钥”。\n\n'
    '先接数据线并解锁；若没有 USB 网络，在手机“设置 → 存储和访问 → USB 连接”选择“连接至 Mac”。\n'
    '已有可用 Root SSH 时无需开启开发模式。无原密钥且无有效 Root 终端时，需先恢复手机访问。')

TRANSFER_HINT = (
    'Mac 不一定能在 Finder 中打开手机内部存储。可用本人已有的传输方式，或用读卡器将公开脚本放到媒体卡，'
    '再由手机文件管理器复制到内部 Downloads；结果也从内部 Downloads 经媒体卡带回本 Mac。'
    '按手机提示安全移除存储卡；不需要格式化，也不要把电脑私钥复制到手机。')


def scrolled_page(parent, padding=18):
    """Keep longer Mac instructions reachable at the wizard's minimum size."""
    page = ttk.Frame(parent)
    canvas = tk.Canvas(page, highlightthickness=0, borderwidth=0,
                       background=ttk.Style(parent).lookup('TFrame', 'background') or '#f0f0f0')
    scrollbar = ttk.Scrollbar(page, orient='vertical', command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side='right', fill='y')
    canvas.pack(side='left', fill='both', expand=True)
    content = ttk.Frame(canvas, padding=padding)
    window = canvas.create_window(0, 0, anchor='nw', window=content)
    content.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda event: canvas.itemconfigure(window, width=event.width))
    # Bind each page's toplevel, and only handle wheel events from its subtree.
    # Destroying the page also removes this additive binding.
    toplevel = parent.winfo_toplevel()
    def wheel(event):
        if str(event.widget).startswith(str(page) + '.') and canvas.winfo_ismapped():
            canvas.yview_scroll(-int(event.delta), 'units')
            return 'break'
    binding = toplevel.bind('<MouseWheel>', wheel, add='+')
    page.bind('<Destroy>', lambda event: toplevel.unbind('<MouseWheel>', binding)
              if event.widget is page else None)
    return page, content


def show_guide(parent):
    """Open the bundled user guide, preserving a wizard's modal grab on close."""
    previous = parent.grab_current()
    popup = tk.Toplevel(parent)
    popup.title('Mac 连接说明 · 按手机现状准备')
    popup.geometry('820x650')
    popup.minsize(640, 450)
    popup.transient(parent)
    body = ttk.Frame(popup, padding=18)
    body.pack(fill='both', expand=True)
    text = tk.Text(body, wrap='word', font=(FONT, 11), padx=12, pady=12,
                   bg='white', relief='flat')
    scroll = ttk.Scrollbar(body, command=text.yview)
    scroll.pack(side='right', fill='y')
    text.configure(yscrollcommand=scroll.set)
    text.pack(fill='both', expand=True)
    text.insert('1.0', (resource_root() / 'docs/MACOS.md').read_text(encoding='utf-8'))
    text.configure(state='disabled')

    def close():
        popup.destroy()
        if previous is not None and previous.winfo_exists():
            previous.grab_set()

    popup.protocol('WM_DELETE_WINDOW', close)
    ttk.Button(popup, text='关闭', command=close).pack(anchor='e', padx=18, pady=(0, 12))
    if previous is not None:
        popup.grab_set()
    return popup
