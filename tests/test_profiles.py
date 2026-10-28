"""Operator configuration, native gates and device-independent recovery contracts."""
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'device'))
sys.path.insert(0, str(ROOT / 'tools'))
import profiles as p
import compatibility as c
import device_info as d
import install
import native as n
import service as s
import workflow as w
from test_preflight import baseline

INTERNET = b'<ServiceConfiguration><Name>internet</Name><RadioAccessTechnology><APN>cmnet</APN></RadioAccessTechnology></ServiceConfiguration>'
EMERGENCY = b'<ServiceConfiguration><Name>emergency</Name><RadioAccessTechnology><APN>sos</APN></RadioAccessTechnology></ServiceConfiguration>'
ALIAS = b'<ServiceConfigurationAlias><Name>ims</Name><Reference>internet</Reference></ServiceConfigurationAlias>'
STOCK = b'<Carrier xmlns="urn:test:carrier">' + INTERNET + EMERGENCY + ALIAS + b'</Carrier>'


def mobile():
    return p.read_json(str(ROOT / 'profiles/china-mobile.json'))


class ProfileTests(unittest.TestCase):
    def test_all_templates_validate_and_remain_experimental(self):
        for path in (ROOT / 'profiles').glob('*.json'):
            profile = p.validate(p.read_json(str(path)))
            self.assertFalse(p.baseline_parameters(profile))
            self.assertEqual(p.validate(json.loads(p.canonical(profile))), profile)

    def test_untrusted_values_cannot_become_xml_paths_or_commands(self):
        for section, field, value in [('ims', 'apn', 'ims</APN>'), ('ims', 'apn', 'ims\n'),
                ('ims', 'home_domain', 'ims.example.org\n'), ('ims', 'home_domain', 'x;command'),
                ('carrier', 'stock_config', '../../file'), ('carrier', 'stock_sha256', 'abc'),
                ('carrier', 'mcc', '46'), ('carrier', 'mncs', [1]), ('carrier', 'mncs', ['01', '01']),
                ('runtime', 'autostart', 'false'), ('runtime', 'poll_seconds', True),
                ('runtime', 'sim_wait_seconds', 999999), ('ims', 'sms', 1), ('ims', 'ip_family', 'auto')]:
            with self.subTest(field=field, value=value):
                profile = p.default(); profile[section][field] = value
                with self.assertRaises(ValueError):
                    p.validate(profile)

    def test_unknown_options_are_rejected_instead_of_silently_ignored(self):
        profile = p.default(); profile['ims']['pcscf'] = 'example.org'
        with self.assertRaises(ValueError): p.validate(profile)
        with self.assertRaises(ValueError): p.request(allow_experimental='yes')

    def test_identity_uses_actual_sim_mnc_and_never_preset_first_entry(self):
        for mcc, mnc, domain in [('460', '02', 'ims.mnc002.mcc460.3gppnetwork.org'),
                                  ('310', '260', 'ims.mnc260.mcc310.3gppnetwork.org')]:
            self.assertEqual(p.home_domain(mobile(), mcc, mnc), domain)
            identity = mcc + mnc + '0' * (15 - len(mcc + mnc))
            self.assertTrue(p.identity_matches(identity, mcc, mnc))
            self.assertFalse(p.identity_matches(identity, mcc, '99'))

    def test_custom_domain_and_sms_options_reach_runtime_pps(self):
        profile = mobile(); profile['ims'].update(home_domain='ims.example.org', sms=False)
        changes = s.profile_updates(profile, '460', '02')[s.IMS]
        self.assertEqual(changes['Home_network_domain_name'], ':ims.example.org')
        self.assertEqual([item['service'] for item in json.loads(changes['IMS_services'][5:])], ['voice'])

    def test_xml_patch_preserves_data_emergency_and_namespace_bytes(self):
        profile = mobile(); profile['ims'].update(apn='custom.ims', ip_family='IPv6')
        result = p.patch_carrier(STOCK, profile)
        self.assertEqual(result, STOCK.replace(ALIAS, p.ims_section(profile).lstrip()))
        self.assertIn(INTERNET, result); self.assertIn(EMERGENCY, result)
        parsed = p.parse_xml(result)
        ims = next(node for node in parsed.iter('ServiceConfiguration') if node.findtext('Name') == 'ims')
        self.assertEqual(next(ims.iter('Type')).text, 'IPv6')
        self.assertEqual(next(ims.iter('APN')).text, 'custom.ims')

    def test_xml_patch_rejects_missing_or_duplicate_ims(self):
        for stock in (STOCK.replace(ALIAS, b''), STOCK.replace(ALIAS, ALIAS + ALIAS), b'bad xml'):
            with self.assertRaises(Exception): p.patch_carrier(stock, mobile())

    def test_stock_selection_uses_actual_home_carrier_not_default(self):
        home = {'mcc': 460, 'mnc': 2, 'preloadedConfigFile': '/etc/carrier/config/77.xml', 'downloadedConfigFile': ''}
        attrs = {'true_home_carrier': 'json:' + json.dumps(home), 'defaultPreloadedConfigFile': ':/etc/carrier/config/298.xml'}
        with patch.object(n, 'read', side_effect=lambda path: attrs if path.endswith('status_private') else STOCK) as read, \
             patch.object(n, 'attrs', side_effect=lambda value: value), patch.object(p.os.path, 'islink', return_value=False):
            info, changed = p.carrier_template(mobile(), '460', '02')
        self.assertEqual(info['path'], home['preloadedConfigFile'])
        self.assertEqual(read.call_args_list[-1].args[0], info['path'])
        self.assertIn(INTERNET, changed)

    def test_wrong_stock_apn_and_downloaded_override_are_blocked(self):
        home = {'mcc': 460, 'mnc': 1, 'preloadedConfigFile': '/etc/carrier/config/36.xml', 'downloadedConfigFile': ''}
        for downloaded in ('', '/private/custom.xml'):
            home['downloadedConfigFile'] = downloaded
            with patch.object(n, 'read', side_effect=lambda path: {'true_home_carrier': 'json:' + json.dumps(home)} if path.endswith('status_private') else STOCK), \
                 patch.object(n, 'attrs', side_effect=lambda value: value):
                with self.assertRaises(ValueError): p.carrier_template(p.default(), '460', '01')

    def test_installed_profile_hash_binds_configuration_and_consent(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); req = p.request(mobile(), True)
            (base / 'carrier-profile.json').write_bytes(p.canonical(req))
            (base / 'installation.json').write_text(json.dumps({'carrier_profile_sha256': p.fingerprint(req)}))
            self.assertEqual(p.installed_request(folder), req)
            req['allow_experimental'] = False
            (base / 'carrier-profile.json').write_bytes(p.canonical(req))
            with self.assertRaises(ValueError): p.installed_request(folder)

    def test_profile_edit_blocks_start_but_allows_stopped_update(self):
        facts = baseline()
        facts['installation'] = {'state': 'stopped', 'current_profile': True,
                                 'carrier_profile_sha256': p.fingerprint(p.request())}
        profile = p.default(); profile['runtime']['poll_seconds'] = 5
        report = c.evaluate(facts, profile)
        self.assertFalse(report['can_start']); self.assertTrue(report['can_update'])

    def test_profile_label_cannot_claim_hardware_validation(self):
        profile = mobile(); profile['id'] = p.DEFAULT['id']; profile['label'] = p.DEFAULT['label']
        facts = baseline(); facts['mnc'] = '00'
        report = c.evaluate(facts, profile, True)
        self.assertEqual(report['hardware_validation'], 'not_hardware_validated')


