"""Manual attach gates, exact restoration and the accepted Q20 management route."""
import copy
import hashlib
import io
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'device'))
sys.path.insert(0, str(ROOT / 'tools'))
import compatibility as c
import native as n
import profiles
import service as s
import telecom_attach as t
import telecom_dca as dca
import workflow as w
import q20_managed
import q20_manage_probe
from test_preflight import baseline


def telecom_profile():
    return profiles.validate(profiles.read_json(str(ROOT / 'profiles/china-telecom-46011.json')))


def attach_facts():
    value = baseline()
    value.update(mnc='11', sim_type=6, network_service=1, apn_matches=None, data_connected=None,
                 data_services_status='ON', data_service_mode='ON',
                 telecom_attach={'native_supported': True, 'source_baseline': True,
                                 'original_usage': True, 'backup_verified': False})
    return value


class AttachGateTests(unittest.TestCase):
    def test_legacy_profile_bytes_remain_canonical_without_new_option(self):
        value = profiles.default()
        self.assertNotIn('lte_attach', profiles.validate(value))
        self.assertEqual(profiles.canonical(value), profiles.canonical(profiles.validate(value)))

    def test_wrong_operator_or_autostart_cannot_select_native_bootstrap(self):
        for change in ('mnc', 'mcc', 'autostart', 'apn'):
            value = telecom_profile()
            if change == 'mnc': value['carrier']['mncs'] = ['03', '11']
            if change == 'mcc': value['carrier']['mcc'] = '999'
            if change == 'autostart': value['runtime']['autostart'] = True
            if change == 'apn': value['carrier']['data_apns'] = ['cmnet']
            with self.subTest(change=change), self.assertRaises(ValueError):
                profiles.validate(value)

    def test_emergency_state_can_only_prepare_manual_port_with_explicit_consent(self):
        value, profile = attach_facts(), telecom_profile()
        denied = c.evaluate(value, profile, False)
        self.assertFalse(denied['can_install'])
        report = c.evaluate(value, profile, True)
        self.assertTrue(report['can_install'])
        self.assertTrue(report['lte_bootstrap_pending'])
        self.assertTrue(report['network_diagnostics']['emergency_service'])
        self.assertEqual(next(row for row in report['checks'] if row['id'] == 'lte')['status'], 'wait')
        self.assertFalse(report['can_enable'])

    def test_sources_native_reads_sim_and_data_switch_still_gate_manual_port(self):
        changes = ({'telecom_attach': {}}, {'root_ready': False}, {'mnc': '03'},
                   {'sim_type': 18}, {'identity_matches': False}, {'radio_on': False},
                   {'network_read_error': True}, {'data_settings_read_error': True},
                   {'data_service_mode': 'OFF'}, {'data_service_mode': None}, {'native_read_error': True},
                   {'carrier_template_ready': False}, {'clean_configuration': False},
                   {'voice_policy': 3}, {'vpn_count': 1})
        for change in changes:
            value = attach_facts(); value.update(change)
            with self.subTest(change=change):
                self.assertFalse(c.evaluate(value, telecom_profile(), True)['can_install'])

    def test_actual_data_off_with_user_mode_on_can_prepare_attach_not_ims(self):
        value = attach_facts()
        value.update(data_services_status='OFF', data_service_mode='ON', internet_enabled=True,
                     internet_active=False, internet_connectable=False, lte=False,
                     installation={'state': 'stopped', 'current_profile': False})
        report = c.evaluate(value, telecom_profile(), True)
        self.assertTrue(report['can_update'])
        self.assertFalse(report['can_start'])
        self.assertFalse(report['can_enable'])
        self.assertEqual(report['network_diagnostics']['data_services_status'], 'OFF')
        self.assertEqual(next(row for row in report['checks'] if row['id'] == 'apn')['status'], 'wait')
        self.assertEqual(c.network_state(value, telecom_profile()), 'not_ready')

    def test_only_q10_variant3_can_use_new_port_and_passport_gate_remains(self):
        for model, variant in (('Passport', 'SQW100-4'), ('Classic', 'SQC100-2'), ('Q10', 'SQN100-1')):
            value = attach_facts(); value.update(model=model, variant=variant)
            with self.subTest(variant=variant):
                report = c.evaluate(value, telecom_profile(), True)
                self.assertFalse(report['can_install'])
                self.assertFalse(report['can_enable'])
                if model == 'Passport': self.assertFalse(report['can_restore'])

    def test_start_requires_verified_desktop_backup(self):
        profile = telecom_profile(); value = attach_facts()
        value['installation'] = {'state': 'stopped', 'current_profile': True,
            'carrier_profile_sha256': profiles.fingerprint(profiles.request(profile, True))}
        self.assertFalse(c.evaluate(value, profile, True)['can_start'])
        value['telecom_attach']['backup_verified'] = True
        self.assertTrue(c.evaluate(value, profile, True)['can_start'])

    def test_failed_attach_never_reaches_ims_configuration(self):
        with patch.object(s, 'ACTIVE_PROFILE', telecom_profile()), patch.object(n, 'verify_stock'), \
                patch.object(t, 'ensure_lte', side_effect=RuntimeError('no data')), \
                patch.object(s, 'configure') as configure:
            with self.assertRaisesRegex(RuntimeError, 'no data'): s.prepare_connection()
            configure.assert_not_called()
        with patch.object(s, 'ready', return_value=False):
            with self.assertRaisesRegex(AssertionError, 'SIM/network changed'): s.configure()


