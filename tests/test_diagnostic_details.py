"""Partial reads, privacy, and actionable baseline reporting without a phone."""
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'device'))
import compatibility as c
import diagnostic_details as d
from test_preflight import baseline


def complete():
    facts = baseline()
    facts['configuration_diagnostics'] = dict.fromkeys(c.CONFIGURATION_FLAGS, True)
    return facts


class DiagnosticTests(unittest.TestCase):
    def observe(self, failure=None, root=True, engine=True):
        reads = {'voice_policy': ('voice_policy', 0), 'crypto': ('crypto_policy', {'swcr_id': -1, 'crypto_support': 0}),
                 'ims_count': ('ims_pids', [123]), 'vpn_count': ('active_vpn_sessions', [])}
        with ExitStack() as stack:
            for obj, name, kwargs in [
                (c, 'read_network', {'return_value': {}}),
                (c, 'incoming_diagnostics', {'return_value': {}}),
                (c, 'installed_state', {'return_value': {'state': 'absent'}}),
                (c, 'configuration_diagnostics', {'return_value': dict.fromkeys(c.CONFIGURATION_FLAGS, True)}),
                (c.os, 'geteuid', {'return_value': 0 if root else 1, 'create': True}),
                (c.os, 'uname', {'return_value': ('QNX',), 'create': True}),
                (c.os.path, 'isfile', {'return_value': root}),
                (c.ctypes, 'sizeof', {'return_value': 4}),
                (c.device_info, 'read_identity', {'return_value': {'model': 'Q10'}}),
                (c.device_info, 'engine_matches', {'return_value': engine}),
                (c.n, 'read', {'return_value': b'fixture'}),
                (c.profiles, 'carrier_template', {'return_value': ({}, {})}),
            ]:
                stack.enter_context(patch.object(obj, name, **kwargs))
            mocked = {}
            for key, (name, result) in reads.items():
                kwargs = {'side_effect': OSError('private failure text')} if key == failure else {'return_value': result}
                mocked[key] = stack.enter_context(patch.object(c.n, name, **kwargs))
            result = c.observe()
            for mock in mocked.values():
                self.assertEqual(mock.call_count, 1 if root and engine else 0)
            return result

    def test_each_failed_read_keeps_all_other_observations(self):
        for failed in c.NATIVE_BASELINE_FIELDS:
            with self.subTest(failed=failed):
                facts = self.observe(failed)
                self.assertTrue(facts['native_read_error'])
                self.assertNotIn(failed, facts)
                self.assertEqual(facts['native_read_status'][failed], 'failed')
                for key in set(c.NATIVE_BASELINE_FIELDS) - {failed}:
                    self.assertIn(key, facts)
                    self.assertEqual(facts['native_read_status'][key], 'read')
                report = c.evaluate(facts)
                self.assertFalse(report['can_install'])
                self.assertNotIn('private failure text', json.dumps(report))
                ids = ('crypto_swcr_id', 'crypto_support') if failed == 'crypto' else (failed,)
                for row in report['baseline_diagnostics']:
                    if row['id'] in ids:
                        self.assertEqual((row['status'], row['reason']), ('unknown', 'read_failed'))

    def test_unverified_root_or_engine_never_calls_native_probes(self):
        for root, engine in ((False, True), (True, False)):
            facts = self.observe(root=root, engine=engine)
            self.assertEqual(set(facts['native_read_status'].values()), {'not_checked'})
            self.assertEqual(c.baseline_diagnostics(facts)[0]['reason'], 'not_checked')

    def test_clean_and_every_individual_baseline_gate_have_consistent_details(self):
        good = complete()
        self.assertTrue(c.evaluate(good)['can_install'])
        self.assertTrue(all(row['status'] == 'pass' for row in c.baseline_diagnostics(good)))
        cases = [('voice_policy', 3, 'voice_policy'), ('ims_count', 1, 'ims_count'),
                 ('vpn_count', 1, 'vpn_count'), ('native_read_error', True, 'native_read_error'),
                 ('clean_configuration', False, 'clean_configuration'),
                 ('crypto', {'swcr_id': 2, 'crypto_support': 0}, 'crypto_swcr_id'),
                 ('crypto', {'swcr_id': -1, 'crypto_support': 1}, 'crypto_support')]
        for key, value, diagnostic in cases:
            facts = copy.deepcopy(good); facts[key] = value
            report = c.evaluate(facts)
            row = next(row for row in report['baseline_diagnostics'] if row['id'] == diagnostic)
            self.assertEqual(row['status'], 'wait')
            self.assertFalse(any(report[key] for key in ('can_install', 'can_start', 'can_update')))

    def test_absent_installation_is_not_told_to_restore_an_owned_service(self):
        facts = complete(); facts['voice_policy'] = 3
        rows = d.baseline_rows(c.evaluate(facts))
        voice = next(row for row in rows if row['id'] == 'voice_policy')
        self.assertIn('当前：3；安装前要求：0', voice['detail'])
        self.assertIn('未检测到本工具安装', voice['detail'])
        self.assertNotIn('更多 → 停用并恢复', voice['detail'])

    def test_unknown_never_looks_like_zero_or_normal_and_read_failure_is_visible_while_running(self):
        facts = complete(); facts.pop('voice_policy')
        facts.update(native_read_error=True, native_read_status={'voice_policy': 'failed'})
        rows = d.baseline_rows(c.evaluate(facts), running=True)
        voice = next(row for row in rows if row['id'] == 'voice_policy')
        self.assertEqual((voice['actual'], voice['state'], voice['problem']), ('未知', '读取失败', True))
        self.assertTrue(next(row for row in rows if row['id'] == 'native_read_error')['problem'])

    def test_old_reports_keep_available_values_and_label_missing_details_unknown(self):
        report = c.evaluate(baseline())
        report.pop('baseline_diagnostics'); report.pop('native_read_status'); report.pop('configuration_diagnostics')
        rows = d.baseline_rows(report)
        self.assertEqual(next(row for row in rows if row['id'] == 'voice_policy')['actual'], '0')
        config = next(row for row in rows if row['id'] == 'ims_override_absent')
        self.assertEqual(config['state'], '未知')
        self.assertFalse(config['problem'])

    def test_report_and_summary_do_not_export_unexpected_values_or_private_input(self):
        secret = 'private-customer-data'
        facts = complete()
        facts.update(voice_policy=secret, crypto={'swcr_id': True, 'crypto_support': secret, 'extra': secret},
                     ims_count=-1, vpn_count=10**20, native_read_error=secret,
                     native_read_status={'voice_policy': secret},
                     configuration_diagnostics={'ims_override_absent': secret}, raw_pps=secret)
        report = c.evaluate(facts)
        self.assertNotIn(secret, json.dumps(report))
        self.assertIsNone(report['baseline']['crypto']['swcr_id'])
        report.update(ssh_key=secret, profile_parameters={'label': secret})
        text = d.support_summary(report, {}, lambda _: '待核实', 'test')
        self.assertNotIn(secret, text)
        self.assertIn('[B01]', text)
        self.assertIn('[C09]', text)


