"""Keep payment QR bytes and the native UI tied to the reviewed source."""
from pathlib import Path
import io
import sys
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import mobile_support


class SupportPackagingTests(unittest.TestCase):
    def bar(self, replacement=None, extra=None):
        blobs = {'native/assets/support/' + Path(name).name: (ROOT / name).read_bytes()
                 for name in mobile_support.support_files()}
        blobs.update({'native/assets/' + p.name: p.read_bytes()
                      for p in (ROOT / 'mobile/native/assets').glob('*.qml')})
        blobs.update(replacement or {})
        blobs.update(extra or {})
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            for name, data in blobs.items():
                archive.writestr(name, data)
        output.seek(0)
        return zipfile.ZipFile(output)

    def test_exact_desktop_receipt_images_and_current_qml_pass(self):
        with self.bar() as archive:
            mobile_support.verify_bar_support(archive)

    def test_changed_payment_pixels_or_stale_ui_cannot_ship(self):
        for name in ('native/assets/support/wechat-custom.png', 'native/assets/Support.qml'):
            with self.subTest(name=name), self.bar({name: b'changed'}) as archive:
                with self.assertRaises(ValueError):
                    mobile_support.verify_bar_support(archive)

    def test_unlisted_payment_asset_cannot_ship(self):
        with self.bar(extra={'native/assets/support/original-receipt.png': b'private'}) as archive:
            with self.assertRaises(ValueError):
                mobile_support.verify_bar_support(archive)


if __name__ == '__main__':
    unittest.main()
