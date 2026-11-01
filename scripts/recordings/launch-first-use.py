"""Launch genuine Tk screens with deterministic demonstration data, no devices.

Run --scene connect|root|install|restart|ready|feedback. UI actions use the real
handlers; only backend boundaries are replaced. Subprocess/network access is
blocked, so this launcher cannot flash, connect to, or discover a real phone.
"""
import argparse
from copy import deepcopy
import ctypes
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import tkinter as tk
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import i18n
i18n.LANGUAGE = 'zh'
import gui
import setup_wizard as setup
import connection_dialog as connection
import auto_carrier_gui as automatic
import feedback
from feedback_gui import FeedbackDialog
from workflow import WorkflowError

parser = argparse.ArgumentParser()
parser.add_argument('--scene', choices=['home', 'connect', 'root', 'root-import', 'root-prepared', 'root-verified', 'install', 'restart', 'ready', 'feedback'], default='home')
parser.add_argument('--ready-file')
args = parser.parse_args()
scratch = tempfile.TemporaryDirectory(prefix='bb10-first-use-')
private = Path(scratch.name)
choice = {'host': 'demo-phone', 'config': str(private / 'ssh_config')}
usb = {'usb_count': 1, 'usb_present': True, 'usb_network': True, 'ssh_port': True,
       'device': {'ModelName': 'SQC100-2', 'PlatformVersion': '10.3.3.3216', 'DeveloperModeEnabled': '1'}}
model = {'root_ready': args.scene in ('install', 'restart', 'ready'),
         'installed': args.scene in ('restart', 'ready'), 'registered': args.scene == 'ready'}


def blocked(*args, **kwargs):
    raise RuntimeError('Demonstration boundary: external operation blocked')


def verify(*args, **kwargs):
    if not model['root_ready']:
        raise WorkflowError('connection_setup_required')
    return deepcopy(choice)


def import_firmware(path, progress, variant=None, **kwargs):
    progress('正在校验固件完整性与 SQC100-2 型号…')
    time.sleep(0.8)
    return str(private / 'firmware.exe')


def prepare(variant, progress, *args, **kwargs):
    progress('构建并校验系统与无线镜像；此步骤尚不刷写手机')
    time.sleep(1.2)
    return str(private / 'root-kit')


def flash(kit, confirmed, progress):
    progress('按已确认的机型分阶段处理，请保持连接。')
    time.sleep(1)
    model['root_ready'] = True
    return deepcopy(choice)


def state():
    return {'phase': 'running' if model['registered'] else 'reboot_required', 'enabled': True,
            'automatic_carrier_selection': True, 'status_from_current_boot': model['registered'],
            'selected_this_boot': model['registered'], 'selected_operator': 'unicom',
            'manager_alive': model['registered'], 'native_alive': model['registered'],
            'current': {'ims': 'connected' if model['registered'] else 'disconnected',
                        'register_status': '200 OK' if model['registered'] else '', 'ran': 'LTE', 'radio': ['lte']}}


class DemoClient:
    def probe(self):
        time.sleep(0.5)
        return {'variant': 'SQC100-2', 'operator': '中国联通', 'installed': model['installed'],
                'can_install': not model['installed'], 'status': state() if model['installed'] else {}}

    def install(self):
        time.sleep(1)
        model['installed'] = True
        return {'status': state(), 'desktop_backup': '本机个人目录 / bb10-volte / backups'}

    def action(self, action):
        time.sleep(0.6)
        if action == 'status':
            return state()
        raise WorkflowError('demonstration_readonly')


patches = [patch.object(gui, 'saved_connection', return_value=None),
    patch.object(setup, 'prepared_kit_history', return_value=[]),
    patch.object(setup, 'local_usb_state', side_effect=lambda: deepcopy(usb)),
    patch.object(setup, 'verify_root', side_effect=verify),
    patch.object(setup, 'import_stock_firmware', side_effect=import_firmware),
    patch.object(setup, 'prepare_root_kit', side_effect=prepare),
    patch.object(setup, 'prepared_images', return_value=({'variant': 'SQC100-2'}, [])),
    patch.object(setup, 'flash_root', side_effect=flash),
    patch.object(connection, 'local_usb_state', side_effect=lambda: deepcopy(usb)),
    patch.object(connection, 'verify_root', side_effect=verify),
    patch.object(automatic, 'resolve_connection', return_value=(None, choice)),
    patch.object(automatic, 'AutoClient', return_value=DemoClient()),
    patch.object(gui, 'resolve_connection', side_effect=blocked),
    patch.object(subprocess, 'Popen', side_effect=blocked),
    patch.object(socket.socket, 'connect', side_effect=blocked)]
