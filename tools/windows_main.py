"""Windowed EXE entry point with a visible, local-only startup error report."""
from i18n import tr
import sys
import traceback
from desktop_paths import private_root


if __name__ == '__main__':
    try:
        from gui import main
        result = main()
    except Exception:
        folder = private_root()
        folder.mkdir(parents=True, exist_ok=True)
        report = folder / 'startup-error.txt'
        report.write_text(traceback.format_exc(), encoding='utf-8')
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, tr('程序未能启动。诊断信息保存在本机：\n') + str(report),
                                         'bb10-volte', 0x10)
        result = 1
    sys.exit(result)
