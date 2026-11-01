"""Candidate contracts, fresh device gates and UI selection; no phone I/O."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'device')]
import variant_trials as trials
import device_support
import compatibility as c
import profiles
import native
import gui
from variant_trial_gui import VariantTrialDialog
from test_preflight import baseline


def facts_for(variant, operator):
    facts = baseline()
    facts.update(variant=variant, model='Passport' if variant.startswith('SQW') else
                 'Classic' if variant.startswith('SQC') else 'Q10',
                 mnc=profiles.TRIAL_OPERATORS[operator][0], trial_observed_board='TEST_BOARD_A')
    facts['trial_native_hashes'] = dict(facts['native_hashes'], **{
        '/radio/bin/qct_rrm': True, '/usr/sbin/dca': True})
    facts['trial_native_sha256'] = {name: 'a' * 64 for name in facts['trial_native_hashes']}
    return facts


class CandidateContracts(unittest.TestCase):
    def test_preview_has_a_distinct_validated_version_without_changing_base_release(self):
        from desktop_paths import desktop_release_version
        project = {'version': '0.5.0', 'desktop_revision': 14}
        self.assertEqual(desktop_release_version(project), '0.5.0-r14')
        self.assertEqual(desktop_release_version(dict(project, preview_id='variants-20261102')),
                         '0.5.0-r14-preview-variants-20261102')
        for value in ('../escape', '', 'not safe', 1):
            with self.assertRaises(ValueError):
                desktop_release_version(dict(project, preview_id=value))

    def test_collector_keeps_unknown_board_and_six_hashes_without_native_calls(self):
        import telecom_native
        expected = dict(native.STOCK_HASHES, **{'/radio/bin/qct_rrm': telecom_native.QCT_HASH,
                                               '/usr/sbin/dca': telecom_native.DCA_HASH})
        p = trials.profile('SQC100-3', 'unicom')
        with patch.object(c, 'read_network', return_value={}), \
                patch.object(c, 'incoming_diagnostics', return_value={}), \
                patch.object(c, 'installed_state', return_value={'state': 'absent'}), \
                patch.object(c.os, 'geteuid', return_value=0, create=True), \
                patch.object(c.os, 'uname', return_value=('QNX',), create=True), \
                patch.object(c.os.path, 'isfile', return_value=True), \
                patch.object(c.ctypes, 'sizeof', return_value=4), \
                patch.object(c.device_info, 'read_identity', return_value={'variant': 'SQC100-3'}), \
                patch.object(c.device_info, 'engine_matches', return_value=True), \
                patch.object(c.n, 'read', side_effect=lambda path: path.encode('ascii')), \
                patch.object(c.n, 'digest', side_effect=lambda value: '0' * 64 if value == b'/usr/sbin/dca' else expected[value.decode('ascii')]), \
                patch.object(c.n, 'attrs', return_value={'Board_Type': 'TEST_UNKNOWN_BOARD'}), \
                patch.object(c.n, 'value', side_effect=lambda attrs, key: attrs[key]), \
                patch.object(c.profiles, 'carrier_template', return_value=({}, None)), \
                patch.object(c.n, 'voice_policy', side_effect=AssertionError('No native call permitted')) as native_call:
            result = c.observe(p)
        native_call.assert_not_called()
        self.assertEqual(result['trial_native_sha256'], dict(expected, **{'/usr/sbin/dca': '0' * 64}))
        self.assertFalse(result['trial_native_hashes']['/usr/sbin/dca'])
        self.assertTrue(all(value for path, value in result['trial_native_hashes'].items() if path != '/usr/sbin/dca'))
        self.assertEqual(result['trial_observed_board'], 'TEST_UNKNOWN_BOARD')

    def test_all_42_combinations_have_explicit_routes_and_only_19_generate_trials(self):
        routes = [trials.plan(v, op)['route'] for v in device_support.catalog() for op in profiles.TRIAL_OPERATORS]
        self.assertEqual({route: routes.count(route) for route in set(routes)},
                         {'manual_candidate': 13, 'read_only_lifecycle_pending': 6,
                          'automatic_supported': 9, 'blocked': 14})
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / 'trial-pack'
            matrix = trials.export(folder)
            self.assertEqual(len(matrix['cases']), 42)
            files = list((folder / 'profiles').glob('*.json'))
            self.assertEqual(len(files), 19)
            for path in files:
                p = profiles.validate(json.loads(path.read_text()))
                self.assertFalse(p['runtime']['autostart'])
                self.assertNotIn('lte_attach', p)
            with self.assertRaises(FileExistsError):
                trials.export(folder)

    def test_13_manual_candidates_require_real_checks_and_explicit_opt_in(self):
        for variant in device_support.catalog():
            for operator in profiles.TRIAL_OPERATORS:
                if trials.plan(variant, operator)['route'] != 'manual_candidate':
                    continue
                with self.subTest(variant=variant, operator=operator):
                    p, facts = trials.profile(variant, operator), facts_for(variant, operator)
                    self.assertFalse(c.evaluate(facts, p, False)['can_install'])
                    result = c.evaluate(facts, p, True)
                    self.assertTrue(result['can_install'])
                    self.assertFalse(result['can_enable'])
                    self.assertEqual(result['hardware_validation'], 'not_hardware_validated')
                    facts['installation'] = {'state': 'stopped', 'current_profile': True,
                        'carrier_profile_sha256': profiles.fingerprint(profiles.request(p, True))}
                    result = c.evaluate(facts, p, True)
                    self.assertTrue(result['can_start'])
                    self.assertFalse(result['can_enable'])

    def test_passport_candidates_never_bypass_the_existing_restoration_gate(self):
        for variant in ('SQW100-1', 'SQW100-3'):
            for operator in profiles.TRIAL_OPERATORS:
                with self.subTest(variant=variant, operator=operator):
                    result = c.evaluate(facts_for(variant, operator), trials.profile(variant, operator), True)
                    self.assertFalse(result['can_install'])
                    self.assertFalse(result['can_start'])
                    self.assertFalse(result['can_restore'])
                    self.assertEqual(result['outcome'], 'needs_adaptation')

    def test_model_native_sim_and_lte_changes_block_a_previously_valid_trial(self):
        p = trials.profile('SQC100-3', 'unicom')
        for changes in ({'variant': 'SQC100-5'}, {'trial_native_hashes': {}},
                        {'mnc': '00'}, {'sim_type': 18}, {'lte': False},
                        {'data_connected': False}, {'clean_configuration': False}):
            with self.subTest(changes=changes):
                facts = facts_for('SQC100-3', 'unicom')
                facts.update(changes)
                self.assertFalse(c.evaluate(facts, p, True)['can_install'])
        facts = facts_for('SQC100-3', 'unicom')
        facts['trial_native_hashes']['/usr/sbin/dca'] = False
        self.assertFalse(c.evaluate(facts, p, True)['can_install'])

    def test_trial_profile_cannot_enable_startup_change_network_or_remove_binding(self):
        original = trials.profile('SQC100-4', 'telecom')
        for change in ('autostart', 'mnc', 'ims', 'malformed_id', 'lte_attach'):
            p = copy.deepcopy(original)
            if change == 'autostart':
                p['runtime']['autostart'] = True
            elif change == 'mnc':
                p['carrier']['mncs'] = ['03']
            elif change == 'ims':
                p['ims']['sms'] = False
            elif change == 'malformed_id':
                p['id'] = 'variant-trial-unbound'
            else:
                p['lte_attach'] = 'telecom_data_centric_v1'
            with self.subTest(change=change), self.assertRaises(ValueError):
                profiles.validate(p)

    def test_report_exports_only_bounded_board_and_known_native_hashes(self):
        facts = facts_for('SQC100-3', 'unicom')
        facts['trial_observed_board'] = 'private\nvalue'
        facts['trial_native_sha256']['/private/secret'] = 'b' * 64
        result = c.evaluate(facts, trials.profile('SQC100-3', 'unicom'), True)['variant_trial']
        self.assertIsNone(result['observed_board'])
        self.assertNotIn('/private/secret', json.dumps(result))
        self.assertEqual(len(result['native_sha256']), 6)


class CandidateWindowTests(unittest.TestCase):
    def setUp(self):
        import i18n
        language = patch.object(i18n, 'LANGUAGE', 'zh')
        language.start()
        self.addCleanup(language.stop)
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def test_dialog_does_not_open_negative_or_existing_supported_trial_routes(self):
        callback = Mock()
        dialog = VariantTrialDialog(self.root, callback)
        dialog.withdraw()
        self.addCleanup(dialog.destroy)
        for variant, operator in (('SQC100-4', 'mobile'), ('SQW100-2', 'unicom'), ('SQC100-2', 'unicom')):
            dialog.variant.set(variant)
            dialog.operator.set(device_support.operator_name(operator))
            dialog.check()
            self.assertIn('disabled', dialog.check_button.state())
        callback.assert_not_called()

    def test_candidate_selection_runs_only_preflight_with_consent_unset(self):
        with patch.object(gui, 'saved_connection', return_value=None):
            app = gui.App(self.root)
        self.addCleanup(lambda: app.root.after_cancel(app._drain_job))
        app.run = Mock()
        app.experimental.set(True)
        app.ack.set(True)
        p = trials.profile('SQC100-3', 'unicom')
        app.check_variant_trial(p)
        app.run.assert_called_once_with('preflight')
        self.assertFalse(app.experimental.get())
        self.assertFalse(app.ack.get())
        self.assertIn('SQC100-3', app.trial_notice.cget('text'))
        self.assertIn('disabled', app.edit_button.state())
        app.root.after_cancel(app._drain_job)
        report = c.evaluate(facts_for('SQC100-3', 'unicom'), p, True)
        report['installation'] = {'state': 'stopped', 'current_profile': True}
        report.update(can_install=False, can_start=True, can_update=False)
        app.events.put(('result', ('install', {'installed': True, 'preflight': report})))
        with patch.object(gui, 'save_connection'):
            app.drain()
        self.assertIn('尚未启动', app.summary.cget('text'))

    def test_install_action_does_not_implicitly_start_the_candidate(self):
        with patch.object(gui, 'saved_connection', return_value=None):
            app = gui.App(self.root)
        self.addCleanup(lambda: app.root.after_cancel(app._drain_job))
        p = trials.profile('SQC100-3', 'unicom')
        app.set_profile(p)
        app.experimental.set(True)
        app.render_report(c.evaluate(facts_for('SQC100-3', 'unicom'), p, True))
        app.ack.set(True)
        client = Mock()
        with patch.object(gui, 'resolve_connection', return_value=(client, {'host': 'bb10-root', 'config': ''})), \
                patch.object(gui.messagebox, 'askokcancel', return_value=True), \
                patch.object(gui.threading, 'Thread', side_effect=lambda target, daemon: SimpleNamespace(start=target)):
            app.run('install')
        client.install.assert_called_once_with('install', start=False)
        client.action.assert_not_called()


if __name__ == '__main__':
    unittest.main()
