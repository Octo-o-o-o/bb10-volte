"""Comprehensive regression and security tests for r59 overseas support, LTE band
diagnostics, and clean-room P-CSCF host route sync.
"""
import contextlib
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'device'))
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'mobile/runtime'))

import carrier_policy as policy
import compatibility as compat
import feedback
import native as n
import overseas_carrier
import overseas_carrier_gui
import profiles
import service as s
import unified_dca
import unified_install
import unified_service as u
import worker as mobile_worker
import workflow

STOCK_0_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?>\r\n'
    b'<CarrierConfiguration xmlns="http://www.rim.com/CarrierConfig/2012-01">\r\n'
    b'  <CarrierDataConfiguration>\r\n'
    b'    <Name>BlackBerry Default</Name>\r\n'
    b'    <CarrierID>0</CarrierID>\r\n'
    b'    <ServiceConfiguration>\r\n'
    b'      <Name>internet</Name>\r\n'
    b'      <RadioAccessTechnology><APN></APN></RadioAccessTechnology>\r\n'
    b'    </ServiceConfiguration>\r\n'
    b'    <ServiceConfigurationAlias>\r\n'
    b'      <Name>ims</Name>\r\n'
    b'      <Reference>internet</Reference>\r\n'
    b'    </ServiceConfigurationAlias>\r\n'
    b'  </CarrierDataConfiguration>\r\n'
    b'</CarrierConfiguration>\r\n'
)

NO_IMS_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<CarrierConfiguration xmlns="http://www.rim.com/CarrierConfig/2012-01">\n'
    b'  <CarrierDataConfiguration version="1">\n'
    b'    <ServiceConfiguration>\n'
    b'      <Name>internet</Name>\n'
    b'      <RadioAccessTechnology><APN>internet.example</APN></RadioAccessTechnology>\n'
    b'    </ServiceConfiguration>\n'
    b'  </CarrierDataConfiguration>\n'
    b'</CarrierConfiguration>\n'
)


class OverseasCatalogTests(unittest.TestCase):
    def test_offline_apache2_catalog_integrity_and_key_carriers(self):
        self.assertTrue((ROOT / 'licenses/APACHE-2.0.txt').is_file())
        notice = (ROOT / 'NOTICE.md').read_text(encoding='utf-8')
        self.assertIn('Apache License 2.0', notice)
        self.assertIn('overseas-carriers.json', notice)
        entries = overseas_carrier.load_catalog()
        self.assertEqual(len(entries), 297)
        self.assertFalse(any(e['mcc'] == '460' for e in entries))
        self.assertTrue(all(e.get('bb10_status') == 'untested' for e in entries))
        # Verify deep-copy isolation of cached catalog
        entries[0]['name'] = 'MUTATED'
        self.assertNotEqual(overseas_carrier.load_catalog()[0]['name'], 'MUTATED')
        # Verify Tier-1 MNO ranking fixes and zero lab/reserved junk
        self.assertEqual(overseas_carrier.lookup_plmn_code('311-480')['name'], 'Verizon Wireless')
        self.assertEqual(overseas_carrier.lookup_plmn_code('440-10')['name'], 'NTT DOCOMO')
        self.assertIsNone(overseas_carrier.lookup_plmn_code('001-01'))
        for plmn in ('450-08', '450-05', '440-10', '440-20', '302-490', '310-260', '262-01', '260-03', '454-00', '466-92'):
            found = overseas_carrier.lookup_plmn_code(plmn)
            self.assertIsNotNone(found, plmn)
        sb = overseas_carrier.lookup_plmn_code('440-20')
        self.assertEqual(sb['ip_family'], 'IPv6')
        cfg = overseas_carrier.preset_to_trial_config(sb, allow_isim=True, observed_apn='plus.4g')
        self.assertEqual(cfg['schema'], 2)
        self.assertIn('auto', cfg['data_apns'])
        self.assertIn('plus.4g', cfg['data_apns'])
        self.assertEqual(cfg['ims']['ip_family'], 'IPv6')


