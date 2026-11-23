"""Regression coverage for the built-in AI skill and headless tools/ai_skill.py CLI."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'tools'))

import ai_skill
from workflow import WorkflowError


class BuiltInSkillPackageTests(unittest.TestCase):
    def test_skill_files_and_frontmatter_are_complete(self):
        skill_dir = REPO / '.agents/skills/bb10-volte'
        skill_md = skill_dir / 'SKILL.md'
        self.assertTrue(skill_md.is_file())
        self.assertTrue((skill_dir / 'scripts/bb10_skill.py').is_file())
        self.assertTrue((skill_dir / 'references/models-and-carriers.md').is_file())
        self.assertTrue((skill_dir / 'references/workflows-and-troubleshooting.md').is_file())

        text = skill_md.read_text(encoding='utf-8')
        self.assertTrue(text.startswith('---\n'))
        frontmatter = text.split('---\n', 2)[1]
        self.assertIn('name: bb10-volte', frontmatter)
        self.assertIn('description:', frontmatter)
        for prefix in ('SQN100-', 'SQC100-', 'SQW100-', 'SQK100-'):
            self.assertIn(prefix, text)
        self.assertIn('PolyForm Noncommercial License 1.0.0', text)
        self.assertNotIn('MIT License', text)

    def test_skill_wrapper_script_invokes_models_json(self):
        wrapper = REPO / '.agents/skills/bb10-volte/scripts/bb10_skill.py'
        proc = subprocess.run(
            [sys.executable, str(wrapper), 'models', '--variant', 'SQK100-1'],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(proc.stdout)
        self.assertTrue(data['ok'])
        self.assertEqual(data['model']['variant'], 'SQK100-1')
        self.assertEqual(data['model']['family'], 'p9983')
        self.assertTrue(data['model']['auto_root_recipe_supported'])

    def test_ai_skill_stays_headless_without_tkinter_import(self):
        code = (
            'import sys; sys.modules["tkinter"] = None; '
            'sys.path.insert(0, "tools"); import ai_skill; '
            'rc, payload = ai_skill.run(["volte", "verify-package"]); '
            'assert rc == 0 and payload["ok"] is True'
        )
        subprocess.run([sys.executable, '-c', code], cwd=REPO, check=True)


class AiSkillModelsTests(unittest.TestCase):
    def test_full_catalog_covers_all_16_models_and_48_carrier_entries(self):
        original_lang = ai_skill.i18n.LANGUAGE
        rc, data = ai_skill.run(['models', '--lang', 'en'])
        self.assertEqual(ai_skill.i18n.LANGUAGE, original_lang)
        self.assertEqual(rc, 0)
        self.assertTrue(data['ok'])
        self.assertEqual(data['total_models'], 16)
        self.assertEqual(data['total_carrier_entries'], 48)
        by_variant = {row['variant']: row for row in data['models']}
        expected = {
            'SQN100-1', 'SQN100-2', 'SQN100-3', 'SQN100-4', 'SQN100-5',
            'SQC100-1', 'SQC100-2', 'SQC100-3', 'SQC100-4', 'SQC100-5',
            'SQW100-1', 'SQW100-2', 'SQW100-3', 'SQW100-4',
            'SQK100-1', 'SQK100-2',
        }
        self.assertEqual(set(by_variant), expected)
        for variant, row in by_variant.items():
            self.assertEqual(row['volte_admitted_operators'], ['mobile', 'telecom', 'unicom'], variant)
            if variant == 'SQK100-2':
                self.assertFalse(row['auto_root_recipe_supported'])
                self.assertIsNone(row['stock_3216_firmware'])
            else:
                self.assertTrue(row['auto_root_recipe_supported'], variant)
                self.assertIsNotNone(row['stock_3216_firmware'], variant)

    def test_family_alias_and_compact_variant_normalization(self):
        rc, fam = ai_skill.run(['models', '--variant', 'q20'])
        self.assertEqual(rc, 0)
        self.assertEqual(fam['family_matched'], 'classic')
        self.assertTrue(fam['exact_suffix_required'])
        self.assertEqual([v['variant'] for v in fam['variants']],
                         ['SQC100-1', 'SQC100-2', 'SQC100-3', 'SQC100-4', 'SQC100-5'])

        rc2, exact = ai_skill.run(['models', '--variant', 'sqw1004', '--operator', 'telecom'])
        self.assertEqual(rc2, 0)
        self.assertEqual(exact['model']['variant'], 'SQW100-4')
        self.assertTrue(exact['model']['operator_assessment']['automatic_volte'])

        rc3, bad = ai_skill.run(['models', '--variant', 'BB-ANDROID-11'])
        self.assertEqual(rc3, 2)
        self.assertEqual(bad['error'], 'model_unconfirmed')


class AiSkillDetectAndOperationsTests(unittest.TestCase):
    def test_status_exposes_valid_plmns_and_known_current_boot_blocker_only(self):
        raw = {'phase': 'error', 'status_from_current_boot': True, 'sim_plmn': '460-07',
               'serving_plmn': '310-260', 'startup_blocker': 'existing_apn_overlay'}
        public = ai_skill.sanitize_probe({'status': raw})
        self.assertEqual(public['status']['sim_plmn'], '460-07')
        self.assertEqual(public['status']['serving_plmn'], '310-260')
        self.assertEqual(public['status']['startup_blocker'], 'existing_apn_overlay')
        self.assertIn('310-260', ai_skill.status_view(public['status'])['details'])
        raw.update(serving_plmn='310260' + '123456789', startup_blocker='private text')
        public = ai_skill.sanitize_probe({'status': raw})
        self.assertNotIn('serving_plmn', public['status'])
        self.assertNotIn('startup_blocker', public['status'])

    def _patch_local_env(self):
        return (
            patch.object(ai_skill.root_setup, 'prepared_kit_history', return_value=[]),
            patch.object(ai_skill.firmware_upgrade, 'pending_upgrades', return_value=[]),
            patch.object(ai_skill.connection_recovery, 'pending_pairings', return_value=[]),
            patch.object(ai_skill.connection, 'saved_connection', return_value=None),
            patch.object(ai_skill.connection, 'candidate_connections', return_value=[]),
        )

    def test_detect_blocks_multiple_usb_devices_without_opening_ssh(self):
        usb = {'usb_present': True, 'usb_count': 2, 'driver_ready': True, 'usb_network': True, 'device': {}}
        p1, p2, p3, p4, p5 = self._patch_local_env()
        with p1, p2, p3, p4, p5, \
             patch.object(ai_skill.root_setup, 'local_usb_state', return_value=usb), \
             patch.object(ai_skill.root_setup, 'verify_root') as mock_ssh:
            rc, out = ai_skill.run(['detect'])
        self.assertEqual(rc, 0)
        mock_ssh.assert_not_called()
        self.assertEqual(out['recommended_next_step']['code'], 'disconnect_extra_devices')

    def test_detect_routes_old_os_to_3216_upgrade_and_never_claims_unrooted(self):
        usb = {
            'usb_present': True,
            'usb_count': 1,
            'driver_ready': True,
            'usb_network': True,
            'usb_peer': '169.254.0.1',
            'usb_source_address': '169.254.0.2',
            'device': {
                'OsType': 'BlackBerry 10',
                'ModelName': 'SQN100-3',
                'PlatformVersion': '10.3.1.2243',
                'DeveloperModeEnabled': '1',
                'OobeCompleted': '1',
                'PrivateSerial': 'DO_NOT_LEAK',
            },
        }
        p1, p2, p3, p4, p5 = self._patch_local_env()
        with p1, p2, p3, p4, p5, \
             patch.object(ai_skill.root_setup, 'local_usb_state', return_value=usb), \
             patch.object(ai_skill.root_setup, 'verify_root', side_effect=WorkflowError('connection_refused')):
            rc, out = ai_skill.run(['detect'])
        self.assertEqual(rc, 0)
        self.assertEqual(out['effective_variant'], 'SQN100-3')
        self.assertEqual(out['os_baseline']['state'], 'upgrade')
        self.assertFalse(out['ssh_root']['unrooted_proven'])
        self.assertNotIn('PrivateSerial', json.dumps(out))
        self.assertEqual(out['recommended_next_step']['code'], 'upgrade_os_to_3216')

    def test_detect_verified_root_strips_sensitive_fields_and_recommends_install(self):
        fake_imsi = '4600' + '1' * 11
        fake_phone = '138' + '0' * 8
        usb = {
            'usb_present': True,
            'usb_count': 1,
            'driver_ready': True,
            'usb_network': True,
            'device': {'ModelName': 'SQW100-1', 'PlatformVersion': '10.3.3.3216', 'OobeCompleted': '1'},
        }
        raw_probe = {
            'schema': 1,
            'management_schema': 2,
            'variant': 'SQW100-1',
            'family': 'passport',
            'os_version': '10.3.3.3216',
            'installed': False,
            'installed_stage': 'absent',
            'can_install': True,
            'call_idle': True,
            'sim_supported': True,
            'operator': 'unicom',
            'imsi': fake_imsi,
            'phone_number': fake_phone,
        }
        raw_app = {
            'schema': 1,
            'state': 'ready',
            'can_install': True,
            'device_id': 'a' * 32,
            'installed': {'state': 'absent', 'can_install': True},
        }
        mock_auto = MagicMock()
        mock_auto.probe.return_value = raw_probe
        mock_inst = MagicMock()
        mock_inst.inspect.return_value = raw_app
        p1, p2, p3, p4, p5 = self._patch_local_env()
        with p1, p2, p3, p4, p5, \
             patch.object(ai_skill.root_setup, 'local_usb_state', return_value=usb), \
             patch.object(ai_skill.root_setup, 'verify_root', return_value={'host': 'bb10-root', 'config': ''}), \
             patch.object(ai_skill.connection, 'resolve_connection', return_value=(MagicMock(), {'host': 'bb10-root', 'config': ''})), \
             patch.object(ai_skill, 'AutoClient', return_value=mock_auto), \
             patch.object(ai_skill, 'MobileAppInstaller', return_value=mock_inst):
            rc, out = ai_skill.run(['detect'])
        self.assertEqual(rc, 0)
        serialized = json.dumps(out)
        self.assertNotIn(fake_imsi, serialized)
        self.assertNotIn(fake_phone, serialized)
        self.assertNotIn('a' * 32, serialized)
        self.assertEqual(out['effective_variant'], 'SQW100-1')
        self.assertEqual(out['recommended_next_step']['code'], 'ready_to_install_volte_and_mobile_app')

    def test_passport_carrier_reboot_and_registered_states_are_classified(self):
        usb = {'usb_present': True, 'usb_count': 1, 'driver_ready': True, 'usb_network': True, 'device': {}}
        carrier_reboot_probe = {
            'schema': 1,
            'variant': 'SQW100-4',
            'family': 'passport',
            'os_version': '10.3.3.3216',
            'installed': True,
            'sim_supported': True,
            'operator': 'telecom',
            'status': {
                'phase': 'carrier_reboot_required',
                'enabled': True,
                'manager_alive': False,
                'native_alive': False,
                'status_from_current_boot': True,
                'automatic_carrier_selection': True,
                'selected_this_boot': True,
                'selected_operator': 'telecom',
                'management_schema': 2,
                'current_sim_matches': True,
                'current': {'ims': 'disconnected', 'register_status': '', 'ran': 'LTE', 'radio': ['lte']},
            },
        }
        mock_auto = MagicMock()
        mock_auto.probe.return_value = carrier_reboot_probe
        mock_inst = MagicMock()
        mock_inst.inspect.return_value = {'schema': 1, 'state': 'ready', 'can_install': True}
        p1, p2, p3, p4, p5 = self._patch_local_env()
        with p1, p2, p3, p4, p5, \
             patch.object(ai_skill.root_setup, 'local_usb_state', return_value=usb), \
             patch.object(ai_skill.root_setup, 'verify_root', return_value={'host': 'bb10-root', 'config': ''}), \
             patch.object(ai_skill.connection, 'resolve_connection', return_value=(MagicMock(), {'host': 'bb10-root', 'config': ''})), \
             patch.object(ai_skill, 'AutoClient', return_value=mock_auto), \
             patch.object(ai_skill, 'MobileAppInstaller', return_value=mock_inst):
            rc, out = ai_skill.run(['detect'])
        self.assertEqual(rc, 0)
        self.assertEqual(out['recommended_next_step']['code'], 'unified_carrier_reboot_required')

        registered_probe = dict(carrier_reboot_probe, status={
            'phase': 'running',
            'enabled': True,
            'manager_alive': True,
            'native_alive': True,
            'status_from_current_boot': True,
            'automatic_carrier_selection': True,
            'selected_this_boot': True,
            'selected_operator': 'telecom',
            'management_schema': 2,
            'current_sim_matches': True,
            'current': {'ims': 'connected', 'register_status': '200 OK', 'ran': 'LTE', 'radio': ['lte']},
        })
        mock_auto.probe.return_value = registered_probe
        with p1, p2, p3, p4, p5, \
             patch.object(ai_skill.root_setup, 'local_usb_state', return_value=usb), \
             patch.object(ai_skill.root_setup, 'verify_root', return_value={'host': 'bb10-root', 'config': ''}), \
             patch.object(ai_skill.connection, 'resolve_connection', return_value=(MagicMock(), {'host': 'bb10-root', 'config': ''})), \
             patch.object(ai_skill, 'AutoClient', return_value=mock_auto), \
             patch.object(ai_skill, 'MobileAppInstaller', return_value=mock_inst):
            rc2, out2 = ai_skill.run(['detect'])
        self.assertEqual(rc2, 0)
        self.assertEqual(out2['recommended_next_step']['code'], 'ready_for_manual_call_sms_acceptance')

    def test_destructive_and_host_trust_commands_require_explicit_confirmation(self):
        rc1, out1 = ai_skill.run(['firmware', 'flash-root', '--kit', 'root-kit-demo'])
        self.assertEqual(rc1, 2)
        self.assertEqual(out1['error'], 'flash_confirmation_required')

        rc2, out2 = ai_skill.run(['firmware', 'flash-upgrade', '--kit', 'root-kit-demo', '--current-os', '10.3.2.2876'])
        self.assertEqual(rc2, 2)
        self.assertEqual(out2['error'], 'flash_confirmation_required')

    def test_mobile_app_install_and_volte_commands_use_verified_session(self):
        mock_inst = MagicMock()
        mock_inst.inspect.return_value = {'schema': 1, 'state': 'ready', 'can_install': True, 'device_id': 'b' * 32}
        mock_inst.install.return_value = {'schema': 1, 'state': 'completed', 'target_version': '0.1.0.46', 'installed_files_verified': True}
        with patch.object(ai_skill.root_setup, 'verify_root', return_value={'host': 'bb10-root', 'config': ''}), \
             patch.object(ai_skill.connection, 'resolve_connection', return_value=(MagicMock(), {'host': 'bb10-root', 'config': ''})), \
             patch.object(ai_skill, 'MobileAppInstaller', return_value=mock_inst):
            rc, out = ai_skill.run(['mobile-app', 'install'])
        self.assertEqual(rc, 0)
        self.assertTrue(out['ok'])
        self.assertEqual(mock_inst.install.call_args[0][1], 'b' * 32)

        mock_auto = MagicMock()
        mock_auto.install.side_effect = WorkflowError('sim_not_ready', {'variant': 'SQC100-2', 'sim_supported': False, 'sim_reason': 'sim_not_ready'})
        with patch.object(ai_skill.root_setup, 'verify_root', return_value={'host': 'bb10-root', 'config': ''}), \
             patch.object(ai_skill.connection, 'resolve_connection', return_value=(MagicMock(), {'host': 'bb10-root', 'config': ''})), \
             patch.object(ai_skill, 'AutoClient', return_value=mock_auto):
            rc_err, out_err = ai_skill.run(['volte', 'install', '--lang', 'en'])
        self.assertEqual(rc_err, 1)
        self.assertEqual(out_err['error'], 'sim_not_ready')
        self.assertEqual(out_err['probe']['variant'], 'SQC100-2')


if __name__ == '__main__':
    unittest.main()