for item in patches:
    item.start()
if sys.platform == 'win32':
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
root = tk.Tk()
root.tk.call('tk', 'scaling', 1.55)
root._feedback_journal = feedback.Journal(private / 'feedback')
app = gui.App(root, config='', auto_connect=False)
root.geometry('1080x780+50+40')
root.title('BB10 Tutorial - ' + args.scene)

if args.scene == 'connect':
    screen = connection.ConnectionDialog(root, lambda *args: None, auto_check=False)
    screen.usb, screen.error = deepcopy(usb), 'connection_setup_required'
    screen.show_guidance()
elif args.scene.startswith('root'):
    screen = setup.SetupWizard(root, lambda *args: None, auto_check=False,
                               initial_page='connection' if args.scene == 'root-verified' else 'root')
    screen.usb = deepcopy(usb)
    screen.variant.set('SQC100-2')
    screen.firmware_path.set('C:/BB10/Classic-SQC100-2.exe')
    if args.scene == 'root-prepared':
        screen.kit = str(private / 'root-kit')
        screen.imported_variant = 'SQC100-2'
        screen.status.configure(text='SQC100-2 的 Root 镜像与个人连接配置已准备。确认备份后，再继续刷写。')
    if args.scene == 'root-verified':
        screen.choice = choice
        screen.device.configure(text='SQC100-2 · 10.3.3.3216')
        screen.facts.configure(text='USB 设备：已就绪    USB 网络：已就绪\n开发模式：已开启    SSH 连接：已就绪\nRoot：已验证')
        screen.status.configure(text='Root 连接已验证，可以继续。开发模式无需为此保持开启。')
    screen.refresh()
elif args.scene in ('install', 'restart', 'ready'):
    controller = automatic.AutoCarrierWindow(root, 'demo-phone', '')
    screen = controller.window
    controller.events.put(('probe', DemoClient().probe(), None))
    if args.scene == 'restart':
        controller.events.put(('install', {'status': state(), 'desktop_backup': '本机个人目录 / bb10-volte / backups'}, None))
elif args.scene == 'feedback':
    journal = root._feedback_journal
    journal.record('connect', 'detect', 'started')
    journal.record('connect', 'detect', 'failed', message='authentication_failed', details={'usb': usb})
    journal.record('connect', 'detect', 'started')
    journal.record('connect', 'detect', 'finished', details={'usb': usb})
    screen = FeedbackDialog(root, 'connect')
    screen.note.insert('1.0', '连接时提示授权失败；重新导入连接材料后已恢复，希望确认是否还需处理。')
    screen.preview()
else:
    screen = root
if screen is not root:
    screen.title('BB10 Tutorial - ' + args.scene)
    screen.geometry('1000x820+60+40')
    root.title('BB10 Tutorial Launcher')
root.deiconify()
screen.deiconify()
screen.lift()
screen.focus_force()


def ready():
    if args.scene in ('root-prepared', 'root-import'):
        page = screen.nametowidget(screen.tabs.tabs()[1])
        def bottom(widget):
            if isinstance(widget, tk.Canvas):
                widget.yview_moveto(1 if args.scene == 'root-prepared' else .40)
            for child in widget.winfo_children():
                bottom(child)
        bottom(page)
    screen.update_idletasks()
    if args.ready_file:
        Path(args.ready_file).write_text(json.dumps({'scene': args.scene,
            'width': screen.winfo_width(), 'height': screen.winfo_height(),
            'dataMode': 'mock', 'deviceOperations': False}), encoding='utf-8')
root.after(600, ready)
root.mainloop()
