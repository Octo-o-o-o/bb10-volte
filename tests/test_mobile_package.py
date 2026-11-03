"""Adversarial package tests exercise the actual phone verifier with fresh keys."""
import base64
import importlib.util
import json
import io
import os
from pathlib import Path
import shutil
import subprocess
import struct
import sys
import tempfile
import unittest
from unittest import mock
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

    def signed_bundle(self, version, capabilities, blobs=None):
        blobs = dict(self.blobs if blobs is None else blobs)
        manifest = dict(self.manifest, version=version, capabilities=capabilities,
                        files={name: {'sha256': package.sha(data), 'size': len(data)}
                               for name, data in blobs.items()})
        raw = package.canonical(manifest)
        signature = dict(self.envelope, signature=base64.b64encode(package.sign(raw, self.private)).decode('ascii'))
        return manifest, raw, package.canonical(signature), blobs

    def write_source_bundle(self, folder, bundle):
        manifest, raw, signature, blobs = bundle
        folder.mkdir(parents=True)
        for name, data in dict(blobs, **{'manifest.json': raw, 'manifest.sig.json': signature}).items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            os.chmod(str(path), 0o600)

    def release_core(self, manifest):
        core = dict(manifest, files={name: item for name, item in manifest['files'].items()
                                    if name != 'runtime/entry.py'})
        return self.entry.digest(self.entry.canonical(core))

    @unittest.skipUnless(hasattr(os, 'geteuid'), 'POSIX private-directory semantics required')
    def test_source_snapshot_verifies_executed_copy_even_if_unused_source_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = str(Path(temp).resolve() / 'private')
            source = Path(temp).resolve() / 'source'
            bundle = self.signed_bundle('0.1.0.18', ['safe_job_outcome_v1', 'active_selection_guard_v1'])
            self.write_source_bundle(source, bundle)
            with mock.patch.object(self.entry, 'ROOT', root), mock.patch.object(self.entry, 'RELEASE_KEY', self.key), \
                 mock.patch.object(self.entry, 'RELEASE_VERSION', bundle[0]['version']), \
                 mock.patch.object(self.entry, 'RELEASE_CORE_SHA256', self.release_core(bundle[0])):
                target, proof = self.entry.source_snapshot(str(source), self.blobs['runtime/entry.py'])
                self.assertEqual(proof.folder, target)
                self.assertEqual((Path(target) / 'runtime/worker.py').read_bytes(), self.blobs['runtime/worker.py'])
                (source / 'runtime/worker.py').write_bytes(b'source is no longer executed')
                with mock.patch.object(self.entry, 'read_bundle', wraps=self.entry.read_bundle) as read:
                    selected, proof = self.entry.source_snapshot(str(source), self.blobs['runtime/entry.py'])
                self.assertEqual(selected, target)
                self.assertEqual([call.args[0] for call in read.call_args_list], [target])
                self.assertEqual(proof.manifest, bundle[0])
                (Path(target) / 'runtime/worker.py').write_bytes(b'corrupt executed copy')
                (source / 'runtime/worker.py').write_bytes(self.blobs['runtime/worker.py'])
                with self.assertRaisesRegex(self.entry.MobileError, 'package_changed'):
                    self.entry.source_snapshot(str(source), self.blobs['runtime/entry.py'])
                self.assertEqual((Path(target) / 'runtime/worker.py').read_bytes(), b'corrupt executed copy')

    @unittest.skipUnless(hasattr(os, 'geteuid'), 'POSIX private-directory semantics required')
    def test_source_snapshot_requires_full_valid_source_before_first_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = str(Path(temp).resolve() / 'private')
            source = Path(temp).resolve() / 'source'
            bundle = self.signed_bundle('0.1.0.18', ['safe_job_outcome_v1', 'active_selection_guard_v1'])
            self.write_source_bundle(source, bundle)
            with mock.patch.object(self.entry, 'ROOT', root), mock.patch.object(self.entry, 'RELEASE_KEY', self.key), \
                 mock.patch.object(self.entry, 'RELEASE_VERSION', bundle[0]['version']), \
                 mock.patch.object(self.entry, 'RELEASE_CORE_SHA256', self.release_core(bundle[0])):
                worker = source / 'runtime/worker.py'
                worker.write_bytes(b'corrupt source')
                with self.assertRaisesRegex(self.entry.MobileError, 'package_changed'):
                    self.entry.source_snapshot(str(source), self.blobs['runtime/entry.py'])
                self.assertFalse(Path(root).exists())
                worker.write_bytes(self.blobs['runtime/worker.py'])
                with self.assertRaisesRegex(self.entry.MobileError, 'bridge_bundle_changed'):
                    self.entry.source_snapshot(str(source), b'wrong bridge entry')
                self.assertFalse(Path(root).exists())
                original_read = self.entry.read_bundle
                def changed_after_header(path, key=None):
                    manifest, unused_raw, signature, blobs = original_read(path, key)
                    return manifest, b'different header', signature, blobs
                with mock.patch.object(self.entry, 'read_bundle', side_effect=changed_after_header):
                    with self.assertRaisesRegex(self.entry.MobileError, 'source_manifest_changed'):
                        self.entry.source_snapshot(str(source), self.blobs['runtime/entry.py'])
                self.assertFalse(Path(root).exists())

    @unittest.skipUnless(hasattr(os, 'geteuid'), 'POSIX private-directory semantics required')
    def test_active_prescreen_only_skips_body_of_an_unselected_signed_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = str(Path(temp).resolve() / 'private')
            guards = ['safe_job_outcome_v1', 'active_selection_guard_v1']
            fallback = self.signed_bundle('0.1.0.18', guards)
            old = self.signed_bundle('0.1.0.13', [])
            newer = self.signed_bundle('0.1.0.19', guards)
            with mock.patch.object(self.entry, 'ROOT', root), mock.patch.object(self.entry, 'RELEASE_KEY', self.key):
                fallback_path, fallback_proof = self.entry.snapshot(fallback, _return_proof=True)
                old_path = self.entry.snapshot(old)
                new_path = self.entry.snapshot(newer)
                pointer = Path(root) / 'active.json'
                pointer.write_bytes(self.entry.canonical({'manifest_sha256': self.entry.digest(old[1])}))
                os.chmod(str(pointer), 0o600)
                old_worker = Path(old_path) / 'runtime/worker.py'
                old_worker.write_bytes(b'damaged but never selected')
                with mock.patch.object(self.entry, 'read_bundle', wraps=self.entry.read_bundle) as read:
                    selected, proof = self.entry.active_bundle(fallback_path, fallback_proof, _return_proof=True)
                self.assertEqual((selected, proof), (fallback_path, fallback_proof))
                self.assertEqual(read.call_count, 0)
                extra = Path(old_path) / 'runtime/unsigned.py'
                extra.write_bytes(b'unsigned'); os.chmod(str(extra), 0o600)
                with self.assertRaisesRegex(self.entry.MobileError, 'unexpected_snapshot_member'):
                    self.entry.active_bundle(fallback_path, fallback_proof, _return_proof=True)
                extra.unlink()
                pointer.write_bytes(self.entry.canonical({'manifest_sha256': self.entry.digest(newer[1])}))
                selected, proof = self.entry.active_bundle(fallback_path, fallback_proof, _return_proof=True)
                self.assertEqual(selected, new_path)
                self.assertEqual(proof.manifest, newer[0])
                (Path(new_path) / 'runtime/worker.py').write_bytes(b'corrupt selected snapshot')
                with self.assertRaisesRegex(self.entry.MobileError, 'package_changed'):
                    self.entry.active_bundle(fallback_path, fallback_proof, _return_proof=True)

    @unittest.skipUnless(hasattr(os, 'geteuid'), 'POSIX private-directory semantics required')
    def test_signed_old_active_rollback_binding_still_requires_full_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            root = str(Path(temp).resolve() / 'private')
            guards = ['safe_job_outcome_v1', 'active_selection_guard_v1']
            fallback = self.signed_bundle('0.1.0.18', guards)
            old = self.signed_bundle('0.1.0.17', guards)
            with mock.patch.object(self.entry, 'ROOT', root), mock.patch.object(self.entry, 'RELEASE_KEY', self.key):
                fallback_path, fallback_proof = self.entry.snapshot(fallback, _return_proof=True)
                old_path = self.entry.snapshot(old)
                pointer = Path(root) / 'active.json'
                pointer.write_bytes(self.entry.canonical({'manifest_sha256': self.entry.digest(old[1]),
                                                          'for_bundle': self.entry.digest(fallback[1])}))
                os.chmod(str(pointer), 0o600)
                selected, proof = self.entry.active_bundle(fallback_path, fallback_proof, _return_proof=True)
                self.assertEqual(selected, old_path)
                self.assertEqual(proof.manifest, old[0])
                (Path(old_path) / 'runtime/worker.py').write_bytes(b'corrupt rollback')
                with self.assertRaisesRegex(self.entry.MobileError, 'package_changed'):
                    self.entry.active_bundle(fallback_path, fallback_proof, _return_proof=True)

    @unittest.skipUnless(hasattr(os, 'geteuid'), 'POSIX private-directory semantics required')
    def test_foreground_import_uses_verified_private_snapshot_not_changed_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = str(Path(temp).resolve() / 'private')
            source = Path(temp).resolve() / 'source'
            blobs = dict(self.blobs, **{'runtime/worker.py': b'ORIGIN = "verified snapshot"\n'})
            bundle = self.signed_bundle('0.1.0.18', ['safe_job_outcome_v1', 'active_selection_guard_v1'], blobs)
            self.write_source_bundle(source, bundle)
            with mock.patch.object(self.entry, 'ROOT', root), mock.patch.object(self.entry, 'RELEASE_KEY', self.key), \
                 mock.patch.object(self.entry, 'RELEASE_VERSION', bundle[0]['version']), \
                 mock.patch.object(self.entry, 'RELEASE_CORE_SHA256', self.release_core(bundle[0])), \
                 mock.patch.object(self.entry.subprocess, 'call', return_value=0):
                self.entry.source_snapshot(str(source), blobs['runtime/entry.py'])
                (source / 'runtime/worker.py').write_bytes(b'ORIGIN = "untrusted source"\n')
                fallback, proof = self.entry.source_snapshot(str(source), blobs['runtime/entry.py'])
                selected, selected_proof = self.entry.active_bundle(fallback, proof, _return_proof=True)
                self.entry.trusted_python(selected, selected_proof)
                spec = importlib.util.spec_from_file_location('snapshot_worker_test', Path(selected) / 'runtime/worker.py')
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.assertEqual(module.ORIGIN, 'verified snapshot')
                self.assertEqual(Path(module.__file__).resolve(), Path(selected) / 'runtime/worker.py')

    @unittest.skipUnless(hasattr(os, 'geteuid'), 'POSIX private-directory semantics required')
    def test_active_prescreen_respects_guards_and_rollback_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            root = str(Path(temp).resolve() / 'private')
            guards = ['safe_job_outcome_v1', 'active_selection_guard_v1']
            fallback = self.signed_bundle('0.1.0.18', guards)
            cases = [
                ('0.1.0.13', [], 'current', False),
                ('0.1.0.14', guards[:1], 'current', False),
                ('0.1.0.15', guards[1:], 'current', False),
                ('0.1.0.16', guards, None, False),
                ('0.1.0.17', guards, 'other', False),
                ('0.1.0.17', guards, 'current', True),
                ('0.1.0.19', guards, None, True),
            ]
            with mock.patch.object(self.entry, 'ROOT', root), mock.patch.object(self.entry, 'RELEASE_KEY', self.key):
                fallback_path, fallback_proof = self.entry.snapshot(fallback, _return_proof=True)
                pointer = Path(root) / 'active.json'
                for version, caps, binding, selected in cases:
                    with self.subTest(version=version, capabilities=caps, binding=binding):
                        candidate = self.signed_bundle(version, caps)
                        candidate_path = self.entry.snapshot(candidate)
                        value = {'manifest_sha256': self.entry.digest(candidate[1])}
                        if binding is not None:
                            value['for_bundle'] = self.entry.digest(fallback[1]) if binding == 'current' else 'f' * 64
                        pointer.write_bytes(self.entry.canonical(value)); os.chmod(str(pointer), 0o600)
                        result, proof = self.entry.active_bundle(fallback_path, fallback_proof, _return_proof=True)
                        self.assertEqual(result, candidate_path if selected else fallback_path)
                        self.assertEqual(proof.manifest, candidate[0] if selected else fallback[0])

    @unittest.skipUnless(hasattr(os, 'geteuid'), 'POSIX private-directory semantics required')
    def test_active_prescreen_rejects_tampered_signature_and_directory_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = str(Path(temp).resolve() / 'private')
            guards = ['safe_job_outcome_v1', 'active_selection_guard_v1']
            fallback = self.signed_bundle('0.1.0.18', guards)
            old = self.signed_bundle('0.1.0.13', [])
            with mock.patch.object(self.entry, 'ROOT', root), mock.patch.object(self.entry, 'RELEASE_KEY', self.key):
                fallback_path, fallback_proof = self.entry.snapshot(fallback, _return_proof=True)
                old_path = self.entry.snapshot(old)
                pointer = Path(root) / 'active.json'
                pointer.write_bytes(self.entry.canonical({'manifest_sha256': self.entry.digest(old[1])}))
                os.chmod(str(pointer), 0o600)
                signature = Path(old_path) / 'manifest.sig.json'
                signature.write_bytes(self.entry.canonical(dict(self.envelope, signature='AA==')))
                with self.assertRaisesRegex(self.entry.MobileError, 'invalid_signature'):
                    self.entry.active_bundle(fallback_path, fallback_proof, _return_proof=True)
                signature.write_bytes(old[2])
                original = self.entry.read_bundle_manifest
                def replace_after_metadata(path, key=None):
                    value = original(path, key)
                    os.rename(path, path + '.previous')
                    shutil.copytree(path + '.previous', path)
                    os.chmod(path, 0o700)
                    return value
                with mock.patch.object(self.entry, 'read_bundle_manifest', side_effect=replace_after_metadata):
                    with self.assertRaisesRegex(self.entry.MobileError, 'snapshot_changed'):
                        self.entry.active_bundle(fallback_path, fallback_proof, _return_proof=True)

    def test_valid_signature_and_archive(self):
        value = self.entry.read_archive(str(self.archive()), self.key)
        self.assertEqual(value[0], self.manifest)
        self.assertEqual(value[3], self.blobs)

    def test_downloaded_hash_is_checked_on_the_bytes_actually_parsed(self):
        from unittest import mock
        path = self.archive()
        expected = package.sha(path.read_bytes())
        self.assertEqual(self.entry.read_archive(str(path), self.key, expected)[0], self.manifest)
        with mock.patch.object(self.entry, 'bounded_directory') as parse:
            with self.assertRaisesRegex(self.entry.MobileError, 'package_changed'):
                self.entry.read_archive(str(path), self.key, '0' * 64)
            parse.assert_not_called()

    def test_closed_progress_pipe_does_not_interrupt_pathtrust(self):
        class ClosedPipe:
            def write(self, value):
                raise OSError('closed pipe')
        bundle = ({'files': {'runtime/a.py': {}, 'runtime/b.py': {}}}, b'', b'', {})
        with mock.patch.object(self.entry, 'BRIDGE_PROGRESS', True), \
             mock.patch.object(self.entry.sys, 'stdout', ClosedPipe()), \
             mock.patch.object(self.entry, '_verified_snapshot', return_value=mock.Mock(manifest=bundle[0])), \
             mock.patch.object(self.entry, '_check_snapshot_proof'), \
             mock.patch.object(self.entry.subprocess, 'call', return_value=0) as trust:
            self.assertEqual(self.entry.trusted_python('/verified'), bundle[0])
            self.assertEqual(trust.call_count, 2)
            self.assertFalse(self.entry.BRIDGE_PROGRESS)

    def test_foreground_bundle_is_bound_to_the_pinned_entry_and_release(self):
        manifest = dict(self.manifest, capabilities=['safe_job_outcome_v1', 'active_selection_guard_v1'])
        bundle = (manifest, self.raw, self.signature, self.blobs)
        core = dict(manifest, files={name: item for name, item in manifest['files'].items() if name != 'runtime/entry.py'})
        with mock.patch.object(self.entry, 'RELEASE_VERSION', self.manifest['version']), \
             mock.patch.object(self.entry, 'RELEASE_CORE_SHA256', self.entry.digest(self.entry.canonical(core))):
            self.entry.verify_bridge_bundle(bundle, self.blobs['runtime/entry.py'])
            with self.assertRaisesRegex(self.entry.MobileError, 'bridge_bundle_changed'):
                self.entry.verify_bridge_bundle(bundle, b'older entry')
            for changed in (dict(manifest, version='0.1.0.0'), dict(manifest, capabilities=[])):
                with self.assertRaisesRegex(self.entry.MobileError, 'bridge_bundle_changed'):
                    self.entry.verify_bridge_bundle((changed, self.raw, self.signature, self.blobs),
                                                    self.blobs['runtime/entry.py'])
            other_blobs = dict(self.blobs, **{'runtime/worker.py': b'# another signed worker\n'})
            other = dict(manifest, files={name: {'sha256': package.sha(data), 'size': len(data)}
                                          for name, data in other_blobs.items()})
            other_raw = package.canonical(other)
            other_envelope = dict(self.envelope, signature=base64.b64encode(package.sign(other_raw, self.private)).decode('ascii'))
            other_path = self.directory / 'same-release-different-worker.zip'
            package.write_zip(other_path, dict(other_blobs, **{'manifest.json': other_raw,
                                                              'manifest.sig.json': package.canonical(other_envelope)}))
            other_bundle = self.entry.read_archive(str(other_path), self.key)
            with self.assertRaisesRegex(self.entry.MobileError, 'bridge_bundle_changed'):
                self.entry.verify_bridge_bundle(other_bundle, self.blobs['runtime/entry.py'])

    @unittest.skipUnless(hasattr(os, 'geteuid'), 'POSIX private-directory semantics required')
    def test_verified_snapshot_proof_is_single_process_and_revalidated_next_request(self):
        with tempfile.TemporaryDirectory() as temp:
            root = str((Path(temp).resolve() / 'private'))
            bundle = (self.manifest, self.raw, self.signature, self.blobs)
            with mock.patch.object(self.entry, 'ROOT', root), mock.patch.object(self.entry, 'RELEASE_KEY', self.key), \
                 mock.patch.object(self.entry, 'read_bundle', wraps=self.entry.read_bundle) as read, \
                 mock.patch.object(self.entry.subprocess, 'call', return_value=0) as trust:
                folder, proof = self.entry.snapshot(bundle, _return_proof=True)
                # New staging and final directory are each verified; neither
                # selecting nor pathtrust rereads that same private snapshot.
                self.assertEqual(read.call_count, 2)
                selected, selected_proof = self.entry.active_bundle(folder, proof, _return_proof=True)
                self.assertEqual(self.entry.trusted_python(selected, selected_proof), self.manifest)
                self.assertEqual(read.call_count, 2)
                self.assertEqual(trust.call_count, 2)
                pointer = Path(root) / 'active.json'
                pointer.write_bytes(self.entry.canonical({'manifest_sha256': self.entry.digest(self.raw)}))
                os.chmod(str(pointer), 0o600)
                selected, selected_proof = self.entry.active_bundle(folder, proof, _return_proof=True)
                self.entry.trusted_python(selected, selected_proof)
                self.assertEqual(read.call_count, 2)
                with mock.patch.object(self.entry.os, 'getpid', return_value=proof.pid + 1):
                    with self.assertRaisesRegex(self.entry.MobileError, 'snapshot_changed'):
                        self.entry.trusted_python(folder, proof)
                (Path(folder) / 'runtime/worker.py').write_bytes(b'corrupt')
                # A later request never accepts the old proof as a cache.
                with self.assertRaisesRegex(self.entry.MobileError, 'package_changed'):
                    self.entry.snapshot(bundle, _return_proof=True)

    @unittest.skipUnless(hasattr(os, 'geteuid'), 'POSIX private-directory semantics required')
    def test_snapshot_rejects_wrong_signed_contents_and_unsigned_modules(self):
        with tempfile.TemporaryDirectory() as temp:
            root = str((Path(temp).resolve() / 'private'))
            bundle = (self.manifest, self.raw, self.signature, self.blobs)
            with mock.patch.object(self.entry, 'ROOT', root), mock.patch.object(self.entry, 'RELEASE_KEY', self.key):
                folder = Path(self.entry.snapshot(bundle))
                for name in ('runtime/unsigned.py', 'runtime/worker.pyc'):
                    extra = folder / name
                    extra.write_bytes(b'unsigned'); os.chmod(str(extra), 0o600)
                    with self.assertRaisesRegex(self.entry.MobileError, 'unexpected_snapshot_member'):
                        self.entry.trusted_python(str(folder))
                    extra.unlink()
                worker_path = folder / 'runtime/worker.py'
                os.chmod(str(worker_path), 0o644)
                with self.assertRaisesRegex(self.entry.MobileError, 'unsafe_snapshot_member'):
                    self.entry.trusted_python(str(folder))
                os.chmod(str(worker_path), 0o600)
                link = folder / 'runtime/unlisted.py'
                link.symlink_to(worker_path)
                with self.assertRaisesRegex(self.entry.MobileError, 'unsafe_snapshot_member'):
                    self.entry.trusted_python(str(folder))
                link.unlink()
                wrong_manifest = dict(self.manifest, version='0.1.0.2')
                wrong_raw = package.canonical(wrong_manifest)
                wrong_envelope = dict(self.envelope, signature=base64.b64encode(package.sign(wrong_raw, self.private)).decode('ascii'))
                (folder / 'manifest.json').write_bytes(wrong_raw)
                (folder / 'manifest.sig.json').write_bytes(package.canonical(wrong_envelope))
                with self.assertRaisesRegex(self.entry.MobileError, 'snapshot_changed'):
                    self.entry.snapshot(bundle)

    @unittest.skipUnless(hasattr(os, 'geteuid'), 'POSIX private-directory semantics required')
    def test_directory_replacement_during_snapshot_validation_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = str((Path(temp).resolve() / 'private'))
            bundle = (self.manifest, self.raw, self.signature, self.blobs)
            with mock.patch.object(self.entry, 'ROOT', root), mock.patch.object(self.entry, 'RELEASE_KEY', self.key):
                folder = self.entry.snapshot(bundle)
                old_layout = self.entry._snapshot_layout
                def swap_after_layout(path, manifest):
                    old_layout(path, manifest)
                    os.rename(path, path + '.previous')
                    shutil.copytree(path + '.previous', path)
                    os.chmod(path, 0o700)
                with mock.patch.object(self.entry, '_snapshot_layout', side_effect=swap_after_layout):
                    with self.assertRaisesRegex(self.entry.MobileError, 'snapshot_changed'):
                        self.entry._verified_snapshot(folder, self.raw)

    @unittest.skipUnless(hasattr(os, 'geteuid'), 'POSIX private-directory semantics required')
    def test_disappearing_snapshot_is_never_recreated_by_identity_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root = str((Path(temp).resolve() / 'private'))
            bundle = (self.manifest, self.raw, self.signature, self.blobs)
            with mock.patch.object(self.entry, 'ROOT', root), mock.patch.object(self.entry, 'RELEASE_KEY', self.key):
                folder = self.entry.snapshot(bundle)
                verify = self.entry.verify_private_directory
                def disappear(path):
                    if path == folder:
                        os.rename(path, path + '.previous')
                    return verify(path)
                with mock.patch.object(self.entry, 'verify_private_directory', side_effect=disappear):
                    with self.assertRaises(OSError):
                        self.entry._verified_snapshot(folder)
                self.assertFalse(os.path.lexists(folder))

    @unittest.skipUnless(hasattr(os, 'geteuid'), 'POSIX private-directory semantics required')
    def test_concurrent_snapshot_winner_must_match_the_requested_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = str((Path(temp).resolve() / 'private'))
            bundle = (self.manifest, self.raw, self.signature, self.blobs)
            wrong_raw = package.canonical(dict(self.manifest, version='0.1.0.2'))
            wrong_envelope = dict(self.envelope, signature=base64.b64encode(package.sign(wrong_raw, self.private)).decode('ascii'))
            def raced(source, destination):
                shutil.copytree(source, destination)
                Path(destination, 'manifest.json').write_bytes(wrong_raw)
                Path(destination, 'manifest.sig.json').write_bytes(package.canonical(wrong_envelope))
                raise OSError('another process won')
            with mock.patch.object(self.entry, 'ROOT', root), mock.patch.object(self.entry, 'RELEASE_KEY', self.key), \
                 mock.patch.object(self.entry.os, 'rename', side_effect=raced):
                with self.assertRaisesRegex(self.entry.MobileError, 'snapshot_changed'):
                    self.entry.snapshot(bundle, _return_proof=True)

    @unittest.skipUnless(hasattr(os, 'geteuid'), 'POSIX private-directory semantics required')
    def test_missing_active_snapshot_does_not_create_an_empty_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = str((Path(temp).resolve() / 'private'))
            bundle = (self.manifest, self.raw, self.signature, self.blobs)
            with mock.patch.object(self.entry, 'ROOT', root), mock.patch.object(self.entry, 'RELEASE_KEY', self.key):
                folder, proof = self.entry.snapshot(bundle, _return_proof=True)
                missing = Path(root) / 'snapshots' / ('f' * 64)
                pointer = Path(root) / 'active.json'
                pointer.write_bytes(self.entry.canonical({'manifest_sha256': 'f' * 64}))
                os.chmod(str(pointer), 0o600)
                with self.assertRaises(OSError):
                    self.entry.active_bundle(folder, proof, _return_proof=True)
                self.assertFalse(missing.exists())

    def test_guarded_bar_cannot_select_a_real_old_worker_after_rollback(self):
        from unittest import mock
        release_key = json.loads((ROOT / 'materials/mobile-release-key.json').read_text(encoding='ascii'))
        candidate = dict(self.manifest, version='0.1.0.17', capabilities=['safe_job_outcome_v1', 'active_selection_guard_v1'])
        candidate_raw = package.canonical(candidate)
        signature = dict(self.envelope, signature=base64.b64encode(package.sign(candidate_raw, self.private)).decode('ascii'))
        verified = self.entry.validate_manifest(candidate_raw, package.canonical(signature), self.key)
        fallback = (verified, candidate_raw, package.canonical(signature), self.blobs)
        fallback_id = self.entry.digest(candidate_raw)
        old_raw = package.canonical(dict(self.manifest, version='0.1.0.13'))
        old_signature = dict(self.envelope, signature=base64.b64encode(package.sign(old_raw, self.private)).decode('ascii'))
        old_manifest = self.entry.validate_manifest(old_raw, package.canonical(old_signature), self.key)
        historical = [('fixture', (old_manifest, old_raw, package.canonical(old_signature), self.blobs))]
        for version in ('0.1.0.13', '0.1.0.15', '0.1.0.16'):
            archive = ROOT / 'dist/mobile' / ('bb10-volte-' + version + '-update.zip')
            if archive.is_file():
                historical.append((version, self.entry.read_archive(str(archive), release_key)))
        for version, old in historical:
            old_id = self.entry.digest(old[1])
            self.assertFalse(self.entry.supports_selection_guard(old[0]))
            pointer = self.entry.canonical({'manifest_sha256': old_id, 'for_bundle': fallback_id})
            with self.subTest(version=version), mock.patch.object(self.entry, 'ROOT', '/private'), \
                 mock.patch.object(self.entry.os.path, 'lexists', return_value=True), \
                 mock.patch.object(self.entry, 'regular', return_value=pointer), \
                 mock.patch.object(self.entry, 'verify_private_directory'), \
                 mock.patch.object(self.entry, 'read_bundle', side_effect=lambda path: fallback if path == '/fallback' else old):
                self.assertEqual(self.entry.active_bundle('/fallback'), '/fallback')

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