class DeviceTests(unittest.TestCase):
    def test_classic_and_other_q10_variants_require_opt_in_passport_stays_paused(self):
        for model, variant, family in [('Q20', 'SQC100-1', 'classic'), ('Classic', 'SQC100-2', 'classic'),
                                      ('Q30', 'SQW100-1', 'passport'), ('Passport', 'SQW100-3', 'passport'),
                                      ('Q10', 'SQN100-1', 'q10')]:
            with self.subTest(model=model):
                facts = baseline(); facts.update(model=model, variant=variant)
                self.assertEqual(d.identify(facts)['family'], family)
                self.assertFalse(c.evaluate(facts)['can_install'])
                report = c.evaluate(facts, allow_experimental=True)
                self.assertEqual(report['outcome'], 'needs_adaptation' if family == 'passport' else 'experimental')
                self.assertEqual(report['can_install'], family != 'passport')
                self.assertEqual(report['hardware_validation'], 'not_hardware_validated')

    def test_experimental_never_bypasses_native_os_abi_sim_or_carrier_guards(self):
        for change in ({'os_version': '10.3.3.2205'}, {'arm32_qnx': False}, {'root_ready': False},
                       {'native_hashes': {}}, {'sim_type': 18}, {'mnc': '99'}, {'carrier_template_ready': False}):
            facts = baseline(); facts.update(model='Passport', variant='SQW100-1'); facts.update(change)
            self.assertFalse(c.evaluate(facts, allow_experimental=True)['can_install'])
        for path in n.STOCK_HASHES:
            facts = baseline(); facts.update(model='Classic', variant='SQC100-1')
            facts['native_hashes'][path] = False
            self.assertFalse(d.engine_matches(facts))
            self.assertFalse(c.evaluate(facts, allow_experimental=True)['can_install'])

    def test_conflicting_identity_and_unknown_variant_are_blocked(self):
        for model, variant in [('Q10', 'SQC100-1'), ('Q30', 'SQC100-1'), ('Classic', 'unknown'), ('Z10', 'STL100-1')]:
            facts = baseline(); facts.update(model=model, variant=variant)
            self.assertFalse(d.identify(facts)['recognized'])
            self.assertFalse(c.evaluate(facts, allow_experimental=True)['can_install'])

    def test_variant_identifies_family_if_friendly_name_is_missing(self):
        self.assertEqual(d.identify({'variant': 'SQW100-3'})['family'], 'passport')

    def test_mobile_template_matches_selected_mnc_but_isim_is_still_unsupported(self):
        for mnc in ('00', '02', '07'):
            facts = baseline(); facts['mnc'] = mnc
            self.assertTrue(c.evaluate(facts, mobile(), True)['can_install'])
            facts['sim_type'] = 18
            self.assertFalse(c.evaluate(facts, mobile(), True)['can_install'])


