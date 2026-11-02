"""Shared mobile/desktop protocol: provenance, interruption and recovery."""
from contextlib import ExitStack
import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'device'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import unified_install as i
import unified_service as u
import profiles
from auto_carrier_view import registration_ready


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.backup = {'owner': i.policy.OWNER, 'variant': 'SQW100-4', 'files': {'ims.original': 'a' * 64}}
        self.receipt = {'schema': 2, 'owner': i.policy.OWNER, 'installation_id': '1' * 32,
            'operation_id': '2' * 32, 'source': 'mobile', 'variant': 'SQW100-4',
            'backup_manifest_sha256': 'b' * 64, 'files': dict(self.backup['files']),
            'readback': dict(self.backup['files']), 'destination': {'type': 'removable', 'id': 'sd/backup'},
            'all_original_hashes_verified': True}

    def check(self, value):
        return i.validate_backup_receipt(value, self.backup, 'b' * 64, '1' * 32)

    def test_mobile_receipt_has_honest_source_and_exact_readback(self):
        self.assertEqual(self.check(self.receipt)['source'], 'mobile')
        for kind in ('same_device', 'removable'):
            self.receipt['destination']['type'] = kind
            self.check(self.receipt)
        self.receipt['destination']['type'] = 'desktop'
        with self.assertRaisesRegex(AssertionError, 'backup_source_invalid'):
            self.check(self.receipt)

    def test_different_installation_manifest_or_missing_readback_is_rejected(self):
        for key, value in (('installation_id', '3' * 32), ('variant', 'SQN100-3'),
                           ('backup_manifest_sha256', 'c' * 64), ('readback', {}),
                           ('all_original_hashes_verified', False), ('schema', 3)):
            with self.subTest(key=key), self.assertRaises(AssertionError):
                self.check(dict(self.receipt, **{key: value}))

    def test_legacy_receipt_is_accepted_without_inventing_new_provenance(self):
        value = {'owner': i.policy.OWNER, 'all_original_hashes_verified': True, 'backup_manifest_sha256': 'b' * 64}
        self.assertIs(self.check(value), value)
        self.assertNotIn('source', value)


class StatusTests(unittest.TestCase):
    def test_read_status_checks_current_sim_without_exporting_identifier(self):
        raw = {'phase': 'running', 'manager_alive': True, 'native_alive': True,
               'status_from_current_boot': True, 'current': {'ims': 'connected', 'register_status': '200 OK', 'ran': 'LTE', 'radio': ['lte']}}
        saved = {'boot': ['boot'], 'operator': 'telecom', 'sim_sha256': 'secret-old-sim'}
        with ExitStack() as stack:
            for item in (patch.object(u, 'verify'), patch.object(u, 'boot_token', return_value=['boot']),
                         patch.object(u.s, 'read_status', return_value=raw),
                         patch.object(u.os.path, 'isfile', side_effect=lambda p: p in (u.SELECTION, u.BASE + '/enabled')),
                         patch.object(u.s, 'load', return_value=saved),
                         patch.object(u.device_info, 'read_identity', return_value={'variant': 'SQW100-4'}),
                         patch.object(u, 'card', return_value={'state': 'READY'}),
                         patch.object(u.policy, 'select', return_value={'sim_sha256': 'secret-new-sim'})):
                stack.enter_context(item)
            value = u.public_status()
            self.assertFalse(value['current_sim_matches'])
            self.assertFalse(registration_ready(value))
            self.assertNotIn('secret', json.dumps(value))
            u.policy.select.return_value = {'sim_sha256': 'secret-old-sim'}
            self.assertTrue(registration_ready(u.public_status()))
            u.policy.select.side_effect = ValueError('sim_not_ready')
            self.assertIsNone(u.public_status()['current_sim_matches'])
            self.assertFalse(registration_ready(u.public_status()))

    def test_desktop_sanitization_retains_sim_gate_but_not_private_values(self):
        from workflow import public_status
        raw = {'management_schema': 2, 'current_sim_matches': False, 'installed_management_schema': 2,
               'installed_stage': 'managed', 'sim_sha256': 'private', 'selected_operator': 'unicom'}
        clean = public_status(raw)
        self.assertEqual(clean['management_schema'], 2)
        self.assertIs(clean['current_sim_matches'], False)
        self.assertNotIn('sim_sha256', clean)
        raw['current_sim_matches'] = 'true'
        self.assertIsNone(public_status(raw)['current_sim_matches'])


class ActivationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.base, self.addon = self.root / 'payload', self.root / 'addons' / 'bb10-unified-volte'
        (self.base / 'device').mkdir(parents=True)
        (self.base / 'backup').mkdir()
        (self.base / 'device/unified_boot.sh').write_bytes(b'#!/bin/sh\nexit 0\n')
        self.pending = {'owner': i.policy.OWNER, 'phase': 'awaiting_desktop_backup', 'variant': 'SQW100-4', 'root_kind': 'autoroot-v4'}
        self.write_pending()
        (self.base / 'backup/manifest.json').write_text('{}')
        stack = ExitStack()
        self.addCleanup(stack.close)
        original_isfile = os.path.isfile
        original_lstat = os.lstat
        def phone_owned(path, *args, **kwargs):
            value = original_lstat(path, *args, **kwargs)
            if str(path) == str(self.addon / 'init/start.sh.new'):
                fields = list(value)
                fields[stat.ST_UID] = 0  # QNX fixture owner; host tests need no Root.
                value = os.stat_result(fields)
            return value
        for item in (patch.object(i, 'BASE', str(self.base)), patch.object(i, 'ADDON', str(self.addon)),
                     patch.object(i.os, 'lstat', side_effect=phone_owned),
                     patch.object(i, 'identity', return_value=({'variant': 'SQW100-4'}, 'passport')),
                     patch.object(i.os.path, 'isfile', side_effect=lambda p: p == '/tmp/root.done' or original_isfile(p)),
                     patch.object(i.s, 'phone_idle', return_value=True), patch.object(i.u, 'setup'),
                     patch.object(i.u, 'verify'), patch.object(i.u, 'boot_token', return_value=['boot']),
                     patch.object(i.migration, 'quiesce', return_value=None),
                     patch.object(i.n, 'read', side_effect=lambda p: Path(p).read_bytes()),
                     patch.object(i.n, 'command', return_value=b'')):
            stack.enter_context(item)

    def write_pending(self):
        (self.base / 'install-pending.json').write_text(json.dumps(self.pending))

    def test_crash_after_addon_creation_resumes_without_requiescing(self):
        original = i.persist
        def fail(path, raw, mode=0o600):
            if path == str(self.base) + '/enabled':
                raise OSError('power loss')
            return original(path, raw, mode)
        with patch.object(i, 'persist', side_effect=fail), self.assertRaises(OSError):
            i.activate()
        self.assertTrue((self.addon / 'init/start.sh').is_file())
        self.assertEqual(json.loads((self.base / 'activation.json').read_text())['phase'], 'committed')
        self.assertTrue(i.activate()['installed'])
        self.assertEqual(i.migration.quiesce.call_count, 1)
        self.assertTrue(i.activate()['already_committed'])

    def test_changed_addon_after_interruption_is_not_overwritten(self):
        original = i.persist
        with patch.object(i, 'persist', side_effect=lambda path, raw, mode=0o600:
                (_ for _ in ()).throw(OSError('power loss')) if path == str(self.base) + '/enabled' else original(path, raw, mode)):
            with self.assertRaises(OSError):
                i.activate()
        (self.addon / 'init/start.sh').write_bytes(b'other owner')
        with self.assertRaisesRegex(AssertionError, 'boot_addon_changed'):
            i.activate()
        self.assertEqual((self.addon / 'init/start.sh').read_bytes(), b'other owner')

    def test_interrupted_atomic_hook_write_resumes_only_expected_prefix(self):
        original = i.persist
        def crash(path, raw, mode=0o600):
            if path == str(self.addon) + '/init/start.sh':
                Path(path + '.new').write_bytes(raw[:4])
                raise OSError('power loss before atomic rename')
            return original(path, raw, mode)
        with patch.object(i, 'persist', side_effect=crash), self.assertRaises(OSError):
            i.activate()
        self.assertTrue(i.activate()['installed'])
        self.assertEqual((self.addon / 'init/start.sh').read_bytes(), (self.base / 'device/unified_boot.sh').read_bytes())
        self.assertFalse((self.addon / 'init/start.sh.new').exists())

    def test_foreign_temporary_hook_is_preserved(self):
        original = i.persist
        def crash(path, raw, mode=0o600):
            if path == str(self.addon) + '/init/start.sh':
                Path(path + '.new').write_bytes(b'foreign command')
                raise OSError('power loss')
            return original(path, raw, mode)
        with patch.object(i, 'persist', side_effect=crash), self.assertRaises(OSError):
            i.activate()
        with self.assertRaisesRegex(AssertionError, 'boot_addon_changed'):
            i.activate()
        self.assertEqual((self.addon / 'init/start.sh.new').read_bytes(), b'foreign command')

    def test_v2_hook_written_before_crash_is_idempotent_and_keeps_inode(self):
        self.pending['root_kind'] = 'autoroot-v2'
        self.write_pending()
        target = self.root / 'btool'
        original = b'#!/bin/sh\n. /base/scripts/sudtools.sh\nfinish\n'
        target.write_bytes(original)
        (self.base / 'backup/btool.original').write_bytes(original)
        inode = target.stat().st_ino
        write = i.persist
        def fail(path, raw, mode=0o600):
            if path == str(self.base) + '/boot-install.json':
                raise OSError('power loss')
            return write(path, raw, mode)
        with patch.object(i, 'BTOOL', str(target)):
            with patch.object(i, 'persist', side_effect=fail), self.assertRaises(OSError):
                i.activate()
            self.assertIn(i.HOOK, target.read_bytes())
            self.assertTrue(i.activate()['installed'])
            self.assertEqual(target.stat().st_ino, inode)
            self.assertEqual(target.read_bytes().count(i.HOOK), 1)


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.stage = '/var/bb10_auto_stage_123456789abc'
        self.fs, self.dirs = {}, {'/var', i.MANAGEMENT, self.stage}
        self.directory_modes = {path: 0o700 for path in self.dirs}
        self.umask = 0o077
        self.mode_changes = []
        self.fail_publish = False
        self.names = ('device/unified_boot.sh', 'device/unified_service.py', 'driver/fixed.so')
        payload = {name: ('payload:' + name).encode() for name in self.names}
        self.manifest = {'owner': i.policy.OWNER, 'schema': 1, 'files': {name: i.n.digest(raw) for name, raw in payload.items()}}
        self.fs.update({self.stage + '/' + name: raw for name, raw in payload.items()})
        self.fs[self.stage + '/payload.json'] = profiles.canonical(self.manifest)
        self.originals = {name: b'original' for name in i.dca.SOURCES}
        self.writes = []
        self.fail = None
        self.metadata = types.SimpleNamespace(st_ino=7, st_mode=stat.S_IFREG | 0o600, st_uid=0, st_gid=0)
        def atomic(path, raw, mode=0o600):
            if path.endswith(self.fail or '\0'):
                raise OSError('power loss')
            self.writes.append(path)
            self.fs[path] = raw
        def mkdir(path, mode=0o700):
            if path in self.dirs:
                raise FileExistsError()
            self.dirs.add(path)
            self.directory_modes[path] = mode & ~self.umask
        def private_directory(path):
            if path not in self.dirs:
                mkdir(path, 0o700)
        def chmod(path, mode):
            self.mode_changes.append((path, mode))
            self.directory_modes[path] = mode
        def lstat(path):
            if path in self.dirs:
                return types.SimpleNamespace(st_ino=7, st_mode=stat.S_IFDIR | self.directory_modes[path], st_uid=0, st_gid=0)
            return self.metadata
        def rename(source, destination):
            if self.fail_publish:
                raise OSError('power loss before publish')
            self.assertNotIn(destination, self.dirs)
            for key in list(self.fs):
                if key.startswith(source + '/'):
                    self.fs[destination + key[len(source):]] = self.fs.pop(key)
            for key in list(self.dirs):
                if key == source or key.startswith(source + '/'):
                    self.dirs.remove(key)
                    self.dirs.add(destination + key[len(source):])
                    self.directory_modes[destination + key[len(source):]] = self.directory_modes.pop(key)
        def walk(top):
            for folder in sorted(self.dirs):
                if folder == top or folder.startswith(top + '/'):
                    directories = [p[len(folder) + 1:] for p in self.dirs if p.startswith(folder + '/') and '/' not in p[len(folder) + 1:]]
                    files = [p[len(folder) + 1:] for p in self.fs if p.startswith(folder + '/') and '/' not in p[len(folder) + 1:]]
                    yield folder, directories, files
        stack = ExitStack()
        self.addCleanup(stack.close)
        for item in (patch.object(i, 'identity', return_value=({'variant': 'SQW100-4'}, 'passport')),
                     patch.object(i.s, 'phone_idle', return_value=True), patch.object(i, 'root_kind', return_value='autoroot-v4'),
                     patch.object(i.migration, 'inspect', return_value=None),
                     patch.object(i, 'original_source', side_effect=lambda name, unused: self.originals[name]),
                     patch.object(i.n, 'voice_policy', return_value=0), patch.object(i.radio, 'ue_usage_policy', return_value=0),
                     patch.object(i.n, 'crypto_policy', return_value={'swcr_id': -1, 'crypto_support': 0}),
                     patch.object(i, 'private_directory', side_effect=private_directory),
                     patch.object(i, 'device_binding', return_value='d' * 32),
                     patch.object(i.n, 'atomic', side_effect=atomic), patch.object(i.n, 'read', side_effect=lambda p: self.fs[p]),
                     patch.object(i.s, 'load', side_effect=lambda p: json.loads(self.fs[p])),
                     patch.object(i.u, 'PAYLOAD_FILES', self.names), patch.object(i.os.path, 'islink', return_value=False),
                     patch.object(i.os.path, 'realpath', side_effect=lambda p: p),
                     patch.object(i.os.path, 'lexists', side_effect=lambda p: p in self.fs or p in self.dirs),
                     patch.object(i.os.path, 'isfile', side_effect=lambda p: p in self.fs),
                     patch.object(i.os.path, 'isdir', side_effect=lambda p: p in self.dirs),
                     patch.object(i.os, 'lstat', side_effect=lstat), patch.object(i.os, 'mkdir', side_effect=mkdir),
                     patch.object(i.os, 'chmod', side_effect=chmod),
                     patch.object(i.os, 'rename', side_effect=rename), patch.object(i.os, 'walk', side_effect=walk)):
            stack.enter_context(item)

    def test_interrupted_private_prepare_keeps_first_original_bytes(self):
        self.fail = '/device/unified_service.py'
        with self.assertRaises(OSError):
            i.prepare(self.stage)
        self.assertNotIn(i.BASE, self.dirs)
        self.originals = {name: b'changed independently' for name in self.originals}
        self.fail = None
        result = i.prepare(self.stage)
        self.assertTrue(result['prepared'])
        self.assertEqual(self.fs[i.BASE + '/backup/ims.original'], b'original')
        self.assertEqual(json.loads(self.fs[i.BASE + '/install-pending.json'])['phase'], 'awaiting_backup')
        self.assertEqual(i.prepare(self.stage)['installation_id'], result['installation_id'])
        self.assertEqual(self.directory_modes[i.BASE + '/runtime/carrier'], 0o755)

    def test_unknown_base_is_not_adopted_or_modified(self):
        self.dirs.add(i.BASE)
        self.fs[i.BASE + '/other-owner'] = b'keep'
        with self.assertRaises(KeyError):
            i.prepare(self.stage)
        self.assertEqual(self.writes, [])
        self.assertEqual(self.fs[i.BASE + '/other-owner'], b'keep')

    def test_mobile_umask_keeps_backup_private_and_native_runtime_readable(self):
        i.prepare(self.stage)
        for suffix in ('', '/runtime', '/runtime/carrier'):
            self.assertEqual(self.directory_modes[i.BASE + suffix], 0o755)
        for suffix in ('/device', '/driver', '/state', '/backup', '/archive'):
            self.assertEqual(self.directory_modes[i.BASE + suffix], 0o700)
        self.assertEqual(self.directory_modes[i.MANAGEMENT], 0o700)

    def test_published_pending_prepare_repairs_previously_masked_runtime(self):
        first = i.prepare(self.stage)
        originals = dict(self.fs)
        self.directory_modes[i.BASE + '/runtime'] = 0o700
        self.directory_modes[i.BASE + '/runtime/carrier'] = 0o700
        self.mode_changes.clear()
        second = i.prepare(self.stage)
        self.assertEqual(first['installation_id'], second['installation_id'])
        self.assertEqual(self.fs, originals)
        self.assertEqual(self.mode_changes, [(i.BASE + '/runtime', 0o755), (i.BASE + '/runtime/carrier', 0o755)])

    def test_publish_interruption_keeps_work_private_and_resumes_correct_modes(self):
        self.fail_publish = True
        with self.assertRaisesRegex(OSError, 'before publish'):
            i.prepare(self.stage)
        intent = json.loads(self.fs[i.MANAGEMENT + '/install-intent.json'])
        work = i.MANAGEMENT + '/prepare-' + intent['operation_id']
        self.assertNotIn(i.BASE, self.dirs)
        self.assertEqual(self.directory_modes[work], 0o700)
        self.assertEqual(self.directory_modes[work + '/runtime/carrier'], 0o755)
        self.fail_publish = False
        self.assertTrue(i.prepare(self.stage)['prepared'])
        self.assertEqual(self.directory_modes[i.BASE + '/runtime/carrier'], 0o755)
        self.assertEqual(self.directory_modes[i.BASE + '/backup'], 0o700)


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self.token = ['first']
        from test_auto_carrier_update import InactiveUpdateTests
        self.fixture = InactiveUpdateTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        name, content = 'device/unified_service.py', b'from unified_install import verify_backup_receipt'
        f.names += (name,)
        f.fs[f.base + '/' + name] = f.fs[f.stage + '/' + name] = content
        f.before['files'][name] = f.after['files'][name] = i.n.digest(content)
        f.fs[f.base + '/payload.json'], f.fs[f.stage + '/payload.json'] = profiles.canonical(f.before), profiles.canonical(f.after)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for item in (patch.object(i.u, 'PAYLOAD_FILES', f.names),
                     patch.object(i.u, 'boot_token', side_effect=lambda: self.token),
                     patch.object(i, 'PREVIOUS_PAYLOADS', (i.n.digest(profiles.canonical(f.before['files'])),)),
                     patch.object(i, 'device_binding', return_value='d' * 32),
                     patch.object(i, 'management_identity', return_value={'schema': 2, 'owner': i.policy.OWNER}),
                     patch.object(i.os.path, 'lexists', side_effect=lambda p: p in f.fs)):
            stack.enter_context(item)

    def test_partial_update_can_rollback_exact_archived_bytes(self):
        f = self.fixture
        f.fail_write = True
        with self.assertRaises(OSError):
            i.update(f.stage)
        archive = json.loads(f.fs[i.UPDATE_PENDING])['backup']
        f.fail_write = False
        self.assertTrue(i.rollback(archive)['rolled_back'])
        self.assertEqual(json.loads(f.fs[f.base + '/payload.json']), f.before)
        self.assertNotIn(i.UPDATE_PENDING, f.fs)
        for name, expected in f.before['files'].items():
            self.assertEqual(i.n.digest(f.fs[f.base + '/' + name]), expected)

    def test_independent_edit_blocks_rollback_before_any_write(self):
        f = self.fixture
        result = i.update(f.stage)
        f.fs[f.base + '/device/unified_dca.py'] = b'other owner'
        f.writes.clear()
        with self.assertRaisesRegex(AssertionError, 'installed_payload_changed'):
            i.rollback(result['phone_backup'])
        self.assertEqual(f.writes, [])

    def test_committed_rollback_finishes_after_actual_reboot_without_more_writes(self):
        f = self.fixture
        archive = i.update(f.stage)['phone_backup']
        self.assertTrue(i.rollback(archive)['reboot_required'])
        f.writes.clear()
        self.assertTrue(i.rollback(archive)['reboot_required'])
        self.token = ['second']
        f.manager = True
        f.crypto = {'swcr_id': 0, 'crypto_support': 0}
        result = i.rollback(archive)
        self.assertTrue(result['already_committed'])
        self.assertFalse(result['reboot_required'])
        self.assertNotIn('committed_boot', result)
        self.assertEqual(f.writes, [])