class DeviceEngineOverseasTests(unittest.TestCase):
    def test_mainland_china_xml_and_pps_remain_unchanged(self):
        china = profiles.default()
        sec = profiles.ims_section(china)
        self.assertIn(b'<AlwaysOn>true</AlwaysOn>', sec)
        self.assertNotIn(b'DisableDAD', sec)
        self.assertNotIn(b'RequestSignallingBearerViaPCO', sec)
        updates = s.profile_updates(china, '460', '01')
        self.assertEqual(set(updates.keys()), {s.VOICE, s.IMS, s.CDSC})
        self.assertNotIn('SilentRedial', updates[s.IMS])
        self.assertNotIn('SIP_Timer_CSFB', updates[s.IMS])

    def test_schema2_multi_carrier_and_optional_ims_ir92_pco_dad(self):
        cfg = {
            'schema': 2,
            'enabled': True,
            'carriers': [
                {
                    'label': 'Freedom CA',
                    'mcc': '302', 'mncs': ['490'],
                    'allow_isim': True, 'allow_stock_default_xml': True,
                    'data_apns': ['auto', 'internet.freedommobile.ca'],
                    'ue_usage': 'data_centric',
                    'ims': {
                        'apn': 'ims', 'ip_family': 'IPv4v6', 'home_domain': 'auto', 'sms': True,
                        'always_on': False, 'request_signalling_bearer_via_pco': True, 'disable_dad': True,
                        'ir92': {'UsePreconditions': 0, 'SMS_Format': '3GPP',
                                 'amr_modeset_list': '0,2,4,7', 'amrwb_modeset_list': '0,1,2'},
                        'ims_pps': {'SilentRedial': False, 'SIP_Timer_CSFB': 6,
                                    'IPsec': True, 'SIP_transport': 'UDP', 'RegExpiration': 3600},
                    },
                },
                {
                    'mcc': '440', 'mncs': ['20'],
                    'allow_isim': False, 'allow_stock_default_xml': True,
                    'data_apns': ['plus.4g', 'a.first.apn'],
                    'ims': {'apn': 'ims', 'ip_family': 'IPv6', 'home_domain': 'auto', 'sms': True},
                },
            ],
        }
        validated = profiles.validate_exp_trial(cfg)
        self.assertEqual(profiles.exp_trial_summary(validated)['plmns'], ['302-490', '440-20'])
        prof = profiles.exp_trial_profile('302', '490', trial=validated)
        self.assertEqual(prof['experimental']['ue_usage'], 'data_centric')
        # Explicit APN priority order must be preserved for experimental profiles
        prof_sb = profiles.exp_trial_profile('440', '20', trial=validated)
        self.assertEqual(prof_sb['carrier']['data_apns'], ['plus.4g', 'a.first.apn'])
        # 460-15 must remain blocked from overseas overrides
        with self.assertRaises(ValueError):
            profiles.validate_exp_trial({'schema': 2, 'enabled': True, 'mcc': '460', 'mncs': ['15'], 'data_apns': ['cbnet']})
        # Out-of-range SIP_Timer_CSFB (>120 seconds) must be rejected
        with self.assertRaises(ValueError):
            profiles.validate_exp_trial({
                'schema': 2, 'enabled': True, 'mcc': '302', 'mncs': ['490'], 'data_apns': ['auto'],
                'ims': {'apn': 'ims', 'ims_pps': {'SIP_Timer_CSFB': 5000}},
            })
        sec = profiles.ims_section(prof)
        self.assertIn(b'<AlwaysOn>false</AlwaysOn>', sec)
        self.assertIn(b'<DisableDAD>true</DisableDAD>', sec)
        self.assertIn(b'<RequestSignallingBearerViaPCO>true</RequestSignallingBearerViaPCO>', sec)
        updates = s.profile_updates(prof, '302', '490')
        self.assertIn(s.IR92, updates)
        self.assertEqual(updates[s.IR92]['UsePreconditions'], 'b:false')
        self.assertEqual(updates[s.IR92]['SMS_Format'], ':3GPP')
        self.assertEqual(updates[s.IR92]['amr_modeset_list'], ':0,2,4,7')
        self.assertEqual(updates[s.IR92]['amrwb_modeset_list'], ':0,1,2')
        self.assertEqual(updates[s.IMS]['SilentRedial'], 'b:false')
        self.assertEqual(updates[s.IMS]['SIP_Timer_CSFB'], 'n:6')
        self.assertEqual(updates[s.IMS]['IPsec'], 'b:true')
        self.assertEqual(updates[s.IMS]['SIP_transport'], ':UDP')
        self.assertEqual(updates[s.IMS]['RegExpiration'], 'n:3600')

        # patch_carrier handles 0 existing IMS blocks + tag attributes
        patched = profiles.patch_carrier(NO_IMS_XML, prof)
        root = profiles.parse_xml(patched)
        names = [node.findtext('Name') for node in root.iter('ServiceConfiguration')]
        self.assertEqual(names, ['internet', 'ims'])
        self.assertIn(b'<CarrierDataConfiguration version="1">', patched)

    def test_non_ims_cdsc_overlay_allowed_only_for_overseas_profile(self):
        non_ims_overlay = (
            b'{"CDSCOverlayVersion":3,"CarrierDataConfiguration":'
            b'{"ServiceConfiguration":[{"Name":"internet","APN":"lte.ktfwing.com"}]}}'
        )
        ims_overlay = (
            b'{"CDSCOverlayVersion":3,"CarrierDataConfiguration":'
            b'{"ServiceConfiguration":[{"Name":"ims","APN":"ims"}]}}'
        )
        kt_prof = profiles.exp_trial_profile('450', '08', trial=overseas_carrier.build_trial_config(
            '450', ['08'], ['lte.ktfwing.com'], allow_isim=True, allow_stock_default_xml=True))
        with tempfile.TemporaryDirectory() as tmp:
            p0 = Path(tmp) / '0.json'
            p0.write_bytes(non_ims_overlay)
            with patch.object(s, 'CDSC_OVERLAYS', tmp):
                # Mainland China default MUST still reject 0.json / non-empty overlay
                with patch.object(s, 'ACTIVE_PROFILE', profiles.default()):
                    self.assertFalse(s.known_empty_cdsc_overlay('0.json'))
                # Overseas profile accepts non-IMS v3 0.json overlay without modifying it
                with patch.object(s, 'ACTIVE_PROFILE', kt_prof):
                    self.assertTrue(s.known_empty_cdsc_overlay('0.json'))
                    p0.write_bytes(ims_overlay)
                    self.assertFalse(s.known_empty_cdsc_overlay('0.json'))

    def test_lte_bands_disabled_strict_non_false_positive_diagnostics(self):
        # True ONLY when radio is ON, LTE is False, and LTE capability mask itself is 0
        self.assertTrue(compat.lte_bands_disabled({
            'radio_on': True, 'lte': False, 'lte_band_capability_mask': 0, 'lte_active_band_mask': 0,
        }))
        # Non-zero capability with active_band_mask == 0 is normal on 3G/2G/searching -> MUST be False!
        self.assertFalse(compat.lte_bands_disabled({
            'radio_on': True, 'lte': False, 'lte_band_capability_mask': 0x10045, 'lte_active_band_mask': 0,
        }))
        self.assertFalse(compat.lte_bands_disabled({
            'radio_on': False, 'lte': False, 'lte_band_capability_mask': 0, 'lte_active_band_mask': 0,
        }))
        self.assertFalse(compat.lte_bands_disabled({
            'radio_on': True, 'lte': True, 'lte_band_capability_mask': 0, 'lte_active_band_mask': 0,
        }))
        self.assertFalse(compat.lte_bands_disabled({
            'radio_on': True, 'lte': False, 'lte_band_capability_mask': 0x10045, 'lte_active_band_mask': 0x4,
        }))
        snap = {
            'sim_state': 'READY', 'sim_read_error': False, 'mcc': '460', 'mnc': '01',
            'sim_type': 2, 'identity_matches': True, 'radio_on': True, 'lte': False,
            'lte_band_capability_mask': 0, 'lte_active_band_mask': 0, 'lte_bands_disabled': True,
            'apn_matches': False, 'data_connected': False, 'network_read_error': False,
        }
        checks = {c['id']: c for c in compat.network_checks(snap, profiles.default())}
        self.assertEqual(checks['lte'], {'id': 'lte', 'status': 'wait', 'code': 'lte_bands_disabled'})

    def test_overseas_ue_usage_opt_in_in_unified_dca(self):
        base_selection = {
            'family': 'classic', 'operator': 'other', 'sim_sha256': 'a' * 64,
            'request': profiles.request(profiles.exp_trial_profile(
                '302', '490',
                trial=overseas_carrier.build_trial_config('302', ['490'], ['auto'], ue_usage='data_centric')), True),
        }
        with patch.object(unified_dca, 'wait_policy_idle'), \
             patch.object(unified_dca, 'restore_network_selection'), \
             patch.object(unified_dca, 'configured_network_lock', return_value=None), \
             patch.object(unified_dca, 'ensure_lte_mode'), \
             patch.object(unified_dca, 'set_usage', return_value={'boot': ['b0']}) as mock_set, \
             patch.object(unified_dca.n, 'voice_policy', return_value=3), \
             patch.object(unified_dca.s, 'boot_token', return_value=['b1']):
            self.assertTrue(unified_dca.prepare(base_selection))
            mock_set.assert_called_once_with(1, base_selection)

        # Default ue_usage='auto' selects 0 (voice_centric / stock unchanged)
        auto_selection = copy.deepcopy(base_selection)
        auto_selection['request']['profile']['experimental']['ue_usage'] = 'auto'
        with patch.object(unified_dca, 'wait_policy_idle'), \
             patch.object(unified_dca, 'restore_network_selection'), \
             patch.object(unified_dca, 'configured_network_lock', return_value=None), \
             patch.object(unified_dca, 'ensure_lte_mode'), \
             patch.object(unified_dca, 'set_usage', return_value={'boot': ['b0']}) as mock_set, \
             patch.object(unified_dca.s, 'boot_token', return_value=['b1']):
            self.assertTrue(unified_dca.prepare(auto_selection))
            mock_set.assert_called_once_with(0, auto_selection)


