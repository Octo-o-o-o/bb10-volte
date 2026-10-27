"""Mac app entry point with a local startup diagnostic when necessary."""
import sys
import traceback
import uuid
from desktop_paths import private_root


if __name__ == '__main__':
    try:
        from gui import main
        result = main()
    except Exception:
        folder = private_root()
        folder.mkdir(parents=True, exist_ok=True)
        report = folder/('startup-error-'+uuid.uuid4().hex[:12]+'.txt')
        report.write_text(traceback.format_exc(), encoding='utf-8')
        if not any(x in sys.argv for x in ('--self-test', '--preflight-report')):
            try:
                import tkinter as tk
                from tkinter import messagebox
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror('bb10-volte', '程序未能启动。诊断信息保存在本机：\n' + str(report), parent=root)
                root.destroy()
            except Exception:
                pass
        result = 1
    sys.exit(result)
