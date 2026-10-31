"""SIM isolation, reboot boundaries and interrupted DCA transactions."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from contextlib import ExitStack
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'device'), str(ROOT / 'tools')]
import carrier_policy as p
import profiles
import unified_dca as d
import unified_service as u


def facts(variant='SQW100-4'):
    return {'variant': variant, 'os_version': p.OS_VERSION, 'board_type': p.MODELS[variant][1]}


def card(mnc='11', suffix='12345'):
    return {'state': 'READY', 'kind': 2, 'mcc': '460', 'mnc': mnc,
            'imsi': '460' + mnc + suffix * 2}


class CarrierSelectionTests(unittest.TestCase):
    def test_all_nine_combinations_derive_only_current_sim_configuration(self):
        for variant in p.MODELS:
            for mnc, (operator, unused_label, apns) in p.CARRIERS.items():
                with self.subTest(variant=variant, mnc=mnc):
                    value = p.select(facts(variant), card(mnc))
                    profile = value['request']['profile']
                    self.assertEqual(profile['carrier']['mncs'], [mnc])
                    self.assertEqual(profile['carrier']['data_apns'], sorted(apns))
                    self.assertEqual(value['operator'], operator)
                    self.assertNotIn(card(mnc)['imsi'], json.dumps(value))
                    self.assertEqual(profiles.home_domain(profile, '460', mnc),
                                     'ims.mnc' + mnc.zfill(3) + '.mcc460.3gppnetwork.org')
        self.assertEqual(profiles.DEFAULT['carrier']['mncs'], ['01'])

    def test_second_card_same_carrier_gets_new_identity_without_changing_code(self):
        first = p.select(facts(), card())
        second = p.select(facts(), card(suffix='54321'))
        self.assertNotEqual(first['sim_sha256'], second['sim_sha256'])
        self.assertEqual(first['request'], second['request'])
        self.assertNotIn('profile-request.json', u.PAYLOAD_FILES)
        self.assertNotIn('state/selection.json', u.PAYLOAD_FILES)

    def test_unknown_sim_and_device_do_not_fall_back_to_unicom(self):
        for change in ({'state': 'PIN_REQUIRED'}, {'kind': 18}, {'mcc': '001'},
                       {'mnc': '09'}, {'imsi': 'unknown'}, {'kind': True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                p.select(facts(), dict(card(), **change))
        for change in ({'variant': 'SQW100-1'}, {'board_type': 'CLASSICATT'}, {'os_version': '10.3.3.9999'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                p.select(dict(facts(), **change), card())

    def test_same_boot_restart_and_hot_swap_wait_for_normal_reboot(self):
        value = p.select(facts(), card())
        previous = dict(value, boot=['old'])
        different = p.select(facts(), card('00'))
        self.assertEqual(p.transition(previous, different, ['old'], True), 'reboot_required')
        self.assertEqual(p.transition(previous, different, ['new'], False), 'reboot_required')
        self.assertEqual(p.transition(previous, different, ['new'], True, {'boot': ['new']}), 'reboot_required')
        self.assertEqual(p.transition(previous, different, ['new'], True, {'boot': ['old']}), 'reconcile_then_start')

    def test_restore_refuses_independent_carrier_changes(self):
        before, applied = {'profile': None, 'domain': ':'}, {'profile': 'json:["IR92"]', 'domain': ':ours'}
        self.assertEqual(p.restore_fields(dict(applied), before, applied), before)
        with self.assertRaises(ValueError):
            p.restore_fields(dict(applied, domain=':another-carrier'), before, applied)

    def test_restore_does_not_republish_already_original_carrier_fields(self):
        before, applied = {'voice': None, 'domain': ':'}, {'voice': 'n:3', 'domain': ':ours'}
        self.assertEqual(p.restore_fields(dict(before), before, applied), {})
        self.assertEqual(p.restore_fields(dict(before, domain=':ours'), before, applied), {'domain': ':'})

    def test_template_binding_uses_actual_checked_stock_path(self):
        selected = p.select(facts(), card('00'))
        bound = p.bind_template(selected, {'path': '/etc/carrier/config/404.xml', 'sha256': 'a' * 64})
        self.assertEqual(bound['request']['profile']['carrier']['stock_config'], '404')
        self.assertEqual(selected['request']['profile']['carrier']['stock_config'], 'auto')

    def test_unknown_sim_is_examined_after_previous_identity_cleanup(self):
        import unified_migrate as migration
        trace = []
        with ExitStack() as stack:
            patches = [patch.object(u, 'verify', return_value=facts()),
                patch.object(u.os.path, 'isfile', return_value=False),
                patch.object(u.n, 'crypto_policy', return_value={'swcr_id': -1, 'crypto_support': 0}),
                patch.object(u, 'handoff', side_effect=lambda: trace.append('handoff')),
                patch.object(migration, 'finish_previous_boot', side_effect=lambda: trace.append('migrate')),
                patch.object(u, 'reconcile', side_effect=lambda: trace.append('reconcile')),
                patch.object(u, 'core_stopping', return_value=False),
                patch.object(u, 'card', return_value={'state': 'READY', 'kind': 18}),
                patch.object(d, 'restore_original', side_effect=lambda: trace.append('restore-original')),
                patch.object(u.s, 'status', side_effect=trace.append)]
            for item in patches:
                stack.enter_context(item)
            self.assertFalse(u.prepare())
        self.assertEqual(trace, ['handoff', 'migrate', 'reconcile', 'restore-original', 'unsupported_sim'])


class DcaTransactionTests(unittest.TestCase):
    def setUp(self):
        self.files = {}
        self.sources = {name: d.dca.HEADER for name in d.dca.SOURCES}
        self.original = dict(self.sources)
        self.meta = {name: {'path': d.dca.source_path(name)} for name in self.sources}
        self.usage, self.token, self.fail_after = 0, ['first'], None
        self.writes = []
        self.selected = p.select(facts(), card())
        def exists(path):
            return path in self.files
        def load(path):
            return json.loads(self.files[path])
        def read(path):
            return self.sources[path.split('/')[4]]
        def atomic(path, blob):
            self.files[path] = blob
        def write(path, before, after, item):
            name = next(name for name in self.sources if path == d.dca.source_path(name))
            self.assertEqual(self.sources[name], before)
            if self.fail_after is not None and len(self.writes) == self.fail_after:
                raise OSError('simulated interruption')
            self.sources[name] = after
            self.writes.append(name)
        def publish(folder, label):
            values = list(self.sources.values())
            if all(b'ue_usage_setting::data_centric' in raw for raw in values):
                self.usage = 1
            elif all(b'ue_usage_setting::voice_centric' in raw for raw in values):
                self.usage = 0
            return {}
        patches = [patch.object(d, 'ensure_lte_mode'), patch.object(d, 'wait_policy_idle'),
            patch.object(d, 'originals', return_value=(self.meta, self.original)),
            patch.object(d.os.path, 'isfile', side_effect=exists), patch.object(d.s, 'load', side_effect=load),
            patch.object(d.s, 'phone_idle', return_value=True), patch.object(d.s, 'boot_token', side_effect=lambda: self.token),
            patch.object(d.n, 'ims_pids', return_value=[]), patch.object(d.n, 'active_vpn_sessions', return_value=[]),
            patch.object(d.n, 'read', side_effect=read), patch.object(d.n, 'atomic', side_effect=atomic),
            patch.object(d.time, 'sleep'),
            patch.object(d.radio, 'verify'), patch.object(d.radio, 'ue_usage_policy', side_effect=lambda: self.usage),
            patch.object(d.dca, 'write_existing', side_effect=write), patch.object(d.dca, 'publish', side_effect=publish)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_passport_policy_requires_new_boot_but_not_new_computer(self):
        self.assertFalse(d.prepare(self.selected))
        self.assertEqual(self.usage, 1)
        self.assertFalse(d.prepare(self.selected))
        self.token = ['second']
        self.assertTrue(d.prepare(self.selected))
        self.assertEqual(len(self.writes), 4)

    def test_recreated_dca_sources_after_boot_do_not_require_endless_passport_reboots(self):
        self.assertFalse(d.prepare(self.selected))
        for token in (['second'], ['third']):
            self.token = token
            self.sources.update(self.original)
            self.assertTrue(d.prepare(self.selected))
            record = json.loads(self.files[d.RECORD])
            self.assertTrue(record['source_repair_only'])
            self.assertEqual(record['ue_usage_before'], 1)
            self.assertEqual(record['policy_changed_boot'], ['first'])

    def test_source_repair_cannot_clear_a_policy_reboot_required_this_boot(self):
        self.assertFalse(d.prepare(self.selected))
        self.sources.update(self.original)
        self.assertFalse(d.prepare(self.selected))
        self.assertEqual(json.loads(self.files[d.RECORD])['policy_changed_boot'], self.token)

    def test_interruption_resumes_only_owned_partial_sources(self):
        self.fail_after = 2
        with self.assertRaises(OSError):
            d.set_usage(1, self.selected)
        self.assertEqual(json.loads(self.files[d.RECORD])['phase'], 'applying')
        self.assertEqual(len(self.writes), 2)
        self.fail_after, self.token = None, ['second']
        d.set_usage(1, self.selected)
        self.assertEqual(self.usage, 1)
        self.assertEqual(len(self.writes), 4)

    def test_external_source_edit_is_never_overwritten(self):
        self.sources['omadm'] = b'externally customized source'
        with self.assertRaises(AssertionError):
            d.set_usage(1, self.selected)
        self.assertFalse(self.writes)
        self.assertNotIn(d.RECORD, self.files)

    def test_unowned_nv_or_data_centric_source_cannot_be_adopted(self):
        self.usage = 1
        with self.assertRaises(AssertionError):
            d.set_usage(1, self.selected)
        self.assertFalse(self.writes)

    def test_switch_away_restores_explicit_original_nv_and_exact_files(self):
        d.set_usage(1, self.selected)
        self.token = ['second']
        selected = p.select(facts(), card('00'))
        self.assertFalse(d.prepare(selected))
        self.assertEqual(self.usage, 0)
        self.assertEqual(self.sources, self.original)
        self.token = ['third']
        self.assertTrue(d.prepare(selected))

    def test_q10_mobile_uses_data_centric_and_unicom_restores_exact_originals(self):
        mobile = p.select(facts('SQN100-3'), card('00'))
        with patch.object(d.n, 'voice_policy', return_value=3):
            self.assertTrue(d.prepare(mobile))
        self.assertEqual(self.usage, 1)
        self.assertTrue(all(b'::data_centric' in raw for raw in self.sources.values()))
        self.token = ['next-sim-boot']
        self.assertTrue(d.prepare(p.select(facts('SQN100-3'), card('01'))))
        self.assertEqual(self.usage, 0)
        self.assertEqual(self.sources, self.original)
        self.assertEqual(json.loads(self.files[d.RECORD])['operator'], 'unicom')

    def test_q10_mobile_repairs_regenerated_sources_without_an_extra_reboot(self):
        mobile = p.select(facts('SQN100-3'), card('00'))
        with patch.object(d.n, 'voice_policy', return_value=3):
            self.assertTrue(d.prepare(mobile))
            self.token = ['later-boot']
            self.sources.update(self.original)
            self.assertTrue(d.prepare(mobile))
        self.assertEqual(self.usage, 1)
        record = json.loads(self.files[d.RECORD])
        self.assertTrue(record['source_repair_only'])
        self.assertEqual(record['policy_changed_boot'], ['first'])

    def test_q10_mobile_fix_does_not_change_other_non_telecom_usage_settings(self):
        for variant, mnc in (('SQC100-2', '00'), ('SQW100-4', '00'),
                             ('SQN100-3', '01'), ('SQC100-2', '01'), ('SQW100-4', '01')):
            with self.subTest(variant=variant, mnc=mnc):
                self.assertTrue(d.prepare(p.select(facts(variant), card(mnc))))
                self.assertEqual(self.usage, 0)
                self.assertEqual(self.sources, self.original)
                self.assertFalse(self.writes)
                self.assertNotIn(d.RECORD, self.files)

    def test_calls_block_all_source_writes(self):
        with patch.object(d.s, 'phone_idle', return_value=False), self.assertRaises(AssertionError):
            d.set_usage(1, self.selected)
        self.assertFalse(self.writes)

    def stale_publisher(self):
        self.published = 1
        def publish(folder, label):
            wanted = (1 if all(b'::data_centric' in raw for raw in self.sources.values()) else
                      0 if all(b'::voice_centric' in raw for raw in self.sources.values()) else None)
            if wanted is not None and wanted != self.published:
                self.published = self.usage = wanted
            return {}
        return publish

    def test_cached_data_notification_with_original_nv_is_republished_and_read_back(self):
        with patch.object(d.dca, 'publish', side_effect=self.stale_publisher()):
            record = d.set_usage(1, self.selected)
        self.assertEqual(self.usage, 1)
        self.assertTrue(record['republish_readback_verified'])
        self.assertEqual(record['phase'], 'ready')
        self.assertTrue(all(b'::data_centric' in raw for raw in self.sources.values()))

    def test_interruption_during_notification_edge_resumes_only_owned_bytes(self):
        self.fail_after = 6
        with patch.object(d.dca, 'publish', side_effect=self.stale_publisher()):
            with self.assertRaises(OSError):
                d.set_usage(1, self.selected)
            self.assertEqual(json.loads(self.files[d.RECORD])['phase'], 'republishing_original')
            self.fail_after, self.token = None, ['second']
            d.set_usage(1, self.selected)
        self.assertEqual(self.usage, 1)
        self.assertTrue(all(b'::data_centric' in raw for raw in self.sources.values()))


if __name__ == '__main__':
    unittest.main()
