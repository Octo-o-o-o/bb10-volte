"""Passport autostart: boot decisions, stock handoff, acceptance and addon ownership."""
import ast
import hashlib
import json
import os
import re
from pathlib import Path
import tempfile
import types
import unittest

SOURCE = Path(__file__).with_name('passport_volte_phone.py')
ADDON_SCRIPT = Path(__file__).with_name('passport_volte_addon_start.sh')
FUNCTIONS = ast.Module(body=[item for item in ast.parse(SOURCE.read_text()).body
                            if isinstance(item, ast.FunctionDef)], type_ignores=[])
TOKEN = [11, 2000.0]
SHA = 'profile-sha'


class FakeOS:
    def __init__(self):
        self.forks = 0
        self.kills = []

    def __getattr__(self, name):
        return getattr(os, name)

    def fork(self):
        self.forks += 1
        return 4242

    def kill(self, pid, signum):
        self.kills.append((pid, signum))


def load(path):
    return json.loads(Path(path).read_text())


def namespace(folder):
    base = Path(folder) / 'base'
    (base / 'state').mkdir(parents=True)
    fake_os = FakeOS()
    s = types.SimpleNamespace(
        STATE=str(base / 'state'), JOURNAL=str(base / 'state/journal.json'),
        LOCK=str(base / 'state/lock.json'), STOP=str(base / 'state/stop-request'),
        ACTIVE_PROFILE={'id': 'passport-mobile-manual-research', 'carrier': {'data_apns': ['cmnet']}},
        ACTIVE_REQUEST={}, load=load, boot_token=lambda: list(TOKEN), alive=lambda pid: False,
        phone_idle=lambda: True, stopping=lambda: False, j=None, current_usim=lambda: 'usim',
        ready=lambda: True, status=lambda *a, **k: None, startup_handoff={}, startup_timing={})

    def atomic(path, data, mode=0o600):
        Path(path).write_bytes(data)
    n = types.SimpleNamespace(atomic=atomic, read=lambda path: Path(path).read_bytes(),
                              digest=lambda data: hashlib.sha256(data).hexdigest(),
                              command=lambda argv, timeout=15: b'', ims_pids=lambda: [],
                              voice_policy=lambda: 0, active_vpn_sessions=lambda: [],
                              crypto_policy=lambda: {'swcr_id': -1, 'crypto_support': 0})
    g = {'os': fake_os, 'json': json, 're': re, 'sys': __import__('sys'), 'signal': types.SimpleNamespace(SIGTERM=15),
         'hashlib': hashlib,
         'time': types.SimpleNamespace(time=lambda: 3000.0, sleep=lambda seconds: None),
         's': s, 'n': n, 'profiles': types.SimpleNamespace(fingerprint=lambda request: SHA)}
    exec(compile(FUNCTIONS, str(SOURCE), 'exec'), g)
    g.update(BASE=str(base), ENABLED=str(base / 'enabled'), ACCEPTANCE=str(base / 'acceptance'),
             EVIDENCE=str(base / 'evidence'), ADDONS=str(Path(folder) / 'addons'),
             ADDON=str(Path(folder) / 'addons/passport-volte'),
             AUTOSTART_RECORD=str(base / 'autostart-install.json'),
             BOOT_RECORD=str(base / 'last-boot-launch.json'),
             AUTOSTART_PROFILES=('passport-unicom-manual-research', 'passport-mobile-manual-research',
                                 'passport-telecom-manual-research'),
             PRESERVED_EXITS=('native_exited', 'suspended_for_shutdown'),
             TELECOM_PROFILES=('passport-telecom-manual-research',),
             TELECOM_DATACENTRIC=str(base / 'telecom-datacentric.json'),
             verify_inputs=lambda: None, acceptance_receipt=lambda: {'profile_sha256': SHA},
             redirect=lambda: None)
    return g, base


