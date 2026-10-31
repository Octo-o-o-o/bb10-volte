"""Per-SIM, source-owned authorization cannot open an untested auto-start path."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'device'))
sys.path.insert(0, str(ROOT / 'tools'))
import autostart_evidence as a
import compatibility as c
import native as n
import profiles
import telecom_dca as dca
import workflow as w
from test_telecom_attach import attach_facts, telecom_profile


class EvidenceFixture:
    def __init__(self):
        self.base = '/var/rootdata/q10_volte'
        self.folder = self.base + '/state/telecom-attach-' + 'a' * 16
        self.request = profiles.request(telecom_profile(), True)
        self.fp = profiles.fingerprint(self.request)
        self.identity = '46011' + '0' * 10
        self.sim = hashlib.sha256(self.identity.encode('ascii')).hexdigest()
        self.blobs = {}
        self.plan = {'owner': 'bb10-telecom-attach-v1', 'profile_sha256': self.fp,
                     'sim_fingerprint': self.sim, 'files': {}}
        self.put(self.base + '/state/telecom-plan.json', {'owner': self.plan['owner'], 'folder': self.folder})
        for name in dca.SOURCES:
            original = b'' if name == 'omadm' else dca.HEADER
            applied = dca.payload(original, 'data_centric')
            path = dca.source_path(name)
            self.blobs[path] = applied
            self.blobs[self.folder + '/' + name + '.original'] = original
            self.plan['files'][name] = {'path': path, 'original_sha256': n.digest(original),
                'applied_sha256': n.digest(applied), 'identity': [10, 0o644, 379, 31]}
        self.put(self.folder + '/plan.json', self.plan)
        self.put(self.folder + '/desktop-backup-receipt.json', {'owner': self.plan['owner'],
            'plan_sha256': n.digest(self.blobs[self.folder + '/plan.json']), 'all_original_hashes_verified': True})
        self.put(self.base + '/state/journal.json', {'owner': c.OWNER, 'original_voice_policy': 0,
            'profile_sha256': self.fp, 'telecom_dca_plan': self.folder})
        self.put(self.base + '/state/telecom-bootstrap.json', {'owner': self.plan['owner'],
            'plan_folder': self.folder, 'profile_sha256': self.fp, 'sim_fingerprint': self.sim, 'phase': 'ready'})
        self.blobs['/pps/services/cellular/uicc/card0/status_private'] = (
            '@status\nuicc_state:json:{"state":"READY"}\nhplmn:json:{"mcc":"460","mnc":"11","other":0}\nuicc_type:n:6\n').encode()
        self.blobs['/pps/services/cellular/uicc/card0/status_restricted'] = ('@status\nimsi::' + self.identity + '\n').encode()
        self.critical = {}
        for name in a.CRITICAL_FILES:
            self.blobs[self.base + '/' + name] = ('code:' + name).encode()
            self.critical[name] = n.digest(self.blobs[self.base + '/' + name])
        self.put(self.base + '/installation.json', {'owner': c.OWNER, 'files': self.critical})
        self.receipt = {'owner': a.OWNER, 'variant': 'SQN100-3', 'profile_sha256': self.fp,
            'sim_fingerprint': self.sim, 'critical_files': self.critical, 'desktop_starts_during_reboot': 0,
            'manual_calls': True, 'normal_reboot': True, 'post_reboot_calls_without_usb': True,
            'audio_both_directions': True, 'lte': True, 'manual_sip_dialogs_verified': True,
            'post_reboot_ims_call_events_verified': True}
        self.put(self.base + '/state/telecom-autostart-acceptance.json', self.receipt)

    def put(self, path, value):
        self.blobs[path] = json.dumps(value).encode('ascii')

    def observe(self, variant='SQN100-3'):
        def read(path):
            if path not in self.blobs: raise OSError('missing fixture')
            return self.blobs[path]
        with patch.object(a.device_info, 'read_identity', return_value={'variant': variant, 'os_version': '10.3.3.3216'}), \
                patch.object(a.profiles, 'installed_request', return_value=self.request), \
                patch.object(a.n, 'read', side_effect=read), patch.object(a.os.path, 'islink', return_value=False), \
                patch.object(a.os.path, 'realpath', side_effect=lambda value: value), \
                patch.object(a.os, 'stat', return_value=SimpleNamespace(st_ino=10, st_mode=0o644, st_uid=379, st_gid=31)):
            return a.observe(self.base, self.request['profile'])


class AuthorizationTests(unittest.TestCase):
    def test_valid_exact_runtime_and_sim_authorizes(self):
        f = EvidenceFixture()
        self.assertEqual(f.observe(), {'owned_configuration': True, 'autostart_authorized': True})
        self.assertNotIn(f.identity, json.dumps(f.observe()))

    def test_missing_acceptance_still_reports_owned_applied_configuration(self):
        f = EvidenceFixture(); del f.blobs[f.base + '/state/telecom-autostart-acceptance.json']
        self.assertEqual(f.observe(), {'owned_configuration': True, 'autostart_authorized': False})

    def test_restore_to_original_sources_keeps_valid_authorization(self):
        f = EvidenceFixture()
        for name in dca.SOURCES:
            f.blobs[dca.source_path(name)] = f.blobs[f.folder + '/' + name + '.original']
        f.put(f.base + '/state/telecom-bootstrap.json', {'owner': f.plan['owner'], 'plan_folder': f.folder,
            'profile_sha256': f.fp, 'sim_fingerprint': f.sim, 'phase': 'restored'})
        self.assertEqual(f.observe(), {'owned_configuration': False, 'autostart_authorized': True})

    def test_wrong_sim_and_passport_cannot_reuse_acceptance(self):
        f = EvidenceFixture()
        self.assertFalse(f.observe(variant='SQW100-4')['autostart_authorized'])
        f.blobs['/pps/services/cellular/uicc/card0/status_restricted'] = ('@status\nimsi::46011' + '1' * 10 + '\n').encode()
        self.assertEqual(f.observe(), {'owned_configuration': False, 'autostart_authorized': False})

    def test_truthy_fields_and_bool_zero_desktop_count_are_rejected(self):
        for key, value in (('lte', 1), ('normal_reboot', 'true'), ('manual_calls', 'yes'),
                           ('desktop_starts_during_reboot', False), ('desktop_starts_during_reboot', 1)):
            f = EvidenceFixture(); receipt = copy.deepcopy(f.receipt); receipt[key] = value
            f.put(f.base + '/state/telecom-autostart-acceptance.json', receipt)
            with self.subTest(key=key, value=value): self.assertFalse(f.observe()['autostart_authorized'])

    def test_changed_runtime_or_unknown_source_does_not_authorize(self):
        f = EvidenceFixture(); f.blobs[f.base + '/device/service.py'] += b'changed'
        self.assertFalse(f.observe()['autostart_authorized'])
        f = EvidenceFixture(); f.blobs[dca.source_path('ims')] += b'other::value\n'
        self.assertEqual(f.observe(), {'owned_configuration': False, 'autostart_authorized': False})

    def test_backup_receipt_and_profile_must_match(self):
        f = EvidenceFixture(); f.put(f.folder + '/desktop-backup-receipt.json', {'owner': f.plan['owner'],
            'all_original_hashes_verified': 'true', 'plan_sha256': n.digest(f.blobs[f.folder + '/plan.json'])})
        self.assertFalse(f.observe()['autostart_authorized'])
        f = EvidenceFixture(); receipt = copy.deepcopy(f.receipt); receipt['profile_sha256'] = 'wrong'
        f.put(f.base + '/state/telecom-autostart-acceptance.json', receipt)
        self.assertFalse(f.observe()['autostart_authorized'])


class EnableWorkflowTests(unittest.TestCase):
    def report(self):
        value = attach_facts()
        value.update(voice_policy=3, crypto={'swcr_id': 0, 'crypto_support': 0}, ims_count=1, vpn_count=1,
                     clean_configuration=False, network_service=2098186, apn_matches=True, data_connected=True,
                     internet_enabled=True, internet_present=True, internet_active=True, internet_connectable=True)
        value['telecom_attach'].update(source_baseline=False, original_usage=False,
                                       owned_configuration=True, autostart_authorized=True)
        value['installation'] = {'state': 'busy', 'payload_verified': True, 'current_profile': True,
            'carrier_profile_sha256': profiles.fingerprint(profiles.request(telecom_profile(), True))}
        return value

    def test_owned_active_service_can_enable_only_with_exact_authorization(self):
        value = self.report(); report = c.evaluate(value, telecom_profile(), True)
        self.assertTrue(report['can_enable']); self.assertFalse(report['can_start'])
        self.assertEqual(report['hardware_validation'], 'q10_telecom_per_sim_accepted')
        for change in ('receipt', 'old_payload', 'unverified', 'different_profile'):
            sample = copy.deepcopy(value)
            if change == 'receipt': sample['telecom_attach']['autostart_authorized'] = 'true'
            if change == 'old_payload': sample['installation']['current_profile'] = False
            if change == 'unverified': sample['installation']['payload_verified'] = False
            if change == 'different_profile': sample['installation']['carrier_profile_sha256'] = 'wrong'
            with self.subTest(change=change): self.assertFalse(c.evaluate(sample, telecom_profile(), True)['can_enable'])

    def test_enabling_accepted_service_does_not_restart_registration(self):
        report = c.evaluate(self.report(), telecom_profile(), True)
        client = object.__new__(w.Client); client.profile = telecom_profile()
        client.request = profiles.request(client.profile, True)
        client.preflight = Mock(return_value=report); client.execute = Mock(return_value={'completed': True})
        client.service = Mock(side_effect=AssertionError('registration restarted'))
        result = client.action('enable')
        self.assertTrue(result['enabled']); self.assertTrue(result['registration_not_restarted'])
        client.execute.assert_called_once_with(w.BASE + '/device/install.py', 'enable')
        client.service.assert_not_called()

    def test_accepted_existing_request_is_preserved_without_a_new_experiment(self):
        profile = telecom_profile()
        before = {'schema': 2, 'profile_sha256': profiles.fingerprint(profiles.request(profile, False)),
                  'telecom_attach': {'autostart_authorized': True},
                  'installation': {'carrier_profile_sha256': profiles.fingerprint(profiles.request(profile, True))}}
        after = copy.deepcopy(before); after['profile_sha256'] = profiles.fingerprint(profiles.request(profile, True))
        client = object.__new__(w.Client); client.profile = profile
        client.request = profiles.request(profile, False)
        client.progress = Mock(); client.execute = Mock(side_effect=[before, after]); client.process = Mock()
        client.scp, client.ssh, client.options, client.host = 'scp', 'ssh', [], 'q10-owner'
        with tempfile.TemporaryDirectory() as folder, patch.object(w, 'private_root', return_value=Path(folder)), \
                patch.object(w, 'evidence_for', return_value={}):
            report = client.inspect_stage('/var/rootdata/q10_volte_stage_' + 'a' * 12)
            self.assertEqual(list(Path(folder).iterdir()), [])
        self.assertTrue(report['use_installed_profile'])
        self.assertTrue(client.request['allow_experimental'])
        self.assertEqual(client.execute.call_count, 2)
        self.assertEqual(client.process.call_count, 1)

    def test_unaccepted_request_is_not_silently_changed(self):
        profile = telecom_profile(); client = object.__new__(w.Client)
        client.profile, client.request = profile, profiles.request(profile, False)
        client.progress = Mock(); client.process = Mock()
        client.execute = Mock(return_value={'schema': 2, 'profile_sha256': profiles.fingerprint(client.request),
                                            'telecom_attach': {'autostart_authorized': False}})
        with patch.object(w, 'evidence_for', return_value={}): client.inspect_stage('/stage')
        self.assertFalse(client.request['allow_experimental']); client.process.assert_not_called()


if __name__ == '__main__':
    unittest.main()
