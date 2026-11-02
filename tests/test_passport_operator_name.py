import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
import tempfile
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / 'experiments/passport_operator_name/name.py'
spec = importlib.util.spec_from_file_location('passport_name_test_module', SOURCE)
op = importlib.util.module_from_spec(spec)
spec.loader.exec_module(op)


class PassportNameTests(unittest.TestCase):
    def test_install_creates_a_missing_addon_parent_and_keeps_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / 'base'
            base.mkdir()
            (base / 'start.sh').write_bytes(b'#!/bin/sh\nexit 0\n')
            (base / 'preserved.txt').write_bytes(b'preserved')
            addon = root / 'addons/passport-operator-name'
            writer = NS(read=lambda path: Path(path).read_bytes(),
                        atomic=lambda path, data, mode=0o600: Path(path).write_bytes(data))
            with patch.object(op, 'BASE', str(base)), patch.object(op, 'ADDON', str(addon)), \
                    patch.object(op, 'n', writer), patch.object(op, 'start', return_value={'started': True}):
                self.assertTrue(op.install()['started'])
            self.assertEqual((addon / 'init/start.sh').read_bytes(), (base / 'start.sh').read_bytes())
            self.assertEqual((base / 'preserved.txt').read_bytes(), b'preserved')
            self.assertTrue((base / 'enabled').is_file())

    def test_normal_passport_service_bitmap_accepts_extra_bits_but_rejects_roaming_and_other_plmn(self):
        cell = {'serving_network': {'mcc': '460', 'mnc': '11', 'is_femto': False},
                'network_technology': 'lte', 'network_service': 52429824,
                'roaming': {'state': 'NOT_ROAMING'}}
        reader = NS(value=lambda obj, key, default=None: obj.get(key, default))
        with patch.object(op, 'n', reader), patch.object(op, 'home', return_value=('READY', {'mcc': '460', 'mnc': '11'})), \
                patch.object(op, 'at', return_value=cell):
            self.assertTrue(op.eligible())
            cell['network_service'] |= 1
            self.assertFalse(op.eligible())
            cell['network_service'] = 52429824
            cell['roaming']['state'] = 'ROAMING'
            self.assertFalse(op.eligible())
            cell['roaming']['state'] = 'NOT_ROAMING'
            cell['serving_network']['mnc'] = '00'
            self.assertFalse(op.eligible())

    def test_wrong_home_card_never_creates_an_overlay_or_changes_display(self):
        writer = Mock()
        writer.value.side_effect = lambda obj, key, default=None: obj.get(key, default)
        with patch.object(op, 'n', writer), patch.object(op, 'home', return_value=('READY', {'mcc': '460', 'mnc': '00'})), \
                patch.object(op, 'manager') as manager:
            self.assertFalse(op.apply_once()['applied'])
        writer.atomic.assert_not_called()
        writer.update_pps.assert_not_called()
        manager.assert_not_called()

    def test_unknown_overlay_is_preserved_without_any_file_or_pps_write(self):
        writer = Mock()
        with patch.object(op, 'n', writer), patch.object(op, 'eligible', return_value=True), \
                patch.object(op, 'target', return_value='/some/other/table'):
            with self.assertRaisesRegex(AssertionError, 'Preserve'):
                op.apply_once()
        writer.atomic.assert_not_called()
        writer.update_pps.assert_not_called()

    def test_original_rows_are_preserved_and_only_one_missing_plmn_is_appended(self):
        original = b'PPCI&N|Abrev. Net. Name|MCC|MNC\nExisting|Existing|460|00\n'
        with patch.object(op, 'n', NS(digest=lambda data: op.STOCK_HASH)):
            result = op.payload(original)
            self.assertTrue(result.startswith(original))
            self.assertEqual(result[len(original):].decode('utf-8'), op.NAME + '|' + op.NAME + '|460|11\n')
            with self.assertRaises(AssertionError):
                op.payload(result)

    def test_an_existing_non_numeric_brand_name_is_not_overwritten(self):
        writer = Mock()
        writer.read.side_effect = lambda path: b'original' if path == op.ORIGINAL else b'overlay'
        writer.value.side_effect = lambda obj, key, default=None: obj.get(key, default)
        with patch.object(op, 'n', writer), patch.object(op, 'eligible', return_value=True), \
                patch.object(op, 'target', return_value=op.TABLE), patch.object(op, 'payload', return_value=b'overlay'), \
                patch.object(op.os.path, 'isfile', return_value=True), patch.object(op.os.path, 'islink', return_value=False), \
                patch.object(op, 'at', return_value={'current_ons': {'name_long': 'Existing Brand', 'name_short': 'Brand'}}):
            self.assertFalse(op.apply_once()['ons_changed'])
        writer.update_pps.assert_not_called()

    def test_restore_preserves_fresh_non_name_fields_and_does_not_restore_old_sim_names(self):
        for mnc in ('11', '00'):
            writer = Mock()
            table_reads = iter([b'overlay', b'original'])
            writer.read.side_effect = lambda path: next(table_reads) if path == op.STOCK else b'original'
            writer.digest.return_value = op.STOCK_HASH
            writer.value.side_effect = lambda obj, key, default=None: obj.get(key, default)
            record = {'owner': op.OWNER, 'boot': [1, 2],
                      'before': {'name_long': '460-11', 'name_short': '', 'old_flag': 1}}
            ons = {'name_long': op.NAME, 'name_short': op.NAME, 'fresh_flag': 2}
            with patch.object(op, 'n', writer), patch.object(op, 'target', side_effect=[op.TABLE, None]), \
                    patch.object(op, 'payload', return_value=b'overlay'), \
                    patch.object(op, 'manager', return_value=NS(pathmgr_unlink=lambda path: 0)), \
                    patch.object(op.os.path, 'isfile', return_value=True), patch.object(op.os, 'unlink'), \
                    patch.object(op, 'load', return_value=record), patch.object(op, 'boot', return_value=[1, 2]), \
                    patch.object(op, 'at', return_value={'current_ons': ons}), \
                    patch.object(op, 'home', return_value=('READY', {'mcc': '460', 'mnc': mnc})):
                self.assertTrue(op.restore()['restored'])
            if mnc == '00':
                writer.update_pps.assert_not_called()
            else:
                value = writer.update_pps.call_args.args[1]['current_ons']
                self.assertEqual(json.loads(value[5:]), {'name_long': '460-11', 'name_short': '', 'fresh_flag': 2})


if __name__ == '__main__':
    unittest.main()
