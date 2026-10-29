"""Compatibility boundaries and safe failure paths; no phone is contacted."""
import copy
import json
import shlex
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

    def telecom_network(self, apn='ctlte', connected=True, data_error=False):
        profile = profiles.read_json(str(ROOT / 'profiles/china-telecom.json'))
        records = {
            '/pps/services/cellular/uicc/card0/status_private':
                'uicc_state:json:{"state":"READY"}\nuicc_type:n:2\nhplmn:json:{"mcc":"460","mnc":"11"}\n',
            '/pps/services/cellular/uicc/card0/status_restricted': 'imsi::' + '46011' + '0' * 10 + '\n',
            c.RADIO: 'power_status::ON\nnetwork_technology:json:["lte"]\n',
            c.DATA: 'internet:json:' + json.dumps({'apn': apn, 'connected': connected}) + '\n'}
        def read(path):
            if data_error and path == c.DATA:
                raise OSError('unavailable')
            return records[path].encode('ascii')
        with patch.object(native, 'read', side_effect=read):
            return profile, c.read_network(profile)

    def test_ctlte_is_recognized_but_still_requires_connected_data_and_clean_baseline(self):
        for connected in (True, False):
            profile, network = self.telecom_network(connected=connected)
            self.assertTrue(network['apn_matches'])
            facts = baseline()
            facts.update(network, model='Classic', variant='SQC100-4')
            report = c.evaluate(facts, profile, True)
            self.assertEqual(report['can_install'], connected)
            self.assertEqual(report['network_diagnostics']['observed_data_apn'], 'ctlte')
            self.assertEqual(report['network_diagnostics']['data_connected'], connected)
            self.assertEqual(next(item['code'] for item in report['checks'] if item['id'] == 'apn'),
                             'data_apn_ready' if connected else 'data_apn_disconnected')
            facts['clean_configuration'] = False
            self.assertFalse(c.evaluate(facts, profile, True)['can_install'])

    def test_old_ctnet_only_profile_reports_mismatch_even_if_data_is_connected(self):
        profile, network = self.telecom_network()
        profile['carrier']['data_apns'] = ['ctnet']
        network['apn_matches'] = False
        check = next(item for item in c.network_checks(network, profile) if item['id'] == 'apn')
        self.assertEqual(check['code'], 'data_apn_profile_mismatch')
        self.assertEqual(check['status'], 'wait')
        self.assertTrue(c.public_network_diagnostics(network)['data_connected'])

    def test_data_read_failure_retains_radio_snapshot_without_claiming_data_readiness(self):
        profile, network = self.telecom_network(data_error=True)
        self.assertTrue(network['lte'])
        self.assertTrue(network['data_read_error'])
        self.assertEqual(c.network_state(network, profile), 'not_ready')
        self.assertEqual(c.network_checks(network, profile)[-1]['code'], 'data_apn_state_unknown')
        self.assertIsNone(c.public_network_diagnostics(network)['data_connected'])

    def test_unknown_connected_value_and_private_apn_do_not_leak_or_pass(self):
        secret = 'private-customer.example'
        profile, network = self.telecom_network(apn=secret, connected=1)
        self.assertIsNone(network['data_connected'])
        self.assertEqual(network['observed_data_apn'], 'other')
        self.assertNotIn(secret, json.dumps(network))
        facts = baseline(); facts.update(network)
        facts['configuration_diagnostics'] = {'ims_profiles_absent': secret, 'raw_pps': secret}
        report = c.evaluate(facts, profile, True)
        self.assertFalse(report['can_install'])
        self.assertNotIn(secret, json.dumps(report))
        self.assertIsNone(report['configuration_diagnostics']['ims_profiles_absent'])

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