class PcscfRouteSyncAndRedactionTests(unittest.TestCase):
    def test_compressed_ipv6_redaction_in_service_and_feedback(self):
        uid = 'c81347c0-d9f4-11f1-ac01-001122334455'
        sample = (
            'bb.cfgmgr:123 SMS_Format::3GPP vpn_login response: uid= ' + uid +
            ' pcscf 2408:8140:2001::ff:f050 gw 2001:db8:: alt fe80::1%msm0'
            ' bracket [2001:db8::9]:5060 lo ::1 v4 10.20.30.40:5060 SIP/2.0 200 OK'
        )
        red = s.redact_ims_event_line(sample)
        self.assertIn('vpn_login response: uid= ' + uid, red)
        self.assertIn('SIP/2.0 200 OK', red)
        self.assertIn('SMS_Format::3GPP', red)
        for secret in ('2408:8140:2001::ff:f050', '2001:db8::', 'fe80::1', '2001:db8::9', '::1', '10.20.30.40'):
            self.assertNotIn(secret, red)
        scrubbed = feedback.scrub('err at 2408:8140:2001::ff:f050 and [2001:db8::1]:5060 and fe80::1%msm0')
        for secret in ('2408:8140', '2001:db8', 'fe80::1'):
            self.assertNotIn(secret, scrubbed)

    def test_route_ip_validation_rejects_unsafe_and_usb_addresses(self):
        for bad in ('0.0.0.1', '127.0.0.1', '169.254.0.1', '169.254.0.2', '224.0.0.1',
                    '255.255.255.255', '::', '::1', 'fe80::1', 'ff02::1', '::ffff:10.0.0.1',
                    'fe80::1%msm0', '10.0.0.1/24', 'not-an-ip', ''):
            self.assertIsNone(s._validate_route_ip(bad), bad)
        self.assertEqual(s._validate_route_ip('10.20.30.40'), ('ipv4', '10.20.30.40'))
        self.assertEqual(s._validate_route_ip('2001:db8::'), ('ipv6', '2001:db8::'))
        self.assertEqual(s._validate_route_ip('2408:8140:2001::ff:f050'), ('ipv6', '2408:8140:2001::ff:f050'))

    def test_pcscf_route_sync_add_delete_stale_sweep_and_cleanup_without_ip_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / 'state'
            net_dir = Path(tmp) / 'net'
            state_dir.mkdir()
            net_dir.mkdir()
            log_file = state_dir / 'native.log'
            journal_file = state_dir / 'journal.json'
            fake_route = Path(tmp) / 'route'
            fake_route.write_bytes(b'#!/bin/sh\n')
            # Real BB10 native.log lines including trailing "::" IPv6 + spoofed USB gateway + unowned delete
            log_file.write_text(
                'route: writing to routing socket: Permission denied\n'
                'delete host 2408:8140:2001::ff:f050: Permission denied\n'
                'add host 2408:8140:2001::ff:f050: gateway 2408:8507:8520:bee::1: Permission denied\n'
                'add host 2001:db8::: gateway 2408:8507:8520:bee::1: Permission denied\n'
                'add host 10.99.0.5: gateway 169.254.0.2: Permission denied\n'
                'add host 10.99.0.6: gateway 192.168.1.1: Permission denied\n'
                'add host 10.99.0.7: gateway 10.99.0.1: Permission denied\n',
                encoding='utf-8',
            )
            # Active cellular msm1 + ignored ncm0/bcm0
            (net_dir / 'msm1').write_text(
                '@msm1\ntype::cellular_system\nip_ok:b:true\nip6_ok:b:true\n'
                'ip_gateway:json:["10.99.0.1"]\n'
                'ip_addresses:json:["2408:8507:8520:bee::1/64"]\n',
                encoding='utf-8',
            )
            (net_dir / 'bcm0').write_text(
                '@bcm0\ntype::wifi\nip_ok:b:true\nip_gateway:json:["192.168.1.1"]\n',
                encoding='utf-8',
            )
            (net_dir / 'ncm0').write_text(
                '@ncm0\ntype::usb\nip_ok:b:true\nip_gateway:json:["169.254.0.2"]\n',
                encoding='utf-8',
            )
            route_calls = []

            def fake_run(argv, timeout=5):
                route_calls.append(argv)
                return 0, '', ''

            j_data = {
                'owner': 'q10-unicom-volte-v1', 'boot': ['boot1'], 'native_pid': 1234,
                'owned_ims_routes': [], 'ims_route_summary': {'status': 'idle', 'family': 'none', 'count': 0, 'verified': False},
            }
            old_j = s.j
            old_cursor = dict(s.route_log_state)
            try:
                s.j = j_data
                s.route_log_state = {'inode': None, 'offset': 0}
                with patch.object(s, 'STATE', str(state_dir)), \
                     patch.object(s, 'JOURNAL', str(journal_file)), \
                     patch.object(s, 'NET_INTERFACES', str(net_dir)), \
                     patch.object(s, 'ROUTE_BIN', str(fake_route)), \
                     patch.object(s, 'boot_token', return_value=['boot1']), \
                     patch.object(s.n, 'read', side_effect=lambda p: Path(p).read_bytes()), \
                     patch.object(s, '_run_route', side_effect=fake_run), \
                     patch.object(s, 'save_journal'):
                    s.sync_ims_routes()
                    # Only the 3 verified cellular routes (2 IPv6 incl. trailing ::, 1 IPv4) were added!
                    # Unowned delete, USB 169.254.0.2, and Wi-Fi 192.168.1.1 were strictly ignored!
                    self.assertEqual(len(route_calls), 3)
                    self.assertEqual(route_calls[0], [str(fake_route), '-n', 'add', '-inet6', '-host', '2408:8140:2001::ff:f050', '2408:8507:8520:bee::1'])
                    self.assertEqual(route_calls[1], [str(fake_route), '-n', 'add', '-inet6', '-host', '2001:db8::', '2408:8507:8520:bee::1'])
                    self.assertEqual(route_calls[2], [str(fake_route), '-n', 'add', '-host', '10.99.0.7', '10.99.0.1'])
                    pub = s.public_route_summary(s.j)
                    self.assertEqual(pub, {
                        'pcscf_route_status': 'synced', 'pcscf_route_family': 'dual',
                        'pcscf_route_count': 3, 'pcscf_route_verified': True,
                    })
                    # Zero raw IPs in public summary or workflow.public_status
                    pub_json = json.dumps(workflow.public_status(dict(pub, phase='running')))
                    for ip in ('2408:8140', '2001:db8', '10.99.0.7', '10.99.0.1'):
                        self.assertNotIn(ip, pub_json)

                    # Stale-gateway sweep when msm1 IPv4 gateway disappears
                    (net_dir / 'msm1').write_text(
                        '@msm1\ntype::cellular_system\nip6_ok:b:true\n'
                        'ip_addresses:json:["2408:8507:8520:bee::1/64"]\n',
                        encoding='utf-8',
                    )
                    route_calls.clear()
                    s.sync_ims_routes()
                    self.assertEqual(route_calls, [[str(fake_route), '-n', 'delete', '-host', '10.99.0.7']])
                    self.assertEqual(len(s.j['owned_ims_routes']), 2)

                    # Cleanup on previous_boot=True clears journal WITHOUT running /sbin/route delete
                    route_calls.clear()
                    s.cleanup_ims_routes(current_boot=False)
                    self.assertEqual(route_calls, [])
                    self.assertEqual(s.j['owned_ims_routes'], [])

                    # Re-add and verify current_boot=True deletes owned routes
                    s.j['owned_ims_routes'] = [{'family': 'ipv6', 'host': '2001:db8::', 'gateway': '2408:8507:8520:bee::1'}]
                    s.cleanup_ims_routes(current_boot=True)
                    self.assertEqual(route_calls, [[str(fake_route), '-n', 'delete', '-inet6', '-host', '2001:db8::']])
                    self.assertEqual(s.j['owned_ims_routes'], [])
            finally:
                s.j = old_j
                s.route_log_state = old_cursor


class UpgradeChainAndLockTests(unittest.TestCase):
    def test_r58_and_r59_payload_hashes_registered_and_payload_count_invariant(self):
        self.assertEqual(len(u.PAYLOAD_FILES), 18)
        self.assertIn('499b01a9e316c4957fe1143945d1cc86196bf30761bef039debcf4513357a8f6', unified_install.PREVIOUS_PAYLOADS)
        self.assertIn('ed79b28d87995d7071f86c80cda303dd6ac8651acdf153f8b6da1234535bc6e7', unified_install.PREVIOUS_PAYLOADS)

    def test_exp_trial_manage_actions_require_idle_and_validate_cleanly(self):
        cfg = overseas_carrier.build_trial_config('450', ['08'], ['auto', 'lte.ktfwing.com'], allow_isim=True)
        with tempfile.TemporaryDirectory() as tmp:
            exp_path = Path(tmp) / 'exp.json'
            with patch.object(profiles, 'EXP_TRIAL_PATH', str(exp_path)), \
                 patch.object(unified_install, 'BASE', tmp), \
                 patch.object(unified_install, 'identity', return_value=({'variant': 'SQC100-5'}, 'classic')), \
                 patch.object(unified_install, 'probe', return_value={'sim_supported': True, 'exp_trial_active': True}), \
                 patch.object(unified_install.s, 'phone_idle', return_value=True):
                res = unified_install.set_exp_trial(cfg)
                self.assertTrue(res['saved'])
                self.assertTrue(res['active'])
                got = unified_install.get_exp_trial()
                self.assertTrue(got['active'])
                self.assertEqual(got['config']['mcc'], '450')
                cleared = unified_install.clear_exp_trial()
                self.assertTrue(cleared['cleared'])
                self.assertFalse(exp_path.exists())

            # Busy call must block writes
            with patch.object(profiles, 'EXP_TRIAL_PATH', str(exp_path)), \
                 patch.object(unified_install, 'identity', return_value=({'variant': 'SQC100-5'}, 'classic')), \
                 patch.object(unified_install.s, 'phone_idle', return_value=False):
                with self.assertRaisesRegex(AssertionError, 'call_active'):
                    unified_install.set_exp_trial(cfg)


