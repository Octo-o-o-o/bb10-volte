"""Adversarial package tests exercise the actual phone verifier with fresh keys."""
import base64
import importlib.util
import json
import io
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import package_mobile as package


class MobilePackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temporary.name).resolve()
        cls.private = cls.directory / 'test.pem'
        subprocess.run([package.openssl(), 'genpkey', '-algorithm', 'RSA', '-pkeyopt',
                        'rsa_keygen_bits:2048', '-out', str(cls.private)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        cls.key = package.public_key(cls.private)
        cls.entry = package.entry_module()
        cls.blobs = {'runtime/entry.py': b'# verified entry\n',
                     'runtime/worker.py': b'# verified worker\n', 'payload/payload.json': b'{}'}
        cls.manifest = {'schema': 2, 'kind': 'bb10-volte-mobile', 'protocol': 2, 'version': '0.1.0.1',
                        'files': {name: {'sha256': package.sha(data), 'size': len(data)}
                                  for name, data in cls.blobs.items()}}
        cls.raw = package.canonical(cls.manifest)
        cls.envelope = {'algorithm': cls.entry.ALGORITHM, 'key_id': cls.key['key_id'],
                        'signature': base64.b64encode(package.sign(cls.raw, cls.private)).decode('ascii')}
        cls.signature = package.canonical(cls.envelope)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def archive(self, additions=None, replacements=None):
        path = self.directory / 'candidate.zip'
        blobs = dict(self.blobs, **{'manifest.json': self.raw, 'manifest.sig.json': self.signature})
        blobs.update(replacements or {})
        blobs.update(additions or {})
        package.write_zip(path, blobs)
        return path

    def reject_archive(self, path):
        with self.assertRaises((self.entry.MobileError, zipfile.BadZipFile)):
            self.entry.read_archive(str(path), self.key)

    def test_valid_signature_and_archive(self):
        value = self.entry.read_archive(str(self.archive()), self.key)
        self.assertEqual(value[0], self.manifest)
        self.assertEqual(value[3], self.blobs)

    def test_signature_covers_exact_bytes_not_reserialized_json(self):
        with self.assertRaises(self.entry.MobileError):
            self.entry.validate_manifest(self.raw + b'\n', self.signature, self.key)

    def test_wrong_publisher_wrong_algorithm_and_malformed_signature(self):
        for changed in ({'key_id': '0' * 64}, {'algorithm': 'none'}, {'signature': 'AA=='},
                        {'signature': self.envelope['signature'][:-4] + '!!!!'}):
            with self.subTest(changed=list(changed)):
                value = dict(self.envelope, **changed)
                with self.assertRaises(self.entry.MobileError):
                    self.entry.verify_signature(self.raw, value, self.key)

    def test_noncanonical_base64_and_small_key_rejected(self):
        for value in ('A===', 'AA', 'AA==\n', 'AB=='):
            with self.assertRaises(self.entry.MobileError):
                self.entry.decode64(value)
        with self.assertRaises(self.entry.MobileError):
            self.entry.verify_signature(self.raw, self.envelope, dict(self.key, n='ff'))

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(self.entry.MobileError):
            self.entry.json_bytes(b'{"schema":2,"schema":2}')

    def test_entry_cleanup_cannot_remove_source_bundle_or_shared_files(self):
        from unittest import mock
        for path in ('/accounts/1000/shared/documents/entry.py',
                     '/var/bb10_volte-mobile/snapshots/' + 'a' * 64 + '/runtime/entry.py',
                     '/var/bb10_mobile_entry_not-a-nonce/entry.py',
                     '/var/bb10_mobile_entry_' + 'a' * 32 + '/different.py'):
            with mock.patch.object(self.entry, '__file__', path), \
                 mock.patch.object(self.entry.os, 'geteuid', return_value=0, create=True), \
                 mock.patch.object(self.entry.os, 'unlink') as remove, \
                 mock.patch.object(self.entry.os, 'rmdir') as directory:
                with self.assertRaises(self.entry.MobileError):
                    self.entry.cleanup_entry()
                remove.assert_not_called()
                directory.assert_not_called()

    def test_changed_payload_and_unlisted_file_rejected(self):
        self.reject_archive(self.archive(replacements={'runtime/worker.py': b'evil'}))
        self.reject_archive(self.archive(additions={'runtime/extra.py': b'evil'}))

    def test_traversal_absolute_windows_and_empty_path_rejected(self):
        for name in ('../outside.py', '/runtime/evil.py', 'runtime/../evil.py',
                     'runtime//evil.py', 'runtime\\evil.py', 'C:/runtime/evil.py'):
            with self.subTest(name=name):
                self.reject_archive(self.archive(additions={name: b'evil'}))

    def test_duplicate_member_rejected(self):
        import warnings
        path = self.archive()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(path, 'a') as archive:
                archive.writestr('runtime/worker.py', self.blobs['runtime/worker.py'])
        self.reject_archive(path)

    def test_symlink_member_rejected(self):
        path = self.directory / 'symlink.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in dict(self.blobs, **{'manifest.json': self.raw,
                                                'manifest.sig.json': self.signature}).items():
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = ((0o120777 if name == 'runtime/worker.py' else 0o100600) << 16)
                archive.writestr(info, data)
        self.reject_archive(path)

    def test_size_limits_before_decompression(self):
        path = self.archive()
        old = self.entry.MAX_TOTAL
        try:
            self.entry.MAX_TOTAL = 10
            self.reject_archive(path)
        finally:
            self.entry.MAX_TOTAL = old

    def test_signed_invalid_manifest_still_rejected(self):
        for change in ({'protocol': 999}, {'version': '../escape'}, {'files': {}}, {'schema': 1}):
            raw = package.canonical(dict(self.manifest, **change))
            envelope = dict(self.envelope, signature=base64.b64encode(package.sign(raw, self.private)).decode('ascii'))
            with self.assertRaises(self.entry.MobileError):
                self.entry.validate_manifest(raw, package.canonical(envelope), self.key)

    def test_old_runtime_size_metadata_does_not_bound_actual_expansion(self):
        # Python 3.2's reader can expose bytes beyond declared file_size. This
        # adversarial stream models that documented behavior, not modern zipfile.
        from unittest import mock
        archive = mock.Mock()
        archive.open.return_value = io.BytesIO(b'x' * (4 * 1024 * 1024))
        archive.getinfo.return_value.file_size = 1
        with self.assertRaisesRegex(self.entry.MobileError, 'expanded_member_too_large'):
            self.entry.bounded_member(archive, 'manifest.json', 131072)

    def test_mismatched_actual_member_size_is_rejected(self):
        from unittest import mock
        archive = mock.Mock()
        archive.open.return_value = io.BytesIO(b'abc')
        archive.getinfo.return_value.file_size = 2
        with self.assertRaisesRegex(self.entry.MobileError, 'member_size_changed'):
            self.entry.bounded_member(archive, 'manifest.json', 131072)

    def test_central_directory_allocations_are_bounded_before_zip_parser(self):
        data = bytearray(self.archive().read_bytes())
        end = data.rfind(b'PK\x05\x06')
        struct.pack_into('<HH', data, end + 8, 40000, 40000)
        with self.assertRaisesRegex(self.entry.MobileError, 'too_many_members'):
            self.entry.bounded_directory(bytes(data))


if __name__ == '__main__':
    unittest.main()
