"""Model-specific image safety; synthetic inputs only, never flash hardware."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import root_images as images
import root_setup as setup
import macos_root
from workflow import WorkflowError


VARIANTS = ('SQN100-3', 'SQC100-2', 'SQW100-4')


def digest(data):
    return hashlib.sha256(data).hexdigest()


class RootImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def build_fixture(self, variant, platform='win32'):
        stock, expected = images.recipe(variant)
        expected = dict(expected)
        expected['unchanged_partitions'] = [dict(item, bytes=5, sha256=digest(b'stock'))
                                            for item in expected['unchanged_partitions']]
        expected['radio_original_sha256'] = digest(b'radio')
        kit = self.folder / (variant + '-' + platform)
        output = kit / 'images'
        output.mkdir(parents=True)
        for item in expected['unchanged_partitions']:
            (output / item['file']).write_bytes(b'stock')
        stem = Path(stock['extracted_file']).stem
        (output / (stem + '.1.signed')).write_bytes(b'radio')
        (output / (stem + '.0.unsigned')).write_bytes(b'owner-specific system')
        if platform == 'win32':
            (output / (stem + '_os.exe')).write_bytes(b'non-executable OS fixture')
            (output / (stem + '_radio.exe')).write_bytes(b'non-executable radio fixture')
        (kit / 'root-build.log').write_text('Batch completed\n')
        (kit / 'setup-state.json').write_text(json.dumps({'variant': variant, 'stage': 'prepared', 'platform': platform}))
        return kit, stock, expected

    def test_every_supported_variant_has_its_own_stock_and_partition_recipe(self):
        for variant in setup.catalog()['auto_root_variants']:
            stock, expected = images.recipe(variant)
            self.assertEqual(stock['id'], expected['firmware_id'])
            self.assertEqual(stock['extracted_sha256'], expected['stock_sha256'])
            stem = Path(stock['extracted_file']).stem
            self.assertEqual(len(expected['unchanged_partitions']), 4)
            self.assertTrue(all(item['file'].startswith(stem + '.0.') for item in expected['unchanged_partitions']))
        self.assertNotEqual(images.recipe('SQC100-2')[1]['radio_original_sha256'],
                            images.recipe('SQN100-3')[1]['radio_original_sha256'])

    def test_classic_exe_is_linked_and_verified_without_extraction_or_execution(self):
        stock = dict(setup.stock_firmware('SQC100-2'), sha256=digest(b'original'), extracted_sha256=digest(b'original'))
        source = self.folder / stock['file']
        source.write_bytes(b'original')
        with patch.object(images.subprocess, 'run') as run:
            target = images.extract_stock(stock, source, self.folder / 'stock', '7zip')
        self.assertEqual(target.read_bytes(), b'original')
        self.assertEqual(source.read_bytes(), b'original')
        self.assertTrue(source.samefile(target))
        source.unlink()
        self.assertEqual(target.read_bytes(), b'original')
        run.assert_not_called()

    def test_classic_exe_copy_fallback_for_filesystems_without_hardlinks(self):
        stock = dict(setup.stock_firmware('SQC100-2'), sha256=digest(b'original'), extracted_sha256=digest(b'original'))
        source = self.folder / stock['file']
        source.write_bytes(b'original')
        with patch.object(Path, 'hardlink_to', side_effect=OSError('not supported')):
            target = images.extract_stock(stock, source, self.folder / 'stock', '7zip')
        self.assertEqual(target.read_bytes(), b'original')
        self.assertFalse(source.samefile(target))

    def test_archive_extracts_only_pinned_autoloader_and_rejects_bad_output(self):
        stock = dict(setup.stock_firmware('SQW100-4'), sha256=digest(b'archive'), extracted_sha256=digest(b'original'))
        source = self.folder / stock['file']
        source.write_bytes(b'archive')
        def extract(command, **kwargs):
            self.assertEqual(command[4], stock['extracted_file'])
            (Path(command[5][2:]) / stock['extracted_file']).write_bytes(b'wrong')
            return SimpleNamespace(returncode=0)
        with patch.object(images.subprocess, 'run', side_effect=extract):
            with self.assertRaisesRegex(setup.SetupError, 'image_not_verified'):
                images.extract_stock(stock, source, self.folder / 'stock', '7zip')
        source.write_bytes(b'damaged archive')
        with patch.object(images.subprocess, 'run') as run:
            with self.assertRaises(setup.SetupError):
                images.extract_stock(stock, source, self.folder / 'another', '7zip')
        run.assert_not_called()

    def test_windows_and_mac_receipts_bind_images_to_exact_variant(self):
        for variant in VARIANTS:
            for platform in ('win32', 'darwin'):
                with self.subTest(variant=variant, platform=platform):
                    kit, stock, spec = self.build_fixture(variant, platform)
                    with patch.object(images, 'recipe', return_value=(stock, spec)):
                        receipt = images.verify_build(kit, variant, platform)
                    state, paths = setup.prepared_images(kit)
                    self.assertEqual(receipt['variant'], variant)
                    self.assertEqual(receipt['firmware_id'], stock['id'])
                    self.assertEqual(state['variant'], variant)
                    self.assertEqual(len(paths), 2)
                    self.assertTrue(all(p.name.startswith(Path(stock['extracted_file']).stem) for p in paths))

    def test_wrong_partition_radio_or_script_error_never_produces_verified_receipt(self):
        for variant, kind in zip(VARIANTS, ('partition', 'radio', 'script')):
            kit, stock, spec = self.build_fixture(variant)
            if kind == 'partition':
                (kit / 'images' / spec['unchanged_partitions'][0]['file']).write_bytes(b'wrong')
            elif kind == 'radio':
                (kit / 'images' / (Path(stock['extracted_file']).stem + '.1.signed')).write_bytes(b'Q10 radio')
            else:
                (kit / 'root-build.log').write_text('Script error: patch failed\nBatch completed\n')
            with patch.object(images, 'recipe', return_value=(stock, spec)):
                with self.assertRaises(setup.SetupError):
                    images.verify_build(kit, variant)
            self.assertFalse((kit / 'build-verification.json').exists())

    def test_q10_receipt_or_relabelled_journal_cannot_flash_another_model(self):
        kit, stock, spec = self.build_fixture('SQN100-3')
        with patch.object(images, 'recipe', return_value=(stock, spec)):
            images.verify_build(kit, 'SQN100-3')
        for variant in ('SQN100-4', 'SQC100-2', 'SQW100-4'):
            (kit / 'setup-state.json').write_text(json.dumps({'variant': variant, 'stage': 'prepared'}))
            with self.assertRaisesRegex(setup.SetupError, 'image_not_verified'):
                setup.prepared_images(kit)

    def test_new_models_require_model_bound_receipt_and_matching_image_names(self):
        for variant in ('SQC100-2', 'SQW100-4'):
            kit, stock, spec = self.build_fixture(variant)
            with patch.object(images, 'recipe', return_value=(stock, spec)):
                receipt = images.verify_build(kit, variant)
            receipt.pop('variant')
            (kit / 'build-verification.json').write_text(json.dumps(receipt))
            with self.assertRaises(setup.SetupError):
                setup.prepared_images(kit)
            receipt['variant'] = variant
            name = receipt['images'][0]['file']
            receipt['images'][0]['file'] = 'Q10_os.exe'
            (kit / 'images' / name).rename(kit / 'images/Q10_os.exe')
            (kit / 'build-verification.json').write_text(json.dumps(receipt))
            with self.assertRaises(setup.SetupError):
                setup.prepared_images(kit)

    def test_q20_and_passport_flash_in_order_only_for_matching_phone(self):
        for variant in ('SQC100-2', 'SQW100-4'):
            kit, stock, spec = self.build_fixture(variant)
            with patch.object(images, 'recipe', return_value=(stock, spec)):
                images.verify_build(kit, variant)
            with patch.object(setup.sys, 'platform', 'win32'), \
                    patch.object(setup, 'root_lock_path', return_value=kit / 'flash.lock'), \
                    patch.object(setup, 'local_usb_state', return_value={'usb_count': 1, 'device': {'ModelName': variant, 'PlatformVersion': '10.3.3.3216'}}), \
                    patch.object(setup, 'verify_root', side_effect=WorkflowError('connection_refused')), \
                    patch.object(setup, 'run_flash_stage', return_value={'completed': True}) as flash:
                setup.flash_root(kit, True, lambda _: None)
                self.assertEqual([c.args[1] for c in flash.call_args_list], ['os', 'radio'])
            (kit / 'setup-state.json').write_text(json.dumps({'variant': variant, 'stage': 'prepared'}))
            with patch.object(setup.sys, 'platform', 'win32'), \
                    patch.object(setup, 'local_usb_state', return_value={'usb_count': 1, 'device': {'ModelName': 'SQN100-3'}}), \
                    patch.object(setup, 'run_flash_stage') as flash:
                with self.assertRaisesRegex(setup.SetupError, 'device_model_not_verified'):
                    setup.flash_root(kit, True, lambda _: None)
                flash.assert_not_called()

    def test_mac_preparation_fetches_selected_family_and_passes_variant_to_builder(self):
        from preparation_cache import KEY_FILES
        def identity(kit):
            for name in KEY_FILES:
                (kit / name).write_bytes(b'non-secret fixture')
        for variant in VARIANTS:
            private = self.folder / variant
            with patch.object(macos_root.platform, 'system', return_value='Darwin'), \
                    patch.object(macos_root, 'architecture', return_value='arm64'), \
                    patch.object(macos_root, 'private_root', return_value=private), \
                    patch.object(macos_root.shutil, 'disk_usage', return_value=SimpleNamespace(free=100 * 1024**3)), \
                    patch.object(macos_root, 'fetch', return_value=self.folder / 'input') as fetch, \
                    patch.object(macos_root, 'prepare_tools', return_value={'seven_zip': '7zz'}), \
                    patch.object(macos_root, 'prepare_identity', side_effect=identity), \
                    patch.object(macos_root, 'extract_stock', return_value=self.folder / 'stock') as extract, \
                    patch.object(macos_root, 'build_images') as build:
                kit = macos_root.prepare_root_kit_macos(variant, lambda _: None, cache_dir=self.folder / 'cache', offline=True)
            self.assertEqual(fetch.call_args_list[-1].args[0]['id'], setup.stock_firmware(variant)['id'])
            self.assertEqual(extract.call_args.args[0]['id'], setup.stock_firmware(variant)['id'])
            self.assertEqual(build.call_args.args[-1], variant)
            self.assertEqual(json.loads((Path(kit) / 'preparation.json').read_text())['variant'], variant)


if __name__ == '__main__':
    unittest.main()