def journal(base, **values):
    data = {'owner': 'q10-unicom-volte-v1', 'original_voice_policy': 0, 'boot': [10, 1000.0],
            'profile_sha256': SHA, 'lifecycle': 'retain-provider-until-reboot'}
    data.update(values)
    (base / 'state/journal.json').write_text(json.dumps(data))


class BootDecisionTests(unittest.TestCase):
    def test_disabled_boot_reads_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            g['verify_inputs'] = lambda: self.fail('Disabled boot must not inspect the phone')
            self.assertEqual(g['boot']()['reason'], 'not_enabled')
            self.assertFalse((base / 'last-boot-launch.json').exists())
            self.assertEqual(g['os'].forks, 0)

    def test_one_attempt_per_boot(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            (base / 'enabled').touch()
            (base / 'last-boot-launch.json').write_text(json.dumps({'boot': TOKEN, 'mode': 'starting'}))
            self.assertEqual(g['boot']()['reason'], 'already_attempted_this_boot')
            self.assertEqual(g['os'].forks, 0)

    def test_journal_from_this_boot_is_never_adopted(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            (base / 'enabled').touch()
            journal(base, boot=TOKEN)
            self.assertEqual(g['boot']()['reason'], 'journal_from_this_boot')
            self.assertEqual(g['os'].forks, 0)

    def test_restored_previous_boot_is_reconciled_before_a_fresh_start(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            (base / 'enabled').touch()
            journal(base, configuration_restored=True)
            calls = []
            def reconcile():
                calls.append(True)
                g['s'].j = {'stale': True}
                return {'previous_boot': [10, 1000.0]}
            g['reconcile_after_reboot'] = reconcile
            result = g['boot']()
            self.assertEqual((result['mode'], result['manager_pid']), ('fresh', 4242))
            self.assertEqual(calls, [True])
            self.assertIsNone(g['s'].j)

    def test_unrestored_previous_boot_continues_and_archives_stale_run_files(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            (base / 'enabled').touch()
            journal(base)
            for name in ('launch.json', 'lease.json', 'retained-provider.json'):
                (base / 'state' / name).write_text(json.dumps({'boot': [10, 1000.0]}))
            result = g['boot']()
            self.assertEqual(result['mode'], 'continue_previous_boot')
            self.assertEqual(sorted(result['previous_boot_files']),
                             ['launch.json', 'lease.json', 'retained-provider.json'])
            self.assertFalse((base / 'state/launch.json').exists())
            self.assertTrue((base / 'state/journal.json').exists())

    def test_another_profile_or_pending_stop_is_not_continued(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            (base / 'enabled').touch()
            journal(base, profile_sha256='other')
            with self.assertRaises(AssertionError):
                g['boot']()
            self.assertEqual(g['os'].forks, 0)
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            (base / 'enabled').touch()
            journal(base)
            (base / 'state/stop-request').touch()
            self.assertEqual(g['boot']()['reason'], 'stop_requested_before_reboot')
            self.assertEqual(g['os'].forks, 0)

    def test_a_swapped_sim_leaves_stock_and_previous_run_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            (base / 'enabled').write_text('on')
            journal(base)
            def other_card():
                raise AssertionError('SIM does not match the installed operator profile')
            g['s'].current_usim = other_card
            result = g['boot']()
            self.assertEqual((result['mode'], result['reason']), ('skipped', 'sim_does_not_match_profile'))
            self.assertEqual(g['os'].forks, 0)
            self.assertEqual(list(base.glob('archive')), [])

    def test_a_card_that_never_becomes_ready_is_skipped_after_the_bound(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            (base / 'enabled').write_text('on')
            clock = [3000.0]
            def sleep(seconds):
                clock[0] += seconds
            g['time'] = types.SimpleNamespace(time=lambda: clock[0], sleep=sleep)
            def absent():
                raise AssertionError('SIM not ready')
            g['s'].current_usim = absent
            result = g['boot']()
            self.assertEqual(result['reason'], 'sim_not_ready')
            self.assertEqual(g['os'].forks, 0)
            self.assertLessEqual(clock[0] - 3000.0, 122)

    def test_current_boot_files_are_not_archived(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            (base / 'state/lease.json').write_text(json.dumps({'boot': TOKEN}))
            with self.assertRaises(AssertionError):
                g['archive_previous_boot_files'](TOKEN)
            self.assertTrue((base / 'state/lease.json').exists())


class AcceptanceTests(unittest.TestCase):
    def receipt(self, **values):
        data = {'owner': 'passport-call-acceptance-v1', 'variant': 'SQW100-4',
                'profile_sha256': SHA, 'profile_id': 'passport-mobile-manual-research',
                'incoming': True, 'outgoing': True, 'audio_both_directions': True,
                'lte': True, 'sip_dialogs_verified': True}
        data.update(values)
        return data

    def test_complete_receipt_for_the_active_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            g, unused = namespace(folder)
            self.assertTrue(g['acceptance_valid'](self.receipt(), SHA))

    def test_truthy_strings_other_profiles_and_trials_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            g, unused = namespace(folder)
            self.assertFalse(g['acceptance_valid'](self.receipt(incoming='true'), SHA))
            self.assertFalse(g['acceptance_valid'](self.receipt(), 'other'))
            g['s'].ACTIVE_PROFILE['id'] = 'passport-mobile-hdvoice-manual-research'
            self.assertFalse(g['acceptance_valid'](
                self.receipt(profile_id='passport-mobile-hdvoice-manual-research'), SHA))


class StockHandoffTests(unittest.TestCase):
    def test_missing_idle_evidence_selects_the_passive_wait(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            g['n'].ims_pids = lambda: [77]
            def proof(pid):
                raise AssertionError('not idle yet')
            g['idle_stock_proof'] = proof
            self.assertFalse(g['boot_stock_handoff']())
            self.assertEqual(g['s'].startup_handoff['reason'], 'no_current_idle_stock_evidence')
            self.assertEqual(g['os'].kills, [])
            self.assertEqual(list(base.glob('stock-handoff-*.json')), [])

    def test_two_proofs_record_then_signal_once(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            g['n'].ims_pids = lambda: [77]
            g['idle_stock_proof'] = lambda pid: None
            receipt = base / 'stock-handoff-11.json'
            def kill(pid, signum):
                self.assertTrue(receipt.exists(), 'Persist the attempt before signalling')
                g['os'].kills.append((pid, signum))
            g['os'].kill = kill
            self.assertTrue(g['boot_stock_handoff']())
            self.assertEqual(g['os'].kills, [(77, 15)])
            self.assertFalse(g['boot_stock_handoff']())
            self.assertEqual(g['s'].startup_handoff['reason'], 'already_attempted_this_boot')
            self.assertEqual(len(g['os'].kills), 1)

    def test_continuation_accepts_the_owned_voice_policy_only(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            journal(base)
            g['n'].ims_pids = lambda: [77]
            g['n'].voice_policy = lambda: 3
            g['idle_stock_proof'] = lambda pid: None
            self.assertTrue(g['boot_stock_handoff']())
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            g['n'].ims_pids = lambda: [77]
            g['n'].voice_policy = lambda: 3
            g['idle_stock_proof'] = lambda pid: None
            self.assertFalse(g['boot_stock_handoff']())
            self.assertEqual(g['os'].kills, [])


class WatchdogTests(unittest.TestCase):
    def run_watchdog(self, phase):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            journal(base, boot=list(TOKEN))
            g['s'].STATUS = str(base / 'state/status.json')
            (base / 'state/status.json').write_text(json.dumps({'phase': phase}))
            restored = []
            g['restore_retaining_provider'] = lambda: restored.append(True)
            g['watchdog'](4242, list(TOKEN), 1000.0)
            return restored

    def test_shutdown_exits_keep_the_journal_for_the_next_boot(self):
        self.assertEqual(self.run_watchdog('native_exited'), [])
        self.assertEqual(self.run_watchdog('suspended_for_shutdown'), [])

    def test_an_unexplained_manager_death_is_restored(self):
        self.assertEqual(self.run_watchdog('running'), [True])


class TelecomGateTests(unittest.TestCase):
    TELECOM = {'id': 'passport-telecom-manual-research', 'lte_attach': 'telecom_data_centric_v1'}

    def gate(self, checks, profile):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            g['compatibility'] = types.SimpleNamespace(network_checks=lambda network, p: checks)
            return g['attach_pending']({}, profile)

    def test_only_missing_lte_data_may_wait_before_the_bootstrap(self):
        emergency = [{'id': 'sim', 'status': 'pass'}, {'id': 'lte', 'status': 'wait'},
                     {'id': 'apn', 'status': 'wait'}]
        self.assertTrue(self.gate(emergency, self.TELECOM))
        self.assertFalse(self.gate(emergency, {'id': 'passport-mobile-manual-research'}))
        self.assertFalse(self.gate([{'id': 'sim', 'status': 'wait'}], self.TELECOM))
        self.assertFalse(self.gate([{'id': 'carrier', 'status': 'adapt'}], self.TELECOM))

    def handoff(self, base, g, voice):
        g['network_usable'] = lambda: True
        g['n'].voice_policy = lambda: voice
        return g['handoff_idle_stock']()

    def test_owned_voice_policy_is_accepted_only_for_an_interrupted_run(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            with self.assertRaises(AssertionError):
                self.handoff(base, g, 3)
            journal(base)
            (base / 'state/lock.json').write_text(json.dumps({'pid': 1, 'boot': [10, 1000.0]}))
            self.assertEqual(self.handoff(base, g, 3), {'stock_already_exited': True, 'signal_sent': False})
            journal(base, configuration_restored=True)
            with self.assertRaises(AssertionError):
                self.handoff(base, g, 3)

    def test_profile_selection_tolerates_only_the_stock_engine(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            g['n'].ims_pids = lambda: [77]
            stock = b'Arguments\n/radio/bin/ims_rrm -U 453:31,80,387,427,521,1001\n'
            g['n'].command = lambda argv, timeout=15: stock
            self.assertTrue(g['only_stock_ims']())
            g['n'].command = lambda argv, timeout=15: b'Arguments\n/var/rootdata/x/runtime/ims_rrm -U 453:31\n'
            self.assertFalse(g['only_stock_ims']())

    def test_previous_boot_restore_is_explicit_and_never_under_autostart(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            journal(base)
            calls = []
            g['restore_retaining_provider'] = lambda previous_boot=False: calls.append(previous_boot)
            (base / 'enabled').write_text('on')
            with self.assertRaises(AssertionError):
                g['restore_previous_boot']()
            (base / 'enabled').unlink()
            result = g['restore_previous_boot']()
            self.assertEqual(calls, [True])
            self.assertEqual(result['next'], 'reconcile-after-reboot')
            journal(base, boot=list(TOKEN))
            with self.assertRaises(AssertionError):
                g['restore_previous_boot']()


TELECOM = {'id': 'passport-telecom-manual-research', 'carrier': {'data_apns': ['ctnet', 'ctlte']},
           'lte_attach': 'telecom_data_centric_v1'}
SOURCES = ('ims', 'ims_defaults', 'omadm', 'test')


def telecom_stub(base, g, data_centric=False, ue_usage=0):
    """Create a plan folder with the four DCA sources and stub telecom()/telecom_dca/telecom_native."""
    import sys as _sys
    g['s'].ACTIVE_PROFILE = dict(TELECOM)
    folder = str(base / 'state' / 'telecom-attach-aaaa0000bbbb1111')
    os.mkdir(folder)
    body = b'ue_usage_setting::data_centric\n' if data_centric else b''
    value = {'owner': 'bb10-telecom-attach-v1', 'profile_sha256': SHA,
             'sim_fingerprint': hashlib.sha256(b'usim').hexdigest(), 'files': {}}
    for name in SOURCES:
        (Path(folder) / (name + '.original')).write_bytes(b'')
        src = base / ('src-' + name)
        src.write_bytes(body)
        value['files'][name] = {'path': str(src), 'original_sha256': hashlib.sha256(b'').hexdigest()}
    usage = [ue_usage]
    writes, restores = [], []

    def publish(target, label):
        usage[0] = 1
        return {'output_bytes': 1, 'label': label}
    dca = types.SimpleNamespace(SOURCES=SOURCES, q=None, write_existing=lambda p, b, a, i: writes.append((p, a)),
                                payload=lambda before, kind: before + ('ue_usage_setting::' + kind + '\n').encode(),
                                publish=publish)
    _sys.modules['telecom_dca'] = dca
    _sys.modules['telecom_native'] = types.SimpleNamespace(ue_usage_policy=lambda: usage[0])

    def checked_plan(service, restoring=False):
        return folder, value
    g['telecom'] = lambda: types.SimpleNamespace(checked_plan=checked_plan, prepare=lambda service: {'folder': folder},
                                                 restore=lambda service: restores.append(True))
    return folder, value, writes, restores, usage


def marker(base, folder, persisted_boot):
    (base / 'telecom-datacentric.json').write_text(json.dumps(
        {'owner': 'bb10-telecom-attach-v1', 'plan_folder': folder, 'profile_sha256': SHA,
         'sim_fingerprint': hashlib.sha256(b'usim').hexdigest(), 'persisted_boot': persisted_boot, 'ue_usage': 1}))


class TelecomPersistTests(unittest.TestCase):
    def test_persist_writes_datacentric_marker_and_record_without_reverting(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            plan, value, writes, restores, usage = telecom_stub(base, g)
            result = g['telecom_persist']()
            self.assertTrue(result['data_centric_persisted'] and result['reboot_required'])
            self.assertEqual(len(writes), 4)
            self.assertEqual(restores, [])
            self.assertEqual(usage[0], 1)
            self.assertTrue((base / 'telecom-datacentric.json').exists())
            record = load(str(base / 'state/telecom-bootstrap.json'))
            self.assertEqual((record['owner'], record['plan_folder'], record['phase']),
                             ('bb10-telecom-attach-v1', plan, 'persisted'))

    def test_persist_refuses_when_a_marker_or_journal_exists(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            plan, value, writes, restores, usage = telecom_stub(base, g)
            marker(base, plan, [10, 1000.0])
            with self.assertRaises(AssertionError):
                g['telecom_persist']()
            (base / 'telecom-datacentric.json').unlink()
            journal(base)
            with self.assertRaises(AssertionError):
                g['telecom_persist']()

    def test_launch_fast_path_accepts_previous_boot_persist_and_skips_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            plan, value, writes, restores, usage = telecom_stub(base, g, data_centric=True, ue_usage=1)
            marker(base, plan, [10, 1000.0])
            g['telecom_ensure_lte']()
            self.assertEqual(g['s'].telecom_dca_plan, plan)
            self.assertEqual(writes, [])

    def test_launch_refuses_without_persist_or_in_the_same_boot(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            plan, value, writes, restores, usage = telecom_stub(base, g, data_centric=True, ue_usage=1)
            with self.assertRaises(RuntimeError):
                g['telecom_ensure_lte']()
            marker(base, plan, list(TOKEN))
            with self.assertRaises(AssertionError):
                g['telecom_ensure_lte']()

    def test_launch_fast_path_times_out_if_data_never_comes_up(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            plan, value, writes, restores, usage = telecom_stub(base, g, data_centric=True, ue_usage=1)
            marker(base, plan, [10, 1000.0])
            clock = [3000.0]
            g['time'] = types.SimpleNamespace(time=lambda: clock[0],
                                             sleep=lambda seconds: clock.__setitem__(0, clock[0] + 60))
            g['s'].ready = lambda: False
            with self.assertRaises(AssertionError):
                g['telecom_ensure_lte']()

    def test_revert_without_an_owned_run_restores_and_clears_the_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            plan, value, writes, restores, usage = telecom_stub(base, g, data_centric=True, ue_usage=1)
            marker(base, plan, [10, 1000.0])
            result = g['telecom_revert']()
            self.assertTrue(result['telecom_datacentric_reverted'])
            self.assertEqual(restores, [True])
            self.assertFalse((base / 'telecom-datacentric.json').exists())

    def test_profile_switch_is_blocked_while_datacentric_is_persisted(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            plan, value, writes, restores, usage = telecom_stub(base, g, data_centric=True, ue_usage=1)
            marker(base, plan, [10, 1000.0])
            with self.assertRaises(AssertionError):
                g['select_candidate_profile']()


class AddonOwnershipTests(unittest.TestCase):
    def test_enable_then_disable_restores_the_original_tree(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            script = ADDON_SCRIPT.read_bytes()
            (base / 'addon-start.sh').write_bytes(script)
            result = g['enable_autostart']()
            self.assertTrue(result['enabled'] and result['addon_installed'])
            start = Path(g['ADDON']) / 'init/start.sh'
            self.assertEqual(start.read_bytes(), script)
            self.assertTrue(load(g['AUTOSTART_RECORD'])['created_addons_root'])
            result = g['disable_autostart']()
            self.assertTrue(result['addon_removed'])
            self.assertFalse(Path(g['ADDONS']).exists())
            self.assertFalse((base / 'enabled').exists())

    def test_unowned_addon_content_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            (base / 'addon-start.sh').write_bytes(ADDON_SCRIPT.read_bytes())
            Path(g['ADDONS']).mkdir()
            (Path(g['ADDONS']) / 'other').mkdir()
            g['enable_autostart']()
            self.assertFalse(load(g['AUTOSTART_RECORD'])['created_addons_root'])
            extra = Path(g['ADDON']) / 'data/foreign'
            extra.write_text('keep')
            with self.assertRaises(AssertionError):
                g['disable_autostart']()
            self.assertEqual(extra.read_text(), 'keep')
            self.assertTrue((Path(g['ADDONS']) / 'other').is_dir())

    def test_an_existing_unowned_addon_blocks_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            (base / 'addon-start.sh').write_bytes(ADDON_SCRIPT.read_bytes())
            Path(g['ADDON']).mkdir(parents=True)
            with self.assertRaises(AssertionError):
                g['enable_autostart']()
            self.assertFalse((base / 'enabled').exists())


class MenuTests(unittest.TestCase):
    def test_menu_failures_never_block_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            g, base = namespace(folder)
            g['n'].attrs = lambda data: {}
            g['n'].value = lambda attrs, key, default=None: {'mcc': '460', 'mnc': '01'}
            g['n'].read = lambda path: b''
            self.assertEqual(g['apply_mobile_menu'](), {'applied': False, 'reason': 'not_460_00'})
            g['n'].value = lambda attrs, key, default=None: {'mcc': '460', 'mnc': '00'}
            g['MENU_TOOL'], g['MENU_TOOL_HASH'] = str(base / 'missing.py'), 'x'
            self.assertEqual(g['apply_mobile_menu'](), {'applied': False, 'error_type': 'AssertionError'})


class AddonScriptTests(unittest.TestCase):
    def test_script_is_gated_and_waits_for_root(self):
        data = ADDON_SCRIPT.read_bytes()
        self.assertNotIn(b'\r', data)
        lines = data.decode('ascii').splitlines()
        self.assertEqual(lines[0], '#!/bin/sh')
        enabled = next(i for i, line in enumerate(lines) if 'enabled' in line)
        root = next(i for i, line in enumerate(lines) if 'root.done' in line)
        python = next(i for i, line in enumerate(lines) if '/usr/bin/python3.2' in line)
        self.assertLess(enabled, root)
        self.assertLess(root, python)
        self.assertTrue(lines[python].startswith('exec ') and ' boot ' in lines[python])


if __name__ == '__main__':
    unittest.main()
