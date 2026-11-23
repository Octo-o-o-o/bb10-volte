import hashlib
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'device'))
sys.path.insert(0, str(ROOT / 'tools'))

import carrier_policy as policy
import compatibility as compat
import kt_isim_trial
import native as n
import profiles
import service
import unified_install


STOCK_0_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?>\r\n'
    b'<CarrierConfiguration xmlns="http://www.rim.com/CarrierConfig/2012-01">\r\n'
    b'  <CarrierDataConfiguration>\r\n'
    b'    <Name>BlackBerry Default</Name>\r\n'
    b'    <CarrierID>0</CarrierID>\r\n'
    b'    <ServiceConfiguration>\r\n'
    b'      <Name>internet</Name>\r\n'
    b'      <RadioAccessTechnology>\r\n'
    b'        <APN></APN>\r\n'
    b'      </RadioAccessTechnology>\r\n'
    b'    </ServiceConfiguration>\r\n'
    b'    <ServiceConfigurationAlias>\r\n'
    b'      <Name>ims</Name>\r\n'
    b'      <Reference>internet</Reference>\r\n'
    b'    </ServiceConfigurationAlias>\r\n'
    b'  </CarrierDataConfiguration>\r\n'
    b'</CarrierConfiguration>\r\n'
)


class ExpIsimKtTrialTests(unittest.TestCase):
    def test_default_kt_trial_json_is_valid(self):
        cfg = kt_isim_trial.load_local_config(ROOT / 'kt-45008-trial.json')
        self.assertTrue(cfg['enabled'])
        self.assertEqual(cfg['mcc'], '450')
        self.assertEqual(cfg['mncs'], ['08'])
        self.assertTrue(cfg['allow_isim'])
        self.assertTrue(cfg['allow_stock_default_xml'])
        self.assertEqual(cfg['data_apns'], ['lte.ktfwing.com'])
        self.assertEqual(cfg['ims']['apn'], 'ims.ktfwing.com')
        self.assertEqual(cfg['ims']['ip_family'], 'IPv4v6')

    def test_isim_remains_blocked_without_opt_in(self):
        facts = {'variant': 'SQC100-5', 'os_version': '10.3.3.3216', 'board_type': 'CLASSICVZWNC'}
        card = {'state': 'READY', 'kind': 18, 'mcc': '450', 'mnc': '08', 'imsi': '45008' + '0' * 10}
        with patch.object(profiles, 'load_exp_trial', return_value=None):
            with self.assertRaisesRegex(ValueError, 'sim_route_unsupported'):
                policy.select(facts, card)

    def test_isim_allowed_for_matching_opt_in_plmn_only(self):
        cfg = kt_isim_trial.load_local_config(ROOT / 'kt-45008-trial.json')
        facts = {'variant': 'SQC100-5', 'os_version': '10.3.3.3216', 'board_type': 'CLASSICVZWNC'}
        kt_card = {'state': 'READY', 'kind': 18, 'mcc': '450', 'mnc': '08', 'imsi': '45008' + '0' * 10}
        other_card = {'state': 'READY', 'kind': 18, 'mcc': '460', 'mnc': '01', 'imsi': '46001' + '0' * 10}
        no_usim_card = {'state': 'READY', 'kind': 16, 'mcc': '450', 'mnc': '08', 'imsi': '45008' + '0' * 10}
        with patch.object(profiles, 'load_exp_trial', return_value=cfg):
            selected = policy.select(facts, kt_card)
            self.assertEqual(selected['operator'], 'other')
            prof = selected['request']['profile']
            self.assertEqual(prof['id'], 'exp-trial-45008')
            self.assertEqual(prof['ims']['apn'], 'ims.ktfwing.com')
            self.assertFalse(prof['runtime']['autostart'])
            self.assertTrue(prof['experimental']['allow_isim'])
            self.assertTrue(prof['experimental']['allow_stock_default_xml'])
            with self.assertRaisesRegex(ValueError, 'sim_route_unsupported'):
                policy.select(facts, other_card)
            with self.assertRaisesRegex(ValueError, 'sim_route_unsupported'):
                policy.select(facts, no_usim_card)

    def test_stock_0_xml_patched_for_kt_and_rejects_tampered_hash(self):
        cfg = kt_isim_trial.load_local_config(ROOT / 'kt-45008-trial.json')
        prof = profiles.exp_trial_profile('450', '08', trial=cfg)
        sha = hashlib.sha256(STOCK_0_XML).hexdigest()
        with patch.object(profiles, 'STOCK_DEFAULT_CONFIG_SHA256', sha), \
             patch.object(profiles, 'preloaded_carrier_config', return_value='/etc/carrier/config/0.xml'), \
             patch.object(profiles.os.path, 'islink', return_value=False), \
             patch.object(n, 'read', return_value=STOCK_0_XML):
            info, patched = profiles.carrier_template(prof, '450', '08')
            self.assertEqual(info['path'], '/etc/carrier/config/0.xml')
            self.assertTrue(info['stock_default_xml_used'])
            root = profiles.parse_xml(patched)
            svcs = {node.findtext('Name'): node for node in root.iter('ServiceConfiguration')}
            self.assertEqual(svcs['internet'].find('.//APN').text, 'lte.ktfwing.com')
            self.assertEqual(svcs['ims'].find('.//APN').text, 'ims.ktfwing.com')
            self.assertEqual(svcs['ims'].find('.//Type').text, 'IPv4v6')

        # Parameter tweak: switching ims.apn to 'ims' and ip_family to 'IPv6' works without code edits
        cfg2 = dict(cfg, ims=dict(cfg['ims'], apn='ims', ip_family='IPv6', home_domain='ims.kt.com'))
        prof2 = profiles.exp_trial_profile('450', '08', trial=cfg2)
        with patch.object(profiles, 'STOCK_DEFAULT_CONFIG_SHA256', sha), \
             patch.object(profiles, 'preloaded_carrier_config', return_value='/etc/carrier/config/0.xml'), \
             patch.object(profiles.os.path, 'islink', return_value=False), \
             patch.object(n, 'read', return_value=STOCK_0_XML):
            _, patched2 = profiles.carrier_template(prof2, '450', '08')
            root2 = profiles.parse_xml(patched2)
            svcs2 = {node.findtext('Name'): node for node in root2.iter('ServiceConfiguration')}
            self.assertEqual(svcs2['ims'].find('.//APN').text, 'ims')
            self.assertEqual(svcs2['ims'].find('.//Type').text, 'IPv6')
            self.assertEqual(profiles.home_domain(prof2, '450', '08'), 'ims.kt.com')

        # Tampered 0.xml hash must be rejected
        with patch.object(profiles, 'preloaded_carrier_config', return_value='/etc/carrier/config/0.xml'), \
             patch.object(profiles.os.path, 'islink', return_value=False), \
             patch.object(n, 'read', return_value=STOCK_0_XML):
            with self.assertRaisesRegex(ValueError, 'hash|changed'):
                profiles.carrier_template(prof, '450', '08')

    def test_compatibility_and_service_respect_allow_isim(self):
        cfg = kt_isim_trial.load_local_config(ROOT / 'kt-45008-trial.json')
        prof = profiles.exp_trial_profile('450', '08', trial=cfg)
        snapshot = {
            'sim_state': 'READY', 'sim_read_error': False, 'mcc': '450', 'mnc': '08',
            'sim_type': 18, 'identity_matches': True, 'radio_on': True, 'lte': True,
            'network_service': 0x0020040a, 'apn_matches': True, 'data_connected': True,
            'network_read_error': False, 'data_services_status': 'ON', 'data_service_mode': 'ON',
            'internet_present': True, 'internet_enabled': True, 'internet_connectable': True,
            'internet_active': True,
        }
        checks = {c['id']: c for c in compat.network_checks(snapshot, prof)}
        self.assertEqual(checks['sim_route'], {'id': 'sim_route', 'status': 'pass', 'code': 'usim_with_isim_experimental'})
        self.assertEqual(compat.network_state(snapshot, prof), 'ready')

        # Without experimental opt-in, ISIM is still adapt/needs_adaptation
        normal = profiles.default()
        normal['carrier'].update(mcc='450', mncs=['08'], data_apns=['lte.ktfwing.com'])
        checks_default = {c['id']: c for c in compat.network_checks(snapshot, normal)}
        self.assertEqual(checks_default['sim_route']['status'], 'adapt')

    def test_redaction_strips_isim_identifiers_but_keeps_status(self):
        fake_imsi = '45008' + '9' * 10
        fake_num = '010' + '8' * 8
        line = ('bb.ims:12 ISIM is present set UICCRequired to true '
                'IMPI:' + fake_imsi + '@ims.kt.com sip:' + fake_num + '@ims.kt.com SIP/2.0 403 Forbidden')
        redacted = service.redact_ims_event_line(line)
        self.assertIn('UICCRequired to true', redacted)
        self.assertIn('SIP/2.0 403 Forbidden', redacted)
        self.assertNotIn(fake_imsi, redacted)
        self.assertNotIn(fake_num, redacted)

    def test_load_exp_trial_from_disk_and_disabled_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'exp.json'
            cfg = kt_isim_trial.load_local_config(ROOT / 'kt-45008-trial.json')
            path.write_text(json.dumps(cfg), encoding='utf-8')
            self.assertIsNotNone(profiles.load_exp_trial(str(path)))
            cfg['enabled'] = False
            path.write_text(json.dumps(cfg), encoding='utf-8')
            self.assertIsNone(profiles.load_exp_trial(str(path)))

    def test_probe_exposes_isim_and_carrier_summary_even_when_unsupported(self):
        def fake_read(path):
            if path == '/pps/services/cellular/uicc/card0/status_isim':
                return b'isim_status::READY\nisim_services:json:{"sm_over_ip":true,"pcscf_discovery":true}\nimpi::secret\n'
            if path == '/pps/services/carriermanager/status_private':
                return b'true_home_carrier:json:{"mcc":450,"mnc":8,"preloadedConfigFile":"/etc/carrier/config/0.xml","downloadedConfigFile":""}\n'
            raise IOError('unexpected ' + path)

        with patch.object(n, 'read', side_effect=fake_read):
            isim = unified_install.read_isim_public_status()
            carrier = unified_install.read_carrier_config_summary()
        self.assertEqual(isim['isim_status'], 'READY')
        self.assertEqual(isim['isim_services'], {'sm_over_ip': True, 'pcscf_discovery': True})
        self.assertNotIn('impi', isim)
        self.assertEqual(carrier['preloaded_carrier_config'], '0.xml')
        self.assertFalse(carrier['downloaded_carrier_config_present'])


if __name__ == '__main__':
    unittest.main()