class BackupAndRestoreTests(unittest.TestCase):
    def test_installer_imports_service_from_verified_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            stage = root / 'stage'; stage.mkdir()
            target = root / 'installed/device'; target.mkdir(parents=True)
            (stage / 'service.py').write_text("raise RuntimeError('untrusted stage was imported')\n")
            (target / 'service.py').write_text("marker = 'verified_destination'\n")
            (target / 'telecom_attach.py').write_text(
                "def prepare(service):\n    assert service.marker == 'verified_destination'\n"
                "    assert service.ACTIVE_PROFILE == {'id': 'test'}\n    return {'prepared': True}\n")
            code = (
                "import sys;sys.path.insert(0,sys.argv[1]);import install;"
                "sys.path.insert(0,sys.argv[2]);install.BASE=sys.argv[3];"
                "assert install.prepare_telecom_plan({'profile': {'id': 'test'}}) == {'prepared': True}"
            )
            subprocess.run([sys.executable, '-c', code, str(ROOT / 'device'), str(stage),
                            (root / 'installed').as_posix()], check=True, capture_output=True)

    def test_existing_source_write_preserves_inode_mode_and_owner(self):
        previous = dca.q
        dca.q = SimpleNamespace(n=SimpleNamespace(read=lambda p: Path(p).read_bytes()))
        try:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'source'; path.write_bytes(dca.HEADER)
                info = path.stat()
                item = {'identity': [info.st_ino, info.st_mode & 0o7777, info.st_uid, info.st_gid]}
                applied = dca.payload(dca.HEADER, 'data_centric')
                dca.write_existing(str(path), dca.HEADER, applied, item)
                after = path.stat()
                self.assertEqual([after.st_ino, after.st_mode & 0o7777, after.st_uid, after.st_gid], item['identity'])
                self.assertEqual(path.read_bytes(), applied)
                with self.assertRaises(AssertionError):
                    dca.write_existing(str(path), b'concurrent edit', dca.HEADER, item)
        finally:
            dca.q = previous

    def test_unknown_nonempty_sources_are_preserved(self):
        for original in (b'ue_usage_setting::voice_centric\n', dca.HEADER + b'other:n:1\n'):
            with self.assertRaises(AssertionError): dca.payload(original, 'data_centric')

    def test_publish_failure_still_restores_original_source_bytes(self):
        previous = dca.q
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder); value = {'files': {}}
                for name in dca.SOURCES:
                    original = b'' if name == 'omadm' else dca.HEADER
                    (root / (name + '.original')).write_bytes(original)
                    target = root / (name + '.source'); target.write_bytes(dca.payload(original, 'data_centric'))
                    info = target.stat()
                    value['files'][name] = {'original_sha256': n.digest(original),
                        'identity': [info.st_ino, info.st_mode & 0o7777, info.st_uid, info.st_gid]}
                (root / 'report.json').write_text('{"voice_preference_change_attempted":true}')
                native = SimpleNamespace(read=lambda p: Path(p).read_bytes(), digest=n.digest, atomic=lambda p,b: Path(p).write_bytes(b),
                                         ims_pids=lambda: [], active_vpn_sessions=lambda: [], voice_policy=lambda: 0)
                phone = SimpleNamespace(phone_idle=lambda: True, load=lambda p: json.loads(Path(p).read_text()))
                dca.q = SimpleNamespace(n=native, s=phone)
                with patch.object(dca, 'source_path', side_effect=lambda name: str(root / (name + '.source'))), \
                        patch.object(dca, 'publish', return_value={'error_type': 'publisher_failed'}), \
                        patch.object(dca, 'ue_usage_policy', return_value=0):
                    result = dca.restore(str(root), value)
                self.assertTrue(result['sources_restored'])
                self.assertTrue(result['restored'])
                for name in dca.SOURCES:
                    self.assertEqual((root / (name + '.source')).read_bytes(), (root / (name + '.original')).read_bytes())
        finally:
            dca.q = previous

    def test_changed_sim_is_rejected_before_any_policy_write(self):
        service = SimpleNamespace(ACTIVE_PROFILE=telecom_profile(), phone_idle=lambda: True,
                                  current_usim=lambda: '46011' + '0' * 10)
        with patch.object(t, 'checked_plan', return_value=('/unused', {'sim_fingerprint': 'different'})), \
                patch.object(n, 'active_vpn_sessions', return_value=[]), \
                patch.object(n, 'crypto_policy', return_value={'swcr_id': -1, 'crypto_support': 0}), \
                patch.object(dca, 'write_existing') as write:
            with self.assertRaisesRegex(AssertionError, 'changing SIM'): t.ensure_lte(service)
            write.assert_not_called()

    def test_desktop_rejects_backup_path_escape_without_transfer(self):
        client = object.__new__(w.Client); client.process = Mock()
        with self.assertRaisesRegex(w.WorkflowError, 'telecom_backup_not_verified'):
            client.backup_telecom_plan({'folder': w.BASE + '/state/../wrong'})
        client.process.assert_not_called()


