"""Evidence, privacy and Passport lifecycle boundaries; no phone is contacted."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'device'))
sys.path.insert(0, str(ROOT / 'tools'))
import compatibility as c
import device_info as d
import native as n
import profiles
import service
import install
import workflow as w
import community_research as research
import build_windows
from test_preflight import baseline


def passport():
    facts = baseline()
    facts.update(model='Passport', variant='SQW100-1', board_type='WINDERMERE4ROW')
    return facts


class EvidenceTests(unittest.TestCase):
    def test_upstream_success_is_never_project_acceptance_or_install_permission(self):
        report = c.evaluate(passport(), allow_experimental=True)
        before = copy.deepcopy(report)
        evidence = research.evidence_for(report)
        self.assertEqual(report, before)
        self.assertEqual(evidence['project_acceptance'], 'not_established')
        self.assertEqual(evidence['records'][0]['evidence_level'], 'upstream_contributed_report')
        self.assertEqual(evidence['records'][0]['outcome']['incoming'], 'reported_working_with_normal_handset_caller')
        self.assertFalse(report['can_install'])

    def test_evidence_requires_exact_board_os_and_actual_sim_not_selected_profile(self):
        facts = passport()
        for change in ({'board_type': None}, {'board_type': 'CLASSICVZW'},
                       {'os_version': 'other'}, {'mnc': '09'}, {'mcc': '999'}):
            report = c.evaluate(dict(facts, **change), allow_experimental=True)
            evidence = research.evidence_for(report)
            # CLASSICVZW has its own distinct record, never a Passport result.
            self.assertNotIn('passport-unicom', [r['id'] for r in evidence['records']])

    def test_catalog_contains_negative_evidence_and_pinned_sources(self):
        value = research.catalog()
        self.assertEqual(len(value['records']), 4)
        for record in value['records']:
            self.assertTrue(record['limitations'])
            self.assertTrue(all(value['source']['commit'] in url for url in record['sources']))
        facts = baseline()
        facts.update(model='Z30', variant='STA100-3', mnc='00')
        report = c.evaluate(facts, allow_experimental=True)
        self.assertFalse(report['can_install'])
        self.assertEqual(research.evidence_for(report)['records'][0]['outcome']['ims'], 'not_tested')

    def test_optional_catalog_failure_does_not_change_action_gates(self):
        report = c.evaluate(baseline())
        with patch.object(research, 'catalog', side_effect=OSError('unavailable')):
            self.assertEqual(research.evidence_for(report)['status'], 'unavailable')
        self.assertTrue(report['can_install'])

    def test_catalog_and_guide_are_in_desktop_resources(self):
        names = build_windows.runtime_data()
        for name in ('materials/community-research.json', 'docs/COMMUNITY-RESEARCH.md',
                     'docs/COMMUNITY-RESEARCH.en.md'):
            self.assertIn(name, names)


class IdentityAndDiagnosticsTests(unittest.TestCase):
    def test_board_alone_never_authorizes_and_conflicting_board_is_rejected(self):
        self.assertFalse(d.identify({'board_type': 'CLASSICATT'})['recognized'])
        self.assertFalse(d.identify(dict(baseline(), board_type='WINDERMERE4ROW'))['recognized'])
        device = d.identify(passport())
        self.assertTrue(device['recognized'])
        self.assertFalse(device['hardware_tested'])

    def test_optional_board_failure_does_not_lose_existing_identity(self):
        def read(path):
            if path.endswith('deviceproperties'):
                return b'@deviceproperties\nmodelname::Q10\nmodelnumber::SQN100-3\n'
            if path == '/etc/os.version':
                return b'10.3.3.3216'
            raise OSError('missing board')
        with patch.object(n, 'read', side_effect=read):
            self.assertTrue(d.identify(d.read_identity())['hardware_tested'])

    def test_diagnostics_keep_engineering_and_dca_enums_separate_and_do_not_write(self):
        records = {
            '/pps/services/ims/status_public': b'@status_public\nstatus::connected\ndefault_ran::lte\nallowVoLteProvisioning:n:1\nprivate::do-not-export\n',
            '/pps/services/escreens/config': b'@config\nvoice_domain_preference_EUTRAN_override::5\n',
            '/pps/services/carrier_config/radio_common/cellular_protocol_configuration': b'@config\nvoice_domain_preference_EUTRAN:n:3\n',
            '/pps/services/carrier_config/ims/ir92': b'@ir92\nUsePreconditions:n:0\n',
        }
        with patch.object(n, 'read', side_effect=lambda path: records[path]), \
             patch.object(n, 'update_pps') as write, patch.object(n, 'command') as command:
            result = c.incoming_diagnostics()
        self.assertEqual(result['engineering_voice_override'], '5')
        self.assertEqual(result['dca_voice_preference'], 3)
        self.assertEqual(result['ims_ran'], 'LTE')
        self.assertEqual(result['call_acceptance'], 'not_assessed')
        self.assertNotIn('do-not-export', json.dumps(result))
        write.assert_not_called(); command.assert_not_called()

    def test_missing_malformed_and_boolean_fields_are_unknown_not_disabled(self):
        for error in (OSError('missing'), ValueError('malformed')):
            with patch.object(n, 'read', side_effect=error):
                result = c.incoming_diagnostics()
            self.assertTrue(all(result[key] is None for key in c.DIAGNOSTIC_VALUES))
        with patch.object(n, 'read', return_value=b'allowVoLteProvisioning:b:true\nUsePreconditions::0\n'):
            result = c.incoming_diagnostics()
        self.assertIsNone(result['allow_volte_provisioning'])
        self.assertIsNone(result['use_preconditions'])

    def test_report_reduces_diagnostics_to_fixed_public_values(self):
        facts = baseline()
        facts['incoming_diagnostics'] = {'ims_state': 'secret', 'imsi': 'do-not-export',
                                         'call_acceptance': 'verified', 'use_preconditions': True}
        result = c.evaluate(facts)['incoming_diagnostics']
        self.assertEqual(result['call_acceptance'], 'not_assessed')
        self.assertIsNone(result['ims_state'])
        self.assertIsNone(result['use_preconditions'])
        self.assertNotIn('do-not-export', json.dumps(result))

    def test_registration_accepts_both_observed_lte_cases_without_weakening_liveness(self):
        value = {'phase': 'running', 'manager_alive': True, 'native_alive': True,
                 'current': {'ims': 'connected', 'register_status': '200 OK', 'ran': 'lte', 'radio': ['lte']}}
        self.assertTrue(w.registered(value))
        value['native_alive'] = False
        self.assertFalse(w.registered(value))


class PassportLifecycleTests(unittest.TestCase):
    def test_opt_in_cannot_enable_install_update_start_or_restore(self):
        for state in ('absent', 'stopped', 'busy', 'recovery_required'):
            facts = passport()
            facts['installation'] = {'state': state, 'current_profile': True,
                'carrier_profile_sha256': profiles.fingerprint(profiles.request(allow_experimental=True))}
            report = c.evaluate(facts, allow_experimental=True)
            self.assertEqual(report['outcome'], 'needs_adaptation')
            self.assertFalse(any(report[k] for k in ('can_install', 'can_update', 'can_start', 'can_restore')))

    def test_desktop_blocks_legacy_phone_mutations_but_keeps_status(self):
        facts = passport(); facts['installation'] = {'state': 'busy'}
        report = c.evaluate(facts, allow_experimental=True)
        with patch.object(w.shutil, 'which', return_value='ssh'):
            client = w.Client(allow_experimental=True)
        with patch.object(client, 'preflight', return_value=report), \
             patch.object(client, 'service', return_value={}) as remote, patch.object(client, 'execute') as execute:
            for action in ('start', 'enable', 'stop', 'disable', 'uninstall'):
                with self.assertRaisesRegex(w.WorkflowError, 'provider_lifecycle_needs_adaptation'):
                    client.action(action)
            remote.assert_not_called(); execute.assert_not_called()
            client.action('status')
            remote.assert_called_once_with('status')

    def test_direct_phone_start_stop_and_addon_actions_fail_before_mutations(self):
        with patch.object(d, 'read_identity', return_value=passport()), \
             patch.object(n, 'verify_stock'), patch.object(n, 'atomic') as write, \
             patch.object(n, 'command') as command, \
             patch.object(profiles, 'installed_request', return_value=profiles.request(allow_experimental=True)), \
             patch.object(service, 'ACTIVE_REQUEST', profiles.request()), \
             patch.object(service, 'ACTIVE_PROFILE', profiles.default()), \
             patch.object(service.os, 'geteuid', return_value=0, create=True), \
             patch.object(service.os, 'fork', create=True) as fork, patch.object(service.os, 'unlink') as unlink:
            for action in ('start', 'stop'):
                with patch.object(sys, 'argv', ['service.py', action]), self.assertRaisesRegex(RuntimeError, 'lifecycle'):
                    service.main()
            for action in ('enable', 'disable', 'uninstall'):
                with patch.object(sys, 'argv', ['install.py', action]), self.assertRaisesRegex(RuntimeError, 'lifecycle'):
                    install.main()
            write.assert_not_called(); command.assert_not_called()
            fork.assert_not_called(); unlink.assert_not_called()


if __name__ == '__main__':
    unittest.main()
