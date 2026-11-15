"""Regression tests for r48 / mobile 0.1.0.48 full-project hardening."""
import builtins
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / 'device'),
    str(ROOT / 'mobile' / 'runtime'),
    str(ROOT / 'tools'),
]

import ai_skill
import autostart_evidence
import carrier_policy
import compatibility
import device_info
import device_support
import entry as mobile_entry
import mobile_app_device
import phone_pairing
import profiles
import service
import unified_operator_name
import unified_service
import worker as mobile_worker


class Py32DistinctIOError(Exception):
    """Simulates Python 3.2 where IOError and OSError are sibling classes."""


class R48HardeningTests(unittest.TestCase):
    def test_apn_oi_suffix_normalization_and_all_twelve_mncs(self):
        self.assertEqual(profiles.normalize_apn('cmnet.mnc008.mcc460.gprs'), 'cmnet')
        self.assertEqual(profiles.normalize_apn('IMS.MNC011.MCC460.GPRS'), 'ims')
        self.assertEqual(profiles.normalize_apn('  3GNET.mnc06.mcc460.gprs '), '3gnet')
        self.assertEqual(profiles.normalize_apn('ctlte'), 'ctlte')
        self.assertEqual(profiles.normalize_apn(None), '')
        self.assertEqual(
            set(profiles.OPERATOR_MNCS['mobile']) | set(profiles.OPERATOR_MNCS['unicom']) | set(profiles.OPERATOR_MNCS['telecom']),
            {'00', '01', '02', '03', '04', '05', '06', '07', '08', '09', '11', '12'},
        )
        for variant in carrier_policy.MODELS:
            for mnc in ('00', '01', '02', '03', '04', '05', '06', '07', '08', '09', '11', '12'):
                self.assertFalse(profiles.carrier_adaptation_blocked(variant, '460', (mnc,)))

    def test_carrier_template_verifies_zero_xml_even_when_stock_config_is_bound(self):
        facts = {'variant': 'SQW100-1', 'board_type': 'WINDERMEREEMEA', 'os_version': '10.3.3.3216'}
        card = {'state': 'READY', 'kind': 2, 'mcc': '460', 'mnc': '08', 'imsi': '46008' + '12345' * 2}
        selected = carrier_policy.select(facts, card)
        bound = carrier_policy.bind_template(
            selected,
            {'path': '/etc/carrier/config/404.xml', 'sha256': profiles.MOBILE_404_SHA256},
        )
        profile = bound['request']['profile']
        self.assertEqual(profile['carrier']['stock_config'], '404')

        zero_path = '/etc/carrier/config/0.xml'
        stock_path = '/etc/carrier/config/404.xml'
        cm_bytes = b'@status_private\ntrue_home_carrier:json:{"mcc":460,"mnc":8,"preloadedConfigFile":"/etc/carrier/config/0.xml","downloadedConfigFile":""}\n'
        valid_xml = (
            b'<?xml version="1.0"?><CarrierData>'
            b'<ServiceConfiguration><Name>internet</Name><RadioAccessTechnology><APN>cmnet</APN></RadioAccessTechnology></ServiceConfiguration>'
            b'<ServiceConfigurationAlias><Name>ims</Name></ServiceConfigurationAlias>'
            b'</CarrierData>'
        )
        zero_xml = b'<?xml version="1.0"?><CarrierData/>'

        def fake_read(path):
            if path == '/pps/services/carriermanager/status_private':
                return cm_bytes
            if path == zero_path:
                return zero_xml
            if path == stock_path:
                return valid_xml
            raise AssertionError(path)

        with patch.object(profiles.os.path, 'islink', return_value=False), \
             patch.object(profiles.n, 'read', side_effect=fake_read), \
             patch.object(profiles.n, 'digest', side_effect=lambda data: 'bad' * 16 + 'aaaa' if data == zero_xml else profiles.MOBILE_404_SHA256):
            with self.assertRaisesRegex(ValueError, 'Default stock carrier file changed'):
                profiles.carrier_template(profile, '460', '08')

        with patch.object(profiles.os.path, 'islink', return_value=False), \
             patch.object(profiles.n, 'read', side_effect=fake_read), \
             patch.object(profiles.n, 'digest', side_effect=lambda data: profiles.STOCK_DEFAULT_CONFIG_SHA256 if data == zero_xml else profiles.MOBILE_404_SHA256):
            info, patched_xml = profiles.carrier_template(profile, '460', '08')
        self.assertTrue(info['fallback_used'])
        self.assertEqual(info['original_preloaded_config'], zero_path)
        self.assertEqual(info['path'], stock_path)
        self.assertIn(b'<APN>ims</APN>', patched_xml)

        sanitized = ai_skill.sanitize_probe({'stock_template': dict(info, raw='<secret/>')})
        self.assertEqual(
            sanitized['stock_template'],
            {
                'path': stock_path,
                'sha256': profiles.MOBILE_404_SHA256,
                'fallback_used': True,
                'original_preloaded_config': zero_path,
            },
        )

    def test_compatibility_normalizes_oi_apn_supports_mme_default_bootstrap_and_flags_ota_override(self):
        profile = json.loads((ROOT / 'profiles/china-mobile.json').read_text(encoding='utf-8'))
        pps_objects = {
            '/pps/services/cellular/uicc/card0/status_private': b'@status_private\nuicc_state:json:{"state":"READY"}\nuicc_type:n:2\nhplmn:json:{"mcc":"460","mnc":"08"}\n',
            '/pps/services/cellular/uicc/card0/status_restricted': ('@status_restricted\nimsi::46008' + '12345' * 2 + '\n').encode('ascii'),
            compatibility.RADIO: b'@status_public\npower_status::ON\nnetwork_technology:json:["lte"]\nnetwork_service:n:2097152\n',
            compatibility.DATA: b'@status\ndata_services_status::ON\ninternet:json:{"enabled":true,"connectable":true,"active":true,"connected":true,"apn":"cmiot.mnc008.mcc460.gprs"}\n',
            compatibility.DATA_SETTINGS: b'@status_persistent\ndata_service_mode::ON\ncdsc_xml::\n',
            '/pps/services/carriermanager/status_private': b'@status_private\ntrue_home_carrier:json:{"mcc":460,"mnc":8,"preloadedConfigFile":"/etc/carrier/config/0.xml","downloadedConfigFile":""}\n',
            '/etc/carrier/config/0.xml': b'<zero/>',
        }
        with patch.object(compatibility.os.path, 'islink', return_value=False), \
             patch.object(compatibility.n, 'read', side_effect=lambda p: pps_objects[p]), \
             patch.object(compatibility.n, 'digest', return_value=profiles.STOCK_DEFAULT_CONFIG_SHA256):
            net = compatibility.read_network(profile)
        self.assertEqual(net['observed_data_apn'], 'other')
        self.assertFalse(net['apn_matches'])
        self.assertTrue(net['stock_apn_bootstrap_eligible'])
        checks = {c['id']: c for c in compatibility.network_checks(net, profile)}
        self.assertEqual(checks['apn'], {'id': 'apn', 'status': 'pass', 'code': 'data_apn_bootstrap_pending'})

        # OI-suffixed standard APN normalizes directly to cmnet without needing bootstrap
        pps_objects[compatibility.DATA] = b'@status\ndata_services_status::ON\ninternet:json:{"enabled":true,"connectable":true,"active":true,"connected":true,"apn":"CMNET.MNC008.MCC460.GPRS"}\n'
        with patch.object(compatibility.os.path, 'islink', return_value=False), \
             patch.object(compatibility.n, 'read', side_effect=lambda p: pps_objects[p]), \
             patch.object(compatibility.n, 'digest', return_value=profiles.STOCK_DEFAULT_CONFIG_SHA256):
            net_oi = compatibility.read_network(profile)
        self.assertEqual(net_oi['observed_data_apn'], 'cmnet')
        self.assertTrue(net_oi['apn_matches'])
        self.assertFalse(net_oi['stock_apn_bootstrap_eligible'])
        checks_oi = {c['id']: c for c in compatibility.network_checks(net_oi, profile)}
        self.assertEqual(checks_oi['apn'], {'id': 'apn', 'status': 'pass', 'code': 'data_apn_ready'})

        # Downloaded OTA config surfaces specific downloaded_carrier_config_present check code
        sample = dict(
            net_oi,
            variant='SQW100-1',
            board_type='WINDERMEREEMEA',
            os_version='10.3.3.3216',
            root_ready=True,
            arm32_qnx=True,
            native_hashes={path: True for path in compatibility.n.STOCK_HASHES},
            carrier_template_ready=False,
            carrier_template_error='downloaded_carrier_config_present',
        )
        evaluated = compatibility.evaluate(sample, profile, allow_experimental=True)
        carrier_check = next(c for c in evaluated['checks'] if c['id'] == 'carrier_config')
        self.assertEqual(carrier_check, {'id': 'carrier_config', 'status': 'adapt', 'code': 'downloaded_carrier_config_present'})

    def test_python32_distinct_ioerror_is_caught_safely_on_phone_modules(self):
        with patch.object(compatibility, 'IOError', Py32DistinctIOError, create=True), \
             patch.object(compatibility.n, 'read', side_effect=Py32DistinctIOError('enoent')):
            snap = compatibility.read_network()
            self.assertTrue(snap['sim_read_error'])
            self.assertTrue(snap['radio_read_error'])
            self.assertTrue(snap['data_read_error'])
            self.assertTrue(snap['data_settings_read_error'])

        with patch.object(autostart_evidence, 'IOError', Py32DistinctIOError, create=True), \
             patch.object(autostart_evidence.device_info, 'read_identity', side_effect=Py32DistinctIOError('enoent')):
            self.assertEqual(autostart_evidence.observe('/base', {}), {'owned_configuration': False, 'autostart_authorized': False})

        with patch.object(phone_pairing, 'IOError', Py32DistinctIOError, create=True), \
             patch.object(phone_pairing.os, 'geteuid', return_value=0, create=True), \
             patch.object(phone_pairing, 'public_key', side_effect=lambda k: k), \
             patch.object(phone_pairing, 'settings', return_value={'authorizedkeysfile': ['/var/etc/ssh/authorized_keys2'], 'hostkey': ['/var/etc/ssh/ssh_host_rsa_key']}), \
             patch.object(phone_pairing.os.path, 'samefile', side_effect=Py32DistinctIOError('enoent')):
            with self.assertRaisesRegex(ValueError, 'UNSUPPORTED_SSH_LAYOUT'):
                phone_pairing.authorize('ssh-rsa AAAA', '0123456789ab')

        with patch.object(mobile_app_device, 'IOError', Py32DistinctIOError, create=True), \
             patch.object(mobile_app_device, 'installed', side_effect=Py32DistinctIOError('eacces')), \
             patch.object(mobile_app_device, 'read_pps', return_value='modelnumber::SQW100-1\n'):
            summary = mobile_app_device.summary(
                {'version': '0.1.0.48', 'identity': {'Package-Name': 'com.octolab.bb10volte'}, 'installer_sha256': '0' * 64},
                'dev1',
            )
            self.assertEqual(summary['state'], 'conflict')
            self.assertEqual(summary['error'], 'app_read_failed')

    def test_collect_vpn_evidence_bounds_slog2info_and_survives_timeout(self):
        old_j = getattr(service, 'j', None)
        try:
            service.j = {'native_pid': 4321, 'boot': 'boot1', 'known_vpn_uids': []}
            with patch.object(service.os.path, 'isfile', return_value=False), \
                 patch.object(service, 'boot_token', return_value='boot1'), \
                 patch.object(service.n, 'command', side_effect=RuntimeError('command_timeout')) as cmd:
                service.collect_vpn_evidence()
            cmd.assert_called_once_with(['/bin/slog2info', '-b', 'ims_rrm'], 8)
        finally:
            service.j = old_j

    def test_unified_operator_name_covers_all_three_carriers_and_preserves_r47_upgrade(self):
        stock = b'PPCI&N|Abrev. Net. Name|MCC|MNC\nCMCC|CMCC|460|00\nCHN-UNICOM|UNICOM|460|01\n'
        with patch.object(unified_operator_name.n, 'digest', return_value=unified_operator_name.STOCK_HASH):
            table = unified_operator_name.payload(stock).decode('utf-8')
            legacy_r47 = unified_operator_name.legacy_payload(stock).decode('utf-8')
        for mnc, label in (
            ('02', '中国移动'), ('04', '中国移动'), ('07', '中国移动'), ('08', '中国移动'),
            ('06', '中国联通'), ('09', '中国联通'),
            ('03', '中国电信'), ('05', '中国电信'), ('11', '中国电信'), ('12', '中国电信'),
        ):
            self.assertIn('%s|%s|460|%s\n' % (label, label, mnc), table)
        # Existing stock rows (00, 01) stay untouched rather than duplicated
        self.assertEqual(table.count('|460|00'), 1)
        self.assertEqual(table.count('|460|01'), 1)

        self.assertIn('46008', unified_operator_name.numeric_ons_values('mobile'))
        self.assertIn('460-8', unified_operator_name.numeric_ons_values('mobile'))
        self.assertIn('460-06', unified_operator_name.numeric_ons_values('unicom'))
        self.assertIn('460-12', unified_operator_name.numeric_ons_values('telecom'))
        self.assertNotIn('CHN-UNICOM', unified_operator_name.numeric_ons_values('unicom'))

        self.assertIn('中国电信|中国电信|460|11\n', legacy_r47)
        self.assertNotIn('中国移动|中国移动|460|08\n', legacy_r47)

    def test_passport_board_widenings_in_device_info_and_unified_service(self):
        facts = {'variant': 'SQW100-3', 'board_type': 'WINDERMERENA', 'os_version': '10.3.3.3216'}
        ident = device_info.identify(facts)
        self.assertEqual(ident['family'], 'passport')
        self.assertTrue(ident['recognized'])
        self.assertFalse(ident['identity_conflict'])
        with patch.object(unified_service, 'boot_token', return_value=None):
            self.assertEqual(
                unified_service.reconcile_stale_sms_busy(facts, {'operator': 'mobile'}, None),
                'normal_boot_not_proven',
            )
            self.assertEqual(
                unified_service.reconcile_stale_sms_busy(dict(facts, board_type='CLASSICROW'), {'operator': 'mobile'}, None),
                'out_of_scope',
            )

    def test_entry_rejects_corrupt_deflate_and_worker_surfaces_specific_sim_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_zip = Path(os.path.realpath(tmp)) / 'corrupt.zip'
            with zipfile.ZipFile(bad_zip, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('manifest.json', b'{"hello": "world"}' * 20)
                zf.writestr('manifest.sig.json', b'{"sig": "abc"}' * 10)
            raw = bytearray(bad_zip.read_bytes())
            # Corrupt the compressed payload bytes inside the first local file entry
            idx = 30 + len('manifest.json') + 2
            raw[idx] ^= 0xff
            raw[idx + 1] ^= 0xff
            bad_zip.write_bytes(bytes(raw))
            with self.assertRaises(mobile_entry.MobileError) as ctx:
                mobile_entry.read_archive(os.path.realpath(str(bad_zip)))
            self.assertEqual(str(ctx.exception), 'invalid_zip_archive')

        fake_manager = MagicMock()
        fake_manager.BASE = '/nonexistent/bb10-volte-test'
        fake_manager.manage.side_effect = RuntimeError('china_broadnet_unsupported')
        fake_manager.u.card.return_value = {'mcc': '460', 'mnc': '15', 'state': 'READY', 'kind': 2}
        job = {
            'id': 'a' * 32,
            'action': 'enable',
            'phase': 'checking',
            'state': 'running',
            'worker_safety': mobile_worker.SAFE_JOB_GUARD,
            'commit_outcome_unknown': False,
        }
        with patch.object(mobile_worker, 'mobile_radio_state', return_value='OFF'), \
             patch.object(mobile_worker, 'progress', side_effect=lambda j_obj, phase, **kw: j_obj.update(phase=phase, **kw)):
            with self.assertRaisesRegex(RuntimeError, 'china_broadnet_unsupported'):
                mobile_worker.prepare_activation_network(job, fake_manager)
        self.assertFalse(job['resumable_failure'])
        self.assertEqual(job['public_result'], {'sim_plmn': '460-15'})
        job['state'] = 'failed'
        job['error_code'] = 'china_broadnet_unsupported'
        self.assertFalse(mobile_worker.resumable_job(job))
        resp = mobile_worker.job_response(job, {'language': 'zh'})
        self.assertFalse(resp['ok'])
        self.assertEqual(resp['state'], 'error')
        self.assertEqual(resp['title_code'], 'sim_broadnet_unsupported')
        self.assertEqual(resp['primary_action'], 'status')
        self.assertNotIn('resume', resp['actions'])

    def test_legacy_cleanup_allowed_across_all_catalog_models_while_install_stays_scoped(self):
        facts = {'variant': 'SQK100-1', 'board_type': 'KHANE', 'os_version': '10.3.3.3216'}
        profile = json.loads((ROOT / 'profiles/china-unicom.json').read_text(encoding='utf-8'))
        mobile_worker.validate_legacy_target(profile, facts, 'legacy-stop', str(ROOT))
        mobile_worker.validate_legacy_target(profile, facts, 'legacy-uninstall', str(ROOT))
        with self.assertRaises(mobile_entry.MobileError) as ctx:
            mobile_worker.validate_legacy_target(profile, facts, 'legacy-install', str(ROOT))
        self.assertEqual(str(ctx.exception), 'trial_exact_profile_required')

    def test_error_message_covers_non_ssh_sim_and_template_codes(self):
        for code in ('china_broadnet_unsupported', 'sim_route_unsupported',
                     'downloaded_carrier_config_present', 'carrier_not_validated',
                     'unified_already_installed', 'unified_package_mismatch',
                     'restore_pending', 'call_active',
                     'root_scheme_not_supported', 'root_boot_script_changed'):
            msg = device_support.error_message(code)
            self.assertIsNotNone(msg, code)
            self.assertNotIn('SSH', msg)
            self.assertTrue(len(msg) > 6, code)


if __name__ == '__main__':
    unittest.main()
