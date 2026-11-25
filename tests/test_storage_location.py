"""Large-file location and cleanup. No phone, network or real personal directory."""
import json
import os
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import root_setup
import storage_location as storage
from i18n import tr
from storage_gui import StorageWindow


class StorageLocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.bundle = root / 'app'
        self.bundle.mkdir()
        self.stable = root / 'private'
        self.stable.mkdir()
        self.work = root / 'work'
        self.work.mkdir()
        (self.bundle / 'downloads').mkdir()
        bundle = patch.object(storage, 'resource_root', lambda: self.bundle)
        bundle.start()
        self.addCleanup(bundle.stop)
        lock = patch.object(root_setup, 'root_lock_path', lambda: self.stable / 'missing.lock')
        lock.start()
        self.addCleanup(lock.stop)

    def test_unset_location_keeps_the_original_directories(self):
        self.assertEqual(storage.preparation_parent(self.stable), self.stable)
        self.assertEqual(storage.active_download_root(self.stable), self.bundle / 'downloads')
        status = storage.location_status(self.stable)
        self.assertIsNone(status['problem'])
        self.assertIsNone(status['configured'])

    def test_choosing_a_folder_does_not_move_existing_files_or_block_fallback(self):
        kept = self.stable / 'connection.json'
        kept.write_text('{"host": "bb10-root"}', encoding='utf-8')
        self.assertEqual(storage.set_work_root(self.stable, self.work), 'saved')
        self.assertEqual(kept.read_text(encoding='utf-8'), '{"host": "bb10-root"}')
        self.assertFalse((self.work / 'connection.json').exists())
        self.assertEqual(storage.preparation_parent(self.stable), self.work)
        self.assertEqual(storage.active_download_root(self.stable), self.work / 'downloads')
        self.work.rmdir()
        self.assertEqual(storage.preparation_parent(self.stable), self.stable)
        self.assertEqual(storage.location_status(self.stable)['problem'], 'missing')
        self.assertEqual(storage.active_download_root(self.stable), self.bundle / 'downloads')

    def test_rejected_choices_leave_the_current_location_unchanged(self):
        nested = self.work / 'root-kit-abcdefabcdef'
        nested.mkdir()
        inside = self.stable / 'elsewhere'
        inside.mkdir()
        linked = self.work / 'linked'
        try:
            os.symlink(self.work, linked, target_is_directory=True)
        except OSError:
            linked = None
        for path, code in ((self.stable, 'default'), (inside, 'inside_private'),
                           (self.bundle / 'downloads', 'bundle'), (nested, 'nested')):
            with self.subTest(code=code):
                self.assertEqual(storage.set_work_root(self.stable, path), code)
                self.assertIsNone(storage.read_setting(self.stable)['work_root'])
        if linked is not None:
            self.assertEqual(storage.set_work_root(self.stable, linked), 'link')

    def test_inventory_shows_purpose_and_size_and_never_lists_keys(self):
        self.assertEqual(storage.set_work_root(self.stable, self.work), 'saved')
        kit = self.work / 'root-kit-abcdefabcdef'
        (kit / 'stock').mkdir(parents=True)
        (kit / 'stock' / 'firmware.bin').write_bytes(b'abc')
        (kit / 'images').mkdir()
        (kit / 'q10_root_rsa').write_text('secret-key', encoding='utf-8')
        (kit / 'ssh_config').write_text('host bb10-root\n', encoding='utf-8')
        (kit / 'setup-state.json').write_text(json.dumps({'stage': 'prepared', 'variant': 'SQN100-3'}), encoding='utf-8')
        download = self.work / 'downloads'
        download.mkdir()
        (download / 'phone.7z').write_bytes(b'12345')
        (download / 'phone.7z.partial').write_bytes(b'12')
        from fetch_materials import _download_lock
        with _download_lock(download / 'phone.7z.partial.lock'):
            items = storage.collect_inventory(self.stable)
            by_name = {item['name']: item for item in items}
            self.assertEqual(by_name['stock']['purpose'], storage.PURPOSE['stock'])
            self.assertEqual(storage.measure_tree(by_name['stock']['path']), 3)
            self.assertTrue(by_name['stock']['enabled'])
            self.assertEqual(by_name['phone.7z']['bytes'], 5)
            self.assertFalse(by_name['phone.7z']['enabled'])
            self.assertFalse(by_name['phone.7z.partial']['enabled'])
            self.assertNotIn('phone.7z.partial.lock', by_name)
            self.assertTrue(all('q10_root_rsa' not in item['path'] and not item['path'].endswith('ssh_config') for item in items))
        (kit / 'setup-state.json').write_text(json.dumps({'stage': 'os_started'}), encoding='utf-8')
        busy = {item['name']: item for item in storage.collect_inventory(self.stable)}
        self.assertFalse(busy['stock']['enabled'])
        self.assertFalse(busy['images']['enabled'])

    def test_delete_removes_only_the_selected_tree_and_keeps_keys(self):
        self.assertEqual(storage.set_work_root(self.stable, self.work), 'saved')
        kit = self.work / 'root-kit-abcdefabcdef'
        (kit / 'stock').mkdir(parents=True)
        (kit / 'stock' / 'firmware.bin').write_bytes(b'abc')
        key = kit / 'q10_root_rsa'
        key.write_text('secret-key', encoding='utf-8')
        items = storage.collect_inventory(self.stable)
        stock = next(item for item in items if item['name'] == 'stock')
        stock['bytes'] = storage.measure_tree(stock['path'])
        deleted, failed = storage.delete_items([stock, {'path': str(key), 'kind': 'file'}], self.stable)
        self.assertEqual(deleted, [str(kit / 'stock')])
        self.assertIn(str(key), failed)
        self.assertFalse((kit / 'stock').exists())
        self.assertEqual(key.read_text(encoding='utf-8'), 'secret-key')

    def test_previous_folder_remains_visible_after_a_later_choice(self):
        first = Path(self.temp.name) / 'first'
        second = Path(self.temp.name) / 'second'
        first.mkdir()
        second.mkdir()
        kit = first / 'root-kit-abcdefabcdef'
        (kit / 'images').mkdir(parents=True)
        (kit / 'images' / 'os.exe').write_bytes(b'image')
        self.assertEqual(storage.set_work_root(self.stable, first), 'saved')
        self.assertEqual(storage.set_work_root(self.stable, second), 'saved')
        names = {item['name'] for item in storage.collect_inventory(self.stable)}
        self.assertIn('images', names)
        self.assertEqual(storage.preparation_parent(self.stable), second)

    def test_window_does_not_grab_and_starts_with_nothing_selected(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        window = StorageWindow(root, stable=self.stable)
        self.addCleanup(window.destroy)
        root.update()
        self.assertIsNone(root.grab_current())
        self.assertIsNone(window.grab_current())
        self.assertEqual(str(window.clean_button.cget('state')), 'disabled')
        self.assertFalse((self.stable / storage.SETTING).exists())
        self.assertEqual(window.title(), tr('存储位置与磁盘清理'))
        scoped = StorageWindow(root, scope_kit=self.work, stable=self.stable)
        self.addCleanup(scoped.destroy)
        root.update()
        self.assertEqual(scoped.close_button.cget('text'), tr('不清理'))
        self.assertIsNone(root.grab_current())

    def test_saved_folder_that_later_cannot_be_written_falls_back(self):
        self.assertEqual(storage.set_work_root(self.stable, self.work), 'saved')
        stock = self.work / 'root-kit-abcdefabcdef' / 'stock'
        stock.mkdir(parents=True)
        (stock / 'firmware.bin').write_bytes(b'abc')
        with patch.object(storage, '_writable', lambda _path: False):
            self.assertEqual(storage.preparation_parent(self.stable), self.stable)
            self.assertEqual(storage.active_download_root(self.stable), self.bundle / 'downloads')
            self.assertEqual(storage.location_status(self.stable)['problem'], 'unwritable')
            names = {item['name'] for item in storage.collect_inventory(self.stable)}
        self.assertIn('stock', names)

    def test_linked_downloads_do_not_receive_new_files(self):
        self.assertEqual(storage.set_work_root(self.stable, self.work), 'saved')
        target = Path(self.temp.name) / 'elsewhere'
        target.mkdir()
        (target / 'known_hosts').write_text('secret', encoding='utf-8')
        link = self.work / 'downloads'
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError:
            if sys.platform != 'win32':
                self.skipTest('directory links are not permitted')
            import subprocess
            created = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                                     capture_output=True, text=True)
            if created.returncode != 0 or not link.is_junction():
                self.skipTest(created.stderr or created.stdout or 'junction was not created')
        self.assertEqual(storage.preparation_parent(self.stable), self.work)
        self.assertEqual(storage.active_download_root(self.stable), self.bundle / 'downloads')
        self.assertEqual(storage.location_status(self.stable)['problem'], 'download_link')
        self.assertFalse(any(item['name'] == 'known_hosts' for item in storage.collect_inventory(self.stable)))

    def test_new_work_reads_the_saved_folder_once(self):
        calls = {'n': 0}

        def counting(stable=None):
            calls['n'] += 1
            if calls['n'] == 1:
                return {'schema': 1, 'work_root': str(self.work), 'known_roots': []}
            return {'schema': 1, 'work_root': None, 'known_roots': []}

        with patch.object(storage, 'read_setting', side_effect=counting):
            parent, download = storage.current_placement(self.stable)
        self.assertEqual(parent, self.work)
        self.assertEqual(download, self.work / 'downloads')
        self.assertEqual(calls['n'], 1)

    def test_non_windows_keeps_the_original_directories(self):
        self.assertEqual(storage.set_work_root(self.stable, self.work), 'saved')
        with patch.object(storage.sys, 'platform', 'darwin'):
            self.assertEqual(storage.preparation_parent(self.stable), self.stable)
            self.assertEqual(storage.active_download_root(self.stable), self.bundle / 'downloads')
            self.assertEqual(storage.location_status(self.stable)['problem'], 'windows_only')

    def test_frozen_program_directory_is_rejected(self):
        program = Path(self.temp.name) / 'program'
        program.mkdir()
        other = Path(self.temp.name) / 'other'
        other.mkdir()
        with patch.object(storage, 'frozen', lambda: True), \
                patch.object(storage.sys, 'executable', str(program / 'bb10-volte.exe')):
            self.assertEqual(storage.usable_work_directory(program, self.stable), (False, 'bundle'))
            self.assertEqual(storage.set_work_root(self.stable, program), 'bundle')
            self.assertTrue(storage.usable_work_directory(other, self.stable)[0])
            self.assertIsNone(storage.read_setting(self.stable)['work_root'])

    def test_flash_lock_accepts_only_managed_kit_names(self):
        self.assertEqual(storage.set_work_root(self.stable, self.work), 'saved')
        backup = self.work / 'root-kit-backup'
        backup.mkdir()
        managed = self.work / 'root-kit-abcdefabcdef'
        managed.mkdir()
        with patch.object(root_setup, 'private_root', return_value=self.stable):
            self.assertIsNone(root_setup._lock_kit_dir({'kit': str(backup)}))
            self.assertEqual(root_setup._lock_kit_dir({'kit': str(managed)}), managed.resolve())

    def test_active_download_lock_covers_related_files_and_a_leftover_lock_does_not(self):
        self.assertEqual(storage.set_work_root(self.stable, self.work), 'saved')
        download = self.work / 'downloads'
        download.mkdir()
        digest = 'ab' * 32
        name = 'phone.7z'
        finished = download / name
        finished.write_bytes(b'12345')
        partial = download / (name + '.' + digest + '.partial')
        partial.write_bytes(b'12')
        meta = partial.with_name(partial.name + '.json')
        meta.write_text('{}', encoding='utf-8')
        importing = download / (name + '.' + ('cd' * 16) + '.importing')
        importing.write_bytes(b'x')
        from fetch_materials import _download_lock
        with _download_lock(partial.with_name(partial.name + '.lock')):
            items = {item['name']: item for item in storage.collect_inventory(self.stable)}
            for item_name in (name, partial.name, meta.name, importing.name):
                self.assertIn(item_name, items)
                self.assertFalse(items[item_name]['enabled'], item_name)
            deleted, failed = storage.delete_items([items[item_name] for item_name in items], self.stable)
            self.assertEqual(deleted, [])
            self.assertTrue(failed)
            self.assertTrue(finished.is_file() and meta.is_file() and importing.is_file())
        afterwards = {item['name']: item for item in storage.collect_inventory(self.stable)}
        self.assertTrue(afterwards[name]['enabled'])
        deleted, failed = storage.delete_items([afterwards[name]], self.stable)
        self.assertEqual(deleted, [str(finished)])
        self.assertFalse(finished.exists())
        self.assertTrue(meta.is_file())

    def test_unknown_model_does_not_stop_the_scoped_list(self):
        self.assertEqual(storage.set_work_root(self.stable, self.work), 'saved')
        kit = self.work / 'root-kit-abcdefabcdef'
        (kit / 'stock').mkdir(parents=True)
        (kit / 'setup-state.json').write_text(
            json.dumps({'variant': 'NOT-A-MODEL', 'stage': 'prepared'}), encoding='utf-8')
        items = storage.collect_inventory(self.stable, scope_kit=kit)
        self.assertIn('stock', {item['name'] for item in items})
