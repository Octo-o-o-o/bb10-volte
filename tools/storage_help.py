"""Show the actual storage locations without deleting user data."""
from tkinter import messagebox

from desktop_paths import private_root, download_root
from i18n import tr


def show_storage_help(parent):
    messagebox.showinfo(
        tr('存储位置与磁盘清理'),
        tr('下载缓存：{}\n个人材料：{}\n\n先关闭所有本程序和刷写窗口。下载缓存可以删除，下次需要时会重新下载。\n\n确认只是电脑准备失败、从未开始手机刷写，或手机已正常启动、Root 和连接已确认且无需继续刷写或恢复时，可删除 root-kit 或 root-kit-* 内的 stock、images、stock-upgrade 子目录。\n\n不要删除整个 private 或 root-kit 目录；保留个人密钥、ssh_config、known_hosts、备份、日志和刷写记录。刷写中断或状态不明时先保留全部材料。').format(download_root(), private_root()),
        parent=parent)
