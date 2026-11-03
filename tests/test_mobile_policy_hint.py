"""Real private files and failure windows for the bounded mobile restart hint."""
import contextlib
import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock
from test_mobile_runtime import ENTRY, WORKER, ready


def load_module():
    spec = importlib.util.spec_from_file_location('policy_hint',
        Path(__file__).resolve().parents[1] / 'mobile/runtime/policy_hint.py')
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {'entry': ENTRY}):
        spec.loader.exec_module(module)
    return module


HINT = load_module()


@unittest.skipUnless(os.name == 'posix', 'Root-private POSIX file semantics')
class PolicyHintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # macOS exposes the temporary root through /var -> /private/var.
        # Use its canonical spelling just as the device's private paths do;
        # keep the production symlink guard and its negative test intact.
        self.top = Path(self.temp.name).resolve()
        self.base, self.root, self.management = [self.top / x for x in ('device', 'mobile', 'management')]
        for path in (self.base, self.root, self.management, self.base / 'state', self.base / 'backup'):
            path.mkdir(mode=0o700)
        self.base.chmod(0o755)
        self.owner = 'bb10-unified-carriers-v1'
        self.boot = [self.owner, 'a' * 48]
        self.sim = 'b' * 64
        self.identity = {'schema': 2, 'owner': self.owner, 'device': 'c' * 32,
                         'installation_id': 'd' * 32, 'variant': 'SQW100-4'}
        self.write(self.management / 'device.json', {'owner': self.owner, 'id': 'c' * 32})
        self.write(self.management / 'lock', b'')
        self.write(self.base / 'management.json', self.identity)
        self.write(self.base / 'enabled', b'')
        self.boot_path = self.top / 'boot.json'
        self.write(self.boot_path, {'owner': self.owner, 'nonce': self.boot[1]})
        self.source_dir = self.top / 'sources'
        self.source_dir.mkdir(mode=0o700)
        self.originals, self.files = {}, {}
        for name in ('ims', 'ims_defaults', 'omadm', 'test'):
            self.originals[name] = b'@cellular_protocol_configuration\n'
            source = self.source_dir / name
            self.write(source, self.payload(self.originals[name], 'voice_centric'))
            info = source.stat()
            self.files[name] = {'path': str(source), 'original_sha256': ENTRY.digest(self.originals[name]),
                'identity': [info.st_ino, stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid]}
            self.write(self.base / 'backup' / (name + '.original'), self.originals[name])
        self.write(self.base / 'backup/manifest.json', {'owner': self.owner, 'variant': 'SQW100-4',
            'files': {name + '.original': ENTRY.digest(data) for name, data in self.originals.items()},
            'dca': self.files})
        self.write(self.base / 'backup-receipt.json', {'schema': 2, 'all_original_hashes_verified': True})
        self.result = {'installed': True, 'installed_stage': 'managed', 'installed_management_schema': 2,
            'variant': 'SQW100-4', 'family': 'passport', 'operator': 'unicom', 'sim_supported': True,
            'call_idle': True, 'status': dict(ready(), phase='error_restored', manager_alive=False, native_alive=False)}
        self.reset_records()
        self.manager = types.SimpleNamespace(BASE=str(self.base), MANAGEMENT=str(self.management),
            management_lock=mock.Mock(side_effect=lambda **kw: contextlib.nullcontext()),
            management_identity=mock.Mock(side_effect=lambda *a, **kw: self.read(self.base / 'management.json')))
        self.service = types.SimpleNamespace(LOCK=str(self.base / 'state/lock.json'),
            VOICE='/pps/fixed-voice', alive=mock.Mock(return_value=False), phone_idle=mock.Mock(return_value=True))
        self.native = types.SimpleNamespace(read=mock.Mock(return_value=b'voice_centric'),
            attrs=lambda raw: {'ue_usage_setting': raw.decode()}, value=lambda a,k: a.get(k),
            ims_pids=mock.Mock(return_value=[]), active_vpn_sessions=mock.Mock(return_value=[]),
            crypto_policy=mock.Mock(return_value={'swcr_id': -1, 'crypto_support': 0}),
            voice_policy=mock.Mock(return_value=0))
        self.radio = types.SimpleNamespace(ue_usage_policy=mock.Mock(return_value=1))
        self.dca = types.SimpleNamespace(SOURCES=tuple(self.originals), payload=self.payload,
            source_path=lambda name: str(self.source_dir / name))
        self.modules = {'entry': ENTRY, 'policy_hint': HINT, 'service': self.service, 'native': self.native,
            'unified_dca': types.SimpleNamespace(dca=self.dca, radio=self.radio,
                originals=mock.Mock(side_effect=lambda: (copy.deepcopy(self.files), dict(self.originals)))),
            'unified_service': types.SimpleNamespace(BOOT=str(self.boot_path), card=lambda: {},
                boot_token=lambda create: [self.owner, self.read(self.boot_path)['nonce']]),
            'device_info': types.SimpleNamespace(read_identity=lambda: {'variant': 'SQW100-4'}),
            'carrier_policy': types.SimpleNamespace(OWNER=self.owner, select=lambda *a:
                {'family': 'passport', 'operator': 'unicom', 'sim_sha256': self.sim})}
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(mock.patch.dict(sys.modules, self.modules))
        self.patches.enter_context(mock.patch.object(WORKER, 'ROOT', str(self.root)))
        self.patches.enter_context(mock.patch.object(WORKER, 'engine', return_value=self.manager))
        self.patches.enter_context(mock.patch.object(WORKER, 'job_lock', side_effect=AssertionError('must not lock jobs')))

    @staticmethod
    def payload(raw, usage):
        return raw + ('ue_usage_setting::' + usage + '\n').encode()

    @staticmethod
    def write(path, value):
        data = value if isinstance(value, bytes) else ENTRY.canonical(value)
        path.write_bytes(data)
        path.chmod(0o600)

    @staticmethod
    def read(path):
        return json.loads(path.read_bytes())

    def reset_records(self):
        self.write(self.base / 'state/status.json', {'boot': self.boot, 'phase': 'error_restored',
            'error': 'usage_restore_unconfirmed', 'native_pid': None})
        self.write(self.base / 'state/selection.json', {'boot': self.boot, 'family': 'passport',
            'operator': 'unicom', 'sim_sha256': self.sim})
        self.write(self.base / 'state/native-attempt.json', {'owner': self.owner, 'boot': self.boot})
        self.write(self.base / 'state/dca.json', {'owner': self.owner, 'boot': self.boot,
            'policy_changed_boot': self.boot, 'phase': 'applying', 'desired': 0, 'ue_usage_before': 1,
            'source_repair_only': False, 'operator': 'unicom', 'sim_sha256': self.sim, 'publish': {}})
        self.write(self.base / 'state/journal.json', {'owner': 'q10-unicom-volte-v1', 'boot': self.boot,
            'sim_sha256': self.sim, 'operator': 'unicom', 'original_voice_policy': 0, 'native_pid': None,
            'managed_files': {}, 'configuration_restored': True, 'restore_completed': True,
            'provider_retained_until_reboot': False})

    def observe(self):
        return WORKER.inspection_response({'language': 'zh'}, copy.deepcopy(self.result), {'version': '0.1.0.14'})

    def record_path(self):
        return next(self.root.glob('policy-restart-hint-*.json'))

    def reboot(self):
        self.boot = [self.owner, 'e' * 48]
        self.write(self.boot_path, {'owner': self.owner, 'nonce': self.boot[1]})
        self.reset_records()

    def test_actual_inspection_suggests_once_and_refresh_never_requeries_native_policy(self):
        before = {str(p): p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        first = self.observe()
        self.assertEqual(first['state'], 'policy_restart_once')
        self.assertEqual(first['actions'], ['status', 'export', 'compatibility'])
        self.assertEqual(first['primary_action'], 'status')
        self.assertNotIn(self.sim, json.dumps(first))
        self.assertEqual(self.observe()['state'], 'policy_restart_once')
        # A newly loaded module/process and an app version change keep the same budget.
        with mock.patch.dict(sys.modules, {'policy_hint': load_module()}):
            self.assertEqual(self.observe()['state'], 'policy_restart_once')
        self.radio.ue_usage_policy.assert_called_once_with()
        self.native.voice_policy.assert_called_once_with()
        self.native.crypto_policy.assert_called_once_with()
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.base.rglob('*') if p.is_file()})
        self.manager.management_identity.assert_called_with({'variant': 'SQW100-4'}, create=False)
        self.assertEqual(self.record_path().stat().st_mode & 0o777, 0o600)

    def test_changed_proof_withdraws_advice_without_new_native_queries(self):
        self.observe()
        path = self.base / 'state/dca.json'
        changed = self.read(path); changed['at'] = 1234; self.write(path, changed)
        self.assertEqual(self.observe()['state'], 'recovery_required')
        self.radio.ue_usage_policy.assert_called_once_with()
        self.assertEqual(self.read(self.record_path())['phase'], 'issued')

    def test_new_boot_spends_budget_despite_rewritten_dca_timestamp(self):
        self.observe(); self.reboot()
        self.assertEqual(self.observe()['state'], 'policy_restart_unconfirmed')
        self.assertEqual(self.observe()['state'], 'policy_restart_unconfirmed')
        self.radio.ue_usage_policy.assert_called_once_with()
        self.assertEqual(self.read(self.record_path())['phase'], 'exhausted')

    def test_sim_a_b_a_retains_separate_unresolved_budget(self):
        self.observe()
        a = self.sim
        self.sim = 'f' * 64; self.reset_records(); self.observe()
        self.sim = a; self.reboot()
        self.assertEqual(self.observe()['state'], 'policy_restart_unconfirmed')
        self.assertEqual(len(list(self.root.glob('policy-restart-hint-*.json'))), 2)
        self.assertEqual(self.radio.ue_usage_policy.call_count, 2)

    def test_reinstallation_separates_budget_but_app_upgrade_does_not(self):
        self.observe(); self.reboot()
        self.identity['installation_id'] = 'f' * 32
        self.write(self.base / 'management.json', self.identity)
        self.assertEqual(self.observe()['state'], 'policy_restart_once')
        self.assertEqual(len(list(self.root.glob('policy-restart-hint-*.json'))), 2)

    def test_only_current_registration_resolves_and_allows_later_incident(self):
        self.observe()
        self.result['status'] = ready()
        self.write(self.base / 'state/status.json', {'boot': self.boot, 'phase': 'running'})
        context = {'binding': {'boot': self.boot, 'sim': self.sim}, 'calls_verified': False, 'context': 'a'*32}
        with mock.patch.object(WORKER, 'call_context', return_value=context):
            self.assertEqual(self.observe()['state'], 'registered')
        self.assertEqual(self.read(self.record_path())['phase'], 'resolved')
        self.result['status'] = dict(ready(), phase='error_restored', manager_alive=False, native_alive=False)
        self.reboot()
        self.assertEqual(self.observe()['state'], 'policy_restart_once')

    def test_stale_registration_context_does_not_resolve_a_different_sim(self):
        self.observe()
        self.result['status'] = ready()
        self.write(self.base / 'state/status.json', {'boot': self.boot, 'phase': 'running'})
        context = {'binding': {'boot': self.boot, 'sim': 'f'*64}, 'calls_verified': False, 'context': 'a'*32}
        with mock.patch.object(WORKER, 'call_context', return_value=context):
            self.assertEqual(self.observe()['state'], 'registered')
        self.assertEqual(self.read(self.record_path())['phase'], 'issued')

    def test_registration_is_not_hidden_if_resolution_persistence_fails(self):
        self.observe(); self.result['status'] = ready()
        self.write(self.base / 'state/status.json', {'boot': self.boot, 'phase': 'running'})
        context = {'binding': {'boot': self.boot, 'sim': self.sim}, 'calls_verified': True, 'context': 'a'*32}
        with mock.patch.object(WORKER, 'call_context', return_value=context), \
             mock.patch.object(HINT, 'persist', side_effect=OSError('disk full')):
            self.assertEqual(self.observe()['state'], 'verified')
        self.assertEqual(self.read(self.record_path())['phase'], 'issued')

    def test_pending_disabled_update_and_stale_status_preserve_existing_paths(self):
        original = copy.deepcopy(self.result)
        for key, value, expected in [('installation_pending',True,'recovery_required'),
                ('update_pending',True,'recovery_required'), ('update_available',True,'update_requires_stop'),
                ('family','q10','recovery_required'), ('operator','mobile','recovery_required')]:
            with self.subTest(key=key):
                self.result = copy.deepcopy(original); self.result[key] = value
                self.assertEqual(self.observe()['state'], expected)
        for key in ('enabled', 'status_from_current_boot', 'selected_this_boot', 'current_sim_matches'):
            self.result = copy.deepcopy(original); self.result['status'][key] = False
            self.assertNotIn(self.observe()['state'], ('policy_restart_once','policy_restart_unconfirmed'))
        self.radio.ue_usage_policy.assert_not_called()
        self.assertFalse(list(self.root.glob('policy-restart-hint-*.json')))

    def test_each_unsafe_private_proof_rejects_before_native_policy(self):
        mutations = [('status','error','other_error'), ('status','boot',None),
            ('selection','sim_sha256','f'*64), ('native-attempt','owner','other'),
            ('dca','desired',False), ('dca','ue_usage_before',0), ('dca','source_repair_only',True),
            ('dca','publish',{'error_type':'failed'}), ('dca','policy_changed_boot',None),
            ('journal','configuration_restored',False), ('journal','managed_files',{'foreign':'hash'}),
            ('journal','restore_completed',False), ('journal','provider_retained_until_reboot',True)]
        for name, key, value in mutations:
            with self.subTest(name=name,key=key):
                self.reset_records()
                path=self.base/'state'/(name+'.json'); changed=self.read(path); changed[key]=value
                self.write(path,changed)
                self.assertEqual(self.observe()['state'],'recovery_required')
        self.radio.ue_usage_policy.assert_not_called()

    def test_markers_live_manager_and_lock_contention_block_suggestion(self):
        for marker in HINT.MARKERS:
            path=self.base/marker; self.write(path,b'')
            self.assertEqual(self.observe()['state'],'recovery_required'); path.unlink()
        self.write(self.base/'state/lock.json',{'boot':self.boot,'pid':123})
        self.service.alive.return_value=True
        self.assertEqual(self.observe()['state'],'recovery_required')
        self.service.alive.assert_called_once_with(123)
        self.service.alive.return_value=False
        self.manager.management_lock.side_effect=RuntimeError('management_busy')
        self.manager.management_lock.reset_mock()
        self.assertEqual(self.observe()['state'],'recovery_required')
        self.manager.management_lock.assert_called_once_with(blocking=False)
        self.radio.ue_usage_policy.assert_not_called()

    def test_missing_management_lock_is_not_created_by_an_observation(self):
        path = self.management / 'lock'
        path.unlink()
        self.assertEqual(self.observe()['state'], 'recovery_required')
        self.manager.management_lock.assert_not_called()
        self.assertFalse(path.exists())
        self.radio.ue_usage_policy.assert_not_called()

    def test_source_backup_receipt_and_published_policy_must_match(self):
        source=self.source_dir/'ims'; before=source.read_bytes(); self.write(source,b'foreign')
        self.assertEqual(self.observe()['state'],'recovery_required'); self.write(source,before)
        backup=self.base/'backup/ims.original'; self.write(backup,b'wrong')
        self.assertEqual(self.observe()['state'],'recovery_required'); self.write(backup,self.originals['ims'])
        self.modules['unified_dca'].originals.reset_mock()
        self.modules['unified_dca'].originals.side_effect=AssertionError('receipt changed')
        self.assertEqual(self.observe()['state'],'recovery_required')
        self.modules['unified_dca'].originals.assert_called_once_with()
        self.modules['unified_dca'].originals.side_effect=lambda:(copy.deepcopy(self.files),dict(self.originals))
        self.native.read.return_value=b'data_centric'
        self.assertEqual(self.observe()['state'],'recovery_required')
        self.radio.ue_usage_policy.assert_not_called()

    def test_symlink_hardlink_and_public_state_are_rejected(self):
        path=self.base/'state/status.json'; raw=path.read_bytes()
        path.chmod(0o644)
        self.assertEqual(self.observe()['state'],'recovery_required'); path.chmod(0o600)
        other=self.top/'other'; os.link(str(path),str(other))
        self.assertEqual(self.observe()['state'],'recovery_required'); other.unlink()
        path.unlink(); self.write(other,raw); path.symlink_to(other)
        self.assertEqual(self.observe()['state'],'recovery_required')
        self.radio.ue_usage_policy.assert_not_called()

    def test_first_live_reads_reject_busy_ims_vpn_provider_nv_and_voice(self):
        for reader,bad in [(self.service.phone_idle,False),(self.native.ims_pids,[7]),
                (self.native.active_vpn_sessions,[1]),(self.native.crypto_policy,{'swcr_id':0,'crypto_support':1}),
                (self.radio.ue_usage_policy,0),(self.native.voice_policy,3)]:
            with self.subTest(reader=reader):
                reader.reset_mock()
                old=reader.return_value; reader.return_value=bad
                self.assertEqual(self.observe()['state'],'recovery_required')
                reader.assert_called_once_with()
                reader.return_value=old
                self.assertFalse(list(self.root.glob('policy-restart-hint-*.json')))

    def test_changed_proof_during_native_read_never_commits_hint(self):
        def changed():
            self.write(self.base/'state/stop-request',b''); return 1
        self.radio.ue_usage_policy.side_effect=changed
        self.assertEqual(self.observe()['state'],'recovery_required')
        self.assertFalse(list(self.root.glob('policy-restart-hint-*.json')))

    def test_fsync_failure_after_rename_never_displays_until_barrier_succeeds(self):
        with mock.patch.object(HINT,'barrier',side_effect=OSError('final fsync failed')) as barrier:
            self.assertEqual(self.observe()['state'],'recovery_required')
            self.assertEqual(self.observe()['state'],'recovery_required')
            self.assertEqual(barrier.call_count,2)
        self.assertEqual(self.read(self.record_path())['phase'],'issued')
        self.assertEqual(self.observe()['state'],'policy_restart_once')
        self.radio.ue_usage_policy.assert_called_once_with()

    def test_temp_fsync_and_rename_failure_never_display_or_leave_hint(self):
        for target in ('write_new','rename'):
            owner=ENTRY if target=='write_new' else HINT.os
            with mock.patch.object(owner,target,side_effect=OSError('storage failed')) as failure:
                self.assertEqual(self.observe()['state'],'recovery_required')
                failure.assert_called_once()
            self.assertFalse(list(self.root.glob('policy-restart-hint-*')))

    def test_final_fsync_and_readback_use_actual_fd_and_exact_bytes(self):
        path=self.root/'durable.json'; value={'verified':True}
        fsync=HINT.os.fsync
        modes=[]
        def capture(fd):
            modes.append(os.fstat(fd).st_mode & 0o777); fsync(fd)
        with mock.patch.object(HINT.os,'fsync',side_effect=capture):
            HINT.persist(str(path),value)
        self.assertEqual(modes,[0o600,0o600])
        self.assertEqual(self.read(path),value)
        with mock.patch.object(HINT.os,'fsync',side_effect=OSError('failed')):
            with self.assertRaises(OSError): HINT.barrier(str(path),ENTRY.canonical(value))
        with self.assertRaises(ENTRY.MobileError): HINT.barrier(str(path),b'changed')

    def test_unknown_record_is_retained_and_never_renews_budget(self):
        self.observe(); path=self.record_path(); self.write(path,{'owner':'foreign'})
        old=path.read_bytes()
        self.assertEqual(self.observe()['state'],'recovery_required')
        self.assertEqual(path.read_bytes(),old)
        self.radio.ue_usage_policy.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
