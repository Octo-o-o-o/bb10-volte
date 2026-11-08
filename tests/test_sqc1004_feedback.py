"""Redacted SQC100-4/Telecom feedback: retain network blockers after exact Telecom admission."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'device'))
import i18n
import carrier_policy
import compatibility as c
import diagnostic_details as d
from test_preflight import baseline


def feedback_facts():
    """Only public observations, with no original report or customer identity."""
    facts = baseline()
    facts.update(model='Classic', variant='SQC100-4', board_type='CLASSICNA', mnc='11', ims_count=1,
                 data_service_mode='ON', data_services_status='OFF',
                 internet_present=True, internet_enabled=True, internet_connectable=True,
                 internet_active=True, network_service=1, apn_matches=None,
                 observed_data_apn='unknown', data_connected=False,
                 lte_active_band_mask=16, lte_band_capability_mask=16846939,
                 native_read_error=False,
                 native_read_status=dict.fromkeys(c.NATIVE_BASELINE_FIELDS, 'read'),
                 configuration_diagnostics=dict.fromkeys(c.CONFIGURATION_FLAGS, True))
    return facts


def feedback_report(facts=None):
    profile = json.loads((ROOT / 'profiles/china-telecom.json').read_text(encoding='utf-8'))
    return c.evaluate(feedback_facts() if facts is None else facts, profile, True)


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        language = patch.object(i18n, 'LANGUAGE', 'zh')
        language.start()
        self.addCleanup(language.stop)

    def test_original_three_blockers_and_permissions_are_preserved(self):
        report = feedback_report()
        self.assertEqual([(row['id'], row['code']) for row in report['checks'] if row['status'] != 'pass'],
                         [('lte', 'lte_emergency_only'), ('apn', 'data_services_off'),
                          ('baseline', 'baseline_not_clean')])
        before = copy.deepcopy(report)
        scope = d.adaptation_note(report)
        self.assertEqual(scope, '')  # Exact Telecom model admission does not remove the three live blockers.
        self.assertIn('设置为 ON，实际状态为 OFF', d.data_service_note(report))
        ims = next(row for row in d.baseline_rows(report) if row['id'] == 'ims_count')
        self.assertIn('不能证明安装残留', ims['detail'])
        self.assertNotIn('已有设置的来源', ims['detail'])
        text = d.support_summary(report, {}, lambda row: row['code'], 'test')
        self.assertIn(scope, text)
        self.assertEqual(report, before)
        self.assertFalse(any(report[key] for key in ('can_install', 'can_update', 'can_start', 'can_enable')))

    def test_waiting_for_stock_ims_is_not_a_network_fix(self):
        facts = feedback_facts()
        facts['ims_count'] = 0
        report = feedback_report(facts)
        self.assertEqual([row['id'] for row in report['checks'] if row['status'] != 'pass'], ['lte', 'apn'])
        self.assertFalse(any(report[key] for key in ('can_install', 'can_update', 'can_start')))
        self.assertEqual(carrier_policy.model(facts), 'classic')
        with self.assertRaisesRegex(ValueError, 'hardware_identity_conflict'):
            carrier_policy.model(dict(facts, board_type='CLASSICATT'))

    def test_actual_status_and_setting_are_explained_separately_in_both_languages(self):
        for language in ('zh', 'en'):
            with patch.object(i18n, 'LANGUAGE', language):
                enabled = d.data_service_note({'network_diagnostics': {'data_service_mode': 'ON', 'data_services_status': 'OFF'}})
                disabled = d.data_service_note({'network_diagnostics': {'data_service_mode': 'OFF', 'data_services_status': 'ON'}})
                unknown = d.data_service_note({'network_diagnostics': {'data_service_mode': 'private-invalid', 'data_services_status': 'OFF'}})
                self.assertNotEqual(enabled, disabled)
                self.assertNotEqual(enabled, unknown)
                self.assertNotIn('private-invalid', unknown)
                self.assertIn('开启数据服务' if language == 'zh' else 'Enable data services', disabled)
                self.assertIn('未知' if language == 'zh' else 'unknown', unknown)
                if language == 'en':
                    self.assertNotRegex(enabled + disabled + unknown + d.adaptation_note(feedback_report()), r'[\u4e00-\u9fff]')
        self.assertIn('检查详情', d.data_service_note({}))

    def test_exact_model_scope_is_not_a_new_blanket_legacy_gate(self):
        report = feedback_report()
        report['device']['variant'] = 'SQC100-2'
        self.assertEqual(d.adaptation_note(report), '')
        for value in ('SQC100-4\nprivate-customer-text', None, 4):
            report['device']['variant'] = value
            self.assertEqual(d.adaptation_note(report), '')
        facts = feedback_facts()
        facts.update(ims_count=0, network_service=2098186, data_services_status='ON',
                     apn_matches=True, data_connected=True)
        ready = feedback_report(facts)
        self.assertTrue(ready['can_install'])
        self.assertNotIn('当前入网阻断', d.adaptation_note(ready))


if __name__ == '__main__':
    unittest.main()