class NetworkSnapshotTests(unittest.TestCase):
    def read_snapshot(self, data=None, radio=None, settings=b'data_service_mode::ON\n'):
        # Relevant fields transcribed from the SQC100-4 report; no identities.
        records = {
            c.RADIO: (b'[n]@status_public\npower_status::ON\nnetwork_technology:json:["lte"]\n'
                      b'network_service:n:1\nactive_bands:json:{"lte":16}\n'
                      b'band_capability:json:{"lte":16846939}\n') if radio is None else radio,
            c.DATA: (b'[n]@status\ndata_services_status::OFF\n'
                     b'internet:json:{"enabled":true,"connectable":false,"active":false,"bid":[16]}\n')
                    if data is None else data,
            c.DATA_SETTINGS: settings,
        }
        def read(path):
            value = records.get(path)
            if value is None:
                raise OSError('private read error')
            return value
        with patch.object(native, 'read', side_effect=read), patch.object(native, 'atomic') as write, \
             patch.object(native, 'update_pps') as update:
            facts = c.read_network()
            write.assert_not_called(); update.assert_not_called()
        return facts

    def test_q20_inactive_service_is_present_and_off_not_an_apn_mismatch(self):
        facts = self.read_snapshot()
        self.assertTrue(facts['internet_present'])
        self.assertTrue(facts['internet_enabled'])
        self.assertFalse(facts['internet_connectable'])
        self.assertFalse(facts['internet_active'])
        self.assertIsNone(facts['apn_matches'])
        self.assertIsNone(facts['data_connected'])
        self.assertEqual(facts['data_service_mode'], 'ON')
        self.assertEqual(facts['data_services_status'], 'OFF')
        self.assertEqual(facts['lte_active_band_mask'], 16)
        checks = {row['id']: row for row in c.network_checks(facts)}
        self.assertEqual(checks['lte']['code'], 'lte_emergency_only')
        self.assertEqual(checks['apn']['code'], 'data_services_off')
        self.assertFalse(c.evaluate(facts)['can_install'])

    def test_negative_observations_block_even_with_stale_connected_true(self):
        cases = ({'network_service': 1}, {'data_services_status': 'OFF'}, {'data_service_mode': 'OFF'})
        cases += tuple({key: False} for key in
                       ('internet_present', 'internet_enabled', 'internet_connectable', 'internet_active'))
        for fields in cases:
            with self.subTest(fields=fields):
                facts = baseline(); facts.update(fields)
                self.assertEqual(c.network_state(facts), 'not_ready')
                self.assertFalse(c.evaluate(facts)['can_install'])
                self.assertFalse(c.evaluate(facts)['can_start'])
                self.assertFalse(c.evaluate(facts)['can_update'])

    def test_enabled_or_active_never_substitute_for_connected_or_apn(self):
        data = b'data_services_status::ON\ninternet:json:{"enabled":true,"active":true,"connectable":true}\n'
        facts = baseline()
        facts.update(self.read_snapshot(data=data, radio=b'power_status::ON\nnetwork_technology:json:["lte"]\n'))
        self.assertIsNone(facts['data_connected'])
        self.assertIsNone(facts['apn_matches'])
        self.assertEqual(c.network_checks(facts)[-1]['code'], 'data_apn_state_unknown')
        self.assertFalse(c.evaluate(facts)['can_install'])

    def test_settings_failure_retains_live_observations_and_cannot_imply_user_off(self):
        facts = self.read_snapshot(settings=None)
        self.assertTrue(facts['data_settings_read_error'])
        self.assertIsNone(facts['data_service_mode'])
        self.assertIsNone(facts['network_read_error'])
        self.assertEqual(facts['data_services_status'], 'OFF')
        self.assertEqual(c.network_checks(facts)[-1]['code'], 'data_services_off')

    def test_valid_connected_snapshot_still_passes_but_inactive_and_missing_differ(self):
        radio = b'power_status::ON\nnetwork_technology:json:["lte"]\nnetwork_service:n:2097408\n'
        data = b'data_services_status::ON\ninternet:json:{"apn":"3gnet","connected":true,"active":true}\n'
        snapshot = self.read_snapshot(data=data, radio=radio)
        facts = baseline()
        facts.update({key: value for key, value in snapshot.items() if key in c.public_network_diagnostics(snapshot)})
        self.assertTrue(c.evaluate(facts)['can_install'])
        for data in (b'', b'internet:json:{"active":false}\n'):
            facts = self.read_snapshot(data=data, radio=radio)
            self.assertEqual(c.network_checks(facts)[-1]['code'], 'data_internet_inactive')

    def test_public_snapshot_bounds_types_and_never_leaks_arbitrary_values(self):
        for bad in (True, -1, 1 << 65, 'private-value', [], {}):
            values = {key: bad for key in c.NETWORK_NUMBERS}
            values.update(data_service_mode='private-value', data_services_status='private-value',
                          raw='private-value', internet_active='private-value')
            public = c.public_network_diagnostics(values)
            self.assertTrue(all(public[key] is None for key in c.NETWORK_NUMBERS))
            self.assertNotIn('private-value', json.dumps(public))
        self.assertIsNone(c.public_network_diagnostics(None)['network_service'])


