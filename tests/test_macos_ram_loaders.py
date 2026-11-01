"""The damaged upstream archive must never cause an unchecked loader fallback."""
import copy
import gzip
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import macos_root as m


class RamLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.data = b'intact signed loader fixture' * 200
        self.packed = gzip.compress(self.data, mtime=0)
        self.source = b'pinned executable prefix' + self.packed + b'tail'
        self.item = {'source': 'cap.exe', 'offset': len(b'pinned executable prefix'),
                     'compressed_bytes': len(self.packed),
                     'compressed_sha256': hashlib.sha256(self.packed).hexdigest(),
                     'bytes': len(self.data), 'sha256': hashlib.sha256(self.data).hexdigest()}
        self.spec = {'shared_files': {'cap.exe': hashlib.sha256(self.source).hexdigest()},
                     'ram_loaders': {'loader_9400270A-00.bin': self.item}}
        (self.folder / 'cap.exe').write_bytes(self.source)

    def test_intact_pinned_gzip_extracts_exactly_without_changing_source(self):
        m.prepare_ram_loaders(self.folder, self.spec)
        self.assertEqual((self.folder / 'loaders/loader_9400270A-00.bin').read_bytes(), self.data)
        self.assertEqual((self.folder / 'cap.exe').read_bytes(), self.source)

    def test_source_slice_and_output_corruption_never_publish_a_loader(self):
        for field in ('source', 'offset', 'compressed_sha256', 'sha256', 'bytes'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                work = Path(directory)
                spec = copy.deepcopy(self.spec)
                item = spec['ram_loaders']['loader_9400270A-00.bin']
                source = self.source
                if field == 'source':
                    source += b'altered'
                elif field.endswith('sha256'):
                    item[field] = '0' * 64
                else:
                    item[field] += 1
                (work / 'cap.exe').write_bytes(source)
                with self.assertRaisesRegex(RuntimeError, 'tool_hash_mismatch'):
                    m.prepare_ram_loaders(work, spec)
                self.assertEqual(list((work / 'loaders').iterdir()), [])

    def test_gzip_crc_is_required_even_when_container_hashes_match(self):
        damaged = bytearray(self.packed)
        damaged[-8] ^= 1
        source = b'pinned executable prefix' + damaged + b'tail'
        (self.folder / 'cap.exe').write_bytes(source)
        self.spec['shared_files']['cap.exe'] = hashlib.sha256(source).hexdigest()
        self.item['compressed_sha256'] = hashlib.sha256(damaged).hexdigest()
        with self.assertRaisesRegex(RuntimeError, 'tool_hash_mismatch'):
            m.prepare_ram_loaders(self.folder, self.spec)
        self.assertEqual(list((self.folder / 'loaders').iterdir()), [])


class NativeToolPatchTests(unittest.TestCase):
    def test_exact_source_edits_and_result_are_all_verified(self):
        source, expected = b'prefix-CREATE-USB-tail', b'prefix-RETURN-USB-tail'
        spec = {'input_sha256': hashlib.sha256(source).hexdigest(),
                'sha256': hashlib.sha256(expected).hexdigest(),
                'patches': [{'offset': 7, 'before': b'CREATE'.hex(), 'after': b'RETURN'.hex()}]}
        self.assertEqual(m.patched_native_tool(source, spec), expected)
        for change in ('input', 'offset', 'before', 'after_length', 'result'):
            with self.subTest(change=change):
                edited = copy.deepcopy(spec)
                candidate = source
                if change == 'input':
                    candidate += b'unknown executable'
                elif change == 'result':
                    edited['sha256'] = '0' * 64
                elif change == 'after_length':
                    edited['patches'][0]['after'] += '00'
                elif change == 'before':
                    edited['patches'][0]['before'] = b'OTHERS'.hex()
                else:
                    edited['patches'][0]['offset'] += 1
                with self.assertRaisesRegex(RuntimeError, 'tool_hash_mismatch'):
                    m.patched_native_tool(candidate, edited)


if __name__ == '__main__':
    unittest.main()
