"""Completion gates and optional support UI; no phone or payment operations."""
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import build_windows
import check_release
import completion_dialog
import gui
import i18n
from support_config import CONTACT_EMAIL, OCTOLAB_URL, PROJECT_WEBSITE_URL, QR_FILES, REPOSITORY_URL


def verified_result():
    return {'installed': True, 'registration': 'verified', 'call_acceptance': 'pending',
            'status': {'phase': 'running', 'manager_alive': True, 'native_alive': True,
                       'current': {'ims': 'connected', 'register_status': '200 OK',
                                   'ran': 'LTE', 'radio': ['lte']}}}


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        for target, value in (('gui.private_root', self.folder), ('gui.saved_connection', None),
                              ('completion_dialog.resource_root', self.folder)):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(i18n, 'LANGUAGE', 'zh')
        patcher.start()
        self.addCleanup(patcher.stop)
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest('Tk display unavailable: ' + str(error))
        self.root.withdraw()
        self.app = gui.App(self.root)
        self.addCleanup(self.app.close)

    def deliver(self, action, result):
        self.root.after_cancel(self.app._drain_job)
        self.app.events.put(('result', (action, result)))
        self.app.drain()

    def receipt(self, provider, amount, invalid=False):
        path = self.folder / QR_FILES[provider][amount]
        path.parent.mkdir(parents=True, exist_ok=True)
        if invalid:
            path.write_text('unreadable receipt image', encoding='utf-8')
        else:
            # A solid test image, never a scannable payment code.
            photo = tk.PhotoImage(master=self.root, width=240, height=240)
            photo.put('white', to=(0, 0, 240, 240))
            photo.write(str(path), format='png')
        return path

    def test_verified_install_opens_page_and_preserves_pending_call_acceptance(self):
        value = verified_result()
        with patch.object(gui, 'Client') as client, patch.object(completion_dialog.webbrowser, 'open') as browser:
            self.deliver('install', value)
            popup = self.app.completion_dialog
            self.assertIsInstance(popup, completion_dialog.CompletionDialog)
            self.assertFalse(popup.payment.winfo_manager())
            self.assertIsNone(popup.grab_current())
            self.assertEqual(self.app.last_result['call_acceptance'], 'pending')
            self.assertEqual(value, verified_result())
            popup.done_button.invoke()
            self.assertFalse(popup.winfo_exists())
            self.assertTrue(self.app.completion_available)
            browser.assert_not_called()
            client.assert_not_called()

    def test_pending_registration_later_status_completes_only_once(self):
        self.deliver('install', {'installed': True, 'registration': 'pending', 'status': {}})
        self.assertIsNone(self.app.completion_dialog)
        value = verified_result()
        value.pop('registration')
        value['registered'] = True
        self.deliver('status', value)
        self.assertIsNotNone(self.app.completion_dialog)
        self.app.completion_dialog.destroy()
        with patch.object(self.app, 'show_completion') as show:
            self.deliver('status', value)
            self.deliver('preflight', value)
            show.assert_not_called()
        self.app.show_completion()
        self.assertTrue(self.app.completion_dialog.winfo_exists())

    def test_verified_start_can_complete(self):
        self.deliver('start', verified_result())
        self.assertTrue(self.app.completion_available)

    def test_read_only_discovery_never_opens_a_support_page(self):
        with patch.object(self.app, 'show_completion') as show:
            for action in ('preflight', 'status'):
                self.deliver(action, verified_result())
            show.assert_not_called()
        self.assertFalse(self.app.completion_available)

    def test_success_flag_without_live_service_or_lte_is_insufficient(self):
        for field, value in (('manager_alive', False), ('native_alive', False), ('phase', 'error')):
            result = verified_result()
            result['status'][field] = value
            self.deliver('install', result)
            self.assertFalse(self.app.completion_available)
        result = verified_result()
        result['status']['current']['ran'] = '3G'
        self.deliver('install', result)
        self.assertIsNone(self.app.completion_dialog)

    def test_pending_setup_survives_a_read_only_connection_error(self):
        self.deliver('install', {'registration': 'pending'})
        self.root.after_cancel(self.app._drain_job)
        self.app.events.put(('error', ('connection_failed', None)))
        self.app.drain()
        self.deliver('status', verified_result())
        self.assertTrue(self.app.completion_available)

    def test_changed_connection_does_not_celebrate_another_phone(self):
        self.deliver('install', {'registration': 'pending'})
        self.app.host.set('another-phone')
        self.deliver('status', verified_result())
        self.assertIsNone(self.app.completion_dialog)

    def test_restore_closes_success_and_clears_pending_flow(self):
        self.deliver('install', verified_result())
        popup = self.app.completion_dialog
        self.deliver('disable', {'restored': True})
        self.assertFalse(popup.winfo_exists())
        self.assertFalse(self.app.completion_available)
        self.assertFalse(self.app.completion_pending)

    def test_fixed_generic_custom_and_missing_codes_explain_the_actual_amount(self):
        self.receipt('alipay', '9.90')
        self.receipt('alipay', 'custom')
        self.deliver('install', verified_result())
        popup = self.app.completion_dialog
        popup.coffee_button.invoke()
        self.assertEqual(popup.payment.winfo_manager(), 'pack')
        self.assertIn('支持 ¥9.90', popup.receipt_note.cget('text'))
        self.assertIsNotNone(popup.qr_image)
        popup.amount_buttons['19.90'].invoke()
        self.assertIn('手动填写 ¥19.90', popup.receipt_note.cget('text'))
        popup.amount_buttons['29.90'].invoke()
        self.assertIn('手动填写 ¥29.90', popup.receipt_note.cget('text'))
        popup.amount_buttons['custom'].invoke()
        self.assertIn('填写你想支持的金额', popup.receipt_note.cget('text'))
        popup.provider_buttons['wechat'].invoke()
        self.assertIsNone(popup.qr_image)
        self.assertEqual(str(popup.qr_label.cget('image')), '')
        self.assertIn('暂未开放', popup.receipt_note.cget('text'))
        popup.coffee_button.invoke()
        self.assertFalse(popup.payment.winfo_manager())

    def test_unreadable_receipt_keeps_done_and_other_support_available(self):
        self.receipt('alipay', '9.90', invalid=True)
        self.deliver('install', verified_result())
        popup = self.app.completion_dialog
        popup.coffee_button.invoke()
        self.assertIsNone(popup.qr_image)
        self.assertIn('无法显示', popup.receipt_note.cget('text'))
        popup.done_button.invoke()
        self.assertFalse(popup.winfo_exists())

    def test_links_require_a_click_and_email_can_be_copied(self):
        with patch.object(completion_dialog.webbrowser, 'open', return_value=True) as browser:
            self.deliver('install', verified_result())
            popup = self.app.completion_dialog
            browser.assert_not_called()
            popup.copy_button.invoke()
            self.assertEqual(popup.clipboard_get(), CONTACT_EMAIL)
            popup.open_link(REPOSITORY_URL)
            browser.assert_called_once_with(REPOSITORY_URL)
            popup.open_link('mailto:' + CONTACT_EMAIL)
            self.assertEqual(browser.call_args.args, ('mailto:' + CONTACT_EMAIL,))
            popup.brand_button.invoke()
            self.assertEqual(browser.call_args.args, ('https://octoooo.com/',))
            self.assertEqual(OCTOLAB_URL, browser.call_args.args[0])
        with patch.object(completion_dialog.webbrowser, 'open', return_value=False):
            popup.open_link(REPOSITORY_URL)
            self.assertIn(REPOSITORY_URL, popup.link_status.cget('text'))

    def test_share_copies_localized_text_and_the_same_website_only_on_click(self):
        messages = {}
        for language in ('zh', 'en'):
            with self.subTest(language=language), patch.object(i18n, 'LANGUAGE', language), \
                    patch.object(completion_dialog.webbrowser, 'open') as browser:
                self.root.clipboard_clear()
                self.root.clipboard_append('existing clipboard')
                popup = completion_dialog.CompletionDialog(self.root)
                try:
                    self.assertEqual(popup.clipboard_get(), 'existing clipboard')
                    popup.share_button.invoke()
                    message = popup.clipboard_get()
                    messages[language] = message
                    self.assertIn('BB10 VoLTE', message)
                    self.assertEqual(message.splitlines()[-1], 'https://bb10-volte.octoooo.com/')
                    self.assertEqual(message.count(PROJECT_WEBSITE_URL), 1)
                    if language == 'zh':
                        self.assertIn('老黑莓重获新生', message)
                    else:
                        self.assertIn('new lease on life', message)
                        self.assertNotRegex(message, r'[\u4e00-\u9fff]')
                    self.assertTrue(popup.link_status.cget('text'))
                    popup.done_button.invoke()
                    self.assertEqual(self.root.clipboard_get(), message)
                    browser.assert_not_called()
                finally:
                    if popup.winfo_exists():
                        popup.destroy()
        self.assertNotEqual(messages['zh'], messages['en'])

    def test_packaging_includes_only_named_public_receipt_images(self):
        fixed = self.receipt('wechat', '29.90')
        (fixed.parent / 'unrelated-private-image.png').write_bytes(fixed.read_bytes())
        with patch.object(build_windows, 'ROOT', self.folder):
            names = build_windows.runtime_data()
        self.assertIn(QR_FILES['wechat']['29.90'], names)
        self.assertNotIn('assets/support/unrelated-private-image.png', names)
        # Source and desktop packaging use the same explicit optional image list.
        self.assertEqual(check_release.bundled_receipt_images(self.folder), [QR_FILES['wechat']['29.90']])


if __name__ == '__main__':
    unittest.main()