class ManagedQ20Tests(unittest.TestCase):
    def test_low_level_client_detection_is_explicit_and_does_no_implicit_io(self):
        client = object.__new__(w.Client); client.remote = Mock()
        self.assertIsNone(client.managed_adapter())
        client.remote.assert_not_called()

    def test_existing_q20_dispatches_without_using_the_generic_installer(self):
        client = object.__new__(w.Client); client.detect_managed = True
        client.remote = Mock(return_value='Q20_ACCEPTED_ADAPTER\n')
        client.stage = Mock(side_effect=AssertionError('generic stage used'))
        with patch.object(w, 'verify_package'), patch.object(q20_managed, 'Adapter') as adapter:
            adapter.return_value.inspect.return_value = {'managed_adapter': 'q20_root_v2'}
            self.assertEqual(client.preflight()['managed_adapter'], 'q20_root_v2')
            with self.assertRaisesRegex(w.WorkflowError, 'q20_managed_existing_only'): client.install()
            self.assertEqual(client.remote.call_count, 1)

    def test_q20_bundle_hash_is_pinned_and_contains_no_private_connection(self):
        spec, source = q20_managed.bundle()
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), spec['probe_sha256'])
        self.assertNotIn('ssh_config', spec)
        self.assertNotIn('known_hosts', spec)

    def test_bad_phone_manifest_is_rejected_before_pathtrust_or_import(self):
        def opening(path, mode):
            return io.BytesIO(b'modelnumber::SQC100-2\n' if 'deviceproperties' in path else b'changed')
        with patch('builtins.open', side_effect=opening), patch.object(os, 'geteuid', return_value=0, create=True), \
                patch.object(os, 'uname', return_value=('QNX',), create=True), \
                patch.object(q20_manage_probe.subprocess, 'check_call') as trust:
            with self.assertRaisesRegex(AssertionError, 'revision'): q20_manage_probe.checked_manifest('0' * 64)
            trust.assert_not_called()


if __name__ == '__main__':
    unittest.main()
