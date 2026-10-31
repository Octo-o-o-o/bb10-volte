"""Known-payload upgrades preserve a recoverable, disabled partial state."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'device'))
import unified_install as installer
import profiles


class InactiveUpdateTests(unittest.TestCase):
    def setUp(self):
        self.base = installer.BASE
        self.stage = '/var/bb10_auto_stage_123456789abc'
        self.names = ('device/unified_dca.py', 'device/unified_install.py', 'driver/fixed.so')
        old = {name: ('old:' + name).encode() for name in self.names}
        new = dict(old, **{name: ('new:' + name).encode() for name in self.names[:2]})
        manifest = lambda values: {'owner': installer.policy.OWNER, 'schema': 1,
            'files': {name: hashlib.sha256(blob).hexdigest() for name, blob in values.items()}}
        self.before, self.after = manifest(old), manifest(new)
        self.fs = {self.base + '/' + name: blob for name, blob in old.items()}
        self.fs.update({self.stage + '/' + name: blob for name, blob in new.items()})
        self.fs[self.base + '/payload.json'] = profiles.canonical(self.before)
        self.fs[self.stage + '/payload.json'] = profiles.canonical(self.after)
        self.fs[self.base + '/enabled'] = b'owner enabled'
        self.writes, self.directories = [], []
        self.fail_write, self.fail_finish = False, False
        self.manager = False
        self.crypto = {'swcr_id': -1, 'crypto_support': 0}
        def atomic(path, blob, mode=0o600):
            if self.fail_write and path == self.base + '/device/unified_install.py':
                raise OSError('simulated write interruption')
            self.writes.append(path)
            self.fs[path] = blob
        def unlink(path):
            if self.fail_finish and path == installer.UPDATE_PENDING:
                raise OSError('simulated completion interruption')
            del self.fs[path]
        def verify():
            value = json.loads(self.fs[self.base + '/payload.json'])
            for name, expected in value['files'].items():
                self.assertEqual(hashlib.sha256(self.fs[self.base + '/' + name]).hexdigest(), expected)
        stack = ExitStack()
        self.addCleanup(stack.close)
        patches = [patch.object(installer, 'identity', return_value=({'variant': 'SQW100-4'}, 'passport')),
            patch.object(installer, 'PREVIOUS_PAYLOADS', (hashlib.sha256(profiles.canonical(self.before['files'])).hexdigest(),)),
            patch.object(installer.u, 'PAYLOAD_FILES', self.names), patch.object(installer.u, 'setup'),
            patch.object(installer.u, 'verify', side_effect=verify), patch.object(installer.u, 'handoff'),
            patch.object(installer.s, 'phone_idle', return_value=True),
            patch.object(installer.s, 'read_status', side_effect=lambda: {'manager_alive': self.manager}),
            patch.object(installer.s, 'load', side_effect=lambda path: json.loads(self.fs[path])),
            patch.object(installer.n, 'read', side_effect=lambda path: self.fs[path]),
            patch.object(installer.n, 'atomic', side_effect=atomic),
            patch.object(installer.n, 'crypto_policy', side_effect=lambda: self.crypto),
            patch.object(installer.n, 'ims_pids', return_value=[]),
            patch.object(installer.n, 'active_vpn_sessions', return_value=[]),
            patch.object(installer.os.path, 'isfile', side_effect=lambda path: path in self.fs),
            patch.object(installer.os.path, 'islink', return_value=False),
            patch.object(installer.os.path, 'realpath', side_effect=lambda path: path),
            patch.object(installer.os, 'mkdir', side_effect=lambda path, mode: self.directories.append(path)),
            patch.object(installer.os, 'unlink', side_effect=unlink)]
        for item in patches:
            stack.enter_context(item)

    def test_active_manager_or_retained_provider_prevents_any_update_write(self):
        self.manager = True
        with self.assertRaisesRegex(AssertionError, 'update_service_active'):
            installer.update(self.stage)
        self.manager = False
        self.crypto = {'swcr_id': 0, 'crypto_support': 0}
        with self.assertRaisesRegex(AssertionError, 'update_reboot_required'):
            installer.update(self.stage)
        self.assertFalse(self.writes)
        self.assertFalse(self.directories)
        self.assertIn(self.base + '/enabled', self.fs)

    def test_interrupted_python_replacement_keeps_boot_disabled_and_resumes(self):
        self.fail_write = True
        with self.assertRaises(OSError):
            installer.update(self.stage)
        self.assertNotIn(self.base + '/enabled', self.fs)
        self.assertEqual(json.loads(self.fs[self.base + '/payload.json']), self.before)
        pending = json.loads(self.fs[installer.UPDATE_PENDING])
        for name in self.names[:2]:
            self.assertEqual(hashlib.sha256(self.fs[pending['backup'] + '/' + name]).hexdigest(), self.before['files'][name])
        self.fail_write = False
        result = installer.update(self.stage)
        self.assertTrue(result['updated'])
        self.assertIn(self.base + '/enabled', self.fs)
        self.assertNotIn(installer.UPDATE_PENDING, self.fs)
        self.assertEqual(json.loads(self.fs[self.base + '/payload.json']), self.after)
        self.assertNotIn(self.base + '/driver/fixed.so', self.writes)

    def test_unknown_payload_edit_is_not_adopted_or_overwritten(self):
        self.fs[self.base + '/device/unified_dca.py'] = b'independent change'
        with self.assertRaisesRegex(AssertionError, 'installed_payload_changed'):
            installer.update(self.stage)
        self.assertFalse(self.writes)

    def test_final_record_cleanup_can_resume_after_new_service_has_started(self):
        self.fail_finish = True
        with self.assertRaises(OSError):
            installer.update(self.stage)
        self.assertEqual(json.loads(self.fs[installer.UPDATE_PENDING])['phase'], 'files_verified')
        self.fail_finish, self.manager = False, True
        self.crypto = {'swcr_id': 0, 'crypto_support': 0}
        self.writes.clear()
        installer.update(self.stage)
        self.assertNotIn(installer.UPDATE_PENDING, self.fs)
        self.assertFalse(any(path in self.writes for path in [self.base + '/' + name for name in self.names]))


if __name__ == '__main__':
    unittest.main()
