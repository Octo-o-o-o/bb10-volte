"""Offline cache import and wizard actions; no real browser or phone operations."""
import hashlib
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import i18n
i18n.LANGUAGE = 'zh'  # Wizard assertions below use Chinese.
import fetch_materials as f
import root_setup
import setup_wizard as w


class MaterialImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'cache'
        self.folder.mkdir()
        self.data = bytes(range(256)) * 4096 + b'complete firmware'
        self.source = self.root / '浏览器下载 (1).7z'
        self.source.write_bytes(self.data)
        self.item = {'file': 'fixed-firmware.7z', 'sha256': hashlib.sha256(self.data).hexdigest(),
                     'url': 'https://example.invalid/firmware.7z'}
        self.target, self.partial = f._input_paths(self.item, self.folder)
        self.messages = []
        network = patch.object(f.urllib.request.OpenerDirector, 'open', side_effect=AssertionError('unexpected network'))
        self.network = network.start()
        self.addCleanup(network.stop)

    def run_import(self, source=None):
        return f.import_material(self.item, source or self.source, self.folder, self.messages.append)

    def test_renamed_browser_file_is_copied_to_pinned_name_and_reused_offline(self):
        self.assertEqual(self.run_import(), self.target)
        self.assertEqual(self.target.read_bytes(), self.data)
        self.assertEqual(self.source.read_bytes(), self.data)
        f.fetch_entries([self.item], self.folder, self.messages.append, verify_only=True)
        f.fetch_entries([self.item], self.folder, self.messages.append)
        self.network.assert_not_called()
        self.assertEqual(list(self.folder.glob('*.importing')), [])

    def test_corrupt_or_incomplete_input_preserves_cache_and_resume_progress(self):
        self.target.write_bytes(self.data)
        self.partial.write_bytes(b'saved download prefix')
        meta = self.partial.with_name(self.partial.name + '.json')
        meta.write_text('{"validator":"saved"}')
        for content in (b'', self.data[:12345], b'wrong firmware'):
            with self.subTest(size=len(content)):
                self.source.write_bytes(content)
                with self.assertRaisesRegex(f.MaterialImportError, 'import_hash_mismatch'):
                    self.run_import()
                self.assertEqual(self.source.read_bytes(), content)
                self.assertEqual(self.target.read_bytes(), self.data)
                self.assertEqual(self.partial.read_bytes(), b'saved download prefix')
                self.assertEqual(meta.read_text(), '{"validator":"saved"}')
                self.assertEqual(list(self.folder.glob('*.importing')), [])

    def test_wrong_input_never_creates_final_file(self):
        self.source.write_bytes(b'wrong')
        with self.assertRaises(f.MaterialImportError):
            self.run_import()
        self.assertFalse(self.target.exists())

    def test_verified_import_replaces_bad_cache_without_altering_source_or_partial(self):
        self.target.write_bytes(b'corrupt cache')
        self.partial.write_bytes(b'old partial')
        self.run_import()
        self.assertEqual(self.target.read_bytes(), self.data)
        self.assertEqual(self.source.read_bytes(), self.data)
        self.assertEqual(self.partial.read_bytes(), b'old partial')

    def test_selecting_cache_itself_only_verifies_without_extra_space(self):
        self.target.write_bytes(self.data)
        with patch.object(f.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)), \
                patch.object(Path, 'replace', side_effect=AssertionError('should not replace selected source')):
            self.run_import(self.target)
        self.assertEqual(self.target.read_bytes(), self.data)
        self.target.write_bytes(b'bad cache')
        with self.assertRaisesRegex(f.MaterialImportError, 'import_hash_mismatch'):
            self.run_import(self.target)
        self.assertEqual(self.target.read_bytes(), b'bad cache')

    def test_missing_file_or_directory_is_actionable(self):
        for source in (self.root / 'missing.7z', self.root):
            with self.subTest(path=source):
                with self.assertRaisesRegex(f.MaterialImportError, 'import_source_invalid'):
                    self.run_import(source)
        self.assertFalse(self.target.exists())

    def test_insufficient_space_preserves_existing_files(self):
        self.target.write_bytes(b'existing')
        with patch.object(f.shutil, 'disk_usage', return_value=SimpleNamespace(free=1)):
            with self.assertRaisesRegex(f.MaterialImportError, 'import_insufficient_disk'):
                self.run_import()
        self.assertEqual(self.target.read_bytes(), b'existing')
        self.assertEqual(self.source.read_bytes(), self.data)
        self.assertEqual(list(self.folder.glob('*.importing')), [])

    def test_atomic_replace_failure_preserves_old_cache_and_cleans_temp(self):
        self.target.write_bytes(b'old cache')
        with patch.object(Path, 'replace', side_effect=PermissionError('cache busy')):
            with self.assertRaisesRegex(f.MaterialImportError, 'import_io_error'):
                self.run_import()
        self.assertEqual(self.target.read_bytes(), b'old cache')
        self.assertEqual(self.source.read_bytes(), self.data)
        self.assertEqual(list(self.folder.glob('*.importing')), [])

    def test_import_shares_download_lock_and_releases_it_after_error(self):
        with f._download_lock(self.partial.with_name(self.partial.name + '.lock')):
            with self.assertRaisesRegex(f.DownloadError, 'download_busy'):
                self.run_import()
        self.source.write_bytes(b'bad')
        with self.assertRaises(f.MaterialImportError):
            self.run_import()
        self.source.write_bytes(self.data)
        self.run_import()
        self.assertEqual(self.target.read_bytes(), self.data)

    def test_pinned_firmware_wrapper_uses_same_application_cache(self):
        with patch.object(root_setup, 'stock_firmware', return_value=self.item), \
                patch.object(f, 'download_root', return_value=self.folder):
            target = root_setup.import_stock_firmware(str(self.source), self.messages.append, variant='SQN100-3')
        self.assertEqual(Path(target).read_bytes(), self.data)


class FirmwareImportGuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        for mocker in (patch.object(w, 'prepared_kit_history', return_value=[]),
                       patch.object(w, 'root_lock_path', return_value=self.folder / 'flash.lock'),
                       patch.object(w, 'prepare_root_kit', side_effect=AssertionError('unexpected preparation')),
                       patch.object(w, 'flash_root', side_effect=AssertionError('unexpected flashing')),
                       patch.object(w.threading, 'Thread', side_effect=lambda target, **_: SimpleNamespace(start=target))):
            mocker.start()
            self.addCleanup(mocker.stop)
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest('Tk display unavailable: ' + str(error))
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.wizard = w.SetupWizard(self.root, lambda *_: None, auto_check=False, initial_page='root')
        self.wizard.variant.set('SQN100-3')
        self.addCleanup(self.close_wizard)

    def close_wizard(self):
        self.wizard.busy = False
        self.wizard.close()

    def drain(self):
        self.wizard.after_cancel(self.wizard._job)
        self.wizard.drain()

    def test_browser_button_uses_manifest_url_and_has_copy_fallback(self):
        url = root_setup.stock_firmware('SQN100-3')['url']
        for result in (True, False):
            with patch.object(w.webbrowser, 'open', return_value=result) as browser:
                self.wizard.browser_download_button.invoke()
            browser.assert_called_once_with(url, new=2)
        self.assertIn('复制下载链接', self.wizard.status.cget('text'))
        with patch.object(self.wizard, 'clipboard_clear'), patch.object(self.wizard, 'clipboard_append') as copy:
            self.wizard.copy_download_button.invoke()
        copy.assert_called_once_with(url)

    def test_picker_cancellation_preserves_entered_path_without_import(self):
        self.wizard.firmware_path.set('existing path')
        with patch.object(w.filedialog, 'askopenfilename', return_value=''), patch.object(w, 'import_stock_firmware') as importer:
            self.wizard.browse_firmware_button.invoke()
        self.assertEqual(self.wizard.firmware_path.get(), 'existing path')
        importer.assert_not_called()

    def test_selected_backup_node_is_used_by_browser_and_copy(self):
        self.wizard.firmware_source.current(1)
        url = self.wizard.firmware_urls[1]
        with patch.object(w.webbrowser, 'open', return_value=True) as browser:
            self.wizard.browser_download_button.invoke()
        browser.assert_called_once_with(url, new=2)
        with patch.object(self.wizard, 'clipboard_clear'), patch.object(self.wizard, 'clipboard_append') as copy:
            self.wizard.copy_download_button.invoke()
        copy.assert_called_once_with(url)

    def test_empty_path_is_rejected_before_worker(self):
        with patch.object(w, 'import_stock_firmware') as importer:
            self.wizard.import_firmware_button.invoke()
        importer.assert_not_called()
        self.assertFalse(self.wizard.busy)
        self.assertIn('选择', self.wizard.status.cget('text'))

    def test_pasted_quoted_path_imports_without_preparing_or_enabling_flash(self):
        source = self.folder / '浏览器 (1).7z'
        source.write_bytes(b'local fixture')
        item = {'file': 'firmware.7z', 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
        self.wizard.firmware_path.set('"' + str(source) + '"')
        with patch.object(root_setup, 'stock_firmware', return_value=item), \
                patch.object(f, 'download_root', return_value=self.folder / 'cache'):
            self.wizard.import_firmware_button.invoke()
        self.drain()
        self.assertEqual((self.folder / 'cache/firmware.7z').read_bytes(), b'local fixture')
        self.assertIn('固件已导入并通过校验', self.wizard.status.cget('text'))
        self.assertFalse(self.wizard.busy)
        self.assertIsNone(self.wizard.kit)
        self.assertEqual(str(self.wizard.flash_button.cget('state')), 'disabled')
        self.assertFalse(self.wizard.ack.get())

    def test_local_error_is_shown_and_controls_reenable_for_retry(self):
        error = f.MaterialImportError('import_hash_mismatch')
        self.wizard.firmware_path.set('wrong file.7z')
        with patch.object(w, 'import_stock_firmware', side_effect=error):
            self.wizard.import_firmware_button.invoke()
        self.assertTrue(self.wizard.busy)
        self.assertEqual(str(self.wizard.firmware_entry.cget('state')), 'disabled')
        self.drain()
        self.assertFalse(self.wizard.busy)
        self.assertEqual(self.wizard.status.cget('text'), error.user_message)
        self.assertEqual(str(self.wizard.import_firmware_button.cget('state')), 'normal')
        self.assertEqual(str(self.wizard.firmware_entry.cget('state')), 'normal')

    def detect_result(self, usb):
        usb = dict(usb, usb_present=True, usb_network=True, ssh_port=False)
        self.wizard.events.put(('result', ('detect', {'usb': usb, 'choice': None, 'error': 'connection_refused'})))
        self.drain()

    def test_no_model_has_no_firmware_link_or_q10_default(self):
        self.wizard.variant.set('')
        self.assertEqual(self.wizard.firmware_urls, [])
        self.assertEqual(str(self.wizard.download_firmware_button.cget('state')), 'disabled')
        with patch.object(w.webbrowser, 'open') as browser:
            self.wizard.open_firmware_download()
        browser.assert_not_called()

    def test_detection_replaces_previous_q10_in_all_download_actions(self):
        for variant, family in [('SQC100-2', 'classic'), ('SQW100-4', 'passport')]:
            usb = {'usb_count': 1, 'device': {'ModelName': variant}}
            self.detect_result(usb)
            self.assertEqual(self.wizard.variant.get(), variant)
            item = root_setup.stock_firmware(variant)
            self.assertEqual(item['family'], family)
            self.assertEqual(self.wizard.firmware_urls, f.source_urls(item))
            self.assertIn(item['file'], self.wizard.firmware_label.cget('text'))
            self.assertEqual(str(self.wizard.prepare_button.cget('state')), 'disabled')
            with patch.object(w, 'local_usb_state', return_value=usb), \
                    patch.object(w, 'download_stock_firmware', return_value='cache/' + item['file']) as fetch:
                self.wizard.download_firmware_button.invoke()
            self.drain()
            fetch.assert_called_once()
            self.assertEqual(fetch.call_args.args[0], variant)
            with patch.object(w.webbrowser, 'open', return_value=True) as browser:
                self.wizard.browser_download_button.invoke()
            browser.assert_called_once_with(item['url'], new=2)
            self.wizard.firmware_path.set('original firmware')
            with patch.object(w, 'import_stock_firmware', return_value='cache/' + item['file']) as importer:
                self.wizard.import_firmware_button.invoke()
            self.drain()
            self.assertEqual(importer.call_args.kwargs['variant'], variant)
            self.assertEqual(str(self.wizard.flash_button.cget('state')), 'disabled')

    def test_ambiguous_or_unknown_detection_discards_stale_firmware(self):
        for usb in ({'usb_count': 2, 'device': {'ModelName': 'SQN100-3'}},
                    {'usb_count': 1, 'device': {'ModelName': 'STL100-1'}},
                    {'usb_count': 1, 'device': {}}):
            self.wizard.usb = {}
            self.wizard.variant.set('SQN100-3')
            self.detect_result(usb)
            self.assertEqual(self.wizard.variant.get(), '')
            self.assertEqual(self.wizard.firmware_urls, [])
            self.assertEqual(str(self.wizard.download_firmware_button.cget('state')), 'disabled')

    def test_swapped_phone_is_rechecked_before_network_download(self):
        self.detect_result({'usb_count': 1, 'device': {'ModelName': 'SQN100-3'}})
        with patch.object(w, 'local_usb_state', return_value={'usb_count': 1, 'device': {'ModelName': 'SQW100-4'}}), \
                patch.object(w, 'download_stock_firmware') as fetch:
            self.wizard.download_firmware_button.invoke()
        self.drain()
        fetch.assert_not_called()
        self.assertEqual(self.wizard.status.cget('text'), w.MESSAGES['firmware_model_mismatch'])

    def test_changing_model_discards_previous_images_and_import_path(self):
        self.wizard.kit = 'old Q10 kit'
        self.wizard.ack.set(True)
        self.wizard.firmware_path.set('old Q10 firmware')
        self.wizard.variant.set('SQW100-4')
        self.assertIsNone(self.wizard.kit)
        self.assertFalse(self.wizard.ack.get())
        self.assertEqual(self.wizard.firmware_path.get(), '')
        self.assertEqual(str(self.wizard.flash_button.cget('state')), 'disabled')

    def test_redetecting_same_variant_preserves_prepared_images(self):
        self.wizard.kit = 'prepared Q10 kit'
        self.wizard.ack.set(True)
        self.detect_result({'usb_count': 1, 'device': {'ModelName': 'SQN100-3'}})
        self.assertEqual(self.wizard.kit, 'prepared Q10 kit')
        self.assertTrue(self.wizard.ack.get())

    def test_domestic_share_is_browser_only_and_names_the_selected_firmware(self):
        for variant in ('SQN100-3', 'SQC100-2', 'SQW100-4'):
            self.wizard.variant.set(variant)
            item = root_setup.stock_firmware(variant)
            with patch.object(w.webbrowser, 'open', return_value=True) as browser, \
                    patch.object(w, 'download_stock_firmware') as fetch:
                self.wizard.domestic_download_button.invoke()
            browser.assert_called_once_with(item['manual_download_url'], new=2)
            fetch.assert_not_called()
            self.assertIn(item['file'], self.wizard.status.cget('text'))
        self.wizard.variant.set('')
        self.assertEqual(str(self.wizard.domestic_download_button.cget('state')), 'disabled')

    def test_backup_share_preserves_each_selected_firmware_and_never_uses_the_downloader(self):
        for variant in ('SQN100-3', 'SQC100-2', 'SQW100-4'):
            self.wizard.variant.set(variant)
            item = dict(root_setup.stock_firmware(variant),
                        backup_manual_download_url='https://example.invalid/baidu/' + variant,
                        backup_manual_download_code='b10x')
            with patch.object(w, 'stock_firmware', return_value=item), \
                    patch.object(w.webbrowser, 'open', return_value=True) as browser, \
                    patch.object(w, 'download_stock_firmware') as fetch:
                self.wizard.refresh()
                self.wizard.backup_download_button.invoke()
            browser.assert_called_once_with(item['backup_manual_download_url'], new=2)
            fetch.assert_not_called()
            self.assertNotIn(item['backup_manual_download_url'], self.wizard.firmware_urls)
            self.assertIn(item['file'], self.wizard.status.cget('text'))
            self.assertIn('b10x', self.wizard.backup_download_hint.cget('text'))

    def test_copy_backup_includes_baidu_share_url_and_access_code(self):
        item = dict(root_setup.stock_firmware('SQN100-3'),
                    backup_manual_download_url='https://example.invalid/baidu/q10',
                    backup_manual_download_code='b10x')
        with patch.object(w, 'stock_firmware', return_value=item), \
                patch.object(self.wizard, 'clipboard_clear') as clear, \
                patch.object(self.wizard, 'clipboard_append') as append:
            self.wizard.refresh()
            self.wizard.copy_backup_download_button.invoke()
        clear.assert_called_once_with()
        append.assert_called_once_with(item['backup_manual_download_url'] + '\n百度网盘提取码：b10x')
        self.assertIn(item['file'], self.wizard.status.cget('text'))

    def test_backup_is_disabled_without_a_link_and_while_busy_or_model_is_ambiguous(self):
        item = dict(root_setup.stock_firmware('SQN100-3'))
        item.pop('backup_manual_download_url', None)
        with patch.object(w, 'stock_firmware', return_value=item), \
                patch.object(w.webbrowser, 'open') as browser:
            self.wizard.refresh()
            self.assertEqual(str(self.wizard.backup_download_button.cget('state')), 'disabled')
            self.wizard.open_backup_download()
        browser.assert_not_called()
        item['backup_manual_download_url'] = 'https://example.invalid/baidu/q10'
        with patch.object(w, 'stock_firmware', return_value=item), \
                patch.object(w.webbrowser, 'open') as browser:
            self.wizard.busy = True
            self.wizard.refresh()
            self.wizard.open_backup_download()
            self.assertEqual(str(self.wizard.backup_download_button.cget('state')), 'disabled')
            self.wizard.busy = False
            self.wizard.usb = {'usb_count': 2}
            self.wizard.refresh()
            self.wizard.open_backup_download()
            self.assertEqual(str(self.wizard.backup_download_button.cget('state')), 'disabled')
        browser.assert_not_called()

    def test_backup_browser_failure_points_to_the_backup_copy_action(self):
        item = dict(root_setup.stock_firmware('SQN100-3'),
                    backup_manual_download_url='https://example.invalid/baidu/q10')
        with patch.object(w, 'stock_firmware', return_value=item), \
                patch.object(w.webbrowser, 'open', side_effect=OSError('browser unavailable')):
            self.wizard.refresh()
            self.wizard.backup_download_button.invoke()
        self.assertIn('复制备用链接', self.wizard.status.cget('text'))


if __name__ == '__main__':
    unittest.main()