class ZeroClutterChinaUiTests(unittest.TestCase):
    def test_desktop_overseas_banner_hidden_for_mainland_china(self):
        for plmn in ('460-00', '460-01', '460-11', '460-07'):
            report = {'sim_plmn': plmn, 'sim_supported': True, 'exp_trial_active': False}
            self.assertFalse(overseas_carrier_gui.should_show_overseas_banner(report), plmn)
            blocked_cn = {'sim_plmn': plmn, 'sim_supported': False, 'sim_reason': 'sim_route_unsupported', 'exp_trial_active': False}
            self.assertFalse(overseas_carrier_gui.should_show_overseas_banner(blocked_cn), plmn)
        for plmn in ('450-08', '310-260', '440-20', '262-01'):
            report = {'sim_plmn': plmn, 'sim_supported': False, 'sim_reason': 'sim_route_unsupported', 'exp_trial_active': False}
            self.assertTrue(overseas_carrier_gui.should_show_overseas_banner(report), plmn)
        self.assertTrue(overseas_carrier_gui.should_show_overseas_banner({'sim_plmn': '460-01', 'exp_trial_active': True}))

    def test_mobile_overseas_prompt_hidden_for_mainland_china_and_shown_for_overseas(self):
        cn_probe = {
            'variant': 'SQN100-3', 'family': 'q10', 'installed': False, 'can_install': True,
            'sim_supported': True, 'sim_plmn': '460-01', 'operator': 'unicom', 'exp_trial_active': False,
        }
        cn_resp = mobile_worker.inspection_response({'language': 'zh'}, cn_probe, {}, folder=str(ROOT))
        self.assertNotIn('overseas_prompt', cn_resp['details'])

        kr_probe = {
            'variant': 'SQC100-5', 'family': 'classic', 'installed': False, 'can_install': False,
            'sim_supported': False, 'sim_reason': 'sim_route_unsupported', 'sim_plmn': '450-08',
            'sim_has_isim': True, 'lte_bands_disabled': True, 'exp_trial_active': False,
        }
        kr_resp = mobile_worker.inspection_response({'language': 'en'}, kr_probe, {}, folder=str(ROOT))
        self.assertTrue(kr_resp['details'].get('overseas_prompt'))
        self.assertNotIn('overseas_preset_name', kr_resp['details'])
        self.assertTrue(kr_resp['details'].get('lte_bands_disabled'))
        self.assertIn('LTE band capability mask is 0', kr_resp['display']['message'])

    def test_configure_always_on_false_skips_ims_apn_wait_and_restores_ir92(self):
        cfg = overseas_carrier.build_trial_config(
            '302', ['490'], ['auto', 'internet.freedommobile.ca'],
            always_on=False, ir92={'UsePreconditions': 0, 'SMS_Format': '3GPP'},
            ims_pps={'SilentRedial': False}, allow_isim=True,
        )
        prof = profiles.exp_trial_profile('302', '490', trial=cfg)
        pps_store = {
            s.VOICE: {'voice_domain_preference_EUTRAN': 'n:0'},
            s.IMS: {'IMS_profilesV2': 'json:[]', 'supported_networks': 'json:[]',
                    'IMS_services': 'json:[]', 'SMS_Over_IP_Network_Indication': 'b:false',
                    'Home_network_domain_name': ':', 'SilentRedial': 'b:true'},
            s.IR92: {'UsePreconditions': 'n:1', 'SMS_Format': ':3GPP'},
            s.CDSC: {'cdsc_xml': ':'},
        }
        def fake_read(path):
            if path in pps_store:
                return ('@obj\n' + '\n'.join(k + ':' + v for k, v in pps_store[path].items() if v is not None) + '\n').encode('utf-8')
            if path in ('/radio/bin/ims_rrm', '/radio/etc/carrier/config/emergency.xml'):
                return b'stock-bytes'
            return Path(path).read_bytes()

        def fake_update(path, updates):
            for k, v in updates.items():
                if v is None:
                    pps_store[path].pop(k, None)
                else:
                    pps_store[path][k] = v

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for sub in ('state', 'runtime/carrier', 'cdsc', 'pps_cfg'):
                (base / sub).mkdir(parents=True, exist_ok=True)
            old_req, old_prof, old_j = s.ACTIVE_REQUEST, s.ACTIVE_PROFILE, s.j
            try:
                s.ACTIVE_REQUEST = profiles.request(prof, True)
                s.ACTIVE_PROFILE = prof
                s.j = {
                    'owner': 'q10-unicom-volte-v1', 'original_voice_policy': 0,
                    'pps_before': {
                        s.VOICE: {'voice_domain_preference_EUTRAN': 'n:0'},
                        s.IMS: {'IMS_profilesV2': 'json:[]', 'supported_networks': 'json:[]',
                                'IMS_services': 'json:[]', 'SMS_Over_IP_Network_Indication': 'b:false',
                                'Home_network_domain_name': ':'},
                        s.CDSC: {'cdsc_xml': ':'},
                    },
                    'known_vpn_uids': [], 'vpn_before_uids': [], 'native_pid': None,
                    'managed_files': {}, 'restore_completed': True,
                }
                with contextlib.ExitStack() as stack:
                    for obj, attr, kw in (
                        (s, 'BASE', {'new': str(base)}),
                        (s, 'STATE', {'new': str(base / 'state')}),
                        (s, 'RUNTIME', {'new': str(base / 'runtime')}),
                        (s, 'JOURNAL', {'new': str(base / 'state/journal.json')}),
                        (s, 'BIN', {'new': str(base / 'runtime/ims_rrm')}),
                        (s, 'APN', {'new': str(base / 'runtime/carrier/36-ims.xml')}),
                        (s, 'XML', {'new': str(base / 'imsconfig_user.xml')}),
                        (s, 'CFG_DIR', {'new': str(base / 'pps_cfg')}),
                        (s, 'CFG', {'new': str(base / 'pps_cfg/ims')}),
                        (s, 'ready', {'return_value': True}),
                        (s, 'current_usim', {'return_value': '302490' + '1' * 9}),
                        (s.compatibility, 'read_network', {'return_value': {'mcc': '302', 'mnc': '490'}}),
                        (profiles, 'carrier_template', {'return_value': ({'path': '/etc/carrier/config/0.xml'}, b'<xml/>')}),
                        (s, 'init_journal', {}),
                        (s, 'collect_vpn_evidence', {}),
                        (s, 'cleanup_vpn', {}),
                        (s, 'temporary_binary', {'return_value': (b'patched-bin', ['p1'])}),
                        (s, 'write_owned', {}),
                        (s, 'boot_token', {'return_value': ['b1']}),
                        (s, 'save_journal', {}),
                        (s.os.path, 'isfile', {'side_effect': lambda p: p == s.IR92 or os.path.exists(p)}),
                        (s.os, 'chmod', {}),
                        (s.n, 'read', {'side_effect': fake_read}),
                        (s.n, 'update_pps', {'side_effect': fake_update}),
                        (s.n, 'ims_pids', {'return_value': []}),
                        (s.n, 'vpn_ids', {'return_value': []}),
                        (s.n, 'vpn_configs', {'return_value': {}}),
                        (s.n, 'voice_policy', {'return_value': 3}),
                        (s.n, 'crypto_policy', {'return_value': {'swcr_id': 7, 'crypto_support': 1}}),
                        (s.n, 'command', {'return_value': b''}),
                    ):
                        stack.enter_context(patch.object(obj, attr, **kw))
                    mock_wait_apn = stack.enter_context(patch.object(s, 'wait_for_ims_apn'))
                    mock_wait_prof = stack.enter_context(patch.object(s, 'wait_for_ims_profile_loaded'))
                    s.j['crypto_boot'] = ['b1']
                    s.j['provider'] = 7
                    pps_store[str(base / 'pps_cfg/ims')] = {}
                    (base / 'pps_cfg/ims').write_text('@ims\n', encoding='utf-8')
                    s.configure()
                    mock_wait_apn.assert_not_called()
                    mock_wait_prof.assert_called_once()
                    self.assertEqual(pps_store[s.IR92]['UsePreconditions'], 'b:false')
                    self.assertEqual(pps_store[s.IMS]['SilentRedial'], 'b:false')
                    self.assertEqual(s.j['pps_before'][s.IR92]['UsePreconditions'], 'n:1')
                    self.assertEqual(s.j['pps_before'][s.IMS]['SilentRedial'], 'b:true')
                with patch.object(s, 'stop_native'), \
                     patch.object(s, 'remove_owned'), \
                     patch.object(s, 'remove_platform'), \
                     patch.object(s, 'save_journal'), \
                     patch.object(s, 'status'), \
                     patch.object(s.time, 'sleep'), \
                     patch.object(s.n, 'read', side_effect=fake_read), \
                     patch.object(s.n, 'update_pps', side_effect=fake_update), \
                     patch.object(s.n, 'crypto_policy', return_value={'swcr_id': -1, 'crypto_support': 0}), \
                     patch.object(s.n, 'voice_policy', return_value=0):
                    s.restore()
                    self.assertEqual(pps_store[s.IR92]['UsePreconditions'], 'n:1')
                    self.assertEqual(pps_store[s.IMS]['SilentRedial'], 'b:true')
            finally:
                s.ACTIVE_REQUEST, s.ACTIVE_PROFILE, s.j = old_req, old_prof, old_j

    def test_route_file_exists_is_never_claimed_as_owned(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / 'state'
            net_dir = Path(tmp) / 'net'
            state_dir.mkdir()
            net_dir.mkdir()
            (state_dir / 'native.log').write_text(
                'add host 10.99.0.8: gateway 10.99.0.1: Permission denied\n', encoding='utf-8')
            (net_dir / 'msm0').write_text(
                '@msm0\ntype::cellular_system\nip_ok:b:true\nip_gateway:json:["10.99.0.1"]\n', encoding='utf-8')
            fake_route = Path(tmp) / 'route'
            fake_route.write_bytes(b'#!/bin/sh\n')
            old_j, old_cursor = s.j, dict(s.route_log_state)
            try:
                s.j = {'owner': 'q10-unicom-volte-v1', 'boot': ['b1'], 'native_pid': 42,
                       'owned_ims_routes': [], 'ims_route_summary': {'status': 'idle', 'family': 'none', 'count': 0, 'verified': False}}
                s.route_log_state = {'inode': None, 'offset': 0}
                with patch.object(s, 'STATE', str(state_dir)), \
                     patch.object(s, 'NET_INTERFACES', str(net_dir)), \
                     patch.object(s, 'ROUTE_BIN', str(fake_route)), \
                     patch.object(s, 'boot_token', return_value=['b1']), \
                     patch.object(s.n, 'read', side_effect=lambda p: Path(p).read_bytes()), \
                     patch.object(s, '_run_route', return_value=(1, '', 'add host 10.99.0.8: gateway 10.99.0.1: File exists\n')), \
                     patch.object(s, 'save_journal'):
                    s.sync_ims_routes()
                    self.assertEqual(s.j['owned_ims_routes'], [])
                    self.assertEqual(s.j['ims_route_summary']['status'], 'existing_kept')
            finally:
                s.j, s.route_log_state = old_j, old_cursor

    def test_ipv6_trailing_colon_and_prefixed_and_7group_redaction(self):
        cases = (
            'add host 2408:8140:2001::ff:f050: gateway 2408:8507:8520:bee::1: Permission denied',
            'add host 2001:db8::: gateway 2408:8507:8520:bee::1: Permission denied',
            'pcscf:2408:8140:2001::ff:f050 sip 2001:db8:1:2:3:4::5 ok',
            'add host dead:beef::1: gateway fe80::1%msm0 pcscf:fe80::: gateway ok',
        )
        for line in cases:
            red = s.redact_ims_event_line(line)
            scrubbed = feedback.scrub(line)
            for leak in ('2408:8140', '2408:8507', '2001:db8', 'f050', 'bee::1', '3:4::5', 'dead:beef', 'fe80::'):
                self.assertNotIn(leak, red, (line, red))
                self.assertNotIn(leak, scrubbed, (line, scrubbed))
        # Preserve non-IP colon tokens
        self.assertIn('SMS_Format::3GPP', s.redact_ims_event_line('SMS_Format::3GPP'))
        self.assertIn('bb.cfgmgr:123', s.redact_ims_event_line('bb.cfgmgr:123'))
        self.assertIn('SMS_Format::3GPP', feedback.scrub('SMS_Format::3GPP'))

    def test_live_cellular_gateways_isolates_corrupt_interface_and_skips_stale_sweep(self):
        with tempfile.TemporaryDirectory() as tmp:
            net_dir = Path(tmp) / 'net'
            net_dir.mkdir()
            (net_dir / 'msm0').write_bytes(b'@msm0\ntype::cellular_system\nip_ok:b:true\nip_gateway:json:[corrupt\n')
            (net_dir / 'msm1').write_text(
                '@msm1\ntype::cellular_system\nip_ok:b:true\nip6_ok:b:true\n'
                'ip_gateway:json:["10.99.0.1"]\nip_addresses:json:["2408:8507::1/64"]\n',
                encoding='utf-8',
            )
            with patch.object(s, 'NET_INTERFACES', str(net_dir)), \
                 patch.object(s.n, 'read', side_effect=lambda p: Path(p).read_bytes()):
                peer_gws, local_ips, incomplete = s.live_cellular_gateways()
                self.assertTrue(incomplete)
                self.assertIn(('ipv4', '10.99.0.1'), peer_gws)
                self.assertIn(('ipv6', '2408:8507::1'), local_ips)

    def test_overseas_stale_numeric_xml_falls_back_to_verified_0xml_and_rejects_alias_ims(self):
        stale_xml = (
            b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<CarrierConfiguration xmlns="http://www.rim.com/CarrierConfig/2012-01">\n'
            b'  <CarrierDataConfiguration>\n'
            b'    <ServiceConfiguration>\n'
            b'      <Name>internet</Name>\n'
            b'      <RadioAccessTechnology><APN>old.legacy.apn</APN></RadioAccessTechnology>\n'
            b'    </ServiceConfiguration>\n'
            b'  </CarrierDataConfiguration>\n'
            b'</CarrierConfiguration>\n'
        )
        alias_ims_overlay = (
            b'{"CDSCOverlayVersion":3,"CarrierDataConfiguration":'
            b'{"ServiceConfigurationAlias":[{"Name":"ims","Reference":"internet"}]}}'
        )
        non_ims_overlay = (
            b'{"CDSCOverlayVersion":3,"CarrierDataConfiguration":'
            b'{"ServiceConfiguration":[{"Name":"internet","APN":"lte.ktfwing.com"}]}}'
        )
        kt_cfg = overseas_carrier.build_trial_config(
            '450', ['08'], ['auto', 'lte.ktfwing.com'], allow_isim=True, allow_stock_default_xml=True)
        kt_prof = profiles.exp_trial_profile('450', '08', trial=kt_cfg)
        with tempfile.TemporaryDirectory() as tmp:
            cfg_dir = Path(tmp) / 'cfg'
            ov_dir = Path(tmp) / 'ov'
            cfg_dir.mkdir()
            ov_dir.mkdir()
            (cfg_dir / '312.xml').write_bytes(stale_xml)
            (cfg_dir / '0.xml').write_bytes(STOCK_0_XML)
            (ov_dir / '312.json').write_bytes(non_ims_overlay)
            sha0 = hashlib.sha256(STOCK_0_XML).hexdigest()
            with patch.object(s, 'CDSC_OVERLAYS', str(ov_dir)), \
                 patch.object(s, 'ACTIVE_PROFILE', kt_prof):
                self.assertTrue(s.known_empty_cdsc_overlay('312.json'))
                (ov_dir / '312.json').write_bytes(alias_ims_overlay)
                self.assertFalse(s.known_empty_cdsc_overlay('312.json'))

            files = {
                '/etc/carrier/config/312.xml': stale_xml,
                '/etc/carrier/config/0.xml': STOCK_0_XML,
            }
            with patch.object(profiles, 'STOCK_DEFAULT_CONFIG_SHA256', sha0), \
                 patch.object(profiles, 'preloaded_carrier_config', return_value='/etc/carrier/config/312.xml'), \
                 patch.object(profiles, 'live_data_apn', return_value='lte.ktfwing.com'), \
                 patch.object(profiles.os.path, 'islink', return_value=False), \
                 patch.object(profiles.n, 'read', side_effect=lambda p: files[p]):
                info, data = profiles.carrier_template(kt_prof, '450', '08')
                self.assertEqual(info['path'], '/etc/carrier/config/0.xml')
                self.assertTrue(info.get('stock_default_xml_used'))
                self.assertIn(b'<APN>lte.ktfwing.com</APN>', data)
                self.assertIn(b'<Name>ims</Name>', data)

            # compatibility allows bootstrap via 0.xml even when preloaded is stale 312.xml
            snap = {
                'sim_state': 'READY', 'sim_read_error': False, 'mcc': '450', 'mnc': '08',
                'sim_type': 2, 'identity_matches': True, 'radio_on': True, 'lte': True,
                'network_service': 0x200000, 'data_service_mode': 'ON',
                'apn_matches': False, 'observed_data_apn': 'other', 'data_connected': True,
                'network_read_error': False, 'data_settings_read_error': False,
                'preloaded_carrier_config': '312.xml',
                'stock_apn_bootstrap_eligible': True,
            }
            checks = {c['id']: c for c in compat.network_checks(snap, kt_prof)}
            self.assertEqual(checks['apn']['status'], 'pass')

    def test_exp_trial_size_limit_checked_before_persist_and_auto_client_raises_on_ok_false(self):
        big_carriers = [
            {
                'label': 'Carrier ' + str(i) + ' ' + ('x' * 60),
                'mcc': str(200 + i),
                'mncs': ['%02d' % m for m in range(1, 17)],
                'allow_isim': False,
                'allow_stock_default_xml': True,
                'data_apns': ['apn%d-%d.example.net' % (i, j) for j in range(16)],
                'ims': {
                    'apn': 'ims', 'ip_family': 'IPv4v6', 'home_domain': 'auto', 'sms': True,
                    'ir92': {'amr_modeset_list': '0,1,2,3,4,5,6,7', 'amrwb_modeset_list': '0,1,2,3,4,5,6,7,8'},
                },
            }
            for i in range(16)
        ]
        big_cfg = {'schema': 2, 'enabled': True, 'carriers': big_carriers}
        self.assertGreater(len(profiles.canonical(profiles.validate_exp_trial(big_cfg))), 5000)
        with tempfile.TemporaryDirectory() as tmp:
            exp_path = Path(tmp) / 'exp.json'
            with patch.object(profiles, 'EXP_TRIAL_PATH', str(exp_path)), \
                 patch.object(unified_install, 'BASE', tmp), \
                 patch.object(unified_install, 'identity', return_value=({'variant': 'SQC100-5'}, 'classic')), \
                 patch.object(unified_install.s, 'phone_idle', return_value=True), \
                 patch.object(unified_install, 'persist') as mock_persist:
                # Force over 16384 limit by lowering canonical check? Test real >16384 payload:
                huge_carriers = copy.deepcopy(big_carriers)
                for item in huge_carriers:
                    item['data_apns'] = [('a' * 50) + str(j) + '.example.net' for j in range(16)]
                huge_cfg = {'schema': 2, 'enabled': True, 'carriers': huge_carriers}
                self.assertGreater(len(profiles.canonical(profiles.validate_exp_trial(huge_cfg))), 16384)
                with self.assertRaisesRegex(AssertionError, 'exp_trial_too_large'):
                    unified_install.set_exp_trial(huge_cfg)
                mock_persist.assert_not_called()

        import auto_carrier
        fake_client = auto_carrier.AutoClient(None)
        with patch.object(fake_client, 'stage') as mock_stage, \
             patch.object(fake_client, 'upload'), \
             patch.object(fake_client, 'execute', return_value={'ok': False, 'error': 'service_active'}):
            mock_stage.return_value.__enter__.return_value = '/var/stage'
            with self.assertRaises(workflow.WorkflowError) as ctx:
                fake_client.set_exp_trial(overseas_carrier.build_trial_config('450', ['08'], ['auto']))
            self.assertEqual(ctx.exception.code, 'service_active')
            with self.assertRaises(workflow.WorkflowError) as ctx2:
                fake_client.clear_exp_trial()
            self.assertEqual(ctx2.exception.code, 'service_active')

    def test_observed_apn_sentinels_filtered_empty_plmn_hidden_and_region_search(self):
        # Catalog region search works for full country names
        jp = overseas_carrier.search_catalog('Japan')
        self.assertTrue(any(e['plmn'] == '440-20' for e in jp))
        kr = overseas_carrier.search_catalog('South Korea')
        self.assertTrue(any(e['plmn'] == '450-08' for e in kr))
        # Sentinel APNs ('other', 'unknown') are never injected into data_apns
        kt = overseas_carrier.lookup_plmn_code('450-08')
        for sentinel in ('other', 'unknown', 'auto', ''):
            cfg = overseas_carrier.preset_to_trial_config(kt, observed_apn=sentinel)
            self.assertNotIn('other', cfg['data_apns'])
            self.assertNotIn('unknown', cfg['data_apns'])
        # Empty PLMN never shows overseas banner/prompt
        empty_report = {'sim_plmn': '', 'sim_supported': False, 'sim_reason': 'carrier_not_validated', 'exp_trial_active': False}
        self.assertFalse(overseas_carrier_gui.should_show_overseas_banner(empty_report))
        empty_mobile = mobile_worker.inspection_response({'language': 'zh'}, empty_report, {}, folder=str(ROOT))
        self.assertNotIn('overseas_prompt', empty_mobile['details'])
        # observed_data_apn='other' filtered from mobile details
        other_probe = {'sim_plmn': '450-08', 'observed_data_apn': 'other', 'sim_supported': False, 'sim_reason': 'carrier_not_validated'}
        other_resp = mobile_worker.inspection_response({'language': 'en'}, other_probe, {}, folder=str(ROOT))
        self.assertNotIn('observed_data_apn', other_resp['details'])

    def test_mobile_worker_overseas_actions_and_error_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp) / 'root'
            jobs_dir = root_dir / 'jobs'
            root_dir.mkdir()
            jobs_dir.mkdir()
            manifest_path = Path(tmp) / 'manifest.json'
            manifest_path.write_text(json.dumps({'version': '0.2.4.0'}), encoding='utf-8')
            fake_probe = {
                'variant': 'SQC100-5', 'family': 'classic', 'installed': False, 'can_install': True,
                'sim_supported': True, 'sim_plmn': '450-08', 'sim_has_isim': True,
                'observed_data_apn': 'other', 'exp_trial_active': True,
            }
            saved_cfg = overseas_carrier.build_trial_config('450', ['08'], ['auto', 'lte.ktfwing.com'], allow_isim=True)

            class FakeEngine:
                @contextlib.contextmanager
                def management_lock(self_inner):
                    yield

                def manage(self_inner, cmd, **kwargs):
                    if cmd == 'probe':
                        return dict(fake_probe)
                    if cmd == 'get-exp-trial':
                        return {'ok': True, 'active': True, 'config': saved_cfg}
                    if cmd == 'set-exp-trial':
                        if kwargs.get('exp_config', {}).get('mcc') == 'BAD':
                            raise ValueError('Invalid experimental trial config')
                        return {'ok': True, 'saved': True, 'active': True, 'probe': dict(fake_probe)}
                    if cmd == 'clear-exp-trial':
                        return {'ok': True, 'cleared': True, 'probe': dict(fake_probe, exp_trial_active=False)}
                    raise AssertionError(cmd)

            with patch.object(mobile_worker, 'ROOT', str(root_dir)), \
                 patch.object(mobile_worker, 'JOBS', str(jobs_dir)), \
                 patch.object(mobile_worker.e, 'private_directory'), \
                 patch.object(mobile_worker, 'job_lock', side_effect=lambda: contextlib.nullcontext()), \
                 patch.object(mobile_worker, 'require_current_selection'), \
                 patch.object(mobile_worker, 'active_job', return_value=None), \
                 patch.object(mobile_worker, 'sanitized_identity', return_value={'variant': 'SQC100-5', 'os_version': '10.3.3.3216'}), \
                 patch.object(mobile_worker, 'engine', return_value=FakeEngine()):
                # overseas-inspect returns overseas_state with 'other' filtered
                r_ins = mobile_worker.dispatch('overseas-inspect', {'language': 'en'}, tmp)
                self.assertTrue(r_ins['ok'])
                self.assertEqual(r_ins['overseas_state']['observed_data_apn'], '')
                self.assertTrue(r_ins['overseas_state']['active'])
                # overseas-save returns overseas_state cleanly
                r_save = mobile_worker.dispatch('overseas-save', {'language': 'en', 'overseas_config': saved_cfg}, tmp)
                self.assertTrue(r_save['ok'])
                self.assertIn('overseas_state', r_save)
                # invalid config returns structured invalid_overseas_config error
                r_bad = mobile_worker.dispatch('overseas-save', {'language': 'en', 'overseas_config': {'mcc': 'BAD'}}, tmp)
                self.assertFalse(r_bad['ok'])
                self.assertEqual(r_bad['error']['code'], 'invalid_overseas_config')
                # overseas-clear returns overseas_state cleanly
                r_clr = mobile_worker.dispatch('overseas-clear', {'language': 'en'}, tmp)
                self.assertTrue(r_clr['ok'])
                self.assertIn('overseas_state', r_clr)

    def test_overseas_cli_apply_sanitizes_local_path_and_restore_waits_for_stop(self):
        import io
        cfg = overseas_carrier.build_trial_config('302', ['490'], ['auto'])
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / 'cfg.json'
            cfg_path.write_text(json.dumps(cfg), encoding='utf-8')
            status_calls = iter([{'manager_alive': True}, {'manager_alive': False}])

            class FakeAuto:
                def __init__(self):
                    self.cleared = False

                def set_exp_trial(self, validated):
                    return {'ok': True, 'probe': {'sim_supported': True, 'installed': False}}

                def install(self):
                    return {'installed': True, 'reboot_required': True, 'desktop_backup': str(Path(tmp) / 'local-backup'), 'phone_backup': '/var/bb10_volte/backup'}

                def action(self, act):
                    if act == 'disable':
                        return {'phase': 'stop_requested', 'manager_alive': True}
                    if act == 'status':
                        return next(status_calls)
                    raise AssertionError(act)

                def clear_exp_trial(self):
                    self.cleared = True
                    return {'ok': True, 'cleared': True}

            fake_auto = FakeAuto()
            buf = io.StringIO()
            with patch.object(overseas_carrier, '_connect', return_value=(None, fake_auto, {})), \
                 patch.object(sys, 'stdout', buf):
                rc = overseas_carrier.main(['apply', '--config', str(cfg_path)])
            self.assertEqual(rc, 0)
            out_apply = json.loads(buf.getvalue())
            self.assertNotIn('desktop_backup', out_apply['install_result'])
            self.assertTrue(out_apply['install_result']['desktop_backup_verified'])
            self.assertNotIn('local-backup', buf.getvalue())

            buf2 = io.StringIO()
            with patch.object(overseas_carrier, '_connect', return_value=(None, fake_auto, {})), \
                 patch.object(overseas_carrier.time, 'sleep'), \
                 patch.object(sys, 'stdout', buf2):
                rc2 = overseas_carrier.main(['restore'])
            self.assertEqual(rc2, 0)
            self.assertTrue(fake_auto.cleared)


