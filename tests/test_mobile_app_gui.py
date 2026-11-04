"""Native app provisioning UI, using real Tk and feedback delivery without SSH."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import feedback
import i18n
import mobile_app_gui as gui
from profile_editor import FONT
from ui_theme import apply_theme
from workflow import WorkflowError


class MobileAppPresentationTests(unittest.TestCase):
    def test_installed_guidance_distinguishes_first_activation_and_daily_startup(self):
        for language, activation, automatic, unfinished in (
                ('zh', '备份并启用', '开机启动', '未完成的任务'),
                ('en', 'back up and enable', 'starts with the phone', 'unfinished tasks')):
            with self.subTest(language=language), patch.object(i18n, 'LANGUAGE', language):
                title, detail = gui.presentation({'state': 'installed'})
                self.assertTrue(title)
                self.assertIn(activation, detail)
                self.assertIn(automatic, detail)
                self.assertIn(unfinished, detail)


class MobileAppGuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest('Tk display unavailable: ' + str(error))
        self.addCleanup(self.root.destroy)
        self.root.attributes('-alpha', 0.0)
        self.root.option_add('*Font', (FONT, 11))
        apply_theme(self.root, FONT)
        self.root._feedback_journal = feedback.Journal(Path(self.temp.name))
        self.root.update()

        self.language = patch.object(i18n, 'LANGUAGE', 'zh')
        self.language.start(); self.addCleanup(self.language.stop)
        self.app = gui.MobileAppInstallWindow(self.root, 'test-host', '/not-a-real-config')
        self.app.window.attributes('-alpha', 0.0)
        self.root.update()

    def tearDown(self):
        if hasattr(self, 'app') and self.app.window.winfo_exists():
            self.app.busy = False
            self.app.close()

    def drain(self):
        self.app.window.after_cancel(self.app.poll_job)
        self.app.poll()
        self.root.update_idletasks()

    def test_real_feedback_delivers_pending_result_without_resubmitting(self):
        pending = {'schema': 1, 'state': 'pending', 'can_install': False, 'variant': 'SQC100-2'}
        self.app.busy = True
        self.app.events.begin('install')
        self.app.events.put(('result', ('install', pending)))
        self.drain()
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.report, pending)
        self.assertIn('同一安装任务', self.app.title.cget('text'))
        self.assertIsNotNone(self.app.recheck_job)
        self.assertEqual(str(self.app.install_button.cget('state')), 'disabled')
        self.assertTrue(self.root._feedback_journal.persistence_ok)
        events = self.root._feedback_journal.history()[-1]['events']
        self.assertEqual(events[-1]['details']['state'], 'pending')
        self.app.close()
        self.assertFalse(self.app.window.winfo_exists())

    def test_transport_failure_returns_to_inspection_without_retrying_install(self):
        manager = self.app.installer = Mock()
        manager.install.side_effect = WorkflowError('mobile_app_result_unconfirmed')
        self.app.bar = '/reviewed.bar'
        self.app.report = {'can_install': True, 'device_id': 'a' * 32}
        with patch.object(gui.threading, 'Thread', side_effect=lambda target, **kwargs: SimpleNamespace(start=target)):
            self.app.run('install')
        self.assertTrue(self.app.busy)
        self.app.run('install')  # Rapid duplicate clicks cannot enter the worker.
        self.drain()
        manager.install.assert_called_once_with('/reviewed.bar', 'a' * 32)
        self.assertIsNone(self.app.installer)
        self.assertIn('结果待确认', self.app.title.cget('text'))
        self.assertEqual(str(self.app.install_button.cget('state')), 'disabled')
        self.assertIsNone(self.app.recheck_job)

    def test_repeated_pending_observation_preserves_explanation_scroll_position(self):
        self.app.window.geometry('680x500')
        tk.Label(self.app.body, text='Additional diagnostic detail\n' * 12).pack()
        pending = {'schema': 1, 'state': 'pending', 'can_install': False}
        self.app.events.put(('result', ('inspect', pending)))
        self.drain(); self.root.update()
        self.app.canvas.yview_moveto(1)
        position = self.app.canvas.yview()
        self.assertGreater(position[0], 0)
        self.app.window.after_cancel(self.app.recheck_job)
        self.app.recheck_job = None
        self.app.events.put(('result', ('inspect', pending)))
        self.drain()
        self.assertEqual(self.app.canvas.yview(), position)

    def test_initial_check_never_installs_and_close_waits_for_inflight_result(self):
        self.assertEqual(str(self.app.install_button.cget('state')), 'disabled')
        manager = self.app.installer = Mock()
        manager.inspect.return_value = {'schema': 1, 'state': 'absent', 'can_install': True,
                                        'device_id': 'a' * 32, 'variant': 'SQC100-2'}
        with patch.object(gui.threading, 'Thread', side_effect=lambda target, **kwargs: SimpleNamespace(start=target)):
            self.app.run('inspect')
        self.app.close()
        self.assertTrue(self.app.window.winfo_exists())
        self.drain()
        manager.inspect.assert_called_once_with()
        manager.install.assert_not_called()
        self.assertEqual(Path(self.app.bar), gui.bundled_bar(self.app.pin))
        self.assertEqual(str(self.app.install_button.cget('state')), 'normal')

    def test_controls_fit_minimum_window_in_both_languages(self):
        for language in ('zh', 'en'):
            with self.subTest(language=language), patch.object(i18n, 'LANGUAGE', language):
                self.app.close()
                self.app = gui.MobileAppInstallWindow(self.root, 'test-host', '/not-a-real-config')
                self.app.window.attributes('-alpha', 0.0)
                self.app.window.geometry('680x500')
                for state in ('absent', 'pending', 'installed'):
                    self.app.events.put(('result', ('inspect', {'state': state, 'can_install': False})))
                    self.drain(); self.root.update()
                    left, top = self.app.window.winfo_rootx(), self.app.window.winfo_rooty()
                    width, height = self.app.window.winfo_width(), self.app.window.winfo_height()
                    for widget in (self.app.file, self.app.status, self.app.check_button,
                                   self.app.choose_button, self.app.install_button, self.app.connect_button):
                        self.assertTrue(widget.winfo_ismapped(), str(widget))
                        self.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight())
                        self.assertGreaterEqual(widget.winfo_rootx(), left)
                        self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), left + width)
                        self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), top + height)
                    for widget in self.app.wrapped_labels:
                        self.assertLessEqual(widget.winfo_reqwidth(), widget.winfo_width())
                        self.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight())
                    self.assertGreater(self.app.canvas.winfo_height(), 80)
                    self.app.canvas.yview_moveto(1)
                    self.root.update_idletasks()
                    self.assertAlmostEqual(self.app.canvas.yview()[1], 1.0, places=2)
                    self.app.canvas.yview_moveto(0)
                    self.assertAlmostEqual(self.app.canvas.yview()[0], 0.0, places=2)


if __name__ == '__main__':
    unittest.main()