class ConfigurationDiagnosticTests(unittest.TestCase):
    def observations(self, *, files=False, directory=False, fields=None, read_error=False):
        records = {'cellular_protocol_configuration': b'', 'ims': b'',
                   'status_persistent': b'cdsc_xml::\n'}
        records.update(fields or {})
        def read(path):
            if read_error and path.endswith('/ims'):
                raise OSError('unavailable')
            return records[path.rsplit('/', 1)[-1]]
        with patch.object(c.os.path, 'lexists', return_value=files), \
             patch.object(c.os, 'listdir', return_value=['private-file'] if directory else []), \
             patch.object(native, 'read', side_effect=read), patch.object(native, 'atomic') as write, \
             patch.object(native, 'update_pps') as update:
            result = c.configuration_diagnostics()
            clean = c.pristine_configuration()
            write.assert_not_called(); update.assert_not_called()
        return result, clean

    def test_default_configuration_is_clean(self):
        result, clean = self.observations()
        self.assertTrue(clean)
        self.assertEqual(set(result), set(c.CONFIGURATION_FLAGS))
        self.assertTrue(all(value is True for value in result.values()))

    def test_each_existing_configuration_gate_remains_enforced(self):
        cases = [({'files': True}, 'ims_override_absent'),
                 ({'directory': True}, 'cdsc_directory_empty'),
                 ({'fields': {'cellular_protocol_configuration': b'voice_domain_preference_EUTRAN:n:0\n'}}, 'voice_override_absent'),
                 ({'fields': {'ims': b'IMS_profilesV2:json:[]\n'}}, 'ims_profiles_absent'),
                 ({'fields': {'ims': b'supported_networks:json:[]\n'}}, 'ims_networks_absent'),
                 ({'fields': {'ims': b'IMS_services:json:[]\n'}}, 'ims_services_absent'),
                 ({'fields': {'ims': b'Home_network_domain_name::private.example\n'}}, 'ims_domain_default'),
                 ({'fields': {'status_persistent': b'cdsc_xml::/private/override.xml\n'}}, 'cdsc_selection_default'),
                 ({'fields': {'status_persistent': b''}}, 'cdsc_selection_default')]
        for args, key in cases:
            with self.subTest(key=key, args=args):
                result, clean = self.observations(**args)
                self.assertFalse(clean)
                self.assertFalse(result[key])
                self.assertNotIn('private', json.dumps(result))

    def test_unreadable_configuration_is_unknown_and_blocks_install(self):
        result, clean = self.observations(read_error=True)
        self.assertIsNone(result['ims_profiles_absent'])
        self.assertTrue(result['cdsc_selection_default'])
        self.assertFalse(clean)
        facts = baseline(); facts.update(clean_configuration=clean, configuration_diagnostics=result)
        self.assertFalse(c.evaluate(facts)['can_install'])


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

    def test_root_diagnostic_transfers_only_probe_and_exact_cleanup_inputs(self):
        client = self.client()
        with tempfile.TemporaryDirectory() as folder, patch.object(w, 'private_root', return_value=Path(folder)), \
                patch.object(client, 'remote', return_value='') as remote, \
                patch.object(client, 'process', return_value='') as transfer, \
                patch.object(client, 'execute', return_value={'stage_removed': True}) as cleanup:
            with client.stage(diagnostic='root') as stage:
                pass
            names = [call.args[0][-1].split(stage + '/')[1] for call in transfer.call_args_list]
            self.assertEqual(names, ['root-probe.py', 'profile-request.json', 'stage-cleanup.py'])
            self.assertIn(stage + '/device', remote.call_args.args[0])
            self.assertIn(stage + '/driver', remote.call_args.args[0])
            self.assertEqual(json.loads(shlex.split(cleanup.call_args.args[1])[0]), names)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_tampered_desktop_probe_is_rejected_before_remote_write(self):
        client = self.client()
        for name in ('tools/root_probe.py', 'tools/stage_cleanup.py'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                for entry in ('materials/desktop-diagnostics.json', 'tools/root_probe.py', 'tools/stage_cleanup.py'):
                    target = root / entry
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes((ROOT / entry).read_bytes())
                (root / name).write_text('modified diagnostic')
                with patch.object(w, 'ROOT', root), patch.object(w, 'verify_package'), patch.object(client, 'remote') as remote:
                    with self.assertRaisesRegex(w.WorkflowError, 'package_mismatch'):
                        with client.stage(diagnostic='root'):
                            self.fail('Must reject before yielding')
                    remote.assert_not_called()

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
