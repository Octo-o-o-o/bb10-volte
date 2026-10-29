"""Launch the real Tk UI in a dedicated read-only recording session."""
import argparse
import ctypes
import json
from pathlib import Path
import sys
import tkinter as tk

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from gui import App

p = argparse.ArgumentParser()
p.add_argument('--ssh-config', required=True)
p.add_argument('--host', default='q10-root')
args = p.parse_args()
ctypes.windll.shcore.SetProcessDpiAwareness(1)
root = tk.Tk()
root.tk.call('tk', 'scaling', 1.55)
app = App(root, args.host, args.ssh_config, auto_connect=False)
root.title('BB10 VoLTE - Q10 Demo')
root.geometry('1000x780+90+80')
original_run = app.run
def readonly_run(action):
    if action not in ('preflight', 'status'):
        raise RuntimeError('Recording session permits only preflight and status')
    return original_run(action)
app.run = readonly_run
evidence = ROOT / 'docs/recordings/evidence'
evidence.mkdir(parents=True, exist_ok=True)
last = None
def save_evidence():
    global last
    if app.last_result is not None:
        encoded = json.dumps(app.last_result, ensure_ascii=False, indent=2)
        if encoded != last:
            (evidence / 'gui-last-result.json').write_text(encoded + '\n', encoding='utf-8')
            last = encoded
    root.after(500, save_evidence)
save_evidence()
root.mainloop()