class IncomingObservationTests(unittest.TestCase):
    def test_snapshot_explanations_preserve_distinct_enums_without_call_acceptance(self):
        report = {'checks': [], 'can_install': False, 'can_start': False,
                  'incoming_diagnostics': {
                      'ims_state': 'connected', 'ims_ran': 'LTE',
                      'allow_volte_provisioning': 1, 'engineering_voice_override': '5',
                      'dca_voice_preference': 3, 'use_preconditions': 0,
                      'call_acceptance': 'verified', 'scope': 'trusted-success'}}
        before = copy.deepcopy(report)
        with patch.object(c.n, 'read') as read, patch.object(c.n, 'command') as command, \
                patch.object(c.n, 'update_pps') as write:
            rows = d.incoming_rows(report)
            text = d.support_summary(report, {}, lambda _: '', 'test')
        read.assert_not_called(); command.assert_not_called(); write.assert_not_called()
        self.assertEqual(report, before)
        by_id = {row['id']: row for row in rows}
        self.assertEqual(by_id['engineering_voice_override']['actual'], '5')
        self.assertEqual(by_id['dca_voice_preference']['actual'], '3')
        self.assertIn('不同接口', by_id['engineering_voice_override']['detail'])
        self.assertTrue(all('不能证明来电可用' in row['detail'] for row in rows))
        self.assertTrue(all(row['state'] == '只读观察' for row in rows))
        self.assertNotIn('verified', text)
        self.assertNotIn('trusted-success', text)
        self.assertIn('安装=否，更新=否，启动=否', text)
        self.assertIn('通话尚未由此验收', text)
        for row in rows:
            self.assertIn('[{}]'.format(row['code']), text)
            self.assertIn(row['detail'], text)

    def test_absent_legacy_field_is_optional_and_invalid_containers_remain_unknown(self):
        self.assertEqual(d.incoming_rows({'checks': []}), [])
        self.assertNotIn('[I01]', d.support_summary({'checks': []}, {}, lambda _: '', 'test'))
        for values in (None, [], True, 'private-customer-data', {}, ['connected']):
            with self.subTest(values=values):
                report = {'checks': [], 'incoming_diagnostics': values}
                rows = d.incoming_rows(report)
                self.assertEqual(len(rows), 6)
                self.assertTrue(all(row['actual'] == '未知' and row['state'] == '未知' for row in rows))
                text = d.support_summary(report, {}, lambda _: '', 'test')
                self.assertNotIn('private-customer-data', text)

    def test_only_exact_public_enum_types_reach_rows_or_summary(self):
        secret = 'private-customer-data\nIMS 已成功'
        for key, (kind, allowed) in c.DIAGNOSTIC_VALUES.items():
            for value in allowed:
                row = next(row for row in d.incoming_rows({'incoming_diagnostics': {key: value}})
                           if row['id'] == key)
                self.assertEqual(row['actual'], str(value))
            invalid = [secret, True, False, [], {}, -1, 999, 0.0, None]
            # The two voice-domain interfaces deliberately use different types.
            invalid += ['3'] if kind is int else [3]
            for value in invalid:
                with self.subTest(key=key, value=value):
                    report = {'checks': [], 'incoming_diagnostics': {key: value, 'extra': secret}}
                    before = copy.deepcopy(report)
                    rows = d.incoming_rows(report)
                    row = next(row for row in rows if row['id'] == key)
                    self.assertEqual(row['actual'], '未知')
                    self.assertNotIn(secret, json.dumps(rows, ensure_ascii=False))
                    self.assertNotIn(secret, d.support_summary(report, {}, lambda _: '', 'test'))
                    self.assertEqual(report, before)


if __name__ == '__main__':
    unittest.main()