class UninstallInventoryTests(unittest.TestCase):
    def test_unknown_empty_directory_is_not_silently_archived(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(i, 'BASE', folder.replace('\\', '/')):
            Path(folder, 'other-owner').mkdir()
            with self.assertRaisesRegex(AssertionError, 'uninstall_unknown_directory'):
                i.inventory()

    def test_unrelated_paths_are_never_classified_as_owned(self):
        manifest = {'files': {'device/unified_service.py': 'a' * 64}}
        self.assertTrue(i.known_uninstall_member('device/unified_service.py', manifest))
        for name in ('another-addon/init/start.sh', 'backup/private-photo.jpg', 'state/user-notes.txt',
                     'archive/update-123456789abc/unknown.py', 'archive/update-123456789abc/../../other'):
            self.assertFalse(i.known_uninstall_member(name, manifest))


class LockTests(unittest.TestCase):
    def setUp(self):
        self.fcntl = types.SimpleNamespace(LOCK_EX=1, LOCK_NB=2, LOCK_UN=4, lockf=Mock())
        info = types.SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=1, st_dev=2, st_ino=3)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for item in (patch.dict(sys.modules, {'fcntl': self.fcntl}), patch.object(i, 'private_directory'),
                     patch.object(i.os, 'geteuid', return_value=0, create=True),
                     patch.object(i.os.path, 'islink', return_value=False), patch.object(i.os, 'open', return_value=44),
                     patch.object(i.os, 'fstat', return_value=info), patch.object(i.os, 'lstat', return_value=info),
                     patch.object(i.os, 'close'), patch.object(i.os, 'unlink'),
                     patch.object(i, '_lock_depth', 0), patch.object(i, '_lock_pid', None)):
            stack.enter_context(item)

    def test_nested_actions_use_one_permanent_lock_inode(self):
        with i.management_lock():
            with i.management_lock():
                self.assertEqual(self.fcntl.lockf.call_count, 1)
        self.assertEqual(self.fcntl.lockf.call_count, 2)
        i.os.open.assert_called_once()
        self.assertEqual(i.os.open.call_args[0][0], i.MANAGEMENT + '/lock')
        self.assertFalse(i.MANAGEMENT.startswith(i.BASE + '/'))
        i.os.unlink.assert_not_called()
        i.os.close.assert_called_once_with(44)

    def test_busy_lock_does_not_run_action_or_remove_other_ownership(self):
        self.fcntl.lockf.side_effect = IOError(errno.EAGAIN, 'busy')
        action = Mock()
        with self.assertRaisesRegex(RuntimeError, 'management_busy'):
            with i.management_lock():
                action()
        action.assert_not_called()
        i.os.unlink.assert_not_called()
        i.os.close.assert_called_once_with(44)


class RetirementTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.base, self.control = self.root / 'payload', self.root / 'management'
        (self.base / 'backup').mkdir(parents=True)
        self.control.mkdir()
        (self.base / 'backup/ims.original').write_bytes(b'original')
        (self.control / 'install-intent.json').write_text(json.dumps({'owner': i.policy.OWNER, 'phase': 'published'}))
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(i, 'BASE', str(self.base)))
        stack.enter_context(patch.object(i, 'MANAGEMENT', str(self.control)))
        stack.enter_context(patch.object(i.n, 'read', side_effect=lambda path: Path(path).read_bytes()))
        self.record = {'owner': i.policy.OWNER, 'uninstalled': True, 'installation_id': '1' * 32, 'retained_files': i.inventory()}
        (self.base / 'uninstalled.json').write_text(json.dumps(self.record))

    def test_interrupted_archive_move_is_reconciled_from_external_intent(self):
        recover = i.recover_retirement
        with patch.object(i, 'recover_retirement', side_effect=OSError('power loss')), self.assertRaises(OSError):
            i.retire_uninstalled()
        self.assertFalse(self.base.exists())
        recover()
        self.assertEqual(json.loads((self.control / 'install-intent.json').read_text())['phase'], 'retired')
        self.assertEqual((self.control / ('retained-' + '1' * 32) / 'backup/ims.original').read_bytes(), b'original')

    def test_changed_retained_data_is_never_moved(self):
        (self.base / 'backup/ims.original').write_bytes(b'independent edit')
        with self.assertRaisesRegex(AssertionError, 'retained_data_changed'):
            i.retire_uninstalled()
        self.assertTrue(self.base.exists())

