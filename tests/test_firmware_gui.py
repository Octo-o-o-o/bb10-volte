"""Owner confirmation and firmware routing in real Tk widgets, without a phone."""
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import firmware_gui as ui
import firmware_upgrade as upgrade
import root_setup


class FirmwareDialogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        for target, name, value in ((upgrade, 'pending_upgrades', []),
                                    (root_setup, 'root_lock_path', self.folder / 'flash.lock')):
            mock = patch.object(target, name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.usb = {'usb_count': 1, 'usb_address_ready': True,
                    'device': {'ModelName': 'SQW100-4', 'PlatformVersion': '10.3.3.2205'}}
        self.dialog = ui.FirmwareDialog(self.root, lambda *_: None, usb=self.usb)
        self.addCleanup(self.dialog.close)

    def enabled(self, button):
        return str(button.cget('state')) == 'normal'

    def test_upgrade_needs_matching_single_device_old_os_materials_and_confirmation(self):
        d = self.dialog
        self.assertFalse(self.enabled(d.upgrade_button))
        d.kit, d.stage = str(self.folder), 'prepared'
        d.refresh()
        self.assertFalse(self.enabled(d.upgrade_button))
        d.ack.set(True)
        d.refresh()
        self.assertTrue(self.enabled(d.upgrade_button))
        for usb in ({'usb_count': 2, 'device': self.usb['device']},
                    {'usb_count': 0},
                    {'usb_count': 1, 'device': {'ModelName': 'SQN100-3', 'PlatformVersion': '10.3.3.2205'}},
                    {'usb_count': 1, 'device': {'ModelName': 'SQW100-4', 'PlatformVersion': '10.3.3.3216'}},
                    {'usb_count': 1, 'device': {'ModelName': 'SQW100-4', 'PlatformVersion': '10.3.3.9999'}},
                    {'usb_count': 1, 'device': {'ModelName': 'SQW100-4'}}):
            d.usb = dict(usb, usb_address_ready=True)
            d.refresh()
            self.assertFalse(self.enabled(d.upgrade_button))
        d.usb = self.usb
        root_setup.root_lock_path().write_text('another operation')
        d.refresh()
        self.assertFalse(self.enabled(d.upgrade_button))

    def test_cancel_is_observation_only_and_acceptance_passes_displayed_os(self):
        d = self.dialog
        d.kit, d.stage = str(self.folder), 'prepared'
        d.ack.set(True)
        with patch.object(ui.messagebox, 'askyesno', return_value=False), patch.object(d, 'start') as start:
            d.flash()
            start.assert_not_called()
        with patch.object(ui.messagebox, 'askyesno', return_value=True) as prompt, \
                patch.object(d, 'start', side_effect=lambda _, fn: fn(lambda _: None)), \
                patch.object(upgrade, 'upgrade') as flash:
            d.flash()
        self.assertIn('SQW100-4', prompt.call_args.args[1])
        self.assertIn('10.3.3.2205', prompt.call_args.args[1])
        self.assertEqual(flash.call_args.args[:3], (str(self.folder), True, '10.3.3.2205'))
        self.assertFalse(d.ack.get())

    def test_uncertain_record_never_enables_retry_or_root(self):
        d = self.dialog
        d.kit, d.stage = str(self.folder), 'uncertain'
        d.ack.set(True)
        d.refresh()
        for button in (d.upgrade_button, d.verify_button, d.root_button):
            self.assertFalse(self.enabled(button))

    def test_macos_requires_usb_source_address_and_fresh_boot_for_root(self):
        d = self.dialog
        d.kit, d.stage = str(self.folder), 'prepared'
        d.ack.set(True)
        d.usb = dict(self.usb, usb_address_ready=False)
        with patch.object(ui.sys, 'platform', 'darwin'):
            d.refresh()
            self.assertFalse(self.enabled(d.upgrade_button))
        d.stage = 'os_verified'
        with patch.object(d, 'start', side_effect=lambda _, fn: fn(lambda _: None)), \
                patch.object(upgrade, 'verify_boot', side_effect=root_setup.SetupError('firmware_boot_not_verified')), \
                patch.object(root_setup, 'prepared_images') as prepare:
            with self.assertRaisesRegex(root_setup.SetupError, 'firmware_boot_not_verified'):
                d.continue_root()
            prepare.assert_not_called()


if __name__ == '__main__':
    unittest.main()
