"""Compatibility boundaries and safe failure paths; no phone is contacted."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'device'))
sys.path.insert(0, str(ROOT / 'tools'))
import compatibility as c
import install
import native
import service
import workflow as w
import profiles


def baseline():
    return dict(model='Q10', variant='SQN100-3', os_version='10.3.3.3216', root_ready=True,
                arm32_qnx=True, native_hashes={path: True for path in native.STOCK_HASHES},
                sim_state='READY', sim_type=2, mcc='460', mnc='01', identity_matches=True,
                radio_on=True, lte=True, apn_matches=True, data_connected=True,
                installation={'state': 'absent'}, voice_policy=0,
                crypto={'swcr_id': -1, 'crypto_support': 0}, ims_count=0, vpn_count=0,
                clean_configuration=True, carrier_template_ready=True)


class CompatibilityTests(unittest.TestCase):
    def test_supported_profile_allows_install_not_uninstalled_start(self):
        report = c.evaluate(baseline())
        self.assertEqual(report['outcome'], 'compatible')
        self.assertTrue(report['can_install'])
        self.assertFalse(report['can_start'])

    def test_province_is_not_a_compatibility_override(self):
        for province in ('Beijing', 'Hebei', 'Guangdong', 'unknown'):
            s = baseline(); s['province'] = province
            self.assertTrue(c.evaluate(s)['can_install'])
            self.assertEqual(c.evaluate(s)['hardware_validation'], 'single_q10_beijing_unicom_only')

    def test_other_mnc_or_isim_needs_adaptation(self):
        for changes in ({'mnc': '06'}, {'mnc': '00'}, {'mnc': '11'}, {'sim_type': 18},
                        {'sim_type': None}, {'identity_matches': False}):
            with self.subTest(changes=changes):
                s = baseline(); s.update(changes)
                report = c.evaluate(s)
                self.assertEqual(report['outcome'], 'needs_adaptation')
                self.assertFalse(report['can_install'])

    def test_unknown_model_os_or_hash_blocked(self):
        for changes in ({'variant': 'UNKNOWN'}, {'os_version': '10.3.3.9999'}, {'model': 'Q20'},
                        {'native_hashes': {}}, {'native_hashes': {p: False for p in native.STOCK_HASHES}}):
            s = baseline(); s.update(changes)
            self.assertEqual(c.evaluate(s)['outcome'], 'unsupported')
            self.assertFalse(c.evaluate(s)['can_install'])

    def test_missing_sim_lte_data_or_root_waits_without_installing(self):
        for changes in ({'sim_state': 'ABSENT'}, {'lte': False}, {'apn_matches': False},
                        {'data_connected': False}, {'root_ready': False}, {'network_read_error': True}):
            s = baseline(); s.update(changes)
            self.assertEqual(c.evaluate(s)['outcome'], 'not_ready')
            self.assertFalse(c.evaluate(s)['can_install'])

    def test_native_conflicts_and_interrupted_install_deny_writes(self):
        for changes in ({'ims_count': 1}, {'vpn_count': 1}, {'voice_policy': 3},
                        {'clean_configuration': False}, {'native_read_error': True},
                        {'installation': {'state': 'interrupted'}}, {'installation': {'state': 'conflict'}}):
            s = baseline(); s.update(changes)
            report = c.evaluate(s)
            self.assertFalse(any(report[k] for k in ('can_install', 'can_update', 'can_start')))

    def test_legacy_payload_can_update_but_not_start_new_workflow(self):
        s = baseline(); s['installation'] = {'state': 'stopped', 'current_profile': False}
        report = c.evaluate(s)
        self.assertTrue(report['can_update']); self.assertFalse(report['can_start'])
        s['installation']['current_profile'] = True
        s['installation']['carrier_profile_sha256'] = profiles.fingerprint(profiles.request())
        self.assertTrue(c.evaluate(s)['can_start'])

    def test_sensitive_inputs_never_enter_report(self):
        s = baseline(); secret = '46001' + '0' * 10
        s.update(imsi=secret, imei='1' * 15, ssh_key='private', raw_pps=secret)
        encoded = json.dumps(c.evaluate(s))
        for key in ('imsi', 'imei', 'ssh_key', 'raw_pps', secret):
            self.assertNotIn(key, encoded)

    def test_read_network_reduces_identity_to_boolean(self):
        records = {'status_private': {'uicc_state': {'state': 'READY'}, 'uicc_type': 2,
                                      'hplmn': {'mcc': '460', 'mnc': '01'}},
                   'status_restricted': {'imsi': '46001' + '0' * 10},
                   'status_public': {'power_status': 'ON', 'network_technology': ['lte']},
                   'status': {'internet': {'apn': '3gnet', 'connected': True}}}
        with patch.object(native, 'read', side_effect=lambda p: records[p.rsplit('/', 1)[-1]]), \
             patch.object(native, 'attrs', side_effect=lambda v: v), \
             patch.object(native, 'value', side_effect=lambda d, k, default=None: d.get(k, default)):
            result = c.read_network()
        self.assertTrue(result['identity_matches'])
        self.assertNotIn('imsi', json.dumps(result))

    def test_service_rejects_wrong_carrier_without_waiting(self):
        s = baseline(); s['mnc'] = '00'
        with patch.object(c, 'read_network', return_value=s), patch.object(service.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'needs adaptation'):
                service.wait_for_network()
            sleep.assert_not_called()

    def test_missing_sim_wait_is_bounded(self):
        s = baseline(); s['sim_state'] = 'ABSENT'
        with patch.object(c, 'read_network', return_value=s), patch.object(service, 'status'), \
             patch.object(service, 'stopping', return_value=False), patch.object(service.time, 'sleep'), \
             patch.object(service.time, 'time', side_effect=[0, 1, 301]):
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                service.wait_for_network()

    def test_sim_change_before_configuration_causes_no_journal_or_writes(self):
        with patch.object(service, 'ready', return_value=False), patch.object(service, 'init_journal') as journal:
            with self.assertRaisesRegex(AssertionError, 'changed after preflight'):
                service.configure()
            journal.assert_not_called()


class WorkflowTests(unittest.TestCase):
    def client(self):
        with patch.object(w.shutil, 'which', return_value='ssh'):
            return w.Client()

    def test_altered_payload_is_rejected_without_blessing_manifest(self):
        manifest_before = (ROOT / w.MANIFEST).read_bytes()
        with patch.object(w.hashlib, 'sha256') as digest:
            digest.return_value.hexdigest.return_value = 'changed'
            with self.assertRaisesRegex(w.WorkflowError, 'package_mismatch'):
                w.verify_package()
        self.assertEqual((ROOT / w.MANIFEST).read_bytes(), manifest_before)

    def test_unknown_host_option_is_rejected(self):
        for host in ('-oProxyCommand=bad', 'q10;command', 'q10 root'):
            with self.assertRaises(w.WorkflowError):
                w.Client(host)

    def test_unknown_remote_outcome_preserves_stage_inputs(self):
        client = self.client()
        with patch.object(client, 'remote', return_value=''), patch.object(client, 'process', return_value=''), \
             patch.object(client, 'execute') as cleanup:
            with self.assertRaises(w.WorkflowError):
                with client.stage(payload=True):
                    raise w.WorkflowError('connection_timeout_state_unknown')
            cleanup.assert_not_called()

    def test_successful_preflight_removes_only_its_exact_stage(self):
        client = self.client()
        with patch.object(client, 'remote', return_value=''), patch.object(client, 'process', return_value=''), \
             patch.object(client, 'execute', return_value={'stage_removed': True}) as cleanup:
            with client.stage() as stage:
                self.assertTrue(stage.startswith('/var/rootdata/q10_volte_stage_'))
            cleanup.assert_called_once()
            self.assertEqual(cleanup.call_args.args[0], stage + '/stage-cleanup.py')
            self.assertIn('device/compatibility.py', cleanup.call_args.args[1])
            self.assertIn('profile-request.json', cleanup.call_args.args[1])
            self.assertNotIn('/var/rootdata/q10_volte/device', cleanup.call_args.args[1])

    def test_clean_install_readback_precedes_activation(self):
        client = self.client(); events = []
        after = c.evaluate(baseline())
        after['installation'] = {'payload_verified': True, 'version': w.verify_package()['version'], 'state': 'stopped',
                                 'carrier_profile_sha256': profiles.fingerprint(client.request)}
        def inspect(_):
            events.append('check')
            return {'can_install': True} if events.count('check') == 1 else after
        with patch.object(client, 'stage') as stage, patch.object(client, 'inspect_stage', side_effect=inspect), \
             patch.object(client, 'execute', side_effect=lambda *_: events.append('write') or {'installed': True}), \
             patch.object(client, 'action', side_effect=lambda *_: events.append('start') or {'registration': 'pending'}):
            stage.return_value.__enter__.return_value = '/stage'
            result = client.install(start=True)
        self.assertEqual(events, ['check', 'write', 'check', 'start'])
        self.assertEqual(result['registration'], 'pending')
        self.assertEqual(result['call_acceptance'], 'pending')

    def test_install_rechecks_and_does_not_write_when_preflight_fails(self):
        client = self.client()
        with patch.object(client, 'stage') as stage, patch.object(client, 'inspect_stage', return_value={'can_install': False}), \
             patch.object(client, 'execute') as execute:
            stage.return_value.__enter__.return_value = '/stage'
            with self.assertRaisesRegex(w.WorkflowError, 'preflight_blocked'):
                client.install()
            execute.assert_not_called()

    def test_installer_itself_blocks_changed_sim_before_first_write(self):
        data = {name: (ROOT / name).read_bytes() for name in w.FILES}
        data['payload-manifest.json'] = (ROOT / w.MANIFEST).read_bytes()
        stage = '/var/rootdata/q10_volte_stage_test'
        with patch.object(native, 'read', side_effect=lambda p: data[p[len(stage) + 1:]]), \
             patch.object(profiles, 'load_request', return_value=profiles.request()), \
             patch.object(install.os.path, 'realpath', return_value=stage), \
             patch.object(native, 'verify_stock'), patch.object(c, 'require', side_effect=RuntimeError('changed SIM')), \
             patch.object(native, 'atomic') as write, patch.object(install.os, 'mkdir') as mkdir:
            with self.assertRaisesRegex(RuntimeError, 'changed SIM'):
                install.install(stage)
            write.assert_not_called(); mkdir.assert_not_called()

    def test_timeout_never_retries_or_starts_after_unknown_install(self):
        client = self.client()
        with patch.object(client, 'stage') as stage, patch.object(client, 'inspect_stage', return_value={'can_install': True}), \
             patch.object(client, 'execute', side_effect=w.WorkflowError('connection_timeout_state_unknown')) as execute, \
             patch.object(client, 'action') as action:
            stage.return_value.__enter__.return_value = '/stage'
            with self.assertRaises(w.WorkflowError):
                client.install(start=True)
            self.assertEqual(execute.call_count, 1); action.assert_not_called()

    def test_failed_readback_never_starts(self):
        client = self.client()
        after = {'installation': {'payload_verified': False}}
        with patch.object(client, 'stage') as stage, \
             patch.object(client, 'inspect_stage', side_effect=[{'can_install': True}, after]), \
             patch.object(client, 'execute', return_value={'installed': True}), patch.object(client, 'action') as action:
            stage.return_value.__enter__.return_value = '/stage'
            with self.assertRaisesRegex(w.WorkflowError, 'installation_not_verified'):
                client.install(start=True)
            action.assert_not_called()

    def test_stale_registration_without_live_process_never_passes(self):
        status = {'phase': 'running', 'manager_alive': True, 'native_alive': True, 'current': {
            'ims': 'connected', 'register_status': '200 OK', 'ran': 'LTE', 'radio': ['lte']}}
        self.assertTrue(w.registered(status))
        for key in ('manager_alive', 'native_alive'):
            stale = copy.deepcopy(status); stale[key] = False
            self.assertFalse(w.registered(stale))
        stale = copy.deepcopy(status); stale['current']['radio'] = ['umts']
        self.assertFalse(w.registered(stale))

    def test_status_report_drops_private_error_and_ids(self):
        status = w.public_status({'error': 'private identity', 'manager_pid': 123, 'native_pid': 456, 'current': {'imsi': 'secret'}})
        self.assertNotIn('private', json.dumps(status)); self.assertNotIn('imsi', json.dumps(status))

    def test_installed_state_refuses_interruption_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            base, addon = Path(folder) / 'base', Path(folder) / 'addon'
            for path in (base / 'device', base / 'driver', base / 'state', base / 'runtime/carrier', addon / 'init', addon / 'data'):
                path.mkdir(parents=True, exist_ok=True)
            (base / 'install-transaction.json').write_text('{}')
            with patch.object(c, 'BASE', str(base)), patch.object(c, 'ADDON', str(addon)):
                self.assertEqual(c.installed_state()['state'], 'interrupted')


if __name__ == '__main__':
    unittest.main()
