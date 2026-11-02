"""Desktop ownership/conflict tests for the Passport-only recovery lifecycle."""
import importlib.util
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'device'))
spec = importlib.util.spec_from_file_location('passport_trial', Path(__file__).with_name('passport_volte_phone.py'))
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class RetentionTests(unittest.TestCase):
    def test_capture_protects_its_directory_without_changing_process_umask(self):
        native, service, current = self.environment()
        current[trial.IMS_LOG_CONTROL] = {}
        service.j['pps_applied'] = service.applied_updates()
        service.apply_fields = Mock()
        meta = SimpleNamespace(st_uid=453, st_gid=31, st_mode=0o40700)
        with patch.object(trial, 'n', native), patch.object(trial, 's', service), \
             patch.object(trial.os.path, 'isdir', return_value=True), \
             patch.object(trial.os.path, 'islink', return_value=False), \
             patch.object(trial.os, 'stat', return_value=meta), \
             patch.object(trial.os, 'umask', side_effect=AssertionError('Do not change IPC creation permissions')):
            trial.enable_native_capture()
        service.apply_fields.assert_called_once_with(trial.IMS_LOG_CONTROL)
        self.assertEqual(service.j['pps_before'][trial.IMS_LOG_CONTROL], {'logToPcap': None})
        self.assertEqual(service.j['pps_applied'][trial.IMS_LOG_CONTROL], {'logToPcap': 'b:true'})

    def test_capture_rejects_public_directory_before_changing_any_setting(self):
        native, service, current = self.environment()
        service.apply_fields = Mock()
        with patch.object(trial, 'n', native), patch.object(trial, 's', service), \
             patch.object(trial.os.path, 'isdir', return_value=True), \
             patch.object(trial.os.path, 'islink', return_value=False), \
             patch.object(trial.os, 'stat', return_value=SimpleNamespace(st_uid=453, st_gid=31, st_mode=0o40755)):
            with self.assertRaises(AssertionError):
                trial.enable_native_capture()
        service.save_journal.assert_not_called()
        service.apply_fields.assert_not_called()

    def nas_environment(self):
        radio = {'voice_domain_preference': 3, 'mode_preference_mask': 28,
                 'service_domain_preference': 2, 'usage_preference': 1,
                 'lte_band_preference_mask': 123}
        receipt = {'owner': 'passport-mobile-nas-voice-only-v1', 'boot': [1, 2],
                   'before_epoch': 0, 'restore_target': 0, 'before_apply': None,
                   'applied': 1, 'attempted': False}
        service = SimpleNamespace(j={'boot': [1, 2], 'original_voice_policy': 0,
                   'native_pid': 77, 'nas_voice_trial': receipt},
                   ACTIVE_PROFILE={'id': 'passport-mobile-psonly-manual-research'},
                   boot_token=lambda: [1, 2], phone_idle=lambda: True,
                   LOCK='lock', load=lambda p: {'pid': 42}, save_journal=Mock())
        def set_voice(domain):
            self.assertTrue(receipt['attempted'])
            self.assertTrue(service.save_journal.called)
            radio['voice_domain_preference'] = domain
            return {'voice_domain_readback': domain}
        client = SimpleNamespace(request=Mock(side_effect=lambda m: dict(radio)),
                                 set_voice_domain=Mock(side_effect=set_voice))
        @contextmanager
        def factory():
            yield client
        native = SimpleNamespace(ims_pids=lambda: [77], voice_policy=lambda: 3)
        return service, native, receipt, radio, client, factory

    def test_ps_only_trial_waits_for_registration_and_journals_before_set(self):
        service, native, receipt, radio, client, factory = self.nas_environment()
        state = {'ims': 'disconnected', 'register_status': None}
        with patch.object(trial, 's', service), patch.object(trial, 'n', native), \
             patch.object(trial, 'nas_client_type', return_value=factory), \
             patch.object(trial, 'research_live', return_value=state), patch.object(trial.os, 'getpid', return_value=42):
            trial.ps_only_live()
            client.set_voice_domain.assert_not_called()
            state.update(ims='connected', register_status='200 OK')
            trial.ps_only_live()
            client.set_voice_domain.assert_called_once_with(1)
            self.assertEqual(receipt['before_apply'], 3)
            self.assertEqual(receipt['after']['voice_domain_preference'], 1)
            trial.ps_only_live()
            client.set_voice_domain.assert_called_once_with(1)

    def test_ps_only_trial_cannot_be_applied_by_a_status_reader(self):
        service, native, receipt, radio, client, factory = self.nas_environment()
        with patch.object(trial, 's', service), patch.object(trial, 'n', native), \
             patch.object(trial, 'nas_client_type', return_value=factory), \
             patch.object(trial, 'research_live', return_value={'ims': 'connected', 'register_status': '200 OK'}), \
             patch.object(trial.os, 'getpid', return_value=99):
            with self.assertRaises(AssertionError):
                trial.ps_only_live()
        client.set_voice_domain.assert_not_called()

    def test_foreign_nas_voice_value_blocks_recovery_before_mutations(self):
        service, native, receipt, radio, client, factory = self.nas_environment()
        receipt.update(attempted=True, before_apply=3)
        radio['voice_domain_preference'] = 2
        service.stop_native = Mock()
        with patch.object(trial, 's', service), patch.object(trial, 'n', native), \
             patch.object(trial, 'nas_client_type', return_value=factory):
            with self.assertRaises(AssertionError):
                trial.restore_retaining_provider()
        service.stop_native.assert_not_called()
        client.set_voice_domain.assert_not_called()

    def test_owned_nas_voice_trial_restores_zero_and_verifies(self):
        service, native, receipt, radio, client, factory = self.nas_environment()
        receipt.update(attempted=True, before_apply=3)
        radio['voice_domain_preference'] = 1
        native.voice_policy = lambda: 0
        service.save_journal()
        with patch.object(trial, 's', service), patch.object(trial, 'n', native), \
             patch.object(trial, 'nas_client_type', return_value=factory):
            trial.restore_nas_voice()
        client.set_voice_domain.assert_called_once_with(0)
        self.assertTrue(receipt['restored'])
        self.assertEqual(radio['voice_domain_preference'], 0)

    def test_signalling_option_preserves_all_existing_carrier_bytes(self):
        before = (b'<root><internet><APN>cmnet</APN></internet><IMSConfiguration>'
                  b'<RequestPCSCFViaPCO>true</RequestPCSCFViaPCO></IMSConfiguration><mms/></root>')
        changed = trial.signalling_bearer_xml(before)
        extra = b'<RequestSignallingBearerViaPCO>true</RequestSignallingBearerViaPCO>'
        self.assertEqual(changed.replace(extra, b''), before)
        self.assertEqual(changed.count(extra), 1)
        with self.assertRaises(AssertionError):
            trial.signalling_bearer_xml(before + before)
        with self.assertRaises(AssertionError):
            trial.signalling_bearer_xml(changed)

    def test_new_carrier_settings_removed_only_with_exact_owned_hash(self):
        content = b'owned-settings'
        native = SimpleNamespace(read=lambda p: content,
                 digest=lambda b: hashlib.sha256(b).hexdigest())
        service = SimpleNamespace(j={'extra_carrier_settings': {'path': trial.MOBILE_SETTINGS,
                 'before_absent': True, 'sha256': hashlib.sha256(content).hexdigest()}})
        with patch.object(trial, 'n', native), patch.object(trial, 's', service), \
             patch.object(trial.os.path, 'lexists', return_value=True), \
             patch.object(trial.os.path, 'islink', return_value=False), patch.object(trial.os, 'unlink') as unlink:
            trial.restore_extra_settings()
            unlink.assert_called_once_with(trial.MOBILE_SETTINGS)
            unlink.reset_mock()
            service.j['extra_carrier_settings']['sha256'] = 'foreign-change'
            with self.assertRaises(AssertionError):
                trial.restore_extra_settings()
            unlink.assert_not_called()
            service.j['extra_carrier_settings']['path'] = '/etc/unrelated'
            with self.assertRaises(AssertionError):
                trial.restore_extra_settings()
            unlink.assert_not_called()

    def test_provider_reuse_requires_original_owned_recovery_receipt(self):
        original = {'owner': 'q10-unicom-volte-v1', 'configuration_restored': True,
                    'lifecycle': 'retain-provider-until-reboot', 'boot': [1, 2],
                    'crypto_boot': [1, 2], 'provider': 0, 'provider_enable_attempted': True}
        request = {'test_request': True}
        original_bytes = json.dumps(original).encode('ascii')
        proof = {'owner': 'passport-retained-provider-epoch-v1', 'boot': [1, 2], 'provider': 0,
                 'profile_sha256': trial.profiles.fingerprint(request),
                 'origin': {'path': trial.BASE + '/archive/trial-100/journal.json',
                            'sha256': hashlib.sha256(original_bytes).hexdigest()}}
        state = {'receipt': original_bytes, 'crypto': {'swcr_id': 0, 'crypto_support': 0}}
        native = SimpleNamespace(read=lambda p: state['receipt'],
                 digest=lambda b: hashlib.sha256(b).hexdigest(), crypto_policy=lambda: state['crypto'])
        service = SimpleNamespace(STATE='state', load=lambda p: proof,
                  boot_token=lambda: [1, 2], ACTIVE_REQUEST=request)
        with patch.object(trial, 'n', native), patch.object(trial, 's', service), patch.object(trial.os.path, 'islink', return_value=False):
            self.assertEqual(trial.retained_provider_proof()['provider'], 0)
            for key, value in (('boot', [2, 3]), ('profile_sha256', 'wrong-profile')):
                saved = proof[key]; proof[key] = value
                with self.assertRaises(AssertionError):
                    trial.retained_provider_proof()
                proof[key] = saved
            state['crypto'] = {'swcr_id': 1, 'crypto_support': 0}
            with self.assertRaises(AssertionError):
                trial.retained_provider_proof()
            state['crypto'] = {'swcr_id': 0, 'crypto_support': 0}
            state['receipt'] = original_bytes + b' '
            with self.assertRaises(AssertionError):
                trial.retained_provider_proof()
            bad = dict(original); bad['configuration_restored'] = False
            state['receipt'] = json.dumps(bad).encode('ascii')
            proof['origin']['sha256'] = hashlib.sha256(state['receipt']).hexdigest()
            with self.assertRaises(AssertionError):
                trial.retained_provider_proof()

    def test_retained_baseline_requires_all_other_guards(self):
        base = {'voice_policy': 0, 'crypto': {'swcr_id': 0, 'crypto_support': 0},
                'ims_count': 0, 'vpn_count': 0, 'native_read_error': False, 'clean_configuration': True}
        self.assertTrue(trial.retained_baseline_matches(base, 0))
        for key, value in (('voice_policy', 3), ('ims_count', 1), ('vpn_count', 1),
                           ('native_read_error', True), ('clean_configuration', False)):
            bad = dict(base); bad[key] = value
            self.assertFalse(trial.retained_baseline_matches(bad, 0), key)
        self.assertFalse(trial.retained_baseline_matches(base, 1))
        self.assertFalse(trial.retained_baseline_matches(base, -1))
        self.assertFalse(trial.retained_baseline_matches(base, True))

    def environment(self):
        current = {'ims': {'profile': 'new'}, 'cdsc': {'xml': 'new'}, 'voice': {'pref': 'new'}}
        before = {'ims': {'profile': None}, 'cdsc': {'xml': ':'}, 'voice': {'pref': None}}
        applied = {name: dict(value) for name, value in current.items()}
        state = {'voice': 3}
        def update(path, changes):
            current[path].update(changes)
        def set_voice(value):
            self.assertEqual(value, 4)
            state['voice'] = 0
            return {'rc': 0}
        native = SimpleNamespace(read=lambda p: current[p], attrs=lambda b: b,
                 update_pps=Mock(side_effect=update), crypto_policy=Mock(return_value={'swcr_id': 7, 'crypto_support': 1}),
                 voice_policy=lambda: state['voice'], command=Mock(side_effect=AssertionError('No native command in retention recovery')))
        service = SimpleNamespace(j={'boot': [1, 2], 'original_voice_policy': 0, 'pps_before': before},
                 boot_token=lambda: [1, 2], phone_idle=Mock(return_value=True), stop_native=Mock(),
                 IMS='ims', CDSC='cdsc', VOICE='voice', XML='xml', applied_updates=lambda: applied,
                 remove_owned=Mock(), remove_platform=Mock(), set_voice_preference=Mock(side_effect=set_voice),
                 save_journal=Mock(), status=Mock())
        return native, service, current

    def test_loaded_provider_is_retained_and_full_restore_is_not_claimed(self):
        native, service, current = self.environment()
        with patch.object(trial, 'n', native), patch.object(trial, 's', service), patch.object(trial.time, 'sleep'):
            trial.restore_retaining_provider()
        self.assertTrue(service.j['configuration_restored'])
        self.assertFalse(service.j['restore_completed'])
        self.assertTrue(service.j['provider_retained_until_reboot'])
        self.assertTrue(service.j['reboot_verification_required'])
        native.command.assert_not_called()
        self.assertEqual(current, service.j['pps_before'])

    def test_ir92_trial_is_restored_without_provider_commands(self):
        for key, value in (('UsePreconditions', 'n:0'), ('HDvoice', 'b:true')):
            with self.subTest(field=key):
                native, service, current = self.environment()
                current[trial.IR92] = {key: value}
                service.j['pps_before'][trial.IR92] = {key: None}
                service.applied_updates()[trial.IR92] = {key: value}
                with patch.object(trial, 'n', native), patch.object(trial, 's', service), patch.object(trial.time, 'sleep'):
                    trial.restore_retaining_provider()
                self.assertIsNone(current[trial.IR92][key])
                native.command.assert_not_called()

    def test_codec_trial_preserves_existing_override_and_journals_before_write(self):
        native, service, current = self.environment()
        service.ACTIVE_PROFILE = {'id': 'passport-mobile-hdvoice-manual-research',
                                  'carrier': {'data_apns': ['cmnet']}}
        service.j.update(pps_applied=service.applied_updates(), compatibility_trial={})
        current[trial.IR92] = {'HDvoice': 'b:false'}
        service.apply_fields = Mock()
        with patch.object(trial, 'n', native), patch.object(trial, 's', service):
            with self.assertRaises(AssertionError):
                trial.enable_mobile_hdvoice()
            service.apply_fields.assert_not_called()
            service.save_journal.assert_not_called()
            current[trial.IR92] = {}
            service.apply_fields.side_effect = lambda path: self.assertTrue(service.save_journal.called)
            trial.enable_mobile_hdvoice()
        self.assertEqual(service.j['pps_before'][trial.IR92], {'HDvoice': None})
        self.assertEqual(service.j['pps_applied'][trial.IR92], {'HDvoice': 'b:true'})
        service.apply_fields.assert_called_once_with(trial.IR92)

    def test_native_trace_flag_is_restored_before_stopping_engine(self):
        native, service, current = self.environment()
        current[trial.IMS_LOG_CONTROL] = {'logToPcap': 'b:true'}
        service.j['pps_before'][trial.IMS_LOG_CONTROL] = {'logToPcap': None}
        service.applied_updates()[trial.IMS_LOG_CONTROL] = {'logToPcap': 'b:true'}
        service.stop_native.side_effect = lambda: self.assertIsNone(current[trial.IMS_LOG_CONTROL]['logToPcap'])
        with patch.object(trial, 'n', native), patch.object(trial, 's', service), patch.object(trial.time, 'sleep'):
            trial.restore_retaining_provider()
        native.command.assert_not_called()
        self.assertIsNone(current[trial.IMS_LOG_CONTROL]['logToPcap'])

    def test_foreign_trace_setting_is_preserved_before_any_cleanup(self):
        native, service, current = self.environment()
        current[trial.IMS_LOG_CONTROL] = {'logToPcap': 'b:false'}
        service.j['pps_before'][trial.IMS_LOG_CONTROL] = {'logToPcap': None}
        service.applied_updates()[trial.IMS_LOG_CONTROL] = {'logToPcap': 'b:true'}
        with patch.object(trial, 'n', native), patch.object(trial, 's', service):
            with self.assertRaises(AssertionError):
                trial.restore_retaining_provider()
        service.stop_native.assert_not_called()
        native.update_pps.assert_not_called()

    def test_external_ir92_change_is_preserved(self):
        native, service, current = self.environment()
        current[trial.IR92] = {'UsePreconditions': 'n:1'}
        service.j['pps_before'][trial.IR92] = {'UsePreconditions': None}
        service.applied_updates()[trial.IR92] = {'UsePreconditions': 'n:0'}
        with patch.object(trial, 'n', native), patch.object(trial, 's', service):
            with self.assertRaises(AssertionError):
                trial.restore_retaining_provider()
        self.assertEqual(current[trial.IR92]['UsePreconditions'], 'n:1')
        native.update_pps.assert_not_called()

    def test_concurrent_carrier_change_is_preserved(self):
        native, service, current = self.environment()
        current['ims']['profile'] = 'external'
        with patch.object(trial, 'n', native), patch.object(trial, 's', service):
            with self.assertRaises(AssertionError):
                trial.restore_retaining_provider()
        native.update_pps.assert_not_called()
        self.assertEqual(current['ims']['profile'], 'external')

    def test_active_call_defers_all_restoration(self):
        native, service, current = self.environment()
        service.phone_idle.return_value = False
        with patch.object(trial, 'n', native), patch.object(trial, 's', service):
            with self.assertRaises(AssertionError):
                trial.restore_retaining_provider()
        service.stop_native.assert_not_called()
        native.update_pps.assert_not_called()

    def test_another_boot_cannot_use_old_journal(self):
        native, service, current = self.environment()
        service.j['boot'] = [2, 3]
        with patch.object(trial, 'n', native), patch.object(trial, 's', service):
            with self.assertRaises(AssertionError):
                trial.restore_retaining_provider()
        service.stop_native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
