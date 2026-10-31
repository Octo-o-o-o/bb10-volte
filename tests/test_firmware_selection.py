"""Device-specific firmware routing; never downloads or executes an autoloader."""
from pathlib import Path
import hashlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import root_setup as r
import fetch_materials as f


class FirmwareSelectionTests(unittest.TestCase):
    def test_every_listed_hardware_variant_has_one_pinned_family(self):
        variants = r.firmware_variants()
        self.assertEqual(len(variants), len(set(variants)))
        for prefix, maximum, family in [('SQN100-', 5, 'q10'), ('SQC100-', 5, 'classic'), ('SQW100-', 4, 'passport')]:
            for number in range(1, maximum + 1):
                variant = prefix + str(number)
                item = r.stock_firmware(variant)
                self.assertEqual(item['family'], family)
                self.assertIn(variant, item['variants'])
                self.assertRegex(item['sha256'], r'\A[0-9a-f]{64}\Z')
                self.assertGreater(item['size'], 0)
                self.assertTrue(all(url.startswith('https://') for url in f.source_urls(item)))
                if family != 'q10':
                    self.assertNotIn('Q10_', item['file'])
                    self.assertNotIn('SQN100', item['file'])

    def test_missing_unknown_and_inexact_models_never_fall_back_to_q10(self):
        for variant in (None, '', 'Q20', 'Q30', 'SQW100-99', 'SQC100-0', 'SQN100-3 extra', 'sqw100-4'):
            with self.subTest(variant=variant), self.assertRaises(r.SetupError):
                r.stock_firmware(variant)

    def test_browser_share_pages_never_enter_automatic_firmware_mirrors(self):
        for variant in ('SQN100-3', 'SQC100-2', 'SQW100-4'):
            item = r.stock_firmware(variant)
            self.assertEqual(item['manual_download_url'], 'https://t3.znas.cn/9jkbxczhAK4')
            self.assertNotIn(item['manual_download_url'], f.source_urls(item))
            self.assertEqual(item['backup_manual_download_url'],
                             'https://pan.baidu.com/s/1zLsoynq3nkOs7AwgSM7rqw?pwd=fp4r')
            self.assertEqual(item['backup_manual_download_code'], 'fp4r')
            self.assertNotIn(item['backup_manual_download_url'], f.source_urls(item))

    def test_single_detected_device_is_authoritative(self):
        usb = {'usb_count': 1, 'device': {'ModelName': 'SQW100-4'}}
        self.assertEqual(r.selected_firmware_variant('', usb), 'SQW100-4')
        self.assertEqual(r.selected_firmware_variant('SQW100-4', usb), 'SQW100-4')
        with self.assertRaisesRegex(r.SetupError, 'firmware_model_mismatch'):
            r.selected_firmware_variant('SQN100-3', usb)

    def test_multiple_unknown_and_missing_identity_cannot_use_stale_selection(self):
        for usb in ({'usb_count': 2, 'device': {'ModelName': 'SQN100-3'}},
                    {'usb_count': 1, 'device': {'ModelName': 'unknown'}},
                    {'usb_count': 1, 'device': {}},
                    {'usb_present': True, 'device': {}}):
            with self.subTest(usb=usb), self.assertRaises(r.SetupError):
                r.selected_firmware_variant('SQN100-3', usb)
        self.assertEqual(r.selected_firmware_variant('SQC100-2', {'usb_count': 0}), 'SQC100-2')

    def test_download_fetches_only_the_requested_firmware_with_shared_cache(self):
        for variant in ('SQN100-3', 'SQC100-2', 'SQW100-4'):
            with patch.object(r, 'fetch_entries', return_value=Path('cache')) as fetch:
                path = r.download_stock_firmware(variant, print, 'proxy', 'cache', True)
            self.assertEqual(fetch.call_args.args, ([r.stock_firmware(variant)],))
            self.assertEqual(fetch.call_args.kwargs, {'folder': 'cache', 'progress': print, 'proxy': 'proxy', 'verify_only': True})
            self.assertEqual(Path(path).name, r.stock_firmware(variant)['file'])

    def test_cli_downloads_tools_only_without_an_explicit_variant(self):
        with patch.object(f, 'fetch_entries') as fetch:
            f.main(['--verify-only'])
        self.assertFalse(any(item['id'].startswith('stock-') for item in fetch.call_args.args[0]))
        for variant in ('SQC100-2', 'SQW100-4'):
            with patch.object(f, 'fetch_entries') as fetch:
                f.main(['--variant', variant])
            stocks = [item for item in fetch.call_args.args[0] if item['id'].startswith('stock-')]
            self.assertEqual(stocks, [r.stock_firmware(variant)])

    def test_download_and_import_reject_missing_target_before_io(self):
        with patch.object(r, 'fetch_entries') as fetch, patch.object(r, 'import_material') as importer:
            with self.assertRaises(r.SetupError):
                r.download_stock_firmware(None, print)
            with self.assertRaises(r.SetupError):
                r.import_stock_firmware('Q10.7z', print)
        fetch.assert_not_called()
        importer.assert_not_called()

    def test_unvalidated_root_recipes_cannot_fetch_q10_as_a_substitute(self):
        with patch.object(r, 'ensure_tools') as tools, patch.object(r, 'fetch_entries') as fetch:
            for variant in ('SQC100-2', 'SQW100-4'):
                with self.assertRaisesRegex(r.SetupError, 'root_model_unsupported'):
                    r.prepare_root_kit(variant, print)
        tools.assert_not_called()
        fetch.assert_not_called()

    def test_wrong_family_import_cannot_replace_or_populate_another_cache_entry(self):
        q10, passport = b'Q10 original firmware fixture', b'Passport original firmware fixture'
        items = [{'id': 'stock-q10', 'variants': ['SQN100-3'], 'file': 'Q10.7z',
                  'sha256': hashlib.sha256(q10).hexdigest()},
                 {'id': 'stock-passport', 'variants': ['SQW100-4'], 'file': 'Passport.7z',
                  'sha256': hashlib.sha256(passport).hexdigest()}]
        with tempfile.TemporaryDirectory() as folder, patch.object(r, 'firmware_entries', return_value=items):
            cache = Path(folder) / 'cache'
            cache.mkdir()
            (cache / 'Q10.7z').write_bytes(q10)
            source = Path(folder) / 'browser-file.7z'
            source.write_bytes(q10)
            with self.assertRaises(f.MaterialImportError):
                r.import_stock_firmware(source, lambda _: None, cache, variant='SQW100-4')
            self.assertFalse((cache / 'Passport.7z').exists())
            self.assertEqual((cache / 'Q10.7z').read_bytes(), q10)
            source.write_bytes(passport)
            result = r.import_stock_firmware(source, lambda _: None, cache, variant='SQW100-4')
            self.assertEqual(Path(result).read_bytes(), passport)
            self.assertEqual((cache / 'Q10.7z').read_bytes(), q10)


if __name__ == '__main__':
    unittest.main()