class R60HardeningAndRegressionTests(unittest.TestCase):
    def test_configure_skips_synthetic_xml_for_real_isim_under_allow_isim(self):
        cfg = overseas_carrier.build_trial_config('450', ['08'], ['lte.ktfwing.com'], allow_isim=True)
        prof = profiles.exp_trial_profile('450', '08', trial=cfg)
        for sim_type, expect_xml in ((18, False), (2, True)):
            pps_store = {
                s.VOICE: {'voice_domain_preference_EUTRAN': 'n:0'},
                s.IMS: {'IMS_profilesV2': 'json:[]', 'supported_networks': 'json:[]',
                        'IMS_services': 'json:[]', 'SMS_Over_IP_Network_Indication': 'b:false',
                        'Home_network_domain_name': ':'},
                s.CDSC: {'cdsc_xml': ':'},
            }
            written_paths = []

            def fake_write(path, *args, **kwargs):
                written_paths.append(path)

            def fake_read(path):
                if path in pps_store:
                    return ('@obj\n' + '\n'.join(k + ':' + v for k, v in pps_store[path].items() if v is not None) + '\n').encode('utf-8')
                return b'stock-bytes'

            def fake_update(path, updates):
                pps_store.setdefault(path, {})
                for k, v in updates.items():
                    if v is None:
                        pps_store[path].pop(k, None)
                    else:
                        pps_store[path][k] = v

            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                for sub in ('state', 'runtime/carrier', 'pps_cfg'):
                    (base / sub).mkdir(parents=True, exist_ok=True)
                (base / 'pps_cfg/ims').write_text('@ims\n', encoding='utf-8')
                pps_store[str(base / 'pps_cfg/ims')] = {'IMS_platform': ':common'}
                old_req, old_prof, old_j = s.ACTIVE_REQUEST, s.ACTIVE_PROFILE, s.j
                try:
                    s.ACTIVE_REQUEST = profiles.request(prof, True)
                    s.ACTIVE_PROFILE = prof
                    s.j = {
                        'owner': 'q10-unicom-volte-v1', 'original_voice_policy': 0,
                        'pps_before': copy.deepcopy(pps_store), 'known_vpn_uids': [],
                        'vpn_before_uids': [], 'native_pid': None, 'managed_files': {},
                        'restore_completed': True, 'crypto_boot': ['b1'], 'provider': 7,
                    }
                    with contextlib.ExitStack() as stack:
                        for obj, attr, kw in (
                            (s, 'BASE', {'new': str(base)}),
                            (s, 'STATE', {'new': str(base / 'state')}),
                            (s, 'RUNTIME', {'new': str(base / 'runtime')}),
                            (s, 'JOURNAL', {'new': str(base / 'state/journal.json')}),
                            (s, 'BIN', {'new': str(base / 'runtime/ims_rrm')}),
                            (s, 'APN', {'new': str(base / 'runtime/carrier/0-ims.xml')}),
                            (s, 'XML', {'new': str(base / 'imsconfig_user.xml')}),
                            (s, 'CFG_DIR', {'new': str(base / 'pps_cfg')}),
                            (s, 'CFG', {'new': str(base / 'pps_cfg/ims')}),
                            (s, 'ready', {'return_value': True}),
                            (s, 'current_usim', {'return_value': '45008' + '1' * 10}),
                            (s.compatibility, 'read_network', {'return_value': {'mcc': '450', 'mnc': '08', 'sim_type': sim_type}}),
                            (profiles, 'carrier_template', {'return_value': ({'path': '/etc/carrier/config/0.xml'}, b'<xml/>')}),
                            (s, 'init_journal', {}),
                            (s, 'collect_vpn_evidence', {}),
                            (s, 'cleanup_vpn', {}),
                            (s, 'temporary_binary', {'return_value': (b'patched-bin', ['p1'])}),
                            (s, 'write_owned', {'side_effect': fake_write}),
                            (s, 'wait_for_ims_apn', {}),
                            (s, 'boot_token', {'return_value': ['b1']}),
                            (s, 'save_journal', {}),
                            (s.os, 'chmod', {}),
                            (s.n, 'read', {'side_effect': fake_read}),
                            (s.n, 'update_pps', {'side_effect': fake_update}),
                            (s.n, 'ims_pids', {'return_value': []}),
                            (s.n, 'vpn_ids', {'return_value': []}),
                            (s.n, 'vpn_configs', {'return_value': {}}),
                            (s.n, 'voice_policy', {'return_value': 3}),
                            (s.n, 'crypto_policy', {'return_value': {'swcr_id': 7, 'crypto_support': 1}}),
                            (s.n, 'command', {'return_value': b''}),
                        ):
                            stack.enter_context(patch.object(obj, attr, **kw))
                        s.configure()
                    xml_written = str(base / 'imsconfig_user.xml') in written_paths
                    self.assertEqual(xml_written, expect_xml, (sim_type, written_paths))
                finally:
                    s.ACTIVE_REQUEST, s.ACTIVE_PROFILE, s.j = old_req, old_prof, old_j

    def test_enhanced_ipv6_and_overseas_phone_redaction(self):
        uid = 'c81347c0-d9f4-11f1-ac01-001122334455'
        line = (
            'key::2001:db8::1 full 2001:0db8:0001:0002:0003:0004:0005:0006:5060 '
            'colon 2001:0db8:0001:0002:0003:0004:0005:0006:5060: fail '
            'arr[0] SMS_Format::3GPP vpn_login response: uid= ' + uid + ' +82-10-9876-5432 caller=01087654321'
        )
        red = s.redact_ims_event_line(line)
        self.assertIn('arr[0]', red)
        self.assertIn('SMS_Format::3GPP', red)
        self.assertIn(uid, red)
        self.assertIn('fail', red)
        for secret in ('2001:db8::1', '2001:0db8:0001', '5060', '9876-5432', '01087654321'):
            self.assertNotIn(secret, red)
        scrubbed = feedback.scrub('key::2001:db8::1 2001:0db8:0001:0002:0003:0004:0005:0006:5060: fail arr[0]')
        self.assertIn('arr[0]', scrubbed)
        self.assertNotIn('2001:db8', scrubbed)
        self.assertNotIn('2001:0db8', scrubbed)
        self.assertNotIn('5060', scrubbed)

    def test_pcscf_route_sync_pending_retry_queue_and_partial_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / 'state'
            net_dir = Path(tmp) / 'net'
            state_dir.mkdir()
            net_dir.mkdir()
            (state_dir / 'native.log').write_text(
                'add host 10.99.0.9: gateway 10.99.0.1: Permission denied\n', encoding='utf-8')
            (net_dir / 'msm0').write_text(
                '@msm0\ntype::cellular_system\nip_ok:b:true\nip_gateway:json:["10.99.0.1"]\n', encoding='utf-8')
            fake_route = Path(tmp) / 'route'
            fake_route.write_bytes(b'#!/bin/sh\n')
            attempts = iter([(1, '', 'route: writing to routing socket: Network is unreachable\n'), (0, '', '')])
            old_j, old_cursor = s.j, dict(s.route_log_state)
            try:
                s.j = {
                    'owner': 'q10-unicom-volte-v1', 'boot': ['b1'], 'native_pid': 42,
                    'owned_ims_routes': [], 'pending_ims_routes': [],
                    'ims_route_summary': {'status': 'idle', 'family': 'none', 'count': 0, 'verified': False},
                }
                s.route_log_state = {'inode': None, 'offset': 0}
                with patch.object(s, 'STATE', str(state_dir)), \
                     patch.object(s, 'NET_INTERFACES', str(net_dir)), \
                     patch.object(s, 'ROUTE_BIN', str(fake_route)), \
                     patch.object(s, 'boot_token', return_value=['b1']), \
                     patch.object(s.n, 'read', side_effect=lambda p: Path(p).read_bytes()), \
                     patch.object(s, '_run_route', side_effect=lambda argv, timeout=5: next(attempts)), \
                     patch.object(s, 'save_journal'):
                    s.sync_ims_routes()
                    self.assertEqual(s.j['ims_route_summary']['status'], 'route_error')
                    self.assertEqual(len(s.pending_ims_routes), 1)
                    # Retry without any new log lines succeeds via pending_ims_routes queue!
                    s.sync_ims_routes()
                    self.assertEqual(s.j['ims_route_summary']['status'], 'synced')
                    self.assertEqual(s.pending_ims_routes, [])
                    self.assertEqual(len(s.j['owned_ims_routes']), 1)
            finally:
                s.j, s.route_log_state, s.pending_ims_routes = old_j, old_cursor, []

    def test_pre_native_retry_available_after_unsupported_sim_when_overseas_saved(self):
        card = {'state': 'READY', 'mcc': '450', 'mnc': '08', 'kind': 18, 'imsi': '45008' + '1' * 10}
        sim_hash = u.ready_sim_hash(card)
        self.assertIsNotNone(sim_hash)
        cfg = overseas_carrier.build_trial_config('450', ['08'], ['auto'], allow_isim=True)
        prof = profiles.exp_trial_profile('450', '08', trial=cfg)
        raw = {
            'phase': 'unsupported_sim', 'enabled': True, 'manager_alive': False,
            'native_alive': False, 'status_from_current_boot': True, 'current': {},
        }
        saved_sel = {'operator': 'other', 'boot': ['b1'], 'sim_sha256': sim_hash}
        with patch.object(u, 'verify'), \
             patch.object(u, 'boot_token', return_value=['b1']), \
             patch.object(u.s, 'read_status', return_value=raw), \
             patch.object(u, 'boot_start_state', return_value=None), \
             patch.object(u.device_info, 'read_identity', return_value={'variant': 'SQC100-5', 'os_version': '10.3.3.3216'}), \
             patch.object(unified_install, 'installed_management_schema', return_value=2), \
             patch.object(unified_dca, 'serving_network_snapshot', return_value={'mcc': '450', 'mnc': '08'}), \
             patch.object(u.os.path, 'isfile', side_effect=lambda p: p in (u.BASE + '/enabled', u.SELECTION)), \
             patch.object(u.s, 'load', return_value=saved_sel), \
             patch.object(u, 'card', return_value=card), \
             patch.object(u.policy, 'select', return_value={'sim_sha256': sim_hash, 'request': profiles.request(prof, True)}), \
             patch.object(u.n, 'read', side_effect=OSError('no sms pps')), \
             patch.object(u.s, 'public_route_summary', return_value={'pcscf_route_status': 'idle', 'pcscf_route_family': 'none', 'pcscf_route_count': 0, 'pcscf_route_verified': False}), \
             patch.object(u, 'pre_native_retryable', return_value=True) as mock_retry:
            pub = u.public_status()
            self.assertTrue(pub['current_sim_matches'])
            self.assertTrue(pub['pre_native_retry_available'])
            mock_retry.assert_called_with(['b1'], saved_sel, sim_hash)

            # Fallback via ready_sim_hash when policy.select raises ValueError
            with patch.object(u.policy, 'select', side_effect=ValueError('carrier_not_validated')):
                pub_unmatched = u.public_status()
                self.assertTrue(pub_unmatched['current_sim_matches'])
                self.assertFalse(pub_unmatched['pre_native_retry_available'])

        # Mobile worker surfaces retry_ready (primary_action='enable') on unsupported_sim + pre_native_retry_available
        probe_retry = {
            'variant': 'SQC100-5', 'family': 'classic', 'installed': True, 'sim_supported': True,
            'sim_plmn': '450-08', 'operator': 'other', 'exp_trial_active': True,
            'status': {'enabled': True, 'phase': 'unsupported_sim', 'manager_alive': False,
                       'status_from_current_boot': True, 'pre_native_retry_available': True},
        }
        resp = mobile_worker.inspection_response({'language': 'en'}, probe_retry, {}, folder=str(ROOT))
        self.assertEqual(resp['state'], 'retry_ready')
        self.assertEqual(resp['primary_action'], 'enable')
        self.assertIn('enable', resp['actions'])

    def test_bind_template_0xml_keeps_bootstrap_eligible_and_china_exp_never_relaxes_gates(self):
        cfg = overseas_carrier.build_trial_config('450', ['08'], ['lte.ktfwing.com'], allow_isim=True, allow_stock_default_xml=True)
        prof = profiles.exp_trial_profile('450', '08', trial=cfg)
        selected = {'request': profiles.request(prof, True)}
        bound = policy.bind_template(selected, {'path': '/etc/carrier/config/0.xml', 'sha256': 'a' * 64})
        bound_prof = bound['request']['profile']
        self.assertEqual(bound_prof['carrier']['stock_config'], '0')

        sha0 = hashlib.sha256(STOCK_0_XML).hexdigest()
        pps = {
            '/pps/services/cellular/uicc/card0/status_private': b'@s\nuicc_state:json:{"state":"READY"}\nuicc_type:n:18\nhplmn:json:{"mcc":"450","mnc":"08"}\n',
            '/pps/services/cellular/uicc/card0/status_restricted': ('@r\nimsi::' + '45008' + '1' * 10 + '\n').encode('ascii'),
            '/pps/services/cellular/radioctrl/status_public': b'@rc\npower_status::ON\nnetwork_technology:json:["lte"]\nnetwork_service:n:2097152\n',
            '/pps/services/cds/cnice/status': b'@c\ndata_services_status::ON\ninternet:json:{"active":false,"connectable":false,"enabled":true}\n',
            '/pps/services/cds/cnice/status_persistent': b'@cp\ndata_service_mode::ON\n',
            '/pps/services/carriermanager/status_private': b'@cm\ntrue_home_carrier:json:{"mcc":450,"mnc":8,"preloadedConfigFile":"/etc/carrier/config/0.xml"}\n',
            '/etc/carrier/config/0.xml': STOCK_0_XML,
        }
        with patch.object(compat.n, 'read', side_effect=lambda p: pps[p]), \
             patch.object(compat.os.path, 'islink', return_value=False), \
             patch.object(profiles, 'STOCK_DEFAULT_CONFIG_SHA256', sha0):
            snap = compat.read_network(bound_prof)
        self.assertTrue(snap['stock_apn_bootstrap_eligible'])
        self.assertEqual(compat.network_state(snap, bound_prof), 'ready')

        # Experimental profile with MCC 460 MUST NOT relax China overseas gates!
        old_prof = s.ACTIVE_PROFILE
        try:
            s.ACTIVE_PROFILE = {'carrier': {'mcc': '460', 'mncs': ['01']}, 'experimental': {'allow_isim': True}}
            self.assertFalse(s._overseas_profile_active())
            s.ACTIVE_PROFILE = {'experimental': {'allow_isim': True}}
            self.assertFalse(s._overseas_profile_active())
            s.ACTIVE_PROFILE = bound_prof
            self.assertTrue(s._overseas_profile_active())
        finally:
            s.ACTIVE_PROFILE = old_prof

    def test_mobile_job_response_maps_stock_apn_mismatch_and_default_apn_required(self):
        for code in ('stock_apn_mismatch', 'default_apn_required'):
            job = {
                'schema': 2, 'worker_safety': mobile_worker.SAFE_JOB_GUARD,
                'id': 'a' * 32, 'action': 'install', 'state': 'failed', 'phase': 'enabling_mobile_network',
                'error_code': code, 'resumable_failure': False, 'commit_outcome_unknown': False,
                'public_result': {'sim_plmn': '450-08'},
            }
            resp = mobile_worker.job_response(job, {'language': 'en'})
            self.assertEqual(resp['primary_action'], 'status')
            self.assertEqual(resp['details'].get('sim_reason'), code)

    def test_pcscf_route_retry_cap_drops_unverified_wifi_gateway_and_keeps_synced(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / 'state'
            net_dir = Path(tmp) / 'net'
            state_dir.mkdir()
            net_dir.mkdir()
            (state_dir / 'native.log').write_text(
                'add host 10.99.0.6: gateway 192.168.1.1: Permission denied\n'
                'add host 10.99.0.7: gateway 10.99.0.1: Permission denied\n',
                encoding='utf-8',
            )
            (net_dir / 'msm0').write_text(
                '@msm0\ntype::cellular_system\nip_ok:b:true\nip_gateway:json:["10.99.0.1"]\n', encoding='utf-8')
            fake_route = Path(tmp) / 'route'
            fake_route.write_bytes(b'#!/bin/sh\n')
            old_j, old_cursor, old_pend = s.j, dict(s.route_log_state), list(s.pending_ims_routes)
            try:
                s.j = {
                    'owner': 'q10-unicom-volte-v1', 'boot': ['b1'], 'native_pid': 42,
                    'owned_ims_routes': [], 'ims_route_summary': {'status': 'idle', 'family': 'none', 'count': 0, 'verified': False},
                }
                s.route_log_state = {'inode': None, 'offset': 0}
                s.pending_ims_routes = []
                with patch.object(s, 'STATE', str(state_dir)), \
                     patch.object(s, 'NET_INTERFACES', str(net_dir)), \
                     patch.object(s, 'ROUTE_BIN', str(fake_route)), \
                     patch.object(s, 'boot_token', return_value=['b1']), \
                     patch.object(s.n, 'read', side_effect=lambda p: Path(p).read_bytes()), \
                     patch.object(s, '_run_route', return_value=(0, '', '')), \
                     patch.object(s, 'save_journal'):
                    for _ in range(20):
                        s.sync_ims_routes()
                    self.assertEqual(s.pending_ims_routes, [])
                    self.assertEqual(s.j['ims_route_summary']['status'], 'synced')
                    self.assertEqual(len(s.j['owned_ims_routes']), 1)
            finally:
                s.j, s.route_log_state, s.pending_ims_routes = old_j, old_cursor, old_pend

    def test_entry_decode64_accepts_full_16kib_json_and_rejects_oversize(self):
        import base64
        import entry as mobile_entry
        raw_ok = json.dumps({'a': 'x' * 16000}).encode('utf-8')
        self.assertLessEqual(len(raw_ok), 16384)
        b64_ok = base64.b64encode(raw_ok).decode('ascii')
        self.assertGreater(len(b64_ok), 16384)
        self.assertEqual(mobile_entry.decode64(b64_ok), raw_ok)
        raw_big = b'x' * 16385
        with self.assertRaises(mobile_entry.MobileError):
            mobile_entry.decode64(base64.b64encode(raw_big).decode('ascii'))

    def test_kt_isim_trial_wrapper_and_ai_skill_overseas_catalog(self):
        import ai_skill
        import io
        import kt_isim_trial
        self.assertTrue(callable(kt_isim_trial.main))
        buf = io.StringIO()
        with patch.object(sys, 'stdout', buf):
            rc = ai_skill.main(['--lang', 'en', 'overseas', 'catalog', '--query', '311-480'])
        self.assertEqual(rc, 0)
        res = json.loads(buf.getvalue())
        self.assertTrue(res['ok'])
        self.assertEqual(res['carriers'][0]['name'], 'Verizon Wireless')


if __name__ == '__main__':
    unittest.main()