class RuntimeTests(unittest.TestCase):
    def client(self, profile=None, experimental=False):
        with patch.object(w.shutil, 'which', return_value='ssh'):
            return w.Client(profile=profile, allow_experimental=experimental)

    def test_remote_preflight_is_bound_to_request_not_only_profile_name(self):
        client = self.client(mobile(), True)
        with patch.object(client, 'execute', return_value={'schema': 2, 'profile_sha256': p.fingerprint(p.request())}):
            with self.assertRaisesRegex(w.WorkflowError, 'invalid_device_response'): client.inspect_stage('/stage')

    def test_start_does_not_enable_autostart_when_profile_disables_it(self):
        profile = p.default(); profile['runtime']['autostart'] = False
        client = self.client(profile)
        facts = baseline(); facts['installation'] = {'state': 'stopped', 'current_profile': True,
                                                    'carrier_profile_sha256': p.fingerprint(client.request)}
        with patch.object(client, 'preflight', return_value=c.evaluate(facts, profile)), \
             patch.object(client, 'execute') as execute, patch.object(client, 'service') as service, \
             patch.object(client, 'wait_registration', return_value={'registration': 'pending'}):
            client.action('start')
            execute.assert_not_called(); service.assert_called_once_with('start')

    def test_poll_interval_and_registration_timeout_are_used(self):
        profile = p.default(); profile['runtime'].update(registration_wait_seconds=60, poll_seconds=7)
        client = self.client(profile)
        with patch.object(w.time, 'monotonic', side_effect=[0, 1, 61]), patch.object(w.time, 'sleep') as sleep, \
             patch.object(client, 'service', return_value={'phase': 'registering'}):
            self.assertEqual(client.wait_registration()['registration'], 'pending')
            sleep.assert_called_once_with(7)

    def test_sim_wait_and_poll_are_used(self):
        profile = p.default(); profile['runtime'].update(sim_wait_seconds=60, poll_seconds=7)
        facts = baseline(); facts['sim_state'] = 'ABSENT'
        with patch.object(s, 'ACTIVE_PROFILE', profile), patch.object(c, 'read_network', return_value=facts), \
             patch.object(s, 'status'), patch.object(s, 'stopping', return_value=False), \
             patch.object(s.time, 'time', side_effect=[0, 1, 61]), patch.object(s.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, '60 seconds'): s.wait_for_network()
            sleep.assert_called_once_with(7)

    def test_installer_persists_selected_profile_and_autostart_setting(self):
        stage = '/var/rootdata/q10_volte_stage_test'
        data = {stage + '/' + name: (ROOT / name).read_bytes() for name in w.FILES}
        data[stage + '/payload-manifest.json'] = (ROOT / w.MANIFEST).read_bytes()
        profile = mobile(); profile['runtime']['autostart'] = False
        req = p.request(profile, True)
        def atomic(path, content, *args): data[path] = content
        with patch.object(n, 'read', side_effect=lambda path: data[path]), patch.object(n, 'atomic', side_effect=atomic), \
             patch.object(p, 'load_request', return_value=req), patch.object(c, 'require') as require, \
             patch.object(n, 'verify_stock'), patch.object(n, 'ims_pids', return_value=[]), \
             patch.object(n, 'voice_policy', return_value=0), patch.object(n, 'crypto_policy', return_value={'swcr_id': -1, 'crypto_support': 0}), \
             patch.object(n, 'active_vpn_sessions', return_value=[]), patch.object(n, 'command'), \
             patch.object(install.os.path, 'realpath', return_value=stage), patch.object(install.os.path, 'exists', return_value=False), \
             patch.object(install.os.path, 'isfile', return_value=False), patch.object(install.os.path, 'isdir', return_value=True), \
             patch.object(install.os.path, 'islink', return_value=False), patch.object(install.os, 'mkdir'), \
             patch.object(install.os, 'chmod'), patch.object(install.os, 'unlink'), patch('sys.stdout', new_callable=io.StringIO):
            install.install(stage)
        require.assert_called_once_with('install', req['profile'], True)
        self.assertEqual(json.loads(data[install.BASE + '/carrier-profile.json']), req)
        receipt = json.loads(data[install.BASE + '/installation.json'])
        self.assertEqual(receipt['carrier_profile_sha256'], p.fingerprint(req))
        self.assertNotIn(install.BASE + '/enabled', data)

    def test_restore_uses_journal_values_even_after_active_profile_changes(self):
        profile = mobile(); profile['ims'].update(home_domain='ims.custom.example', sms=False)
        applied = s.profile_updates(profile, '460', '02')
        before = {path: {key: None for key in fields} for path, fields in applied.items()}
        before[s.CDSC]['cdsc_xml'] = ':'
        records = copy.deepcopy(applied)
        journal = {'pps_applied': applied, 'pps_before': before, 'original_voice_policy': 0, 'managed_files': {}}
        def update(path, fields): records[path].update(fields)
        with patch.object(s, 'j', journal), patch.object(s, 'ACTIVE_PROFILE', p.default()), \
             patch.object(s, 'stop_native'), patch.object(s, 'remove_owned'), patch.object(s, 'remove_platform'), \
             patch.object(s, 'save_journal'), patch.object(s, 'status'), patch.object(s.time, 'sleep'), \
             patch.object(n, 'read', side_effect=lambda path: records[path]), patch.object(n, 'attrs', side_effect=lambda value: value), \
             patch.object(n, 'update_pps', side_effect=update), patch.object(n, 'voice_policy', return_value=0), \
             patch.object(n, 'crypto_policy', return_value={'swcr_id': -1, 'crypto_support': 0}):
            s.restore()
        self.assertEqual(records, before)
        self.assertTrue(journal['restore_completed'])


if __name__ == '__main__':
    unittest.main()
