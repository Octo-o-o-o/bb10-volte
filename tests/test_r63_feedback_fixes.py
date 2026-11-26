"""Regression tests for v0.5.0-r63 desktop feedback diagnostics and driver UX fixes."""
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

import feedback
import root_setup
import setup_wizard


def _tk_available():
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        r.destroy()
        return True
    except Exception:
        return False


class R63FeedbackFixesTests(unittest.TestCase):
    def test_discovery_reason_covers_apipa_http_timeout_refused_and_ok(self):
        # 1. USB present + network up, but /16 APIPA instead of /30 -> no_link_local_30
        apipa = {'index': 19, 'active': True, 'ipv4': ['169.254.12.34'], 'prefixes': {'169.254.12.34': 16}}
        state = {'usb_present': True, 'usb_count': 1, 'usb_network': True, 'network_interfaces': [apipa]}
        with patch.object(root_setup.sys, 'platform', 'win32'), \
                patch.object(root_setup, 'powershell', return_value='powershell.exe'), \
                patch.object(root_setup.subprocess, 'run',
                             return_value=MagicMock(returncode=0, stdout=json.dumps(state))), \
                patch.object(root_setup, 'discovery') as probe:
            usb = root_setup.local_usb_state()
        probe.assert_not_called()
        self.assertEqual(usb['device'], {})
        self.assertEqual(usb['discovery_reason'], 'no_link_local_30')

        # 2. HTTP 401/403 from discovery.cgi -> http_401 / http_403
        link30 = {'index': 19, 'active': True, 'ipv4': ['169.254.237.210'], 'prefixes': {'169.254.237.210': 30}}
        state30 = {'usb_present': True, 'usb_count': 1, 'usb_network': True, 'network_interfaces': [link30]}
        for status_code, expected_reason in [(401, 'http_401'), (403, 'http_403')]:
            conn = MagicMock()
            conn.getresponse.return_value = MagicMock(status=status_code)
            with patch.object(root_setup.sys, 'platform', 'win32'), \
                    patch.object(root_setup, 'powershell', return_value='powershell.exe'), \
                    patch.object(root_setup.subprocess, 'run',
                                 return_value=MagicMock(returncode=0, stdout=json.dumps(state30))), \
                    patch.object(root_setup.http.client, 'HTTPConnection', return_value=conn), \
                    patch.object(root_setup.socket, 'socket', return_value=MagicMock()):
                usb = root_setup.local_usb_state()
            self.assertEqual(usb['device'], {})
            self.assertEqual(usb['discovery_reason'], expected_reason)

        # 3. Socket timeout and connection refused
        for exc, expected_reason in [(socket.timeout('timed out'), 'timeout'),
                                     (ConnectionRefusedError('refused'), 'connection_refused')]:
            sock = MagicMock()
            sock.connect.side_effect = exc
            with patch.object(root_setup.sys, 'platform', 'win32'), \
                    patch.object(root_setup, 'powershell', return_value='powershell.exe'), \
                    patch.object(root_setup.subprocess, 'run',
                                 return_value=MagicMock(returncode=0, stdout=json.dumps(state30))), \
                    patch.object(root_setup.http.client, 'HTTPConnection', return_value=MagicMock()), \
                    patch.object(root_setup.socket, 'socket', return_value=sock):
                usb = root_setup.local_usb_state()
            self.assertEqual(usb['device'], {})
            self.assertEqual(usb['discovery_reason'], expected_reason)

        # 4. Successful XML metadata -> ok
        conn = MagicMock()
        resp = MagicMock(status=200)
        resp.read.return_value = b'<d><ModelName>SQK100-1</ModelName><PlatformVersion>10.3.3.3216</PlatformVersion></d>'
        conn.getresponse.return_value = resp
        with patch.object(root_setup.sys, 'platform', 'win32'), \
                patch.object(root_setup, 'powershell', return_value='powershell.exe'), \
                patch.object(root_setup.subprocess, 'run',
                             return_value=MagicMock(returncode=0, stdout=json.dumps(state30))), \
                patch.object(root_setup.http.client, 'HTTPConnection', return_value=conn), \
                patch.object(root_setup.socket, 'socket', return_value=MagicMock()):
            usb = root_setup.local_usb_state()
        self.assertEqual(usb['device']['ModelName'], 'SQK100-1')
        self.assertEqual(usb['discovery_reason'], 'ok')

    def test_feedback_projection_keeps_discovery_reason_and_blocked_process(self):
        projected = feedback.project({
            'usb': {
                'usb_present': True,
                'usb_network': True,
                'discovery_reason': 'no_link_local_30',
                'usb_peer': '169.254.1.1',  # must still be dropped
                'device': {},
            },
            'blocked_process': 'nginx',
        })
        self.assertEqual(projected['usb']['discovery_reason'], 'no_link_local_30')
        self.assertNotIn('usb_peer', projected['usb'])
        self.assertEqual(projected['blocked_process'], 'nginx')

        # Reject unsafe/PII/long blocked_process strings (paths, IPv4, IMEI/phone, 40+ char tokens)
        for bad in (
            'C:\\bad\\nginx.exe --secret',
            '169.254.0.1',
            '460' + '01' + '12345' + '67890',
            '138' + '0013' + '8000',
            'proc' + '1234' + '567',
            'a' * 40,
        ):
            unsafe = feedback.project({'blocked_process': bad})
            self.assertNotIn('blocked_process', unsafe, f'Should reject {bad}')
        # Allow short vendor process names including 8.3 short names like RIMDEV~1
        self.assertEqual(feedback.project({'blocked_process': 'RIMDEV~1'})['blocked_process'], 'RIMDEV~1')

    def test_usb_discovery_hint_mentions_reason_and_offline_download(self):
        for reason in ('no_link_local_30', 'http_401', 'http_403', 'timeout',
                       'connection_refused', 'unreachable', 'multiple_usb_devices',
                       'multiple_usb_links', 'empty_metadata'):
            hint = setup_wizard._usb_discovery_hint({
                'usb_present': True,
                'usb_network': True,
                'device': {},
                'discovery_reason': reason,
            })
            self.assertTrue(hint, f'Expected hint for {reason}')
        multi_hint = setup_wizard._usb_discovery_hint({
            'usb_present': True, 'usb_network': True, 'device': {},
            'discovery_reason': 'multiple_usb_devices',
        })
        self.assertEqual(
            multi_hint,
            setup_wizard.tr('机型识别提示：检测到多台黑莓 USB 设备，已跳过自动读取以避免混淆。请只连接一台手机后重新检测；若只需先下载固件，可拔掉全部数据线并点击“重新检测”，再手动选择型号。'),
        )
        # No hint when ModelName is already identified
        self.assertEqual(setup_wizard._usb_discovery_hint({
            'usb_present': True, 'usb_network': True,
            'device': {'ModelName': 'SQK100-1'}, 'discovery_reason': 'ok',
        }), '')

    @unittest.skipUnless(_tk_available(), 'Tk display unavailable')
    def test_feedback_dialog_omits_hidden_flash_lock_banner_and_setup_wizard_names_blocked_process(self):
        import tkinter as tk
        import feedback_gui

        root = tk.Tk()
        root.withdraw()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                lock_file = Path(tmp) / 'root-flash.lock'
                with patch.object(setup_wizard, 'root_lock_path', return_value=lock_file), \
                        patch.object(setup_wizard, 'prepared_kit_history', return_value=[]):
                    wiz = setup_wizard.SetupWizard(root, lambda *_: None, auto_check=False)
                    # Unlocked: flash_lock_bar is unpacked and flash_lock_label is blank
                    self.assertFalse(wiz.flash_lock_bar.winfo_manager())
                    self.assertEqual(wiz.flash_lock_label.cget('text'), '')
                    self.assertFalse(feedback_gui._widget_visible_in(wiz.flash_lock_label, wiz))

                    expected_lock = setup_wizard.tr('检测到上次刷写处于暂停状态，刷写与重新准备已锁定（仍可安装 Windows 驱动）。')
                    # Even if a hidden label has static text, _widget_visible_in must exclude it
                    wiz.flash_lock_label.configure(text='SHOULD_NOT_LEAK_WHEN_HIDDEN')
                    dlg = feedback_gui.FeedbackDialog(wiz, 'connect')
                    observed = [e for e in dlg.journal.events if e['action'] == 'open_feedback'][-1]
                    self.assertNotIn('SHOULD_NOT_LEAK_WHEN_HIDDEN', observed.get('message', ''))
                    self.assertNotIn(expected_lock, observed.get('message', ''))
                    dlg.close()

                    # Locked: banner is packed, label text populated, and captured by FeedbackDialog
                    lock_file.write_text('{"pid": 0}', encoding='utf-8')
                    wiz.refresh()
                    self.assertTrue(wiz.flash_lock_bar.winfo_manager())
                    self.assertTrue(feedback_gui._widget_visible_in(wiz.flash_lock_label, wiz))
                    self.assertEqual(wiz.flash_lock_label.cget('text'), expected_lock)
                    dlg2 = feedback_gui.FeedbackDialog(wiz, 'connect')
                    observed2 = [e for e in dlg2.journal.events if e['action'] == 'open_feedback'][-1]
                    self.assertIn(expected_lock, observed2.get('message', ''))
                    dlg2.close()

                    # Driver blocked_process error names exact process (nginx) in UI status
                    wiz.events.put(('error', ('driver_process_running', {'blocked_process': 'nginx'})))
                    wiz.drain()
                    self.assertIn('nginx', wiz.status.cget('text'))

                    wiz.close()
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