class UninstallTransactionTests(unittest.TestCase):
    def setUp(self):
        self.token = ['first']
        self.fs = {}
        self.writes = []
        self.fail_delete = None
        self.payload = {'owner': i.policy.OWNER, 'schema': 1, 'files': {
            'device/unified_service.py': i.n.digest(b'service'), 'driver/helper.so': i.n.digest(b'helper')}}
        self.fs.update({i.BASE + '/device/unified_service.py': b'service', i.BASE + '/driver/helper.so': b'helper',
            i.BASE + '/payload.json': profiles.canonical(self.payload), i.BASE + '/enabled': b'enabled',
            i.BASE + '/installation.json': profiles.canonical({'owner': i.policy.OWNER, 'root_kind': 'autoroot-v4'})})
        for name in i.dca.SOURCES:
            self.fs[i.BASE + '/backup/' + name + '.original'] = b'original'
            self.fs[i.dca.source_path(name)] = b'original'
        def atomic(path, raw, mode=0o600):
            self.writes.append(path)
            self.fs[path] = raw
        def unlink(path):
            if path == self.fail_delete:
                raise OSError('power loss')
            del self.fs[path]
        def inventory():
            return {name[len(i.BASE) + 1:]: i.n.digest(raw) for name, raw in self.fs.items() if name.startswith(i.BASE + '/')}
        def disable(action):
            self.assertEqual(action, 'disable')
            self.fs.pop(i.BASE + '/enabled', None)
            return {'disabled': True}
        stack = ExitStack()
        self.addCleanup(stack.close)
        import unified_dca
        import unified_operator_name
        for item in (patch.object(i, 'identity', return_value=({'variant': 'SQW100-4'}, 'passport')),
                     patch.object(i.u, 'setup'), patch.object(i.u, 'verify'), patch.object(i.u, 'handoff'),
                     patch.object(i.u, 'reconcile'), patch.object(i.migration, 'finish_previous_boot'),
                     patch.object(unified_dca, 'restore_original'), patch.object(unified_operator_name, 'target', return_value=None),
                     patch.object(i.u, 'boot_token', side_effect=lambda: self.token),
                     patch.object(i.u, 'service_action', side_effect=disable),
                     patch.object(i, 'management_identity', return_value={'installation_id': '1' * 32}),
                     patch.object(i, 'device_binding', return_value='d' * 32), patch.object(i, 'verify_backup_receipt'),
                     patch.object(i.s, 'phone_idle', return_value=True), patch.object(i.s, 'read_status', return_value={'manager_alive': False}),
                     patch.object(i.n, 'crypto_policy', return_value={'swcr_id': -1, 'crypto_support': 0}),
                     patch.object(i.n, 'voice_policy', return_value=0), patch.object(i.radio, 'ue_usage_policy', return_value=0),
                     patch.object(i.n, 'ims_pids', return_value=[]), patch.object(i.n, 'active_vpn_sessions', return_value=[]),
                     patch.object(i.n, 'read', side_effect=lambda p: self.fs[p]), patch.object(i.n, 'atomic', side_effect=atomic),
                     patch.object(i.s, 'load', side_effect=lambda p: json.loads(self.fs[p])),
                     patch.object(i.os.path, 'isfile', side_effect=lambda p: p in self.fs),
                     patch.object(i.os.path, 'lexists', side_effect=lambda p: p in self.fs),
                     patch.object(i.os.path, 'islink', return_value=False), patch.object(i.os, 'unlink', side_effect=unlink),
                     patch.object(i, 'inventory', side_effect=inventory)):
            stack.enter_context(item)
        self.fs[i.BASE + '/backup/manifest.json'] = profiles.canonical({'owner': i.policy.OWNER})

    def test_uninstall_waits_for_both_real_boot_boundaries_and_retains_backup(self):
        first = i.uninstall()
        self.assertEqual(first['phase'], 'awaiting_reboot')
        self.assertEqual(i.uninstall()['phase'], 'awaiting_reboot')
        self.assertIn(i.BASE + '/device/unified_service.py', self.fs)
        self.token = ['second']
        self.assertEqual(i.uninstall()['phase'], 'awaiting_final_reboot')
        self.assertNotIn(i.BASE + '/device/unified_service.py', self.fs)
        self.assertFalse(i.uninstall()['uninstalled'])
        self.token = ['third']
        self.assertTrue(i.uninstall()['uninstalled'])
        self.assertEqual(self.fs[i.BASE + '/backup/ims.original'], b'original')
        self.assertEqual(i.u.service_action.call_count, 1)

    def test_payload_deletion_interruption_resumes_only_known_members(self):
        i.uninstall()
        self.token = ['second']
        self.fail_delete = i.BASE + '/driver/helper.so'
        with self.assertRaises(OSError):
            i.uninstall()
        self.assertNotIn(i.BASE + '/device/unified_service.py', self.fs)
        self.fail_delete = None
        self.assertEqual(i.uninstall()['phase'], 'awaiting_final_reboot')
        self.assertEqual(self.fs[i.BASE + '/backup/ims.original'], b'original')

    def test_unknown_member_blocks_before_service_or_files_change(self):
        self.fs[i.BASE + '/unrelated.txt'] = b'keep'
        with self.assertRaisesRegex(AssertionError, 'uninstall_unknown_member'):
            i.uninstall()
        self.assertEqual(self.writes, [])
        i.u.service_action.assert_not_called()

    def test_real_running_layout_is_claimed_only_by_its_journal(self):
        names = ('runtime/ims_rrm', 'runtime/carrier/36-ims.xml', 'runtime/carrier/emergency.xml')
        managed = {}
        for name in names:
            path = i.BASE + '/' + name
            self.fs[path] = ('owned ' + name).encode()
            managed[path] = i.n.digest(self.fs[path])
        self.fs[i.BASE + '/state/journal.json'] = profiles.canonical(
            {'owner': 'q10-unicom-volte-v1', 'managed_files': managed})
        for label in ('usage', 'explicit-original', 'original-files', 'republish-original', 'republish-data'):
            self.fs[i.BASE + '/backup/dca-auto-' + label + '.log'] = b'diagnostic'
        self.assertEqual(i.uninstall()['phase'], 'awaiting_reboot')
        i.u.service_action.assert_called_once_with('disable')

    def test_changed_owned_runtime_blocks_before_disabling(self):
        path = i.BASE + '/runtime/ims_rrm'
        self.fs[path] = b'foreign bytes'
        self.fs[i.BASE + '/state/journal.json'] = profiles.canonical(
            {'owner': 'q10-unicom-volte-v1', 'managed_files': {path: i.n.digest(b'expected')}})
        with self.assertRaisesRegex(AssertionError, 'uninstall_unknown_member'):
            i.uninstall()
        i.u.service_action.assert_not_called()
        self.assertEqual(self.fs[path], b'foreign bytes')

    def test_completion_marker_survives_failure_removing_pending_record(self):
        i.uninstall()
        self.token = ['second']
        self.fail_delete = i.BASE + '/uninstall-pending.json'
        with self.assertRaises(OSError):
            i.uninstall()
        self.assertIn(i.BASE + '/uninstalled.json', self.fs)
        self.fail_delete = None
        self.assertEqual(i.uninstall()['phase'], 'awaiting_final_reboot')
        self.assertNotIn(i.BASE + '/uninstall-pending.json', self.fs)


if __name__ == '__main__':
    unittest.main()
