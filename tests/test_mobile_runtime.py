"""User-visible success and transaction boundaries; no phone required."""
import contextlib
import base64
import io
import json
import os
import posixpath
import tempfile
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


ENTRY = module('test_mobile_entry', ROOT / 'mobile/runtime/entry.py')
with mock.patch.dict(sys.modules, {'entry': ENTRY}):
    WORKER = module('test_mobile_worker', ROOT / 'mobile/runtime/worker.py')


def ready():
    return {'enabled': True, 'status_from_current_boot': True, 'selected_this_boot': True,
            'current_sim_matches': True, 'phase': 'running', 'manager_alive': True,
            'native_alive': True, 'current': {'ims': 'connected', 'register_status': '200 OK',
                                             'ran': 'LTE', 'radio': ['lte']}}


class MobileRuntimeTests(unittest.TestCase):
    def setUp(self):
        # These tests isolate transaction behavior with synthetic /verified
        # paths. Selection itself has dedicated real-lock tests below.
        patch = mock.patch.object(WORKER, 'require_current_selection')
        self.selection_guard = patch.start()
        self.addCleanup(patch.stop)

    def test_radio_off_hint_requires_one_exact_public_value(self):
        cases = [(b'@status_public\npower_status::OFF\n', 'OFF'),
                 (b'@status_public\n[n]power_status::ON\n', 'ON'),
                 (b'', None), (b'power_status::UNKNOWN\n', None),
                 (b'power_status:n:0\n', None), (b'power_status::OFF\npower_status::ON\n', None),
                 (b'power_status::OFF\npower_status:broken\n', None),
                 (b'power_status::OFF', None), (b'-@status_public\npower_status::OFF\n', None),
                 (b'@status_public\npower_status::OFF\n#@status_public\n', None),
                 (b'@status_public\n[n]power_status::OFF\n*@status_public\n', None),
                 (b'power_status::OFF\n-power_status\n', None),
                 (b'power_status::OFF\n\xff', None), (b'x' * 65537, None)]
        for value, expected in cases:
            with self.subTest(value=value[:80]), mock.patch.dict(sys.modules, {'native': types.SimpleNamespace(read=lambda _: value)}):
                self.assertEqual(WORKER.mobile_radio_state(), expected)
        with mock.patch.dict(sys.modules, {'native': types.SimpleNamespace(read=mock.Mock(side_effect=OSError()))}):
            self.assertIsNone(WORKER.mobile_radio_state())

    def test_radio_off_only_precedes_ready_install_or_enable_not_recovery(self):
        base = {'installed': False, 'sim_supported': True, 'can_install': True}
        with mock.patch.object(WORKER, 'mobile_radio_state', return_value='OFF'):
            for lang in ('zh', 'en'):
                result = WORKER.inspection_response({'language': lang}, dict(base), {})
                self.assertEqual(result['state'], 'mobile_network_off')
                self.assertNotIn('install', result['actions'])
                self.assertTrue(result['display']['message'])
            restored = dict(base, installed_stage='uninstalled')
            self.assertEqual(WORKER.inspection_response({}, restored, {})['state'], 'mobile_network_off')
            pending = dict(base, installed_stage='pending', phase='awaiting_reboot', reboot_required=True)
            self.assertEqual(WORKER.inspection_response({}, pending, {})['state'], 'reboot_required')
            disabled = {'installed': True, 'sim_supported': True, 'status': {'enabled': False, 'phase': 'disabled'}}
            result = WORKER.inspection_response({}, disabled, {})
            self.assertEqual(result['state'], 'mobile_network_off')
            self.assertNotIn('enable', result['actions'])
            self.assertIn('uninstall', result['actions'])
            disabled['can_update'] = True
            self.assertEqual(WORKER.inspection_response({}, disabled, {})['state'], 'update_ready')
        with mock.patch.object(WORKER, 'mobile_radio_state', return_value=None):
            self.assertEqual(WORKER.inspection_response({}, dict(base), {})['state'], 'ready_to_install')

    def test_radio_hint_handles_only_transient_sim_reads_and_never_masks_recovery(self):
        for installed in (False, True):
            for reason in ('sim_not_ready', 'sim_identity_unavailable', 'sim_route_unsupported'):
                for radio in ('OFF', 'ON', None):
                    result = {'installed': installed, 'sim_supported': False, 'sim_reason': reason,
                              'status': {'enabled': False, 'phase': 'disabled'}}
                    with self.subTest(installed=installed, reason=reason, radio=radio), \
                         mock.patch.object(WORKER, 'mobile_radio_state', return_value=radio), \
                         mock.patch.object(WORKER, 'engine') as manager:
                        manager.return_value.BASE = '/absent'
                        actual = WORKER.inspection_response({}, result, {})['state']
                    expected = ('mobile_network_off' if radio == 'OFF' and reason != 'sim_route_unsupported' else
                                'sim_unsupported' if reason == 'sim_route_unsupported' else 'waiting_sim')
                    self.assertEqual(actual, expected)
        result = {'installed': True, 'sim_supported': False, 'sim_reason': 'sim_not_ready',
                  'status': {'enabled': True, 'phase': 'error_restored'}}
        with mock.patch.object(WORKER, 'mobile_radio_state', return_value='OFF'), \
             mock.patch.object(WORKER, 'engine') as manager:
            manager.return_value.BASE = '/absent'
            self.assertEqual(WORKER.inspection_response({}, result, {})['state'], 'recovery_required')

    def test_busy_inspection_preserves_protocol_and_explains_a_confirmed_off_radio(self):
        job = {'id': 'a' * 32, 'action': 'enable', 'state': 'waiting_reboot'}
        for radio in ('OFF', 'ON', None):
            manager = mock.Mock()
            manager.management_lock.side_effect = RuntimeError('management_busy')
            with self.subTest(radio=radio), mock.patch.object(WORKER, 'engine', return_value=manager), \
                 mock.patch.object(WORKER, 'inspection_details', return_value={}), \
                 mock.patch.object(WORKER, 'mobile_radio_state', return_value=radio):
                result = WORKER.inspect({'language': 'en'}, '/verified')
                pending = WORKER.task_observation_unavailable(job, {'language': 'en'}, RuntimeError('management_busy'))
            self.assertEqual(result['state'], 'error')  # Older native clients require this for a failed probe.
            self.assertEqual(result['error']['code'], 'management_busy')
            self.assertEqual(result['details'].get('mobile_network_off', False), radio == 'OFF')
            self.assertEqual(pending['state'], 'task_service_busy_radio_off' if radio == 'OFF' else 'task_service_busy')
            self.assertEqual(pending['job_id'], job['id'])
            self.assertEqual(pending['job']['state'], 'waiting_reboot')
            manager.manage.assert_not_called()

    def test_radio_off_write_recheck_preserves_the_same_resumable_job(self):
        for action, phase in (('install', 'checking'), ('install', 'exporting_original_backup'), ('enable', 'checking')):
            job = {'id': 'a' * 32, 'attempt': 'b' * 32, 'action': action, 'request': {},
                   'bundle': '/verified', 'state': 'queued', 'phase': phase,
                   'worker_safety': WORKER.SAFE_JOB_GUARD, 'commit_outcome_unknown': False}
            def progress(value, new_phase, **fields):
                value.update(phase=new_phase, **fields)
            engine = mock.Mock(BASE='/owned')
            engine.management_lock.return_value = contextlib.nullcontext()
            with self.subTest(action=action, phase=phase), \
                 mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
                 mock.patch.object(WORKER, 'load', return_value=job), \
                 mock.patch.object(WORKER, 'progress', side_effect=progress), \
                 mock.patch.object(WORKER, 'mobile_radio_state', return_value='OFF'), \
                 mock.patch.object(ENTRY, 'private_directory'), mock.patch.object(ENTRY, 'read_bundle'), \
                 mock.patch.object(WORKER, 'engine', return_value=engine), \
                 mock.patch.object(WORKER, 'stage_payload') as stage:
                WORKER.run_job(job['id'], job['attempt'])
            self.assertEqual(job['id'], 'a' * 32)
            self.assertEqual(job['state'], 'failed')
            self.assertEqual(job['error_code'], 'mobile_network_off')
            self.assertFalse(job['commit_outcome_unknown'])
            self.assertTrue(WORKER.resumable_job(job))
            stage.assert_not_called()
            engine.manage.assert_not_called()
            for language, title in (('zh', '上次操作时移动网络关闭'), ('en', 'Mobile network was off')):
                response = WORKER.job_response(job, {'language': language})
                self.assertEqual(response['state'], 'recovery_required')
                self.assertEqual(response['display']['title'], title)
                self.assertEqual(response['display_i18n']['en']['primary_label'], 'Continue task')
                self.assertFalse(response['ok'])
                self.assertEqual(response['job_id'], job['id'])
                self.assertEqual(response['primary_action'], 'resume')

    def test_diagnostic_task_summary_is_bounded_and_never_exports_identity(self):
        job = {'id': 'f' * 32, 'action': 'enable', 'state': 'interrupted',
               'phase': 'enable', 'error_code': 'worker_interrupted',
               'request': {'imsi': 'private-sim-token'}, 'message': 'private data', 'binding': 'secret'}
        with mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
             mock.patch.object(WORKER, 'active_job', return_value=job), mock.patch.object(WORKER, 'save') as save:
            summary = WORKER.diagnostic_job_summary('f' * 32)
        self.assertEqual(summary, {'availability': 'matching_snapshot_only', 'action': 'enable', 'state': 'interrupted',
                                   'phase': 'enable', 'error_code': 'worker_interrupted'})
        self.assertNotIn('private-sim-token', str(summary))
        self.assertNotIn('f' * 32, str(summary))
        save.assert_not_called()
        job.update(phase='secret_identity', error_code='imsi_private_sim_token')
        with mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
             mock.patch.object(WORKER, 'active_job', return_value=job):
            summary = WORKER.diagnostic_job_summary('f' * 32)
            matching = WORKER.diagnostic_job_summary('f' * 32)
            different = WORKER.diagnostic_job_summary('a' * 32)
        self.assertEqual(summary['phase'], 'other')
        self.assertEqual(summary['error_code'], 'other')
        self.assertEqual(matching['availability'], 'matching_snapshot_only')
        self.assertEqual(different, {'availability': 'different_active_task'})
        self.assertNotIn('f' * 32, str(matching))
        with mock.patch.object(WORKER, 'job_lock', side_effect=ENTRY.MobileError('operation_in_progress')) as lock:
            self.assertEqual(WORKER.diagnostic_job_summary(), {'availability': 'not_requested'})
            lock.assert_not_called()
            self.assertEqual(WORKER.diagnostic_job_summary('f' * 32), {'availability': 'unavailable'})

    def test_online_update_requires_selected_runtime_capability_before_dispatch(self):
        request = {'schema': 2, 'package_path': '/accounts/1000/shared/downloads/update.zip',
                   'expected_version': '0.1.0.16', 'expected_sha256': 'a' * 64}
        encoded = base64.b64encode(ENTRY.canonical(request)).decode('ascii')
        for capabilities in (None, 'expected_update_version_v1', [], ['expected_update_version_v1']):
            output = io.StringIO()
            worker = types.SimpleNamespace(dispatch=mock.Mock(return_value={'ok': True, 'state': 'working'}))
            with self.subTest(capabilities=capabilities), \
                 mock.patch.object(ENTRY, 'BRIDGE_PROGRESS', False), \
                 mock.patch.object(ENTRY.sys, 'argv', ['entry.py', 'update', encoded, '/bundle']), \
                 mock.patch.object(ENTRY.sys, 'path', list(ENTRY.sys.path)), \
                 mock.patch.object(ENTRY.os, 'geteuid', return_value=0, create=True), \
                 mock.patch.object(ENTRY.os, 'uname', return_value=('QNX',), create=True), \
                 mock.patch.dict(sys.modules, {'test_mobile_entry': ENTRY, 'worker': worker}), \
                 mock.patch.object(ENTRY, 'bridge_entry_bytes', return_value=b'entry'), \
                 mock.patch.object(ENTRY, 'source_snapshot', return_value=('/snapshot/fallback', 'fallback proof')), \
                 mock.patch.object(ENTRY, 'active_bundle', return_value=('/snapshot/active', 'active proof')), \
                 mock.patch.object(ENTRY, 'trusted_python', return_value={'capabilities': capabilities}) as trust, \
                 contextlib.redirect_stdout(output):
                if isinstance(capabilities, list) and 'expected_update_version_v1' in capabilities:
                    ENTRY.main()
                    worker.dispatch.assert_called_once_with('update', request, '/snapshot/active')
                    self.assertTrue(json.loads(output.getvalue().splitlines()[-1])['ok'])
                else:
                    with self.assertRaisesRegex(ENTRY.MobileError, 'update_runtime_upgrade_required'):
                        ENTRY.main()
                    worker.dispatch.assert_not_called()
                trust.assert_called_once_with('/snapshot/active', 'active proof')

    def test_online_update_binds_signed_version_and_hash_before_staging(self):
        request = {'operation_id': 'a' * 32, 'package_path': '/accounts/1000/shared/downloads/update.zip',
                   'expected_version': '0.1.0.16', 'expected_sha256': 'b' * 64}
        for version in ('0.1.0.15', '0.1.0.16'):
            job = {'id': request['operation_id'], 'action': 'update', 'request': request, 'bundle': '/verified'}
            bundle = ({'version': version}, b'', b'', {})
            native = types.SimpleNamespace(command=mock.Mock(return_value=b'{"ok":true,"updated":false}'))
            def progress(value, phase, **fields):
                value.update(phase=phase, **fields)
            with self.subTest(version=version), mock.patch.dict(sys.modules, {'native': native}), \
                 mock.patch.object(ENTRY, 'private_directory'), mock.patch.object(ENTRY, 'read_bundle'), \
                 mock.patch.object(ENTRY, 'read_archive', return_value=bundle) as read_archive, \
                 mock.patch.object(ENTRY, 'snapshot', return_value='/candidate') as snapshot, \
                 mock.patch.object(ENTRY, 'trusted_python'), mock.patch.object(WORKER, 'engine'), \
                 mock.patch.object(WORKER, 'load', return_value={'version': '0.1.0.14'}), \
                 mock.patch.object(WORKER, 'save'), mock.patch.object(WORKER, 'progress', side_effect=progress), \
                 mock.patch.object(WORKER.os.path, 'isfile', return_value=False):
                if version == '0.1.0.15':
                    with self.assertRaisesRegex(ENTRY.MobileError, 'update_version_mismatch'):
                        WORKER.run_operation(job)
                    snapshot.assert_not_called()
                    native.command.assert_not_called()
                else:
                    self.assertTrue(WORKER.run_operation(job)['ok'])
                    snapshot.assert_called_once_with(bundle)
                    native.command.assert_called_once()
                read_archive.assert_called_once_with(request['package_path'], expected_sha256=request['expected_sha256'])

    def test_update_prelock_busy_receipt_requires_capability_and_exact_identity(self):
        operation = 'a' * 32
        valid = {'ok': False, 'error_code': 'management_busy', 'operation_id': operation, 'not_dispatched': True}
        cases = [([WORKER.PRELOCK_UPDATE_GUARD], valid, True, False),
                 ([WORKER.PRELOCK_UPDATE_GUARD], valid, True, True),  # old entry returns no manifest
                 ([], valid, False, False),
                 ([WORKER.PRELOCK_UPDATE_GUARD], dict(valid, operation_id='b' * 32), False, False),
                 ([WORKER.PRELOCK_UPDATE_GUARD], dict(valid, not_dispatched=False), False, False),
                 ([WORKER.PRELOCK_UPDATE_GUARD], dict(valid, extra=True), False, False)]
        for capabilities, receipt, safe, legacy_entry in cases:
            job = {'id': operation, 'action': 'update', 'request': {}, 'bundle': '/verified',
                   'commit_outcome_unknown': False}
            native = types.SimpleNamespace(command=mock.Mock(return_value=ENTRY.canonical(receipt)))
            manager = mock.Mock(BASE='/owned')
            with self.subTest(capabilities=capabilities, receipt=receipt, legacy_entry=legacy_entry), \
                 mock.patch.dict(sys.modules, {'native': native}), \
                 mock.patch.object(ENTRY, 'private_directory'), \
                 mock.patch.object(ENTRY, 'read_bundle', return_value=({'capabilities': capabilities},)), \
                 mock.patch.object(ENTRY, 'trusted_python', return_value=None if legacy_entry else {'capabilities': capabilities}), \
                 mock.patch.object(WORKER, 'engine', return_value=manager), \
                 mock.patch.object(WORKER, 'save'), mock.patch.object(WORKER, 'progress'), \
                 mock.patch.object(WORKER.os.path, 'isfile', return_value=False):
                with self.assertRaisesRegex(ENTRY.MobileError, 'management_busy'):
                    WORKER.run_operation(job)
            self.assertEqual(job['commit_outcome_unknown'], not safe)
            self.assertEqual(job.get('resumable_failure'), safe)

    def test_signed_child_only_attests_busy_before_entering_manager_lock(self):
        with mock.patch.dict(sys.modules, {'entry': ENTRY}):
            child = module('test_mobile_job_entry', ROOT / 'mobile/runtime/job_entry.py')
        raw = b'signed manifest fixture'
        folder = '/var/test/snapshots/' + ENTRY.digest(raw)
        request = {'action': 'engine-update', 'operation_id': 'a' * 32}
        encoded = base64.b64encode(ENTRY.canonical(request)).decode('ascii')
        fake_worker = types.SimpleNamespace(stage_payload=mock.Mock(return_value='/stage'))
        for entered in (False, True):
            manager = types.SimpleNamespace(management_lock=mock.Mock(
                return_value=contextlib.nullcontext() if entered else None),
                s=types.SimpleNamespace(load=mock.Mock(side_effect=RuntimeError('management_busy'))), BASE='/owned')
            if not entered:
                manager.management_lock.side_effect = RuntimeError('management_busy')
            with self.subTest(entered=entered), \
                 mock.patch.object(child, '__file__', folder + '/runtime/job_entry.py'), \
                 mock.patch.object(ENTRY, 'ROOT', '/var/test'), mock.patch.object(ENTRY.os, 'path', posixpath), \
                 mock.patch.object(ENTRY.os, 'geteuid', return_value=0, create=True), \
                 mock.patch.object(ENTRY.os, 'uname', return_value=('QNX',), create=True), \
                 mock.patch.object(ENTRY, 'private_directory'), \
                 mock.patch.object(ENTRY, 'read_bundle', return_value=({}, raw, b'', {})), \
                 mock.patch.object(ENTRY.sys, 'argv', ['job_entry.py', encoded]), \
                 mock.patch.object(ENTRY.sys, 'path', list(ENTRY.sys.path)), \
                 mock.patch.dict(sys.modules, {'worker': fake_worker, 'unified_install': manager}):
                if entered:
                    with self.assertRaisesRegex(RuntimeError, 'management_busy'):
                        child.main()
                else:
                    self.assertEqual(child.main(), {'ok': False, 'error_code': 'management_busy',
                                                    'operation_id': request['operation_id'], 'not_dispatched': True})

    def test_detached_child_entries_keep_stdout_as_one_json_response(self):
        for name in ('job_entry.py', 'legacy_entry.py'):
            output = io.StringIO()
            path = '/var/bb10_volte-mobile/snapshots/' + 'a' * 64 + '/runtime/' + name
            def read_bundle(folder):
                ENTRY.bridge_progress()
                return ({}, b'wrong snapshot', b'', {})
            source = (ROOT / 'mobile/runtime' / name).read_text(encoding='utf-8')
            with self.subTest(entry=name), mock.patch.object(ENTRY, 'BRIDGE_PROGRESS', False), \
                 mock.patch.object(ENTRY.os, 'geteuid', return_value=0, create=True), \
                 mock.patch.object(ENTRY.os, 'uname', return_value=('QNX',), create=True), \
                 mock.patch.object(ENTRY.os, 'path', posixpath), \
                 mock.patch.object(posixpath, 'realpath', side_effect=lambda value: value), \
                 mock.patch.object(ENTRY, 'private_directory'), \
                 mock.patch.object(ENTRY, 'read_bundle', side_effect=read_bundle) as read, \
                 mock.patch.dict(sys.modules, {'entry': ENTRY}), contextlib.redirect_stdout(output):
                exec(compile(source, path, 'exec'), {'__name__': '__main__', '__file__': path})
            read.assert_called_once()
            lines = output.getvalue().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertFalse(json.loads(lines[0])['ok'])

    def test_historical_device_write_failures_without_a_classification_are_protected(self):
        actions = ('install', 'enable', 'disable', 'update', 'rollback', 'uninstall',
                   'legacy-install', 'legacy-start', 'legacy-stop', 'legacy-update', 'legacy-uninstall')
        for action in actions:
            for state in ('failed', 'interrupted'):
                job = {'id': 'a' * 32, 'action': action, 'state': state,
                       'phase': action, 'resumable_failure': False}
                with self.subTest(action=action, state=state):
                    self.assertTrue(WORKER.unknown_job_outcome(job))
                    self.assertTrue(WORKER.protected_job(job))
                    self.assertEqual(WORKER.job_response(job, {})['state'], 'job_outcome_unknown')

    def test_old_multiphase_job_cannot_spawn_even_with_forged_new_journal_marker(self):
        old_boot, new_boot = ['owner', '1' * 48], ['owner', '2' * 48]
        for marker in (None, WORKER.SAFE_JOB_GUARD):
            job = {'id': 'a' * 32, 'action': 'uninstall', 'state': 'waiting_reboot',
                   'phase': 'awaiting_reboot', 'boot': old_boot, 'bundle': '/old', 'request': {}}
            if marker:
                job['worker_safety'] = marker
            with self.subTest(marker=marker), \
                 mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
                 mock.patch.object(WORKER, 'active_job', return_value=job), \
                 mock.patch.object(WORKER, 'load', return_value=job), \
                 mock.patch.object(WORKER, 'boot', return_value=new_boot), \
                 mock.patch.object(ENTRY, 'read_bundle', return_value=({'version': '0.1.0.13'},)), \
                 mock.patch.object(WORKER, 'spawn') as spawn:
                if marker is None:
                    self.assertEqual(WORKER.observed_job_response(job, {}, '/new')['state'], 'job_outcome_unknown')
                with self.assertRaisesRegex(ENTRY.MobileError, 'legacy_job_requires_review'):
                    WORKER.resume({'job_id': job['id']})
                spawn.assert_not_called()
                self.assertEqual(job['state'], 'waiting_reboot')

    def test_spawn_rejects_signed_old_worker_even_if_journal_claims_new_guard(self):
        job = {'id': 'a' * 32, 'attempt': 'b' * 32, 'action': 'enable', 'state': 'queued',
               'phase': 'checking', 'bundle': '/old', 'worker_safety': WORKER.SAFE_JOB_GUARD,
               'commit_outcome_unknown': False}
        native = types.SimpleNamespace(command=mock.Mock())
        with mock.patch.dict(sys.modules, {'native': native}), \
             mock.patch.object(ENTRY, 'read_bundle', return_value=({'version': '0.1.0.15'},)), \
             mock.patch.object(ENTRY, 'trusted_python') as trust, mock.patch.object(WORKER, 'save'):
            WORKER.spawn(job)
        native.command.assert_not_called()
        trust.assert_not_called()
        self.assertTrue(WORKER.unknown_job_outcome(job))
        self.assertEqual(WORKER.job_response(job, {})['state'], 'job_outcome_unknown')

    def test_rollback_never_selects_an_unguarded_management_component(self):
        for runtime_only in (False, True):
            prior = {'before_bundle': '/old', 'after_bundle': '/new', 'engine_result': {'runtime_only': runtime_only}}
            job = {'id': 'a' * 32, 'action': 'rollback', 'request': {}, 'bundle': '/new',
                   'commit_outcome_unknown': False, 'worker_safety': WORKER.SAFE_JOB_GUARD}
            manager = mock.Mock(BASE='/owned')
            manager.manage.return_value = {'rolled_back': True}
            manager.management_lock.return_value = contextlib.nullcontext()
            def read_bundle(folder):
                # v16 has the older outcome guard but not the newer active
                # selection guard, so it cannot replace this management code.
                return ({'version': '0.1.0.16', 'capabilities': [WORKER.SAFE_JOB_GUARD]} if folder == '/old' else
                        {'version': '0.1.0.17', 'capabilities': [WORKER.SAFE_JOB_GUARD, WORKER.SELECTION_GUARD]},)
            with self.subTest(runtime_only=runtime_only), mock.patch.object(ENTRY, 'private_directory'), \
                 mock.patch.object(ENTRY, 'read_bundle', side_effect=read_bundle), \
                 mock.patch.object(WORKER, 'engine', return_value=manager), \
                 mock.patch.object(WORKER, 'load', return_value=prior), \
                 mock.patch.object(WORKER, 'progress'), mock.patch.object(WORKER, 'save') as save, \
                 mock.patch.object(WORKER.os.path, 'isfile', return_value=True):
                if runtime_only:
                    with self.assertRaisesRegex(ENTRY.MobileError, 'rollback_component_too_old'):
                        WORKER.run_operation(job)
                    manager.manage.assert_not_called()
                else:
                    result = WORKER.run_operation(job)
                    self.assertTrue(result['management_component_retained'])
                    manager.manage.assert_called_once_with('rollback', operation_id=job['id'])
                save.assert_not_called()

    def test_service_detection_does_not_confuse_management_bundle_with_installed_service(self):
        cases = (
            ({'installed': True, 'installed_stage': 'legacy', 'sim_supported': False}, 'installed'),
            ({'installed': False, 'installed_stage': 'absent', 'legacy_detected': False, 'sim_supported': False}, 'absent'),
            ({'installed': False, 'installed_stage': 'absent', 'legacy_detected': True, 'sim_supported': False}, 'legacy'),
            ({'installed': True, 'installed_stage': 'managed', 'sim_supported': False}, 'installed'),
            ({'installed': True, 'installed_stage': 'pending', 'phase': 'removing_payload'}, 'pending'),
            ({'installed': False, 'scope_error': 'os_not_supported'}, 'unknown'),
        )
        for result, expected in cases:
            with self.subTest(result=result), mock.patch.object(WORKER.os.path, 'isfile', return_value=False):
                response = WORKER.inspection_response({}, result, {'version': '0.1.0.16'})
            self.assertEqual(response['details']['version'], '0.1.0.16')
            self.assertEqual(response['details']['service_state'], expected)

    def test_interrupted_manual_export_does_not_block_device_writes(self):
        for action in ('export', 'compatibility'):
            job = {'id': 'a' * 32, 'action': action, 'state': 'running', 'phase': 'checking',
                   'created': 100, 'updated': 100, 'request': {'export_kind': 'backup'}}
            def progress(value, phase, **fields):
                value.update(fields)
            with self.subTest(action=action), \
                 mock.patch.object(WORKER, 'job_lock', side_effect=lambda **kwargs: contextlib.nullcontext()), \
                 mock.patch.object(WORKER, 'load', return_value=job), \
                 mock.patch.object(WORKER, 'progress', side_effect=progress):
                WORKER.recover_job(job)
            self.assertEqual(job['state'], 'interrupted')
            self.assertFalse(job['commit_outcome_unknown'])
            self.assertFalse(WORKER.protected_job(job))
            self.assertEqual(WORKER.job_response(job, {})['state'], 'export_interrupted')
            with mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
                 mock.patch.object(WORKER.os.path, 'isfile', return_value=False), \
                 mock.patch.object(WORKER, 'active_job', return_value=job), \
                 mock.patch.object(WORKER, 'boot', return_value=['owner', '1' * 48]), \
                 mock.patch.object(WORKER, 'save'), mock.patch.object(WORKER, 'spawn') as spawn:
                WORKER.submit('enable', {'operation_id': 'b' * 32}, '/verified')
                spawn.assert_called_once()

    def test_busy_call_before_enable_or_disable_is_known_no_write(self):
        for action in ('enable', 'disable'):
            job = {'id': 'a' * 32, 'attempt': 'b' * 32, 'action': action,
                   'state': 'queued', 'phase': 'checking', 'request': {}, 'bundle': '/verified',
                   'commit_outcome_unknown': False, 'worker_safety': WORKER.SAFE_JOB_GUARD}
            manager = mock.Mock(BASE='/owned')
            manager.s.phone_idle.return_value = False
            def progress(value, phase, **fields):
                value.update(phase=phase, **fields)
            with self.subTest(action=action), \
                 mock.patch.object(WORKER, 'job_lock', side_effect=lambda **kwargs: contextlib.nullcontext()), \
                 mock.patch.object(WORKER, 'load', return_value=job), \
                 mock.patch.object(WORKER, 'progress', side_effect=progress), \
                 mock.patch.object(ENTRY, 'private_directory'), mock.patch.object(ENTRY, 'read_bundle'), \
                 mock.patch.object(WORKER, 'engine', return_value=manager):
                WORKER.run_job(job['id'], job['attempt'])
            self.assertEqual(job['state'], 'failed')
            self.assertEqual(job['error_code'], 'call_active')
            self.assertFalse(WORKER.unknown_job_outcome(job))
            self.assertEqual(WORKER.job_response(job, {})['primary_action'], 'resume')
            manager.manage.assert_not_called()

    def test_recoverable_failed_jobs_cannot_be_replaced_by_a_new_submission(self):
        operation = 'b' * 32
        for state in ('failed', 'interrupted'):
            for action in ('install', 'enable', 'disable', 'rollback', 'uninstall', 'legacy-install', 'update'):
                previous = {'id': 'a' * 32, 'action': action, 'state': state,
                            'phase': 'exporting_original_backup', 'candidate': '/verified',
                            'resumable_failure': True}
                with self.subTest(state=state, action=action), \
                     mock.patch.object(WORKER, 'job_lock', side_effect=contextlib.nullcontext), \
                     mock.patch.object(WORKER.os.path, 'isfile', return_value=False), \
                     mock.patch.object(WORKER, 'active_job', return_value=previous), \
                     mock.patch.object(WORKER, 'save') as save, mock.patch.object(WORKER, 'spawn') as spawn:
                    with self.assertRaisesRegex(ENTRY.MobileError, 'operation_in_progress'):
                        WORKER.submit('enable', {'operation_id': operation}, '/verified')
                    save.assert_not_called()
                    spawn.assert_not_called()

    def test_nonrecoverable_failure_allows_new_job_and_same_id_stays_idempotent(self):
        operation = 'b' * 32
        old = {'id': 'a' * 32, 'action': 'export', 'state': 'failed', 'phase': 'checking'}
        with mock.patch.object(WORKER, 'job_lock', side_effect=contextlib.nullcontext), \
             mock.patch.object(WORKER.os.path, 'isfile', return_value=False), \
             mock.patch.object(WORKER, 'active_job', return_value=old), \
             mock.patch.object(WORKER, 'boot', return_value=['boot']), \
             mock.patch.object(WORKER, 'save') as save, mock.patch.object(WORKER, 'spawn') as spawn:
            response = WORKER.submit('enable', {'operation_id': operation}, '/verified')
        self.assertEqual(response['job_id'], operation)
        self.assertEqual(save.call_count, 2)
        spawn.assert_called_once()
        request = {'operation_id': operation}
        prior = {'id': operation, 'action': 'enable', 'request': request,
                 'state': 'interrupted', 'phase': 'checking'}
        with mock.patch.object(WORKER, 'job_lock', side_effect=contextlib.nullcontext), \
             mock.patch.object(WORKER.os.path, 'isfile', return_value=True), \
             mock.patch.object(WORKER, 'load', return_value=prior), \
             mock.patch.object(WORKER, 'save') as save, mock.patch.object(WORKER, 'spawn') as spawn:
            response = WORKER.submit('enable', request, '/verified')
        self.assertEqual(response['job_id'], operation)
        save.assert_not_called()
        spawn.assert_not_called()

    def test_pending_uninstall_primary_action_matches_its_label(self):
        for reboot in (True, False):
            result = {'installed_stage': 'pending', 'phase': 'awaiting_reboot' if reboot else 'removing_hook',
                      'installed': True, 'reboot_required': reboot}
            response = WORKER.inspection_response({'language': 'zh'}, result, {})
            if reboot:
                self.assertEqual(response['state'], 'reboot_required')
                self.assertEqual(response['primary_action'], 'status')
                self.assertNotIn('uninstall', response['actions'])
            else:
                self.assertEqual(response['state'], 'uninstall_recovery_required')
                self.assertEqual(response['primary_action'], 'status')
                self.assertIn('uninstall', response['actions'])
                self.assertEqual(response['display']['primary_label'], '重新检查')

    def test_failed_probe_is_not_an_unsupported_device(self):
        with mock.patch.object(WORKER, 'inspection_details', return_value={}), \
             mock.patch.object(WORKER, 'engine') as manager:
            manager.return_value.manage.side_effect = RuntimeError('private timeout details')
            response = WORKER.inspect({'language': 'en'}, '/verified')
        self.assertFalse(response['ok'])
        self.assertEqual(response['state'], 'error')
        self.assertEqual(response['error']['code'], 'preflight_or_recovery_check_failed')
        self.assertNotIn('private timeout details', str(response))

    def test_completed_observation_can_change_language_without_another_operation(self):
        # An English request may finish after the UI has switched to Chinese.
        # Both presentations belong to the same observation and acceptance.
        with mock.patch.object(WORKER, 'engine') as manager:
            response = WORKER.ui('verified', 'en', 'status', {'version': '0.1.0.11'},
                                 actions=['status', 'confirm-calls'], call_context='a' * 32)
        manager.assert_not_called()
        self.assertEqual(response['display']['primary_label'], 'Refresh')
        self.assertEqual(response['display_i18n']['zh']['primary_label'], '刷新状态')
        self.assertEqual(response['display_i18n']['zh']['title'], '当前 SIM 已完成通话验收')
        self.assertEqual(response['call_context'], 'a' * 32)
        self.assertEqual(response['actions'], ['status', 'confirm-calls'])

    def test_every_state_has_complete_bilingual_presentation_for_late_responses(self):
        for state in WORKER.MESSAGES:
            for language in ('zh', 'en'):
                response = WORKER.ui(state, language, ok=state != 'error')
                self.assertEqual(response['display_language'], language)
                self.assertEqual(response['display'], response['display_i18n'][language])
                for field in ('title', 'message', 'primary_label'):
                    self.assertRegex(response['display_i18n']['zh'][field], r'[\u4e00-\u9fff]')
                    self.assertNotRegex(response['display_i18n']['en'][field], r'[\u4e00-\u9fff]')
                self.assertEqual(response['ok'], state != 'error')

    def test_export_child_has_only_shared_storage_credentials_before_writing(self):
        class ChildExit(BaseException):
            pass
        # Run the actual child branch without changing the test runner's IDs.
        # Every privilege failure must stop before any shared-storage traversal.
        import os
        import json
        for failure in (None, 'setgroups', 'setgid', 'setuid', 'readback'):
            credentials = {'uid': 0, 'euid': 0, 'gid': 0, 'egid': 0, 'groups': [0, 1, 3]}
            output = []
            visited = []
            def change(name, values):
                if failure == name:
                    raise OSError('permission denied')
                credentials.update(values)
            def write_export(*args):
                self.assertEqual(credentials, {'uid': 1000, 'euid': 1000, 'gid': 1001,
                                               'egid': 1001, 'groups': []})
                visited.append(True)
                return '/accounts/1000/shared/documents/BB10-VoLTE/' + 'a' * 32
            read_fd, write_fd = os.pipe()
            try:
                with self.subTest(failure=failure), contextlib.ExitStack() as stack:
                    methods = {
                        'pipe': lambda: (read_fd, write_fd), 'fork': lambda: 0,
                        'setgroups': lambda groups: change('setgroups', {'groups': groups}),
                        'setgid': lambda gid: change('setgid', {'gid': gid, 'egid': gid}),
                        'setuid': lambda uid: change('setuid', {'uid': uid, 'euid': uid}),
                        'getuid': lambda: credentials['uid'], 'geteuid': lambda: credentials['euid'],
                        'getgid': lambda: credentials['gid'], 'getegid': lambda: credentials['egid'],
                        'getgroups': lambda: [0] if failure == 'readback' else credentials['groups'],
                        'write': lambda fd, data: output.append(json.loads(data)),
                        '_exit': mock.Mock(side_effect=ChildExit),
                    }
                    for name, function in methods.items():
                        stack.enter_context(mock.patch.object(WORKER.os, name, function, create=True))
                    stack.enter_context(mock.patch.object(WORKER, 'export_as_user', side_effect=write_export))
                    with self.assertRaises(ChildExit):
                        WORKER.export_blobs({'probe.txt': b'nonprivate'}, 'internal', 'a' * 32)
                    self.assertEqual(bool(visited), failure is None)
                    self.assertEqual(output[0]['ok'], failure is None)
            finally:
                os.close(write_fd)

    def test_registration_requires_live_sim_boot_and_owned_process(self):
        self.assertTrue(WORKER.registered(ready()))
        for field in ('enabled', 'status_from_current_boot', 'selected_this_boot',
                      'current_sim_matches', 'manager_alive', 'native_alive'):
            for value in (None, False):
                state = ready()
                state[field] = value
                self.assertFalse(WORKER.registered(state), field)
        for field, value in (('ims', 'disconnected'), ('register_status', '403 Forbidden'),
                             ('ran', 'WLAN'), ('radio', ['umts'])):
            state = ready()
            state['current'][field] = value
            self.assertFalse(WORKER.registered(state), field)

    def test_old_desktop_install_promotes_only_a_ready_bundled_update(self):
        manager = mock.Mock(BASE='/owned')
        manager.management_lock.return_value = contextlib.nullcontext()
        for ready_update in (False, True):
            manager.manage.return_value = {'installed': True, 'installed_management_schema': 1,
                'sim_supported': True, 'can_update': ready_update, 'status': {'enabled': False}}
            with mock.patch.object(WORKER, 'engine', return_value=manager), \
                 mock.patch.object(WORKER, 'sanitized_identity', return_value={}), \
                 mock.patch.object(WORKER, 'load', return_value={'version': '0.1.0.5'}):
                response = WORKER.inspect({}, '/verified')
            self.assertEqual(response['primary_action'], 'update' if ready_update else 'enable')
            self.assertEqual(response['details']['bundled_update_available'], ready_update)

    def test_active_old_engine_offers_restoration_without_waiting_for_registration(self):
        manager = mock.Mock(BASE='/owned')
        manager.management_lock.return_value = contextlib.nullcontext()
        for phase in ('registering', 'running'):
            manager.manage.return_value = {'installed': True, 'installed_management_schema': 1,
                'sim_supported': True, 'can_update': False, 'update_available': True,
                'status': dict(ready(), phase=phase)}
            with mock.patch.object(WORKER, 'engine', return_value=manager), \
                 mock.patch.object(WORKER, 'sanitized_identity', return_value={}), \
                 mock.patch.object(WORKER, 'load', return_value={'version': '0.1.0.13'}), \
                 mock.patch.object(WORKER, 'call_context') as context:
                response = WORKER.inspect({}, '/verified')
            self.assertEqual(response['state'], 'update_requires_stop')
            self.assertEqual(response['primary_action'], 'disable')
            self.assertNotIn('update', response['actions'])
            self.assertNotIn('confirm-calls', response['actions'])
            context.assert_not_called()
            manager.manage.assert_called_with('probe')

    def test_ims_waits_do_not_describe_web_access_as_disconnected(self):
        manager = mock.Mock(BASE='/owned')
        manager.management_lock.return_value = contextlib.nullcontext()
        for phase, state in (('registering', 'waiting_ims'),
                             ('waiting_for_ims_apn', 'waiting_ims_apn'),
                             ('waiting_for_lte_and_usim', 'waiting')):
            manager.manage.return_value = {'installed': True, 'installed_management_schema': 2,
                'sim_supported': True, 'can_update': False, 'update_available': False,
                'status': dict(ready(), phase=phase)}
            with mock.patch.object(WORKER, 'engine', return_value=manager), \
                 mock.patch.object(WORKER, 'sanitized_identity', return_value={}), \
                 mock.patch.object(WORKER, 'load', return_value={'version': '0.1.0.13'}):
                response = WORKER.inspect({}, '/verified')
            self.assertEqual(response['state'], state)
            self.assertEqual(response['primary_action'], 'status')
            self.assertNotIn('confirm-calls', response['actions'])

    def test_sim_startup_wait_differs_from_a_rejected_card_and_cannot_activate(self):
        for installed in (False, True):
            for reason, expected in (('sim_not_ready', 'waiting_sim'),
                                     ('sim_identity_unavailable', 'waiting_sim'),
                                     ('sim_route_unsupported', 'sim_unsupported'),
                                     ('carrier_not_validated', 'sim_unsupported')):
                with self.subTest(installed=installed, reason=reason):
                    result = {'installed': installed, 'installed_management_schema': 2,
                              'sim_supported': False, 'sim_reason': reason,
                              'status': dict(ready(), phase='waiting_for_lte_and_usim')}
                    with mock.patch.object(WORKER, 'engine') as manager:
                        manager.return_value.BASE = '/absent'
                        response = WORKER.inspection_response({'language': 'zh'}, result, {})
                    self.assertEqual(response['state'], expected)
                    self.assertEqual(response['primary_action'], 'status')
                    self.assertNotIn('install', response['actions'])
                    self.assertNotIn('enable', response['actions'])

    def test_sim_startup_wait_does_not_hide_required_restart_or_restoration(self):
        for reason in ('sim_not_ready', 'sim_identity_unavailable'):
            for phase, expected in (('reboot_required', 'reboot_required'),
                                    ('carrier_reboot_required', 'carrier_reboot_required'),
                                    ('native_exited', 'reboot_required'),
                                    ('error', 'recovery_required'),
                                    ('error_restored', 'recovery_required'),
                                    ('cleanup_required', 'recovery_required')):
                with self.subTest(reason=reason, phase=phase):
                    status = dict(ready(), phase=phase, current_sim_matches=None)
                    result = {'installed': True, 'installed_management_schema': 2,
                              'sim_supported': False, 'sim_reason': reason, 'status': status}
                    with mock.patch.object(WORKER, 'engine') as manager:
                        manager.return_value.BASE = '/absent'
                        response = WORKER.inspection_response({'language': 'zh'}, result, {})
                    self.assertEqual(response['state'], expected)
                    self.assertEqual(response['primary_action'], 'status')
            result['status'] = dict(ready(), phase='running', current_sim_matches=False)
            with mock.patch.object(WORKER, 'engine') as manager:
                manager.return_value.BASE = '/absent'
                response = WORKER.inspection_response({'language': 'en'}, result, {})
            self.assertEqual(response['state'], 'reboot_required')

    def test_pending_restore_and_restart_remain_ahead_of_upgrade_prompt(self):
        manager = mock.Mock(BASE='/owned')
        manager.management_lock.return_value = contextlib.nullcontext()
        for phase in ('reboot_required', 'carrier_reboot_required'):
            manager.manage.return_value = {'installed': True, 'sim_supported': True,
                'can_update': False, 'update_available': True, 'status': dict(ready(), phase=phase)}
            with mock.patch.object(WORKER, 'engine', return_value=manager), \
                 mock.patch.object(WORKER, 'sanitized_identity', return_value={}), \
                 mock.patch.object(WORKER, 'load', return_value={'version': '0.1.0.13'}):
                response = WORKER.inspect({}, '/verified')
            self.assertEqual(response['state'], phase)
            self.assertEqual(response['primary_action'], 'status')

    def test_call_confirmation_rejects_sim_change_even_if_ims_is_ready(self):
        request = dict.fromkeys(('confirmed', 'incoming', 'outgoing', 'audio', 'lte'), True)
        request['call_context'] = 'a' * 32
        manager = mock.Mock()
        manager.manage.return_value = {'status': ready()}
        with mock.patch.object(WORKER, 'engine', return_value=manager), \
             mock.patch.object(WORKER, 'call_context', return_value={'context': 'b' * 32}), \
             mock.patch.object(WORKER, 'save') as save:
            with self.assertRaisesRegex(ENTRY.MobileError, 'call_context_changed'):
                WORKER.check_confirmation(request)
            save.assert_not_called()

    def test_call_confirmation_requires_all_four_manual_checks(self):
        request = dict.fromkeys(('confirmed', 'incoming', 'outgoing', 'audio', 'lte'), True)
        request['audio'] = False
        with mock.patch.object(WORKER, 'engine') as manager:
            with self.assertRaisesRegex(ENTRY.MobileError, 'call_confirmation_incomplete'):
                WORKER.check_confirmation(request)
            manager.assert_not_called()

    def test_call_confirmation_is_persisted_only_for_current_context(self):
        request = dict.fromkeys(('confirmed', 'incoming', 'outgoing', 'audio', 'lte'), True)
        request['call_context'] = 'a' * 32
        manager = mock.Mock()
        manager.manage.return_value = {'status': ready()}
        context = {'context': 'a' * 32, 'binding': {}, 'calls_verified': False}
        with mock.patch.object(WORKER, 'engine', return_value=manager), \
             mock.patch.object(WORKER, 'call_context', return_value=context), \
             mock.patch.object(WORKER, 'save') as save:
            WORKER.check_confirmation(request)
            self.assertTrue(save.call_args.args[1]['calls_verified'])

    def test_call_confirmation_ack_does_not_depend_on_post_commit_probe(self):
        request = dict.fromkeys(('confirmed', 'incoming', 'outgoing', 'audio', 'lte'), True)
        request['call_context'] = 'a' * 32
        result = {'installed': True, 'sim_supported': True, 'installed_management_schema': 2,
                  'can_update': False, 'status': ready()}
        state = {'saved': False, 'locked': False}
        manager = mock.Mock(BASE='/owned')
        @contextlib.contextmanager
        def locked():
            state['locked'] = True
            try:
                yield
            finally:
                state['locked'] = False
        def probe(action):
            self.assertEqual(action, 'probe')
            self.assertTrue(state['locked'])
            if state['saved']:
                raise TimeoutError('post-commit probe exceeded response budget')
            return result
        def save(path, value):
            self.assertTrue(state['locked'])
            self.assertTrue(value['calls_verified'])
            state['saved'] = True
        manager.management_lock.side_effect = locked
        manager.manage.side_effect = probe
        context = {'context': 'a' * 32, 'calls_verified': False}
        with mock.patch.object(ENTRY, 'private_directory'), \
             mock.patch.object(WORKER, 'engine', return_value=manager), \
             mock.patch.object(WORKER, 'job_lock', side_effect=contextlib.nullcontext), \
             mock.patch.object(WORKER, 'active_job', return_value=None), \
             mock.patch.object(WORKER, 'inspection_details', return_value={}), \
             mock.patch.object(WORKER, 'call_context', return_value=context) as current, \
             mock.patch.object(WORKER, 'save', side_effect=save) as write:
            response = WORKER.dispatch('confirm-calls', request, '/verified')
        self.assertEqual(response['state'], 'verified')
        self.assertEqual(response['call_context'], request['call_context'])
        self.assertTrue(state['saved'])
        self.assertFalse(state['locked'])
        manager.manage.assert_called_once_with('probe')
        current.assert_called_once_with(False)
        write.assert_called_once()

    def test_lost_confirmation_response_is_recovered_by_reading_without_another_save(self):
        request = dict.fromkeys(('confirmed', 'incoming', 'outgoing', 'audio', 'lte'), True)
        request['call_context'] = 'a' * 32
        manager = mock.Mock(BASE='/owned')
        manager.management_lock.side_effect = contextlib.nullcontext
        manager.manage.return_value = {'installed': True, 'sim_supported': True,
            'installed_management_schema': 2, 'can_update': False, 'status': ready()}
        stored = {'context': 'a' * 32, 'calls_verified': False}
        with mock.patch.object(ENTRY, 'private_directory'), \
             mock.patch.object(WORKER, 'engine', return_value=manager), \
             mock.patch.object(WORKER, 'job_lock', side_effect=contextlib.nullcontext), \
             mock.patch.object(WORKER, 'active_job', return_value=None), \
             mock.patch.object(WORKER, 'inspection_details', return_value={}), \
             mock.patch.object(WORKER, 'call_context', side_effect=lambda *args: dict(stored)), \
             mock.patch.object(WORKER, 'save', side_effect=lambda path, value: stored.update(value)) as write:
            WORKER.dispatch('confirm-calls', request, '/verified')  # Its response is lost.
            response = WORKER.dispatch('inspect', {}, '/verified')
        self.assertEqual(response['state'], 'verified')
        self.assertEqual(response['call_context'], request['call_context'])
        self.assertEqual(manager.manage.call_count, 2)  # One per request, neither is a mutation.
        write.assert_called_once()

    def test_call_confirmation_rejects_every_unfinished_transaction_before_probe(self):
        request = dict.fromkeys(('confirmed', 'incoming', 'outgoing', 'audio', 'lte'), True)
        request['call_context'] = 'a' * 32
        for state in ('queued', 'running', 'waiting_reboot', 'interrupted', 'failed'):
            job = {'id': 'b' * 32, 'state': state, 'action': 'disable'}
            manager = mock.Mock()
            with self.subTest(state=state), mock.patch.object(ENTRY, 'private_directory'), \
                 mock.patch.object(WORKER, 'job_lock', side_effect=lambda **kwargs: contextlib.nullcontext()), \
                 mock.patch.object(WORKER, 'active_job', return_value=job), \
                 mock.patch.object(WORKER, 'engine', return_value=manager), \
                 mock.patch.object(WORKER, 'save') as save:
                with self.assertRaisesRegex(ENTRY.MobileError, 'operation_in_progress'):
                    WORKER.dispatch('confirm-calls', request, '/verified')
                manager.management_lock.assert_not_called()
                manager.manage.assert_not_called()
                save.assert_not_called()

    def test_call_confirmation_holds_job_then_management_lock_through_save(self):
        request = dict.fromkeys(('confirmed', 'incoming', 'outgoing', 'audio', 'lte'), True)
        request['call_context'] = 'a' * 32
        held = []
        @contextlib.contextmanager
        def acquire(name):
            held.append(name)
            try:
                yield
            finally:
                self.assertEqual(held.pop(), name)
        manager = mock.Mock(BASE='/owned')
        manager.management_lock.side_effect = lambda: acquire('management')
        manager.manage.return_value = {'installed': True, 'sim_supported': True,
            'installed_management_schema': 2, 'can_update': False, 'status': ready()}
        context = {'context': 'a' * 32, 'calls_verified': False}
        def save(path, value):
            self.assertEqual(held, ['job', 'management'])
            self.assertTrue(value['calls_verified'])
        with mock.patch.object(ENTRY, 'private_directory'), \
             mock.patch.object(WORKER, 'job_lock', side_effect=lambda: acquire('job')), \
             mock.patch.object(WORKER, 'active_job', return_value=None), \
             mock.patch.object(WORKER, 'engine', return_value=manager), \
             mock.patch.object(WORKER, 'inspection_details', return_value={}), \
             mock.patch.object(WORKER, 'call_context', return_value=context), \
             mock.patch.object(WORKER, 'save', side_effect=save) as write:
            response = WORKER.dispatch('confirm-calls', request, '/verified')
        self.assertEqual(response['state'], 'verified')
        self.assertEqual(held, [])
        write.assert_called_once()

    def test_shareable_errors_never_include_raw_native_messages(self):
        self.assertEqual(WORKER.safe_error(RuntimeError('private identity: example')), 'preflight_or_recovery_check_failed')
        self.assertEqual(WORKER.safe_error(RuntimeError('call_active')), 'call_active')

    def test_background_launch_failure_remains_an_explicit_recoverable_job(self):
        job = {'id': 'a' * 32, 'attempt': 'b' * 32, 'action': 'install',
               'state': 'queued', 'phase': 'checking', 'bundle': '/var/snapshot', 'worker_safety': WORKER.SAFE_JOB_GUARD}
        native = types.SimpleNamespace(command=mock.Mock(side_effect=RuntimeError('spawn denied')))
        with mock.patch.dict(sys.modules, {'native': native}), \
             mock.patch.object(ENTRY, 'read_bundle', return_value=({'capabilities': [WORKER.SAFE_JOB_GUARD]},)), \
             mock.patch.object(ENTRY, 'trusted_python'), mock.patch.object(WORKER, 'save'):
            WORKER.spawn(job)
        self.assertEqual(job['state'], 'interrupted')
        self.assertEqual(job['error_code'], 'background_launch_failed')
        self.assertTrue(WORKER.resumable_job(job))

    def test_background_launch_uses_only_validated_job_arguments(self):
        for operation in ('a' * 32, '../escape'):
            job = {'id': operation, 'attempt': 'b' * 32, 'action': 'install',
                   'state': 'queued', 'phase': 'checking', 'bundle': '/var/snapshot', 'worker_safety': WORKER.SAFE_JOB_GUARD}
            native = types.SimpleNamespace(command=mock.Mock(return_value=b'12345\n'))
            with mock.patch.dict(sys.modules, {'native': native}), \
                 mock.patch.object(ENTRY, 'read_bundle', return_value=({'capabilities': [WORKER.SAFE_JOB_GUARD]},)), \
                 mock.patch.object(ENTRY, 'trusted_python'), mock.patch.object(WORKER, 'save'):
                if operation == '../escape':
                    with self.assertRaisesRegex(ENTRY.MobileError, 'invalid_operation_id'):
                        WORKER.spawn(job)
                else:
                    WORKER.spawn(job)
            if operation == '../escape':
                native.command.assert_not_called()
                self.assertEqual(job['state'], 'queued')
            else:
                native.command.assert_called_once_with(['/var/snapshot/runtime/job-launcher', operation, 'b' * 32], 30)
                self.assertEqual(job['worker_pid'], 12345)
                self.assertEqual(job['state'], 'queued')

    def test_pending_job_response_has_exact_id_and_no_request_or_binding(self):
        job = {'id': 'a' * 32, 'state': 'waiting_reboot', 'action': 'uninstall',
               'phase': 'awaiting_reboot', 'request': {'private': 'secret'}, 'binding': 'secret'}
        response = WORKER.job_response(job, {'language': 'en'})
        self.assertEqual(response['primary_action'], 'poll')
        self.assertEqual(response['job_id'], job['id'])
        self.assertNotIn('secret', str(response))

    def test_stale_fork_cannot_execute_after_recovery_invalidates_attempt(self):
        job = {'state': 'queued', 'attempt': 'new'}
        with mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
             mock.patch.object(WORKER, 'load', return_value=job), \
             mock.patch.object(WORKER, 'run_operation') as execute:
            WORKER.run_job('a' * 32, 'old')
            execute.assert_not_called()

    def test_queued_job_clock_rollback_does_not_poll_forever(self):
        current_boot = ['owner', '1' * 48]
        for now, changed_boot, expected in ((105, False, 'queued'), (90, False, 'interrupted'),
                                            (120, False, 'interrupted'), (105, True, 'interrupted')):
            job = {'id': 'a' * 32, 'state': 'queued', 'phase': 'checking', 'attempt': 'b' * 32,
                   'created': 100, 'updated': 100, 'boot': current_boot}
            def progress(value, phase, **fields):
                value.update(fields)
            with self.subTest(now=now, changed_boot=changed_boot), \
                 mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
                 mock.patch.object(WORKER, 'load', return_value=job), \
                 mock.patch.object(WORKER, 'boot', return_value=['owner', '2' * 48] if changed_boot else current_boot), \
                 mock.patch.object(WORKER.time, 'time', return_value=now), \
                 mock.patch.object(WORKER, 'progress', side_effect=progress):
                result = WORKER.recover_job(job)
            self.assertEqual(result['state'], expected)
            if expected == 'interrupted':
                with mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
                     mock.patch.object(WORKER, 'load', return_value=job), \
                     mock.patch.object(WORKER, 'run_operation') as execute:
                    WORKER.run_job(job['id'], job['attempt'])
                    execute.assert_not_called()

    def test_lost_running_worker_preserves_unknown_outcome_and_blocks_all_writes(self):
        job = {'id': 'a' * 32, 'action': 'enable', 'state': 'running', 'phase': 'enable',
               'attempt': 'b' * 32, 'created': 100, 'updated': 100, 'boot': ['owner', '1' * 48]}
        def progress(value, phase, **fields):
            value.update(fields)
        with mock.patch.object(WORKER, 'job_lock', side_effect=contextlib.nullcontext), \
             mock.patch.object(WORKER, 'load', return_value=job), \
             mock.patch.object(WORKER, 'progress', side_effect=progress):
            WORKER.recover_job(job)
        self.assertEqual(job['state'], 'interrupted')
        self.assertTrue(job['commit_outcome_unknown'])
        response = WORKER.job_response(job, {})
        self.assertEqual(response['state'], 'job_outcome_unknown')
        self.assertEqual(response['primary_action'], 'export')
        with mock.patch.object(WORKER, 'job_lock', side_effect=contextlib.nullcontext), \
             mock.patch.object(WORKER, 'load', return_value=job), \
             mock.patch.object(WORKER, 'active_job', return_value=job), \
             mock.patch.object(WORKER.os.path, 'isfile', return_value=False), \
             mock.patch.object(WORKER, 'spawn') as spawn:
            with self.assertRaisesRegex(ENTRY.MobileError, 'operation_unknown'):
                WORKER.resume({'job_id': job['id']})
            with self.assertRaisesRegex(ENTRY.MobileError, 'operation_in_progress'):
                WORKER.submit('disable', {'operation_id': 'c' * 32}, '/verified')
            spawn.assert_not_called()

    def test_final_result_save_failure_never_overwrites_it_as_retryable_failure(self):
        for reboot in (True, False):
            job = {'id': 'a' * 32, 'action': 'enable', 'state': 'queued', 'phase': 'enable',
                   'attempt': 'b' * 32}
            states = []
            def progress(value, phase, **fields):
                value.update(fields)
                states.append(fields.get('state'))
                if fields.get('state') in ('waiting_reboot', 'completed'):
                    raise ENTRY.MobileError('state_persistence_unconfirmed')
            with self.subTest(reboot=reboot), \
                 mock.patch.object(WORKER, 'job_lock', side_effect=lambda **kwargs: contextlib.nullcontext()), \
                 mock.patch.object(WORKER, 'load', return_value=job), \
                 mock.patch.object(WORKER, 'progress', side_effect=progress), \
                 mock.patch.object(WORKER, 'run_operation', return_value={'enabled': True, 'reboot_required': reboot}):
                with self.assertRaisesRegex(ENTRY.MobileError, 'state_persistence_unconfirmed'):
                    WORKER.run_job(job['id'], job['attempt'])
            self.assertNotIn('failed', states)
            self.assertEqual(job['result']['reboot_required'], reboot)

    def test_old_failed_job_with_a_result_is_not_blindly_resumed(self):
        job = {'id': 'a' * 32, 'action': 'enable', 'state': 'failed', 'phase': 'enable',
               'result': {'enabled': True, 'reboot_required': True}}
        self.assertTrue(WORKER.protected_job(job))
        self.assertEqual(WORKER.job_response(job, {})['state'], 'job_outcome_unknown')
        with mock.patch.object(WORKER, 'job_lock', side_effect=contextlib.nullcontext), \
             mock.patch.object(WORKER, 'load', return_value=job), \
             mock.patch.object(WORKER, 'active_job', return_value=job), \
             mock.patch.object(WORKER, 'spawn') as spawn:
            with self.assertRaisesRegex(ENTRY.MobileError, 'operation_unknown'):
                WORKER.resume({'job_id': job['id']})
            spawn.assert_not_called()

    def test_same_boot_resume_does_not_repeat_mutation(self):
        same = ['bb10-unified-carriers-v1', '1' * 48]
        job = {'id': 'a' * 32, 'action': 'uninstall', 'state': 'waiting_reboot', 'boot': same}
        with mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
             mock.patch.object(WORKER, 'load', return_value=job), \
             mock.patch.object(WORKER, 'active_job', return_value=job), \
             mock.patch.object(WORKER, 'boot', return_value=same), \
             mock.patch.object(WORKER, 'spawn') as spawn:
            with self.assertRaisesRegex(ENTRY.MobileError, 'normal_reboot_required'):
                WORKER.resume({'job_id': 'a' * 32})
            spawn.assert_not_called()

    def test_successful_install_after_reboot_only_closes_job(self):
        job = {'id': 'a' * 32, 'action': 'install', 'phase': 'awaiting_reboot',
               'state': 'waiting_reboot', 'boot': ['bb10-unified-carriers-v1', '1' * 48], 'result': {'installed': True}}
        with mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
             mock.patch.object(WORKER, 'load', return_value=job), \
             mock.patch.object(WORKER, 'active_job', return_value=job), \
             mock.patch.object(WORKER, 'boot', return_value=['bb10-unified-carriers-v1', '2' * 48]), \
             mock.patch.object(WORKER, 'save'), \
             mock.patch.object(WORKER, 'spawn') as spawn:
            WORKER.resume({'job_id': 'a' * 32})
            self.assertEqual(job['state'], 'completed')
            spawn.assert_not_called()

    def test_legacy_dangerous_jobs_are_not_blindly_resumed(self):
        with mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
             mock.patch.object(WORKER, 'load', return_value={'id': 'a' * 32, 'action': 'legacy-start', 'state': 'waiting_reboot'}), \
             mock.patch.object(WORKER, 'active_job', return_value={'id': 'a' * 32}), \
             mock.patch.object(WORKER, 'spawn') as spawn:
            with self.assertRaisesRegex(ENTRY.MobileError, 'manual_recovery_required'):
                WORKER.resume({'job_id': 'a' * 32})
            spawn.assert_not_called()

    def test_enable_and_disable_close_after_real_reboot_without_repeating_write(self):
        for action in ('enable', 'disable'):
            job = {'id': 'a' * 32, 'action': action, 'phase': 'awaiting_reboot',
                   'state': 'waiting_reboot', 'boot': ['bb10-unified-carriers-v1', '1' * 48]}
            manager = mock.Mock()
            manager.manage.return_value = {'enabled': action == 'enable', 'manager_alive': action == 'enable'}
            manager.management_lock.return_value = contextlib.nullcontext()
            with self.subTest(action=action), \
                 mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
                 mock.patch.object(WORKER, 'load', return_value=job), \
                 mock.patch.object(WORKER, 'active_job', return_value=job), \
                 mock.patch.object(WORKER, 'boot', return_value=['bb10-unified-carriers-v1', '2' * 48]), \
                 mock.patch.object(WORKER, 'engine', return_value=manager), \
                 mock.patch.object(WORKER, 'save'), mock.patch.object(WORKER, 'spawn') as spawn:
                self.assertEqual(WORKER.job_response(job, {})['primary_action'], 'poll')
                WORKER.resume({'job_id': job['id']})
                self.assertEqual(job['state'], 'completed')
                manager.manage.assert_called_once_with('status')
                spawn.assert_not_called()

    def test_disable_does_not_claim_restored_while_manager_still_running(self):
        job = {'id': 'a' * 32, 'action': 'disable', 'phase': 'awaiting_reboot',
               'state': 'waiting_reboot', 'boot': ['bb10-unified-carriers-v1', '1' * 48]}
        manager = mock.Mock()
        manager.manage.return_value = {'enabled': False, 'manager_alive': True}
        manager.management_lock.return_value = contextlib.nullcontext()
        with mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
             mock.patch.object(WORKER, 'load', return_value=job), \
             mock.patch.object(WORKER, 'active_job', return_value=job), \
             mock.patch.object(WORKER, 'boot', return_value=['bb10-unified-carriers-v1', '2' * 48]), \
             mock.patch.object(WORKER, 'engine', return_value=manager), \
             mock.patch.object(WORKER, 'save') as save:
            result = WORKER.resume({'job_id': job['id']})
            self.assertEqual(result['state'], 'task_status_unavailable')
            self.assertEqual(result['job_id'], job['id'])
            self.assertEqual(result['details']['error_code'], 'restoration_still_pending')
            save.assert_not_called()

    def test_reinstall_after_uninstall_uses_prepare_even_with_retained_activation(self):
        manager = mock.Mock(BASE='/owned')
        manager.management_lock.return_value = contextlib.nullcontext()
        manager.manage.side_effect = [{'prepared': True}, {'installed': True, 'reboot_required': True}]
        job = {'id': 'a' * 32, 'action': 'install', 'request': {}, 'bundle': '/verified'}
        existing = {'/owned/activation.json', '/owned/uninstalled.json'}
        with mock.patch.object(ENTRY, 'private_directory'), mock.patch.object(ENTRY, 'read_bundle'), \
             mock.patch.object(WORKER, 'engine', return_value=manager), \
             mock.patch.object(WORKER, 'stage_payload', return_value='/stage'), \
             mock.patch.object(WORKER, 'progress'), \
             mock.patch.object(WORKER, 'backup_originals', return_value='/backup'), \
             mock.patch.object(WORKER.os.path, 'isfile', side_effect=lambda path: path in existing):
            result = WORKER.run_operation(job)
        self.assertTrue(result['installed'])
        self.assertEqual([call.args[0] for call in manager.manage.call_args_list], ['prepare', 'activate'])

    def test_radio_off_after_backup_keeps_prepared_install_resumable(self):
        job = {'id': 'a' * 32, 'attempt': 'b' * 32, 'action': 'install', 'request': {},
               'bundle': '/verified', 'state': 'queued', 'phase': 'checking',
               'worker_safety': WORKER.SAFE_JOB_GUARD, 'commit_outcome_unknown': False}
        manager = mock.Mock(BASE='/owned')
        manager.management_lock.return_value = contextlib.nullcontext()
        manager.manage.return_value = {'prepared': True}
        def progress(value, phase, **fields): value.update(phase=phase, **fields)
        with mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
             mock.patch.object(WORKER, 'load', return_value=job), \
             mock.patch.object(WORKER, 'progress', side_effect=progress), \
             mock.patch.object(WORKER, 'mobile_radio_state', side_effect=['ON', 'OFF']), \
             mock.patch.object(ENTRY, 'private_directory'), mock.patch.object(ENTRY, 'read_bundle'), \
             mock.patch.object(WORKER, 'engine', return_value=manager), \
             mock.patch.object(WORKER, 'stage_payload', return_value='/stage'), \
             mock.patch.object(WORKER, 'backup_originals', return_value='/backup') as backup, \
             mock.patch.object(WORKER.os.path, 'isfile', return_value=False):
            WORKER.run_job(job['id'], job['attempt'])
        backup.assert_called_once()
        self.assertEqual([call.args[0] for call in manager.manage.call_args_list], ['prepare'])
        self.assertEqual(job['phase'], 'exporting_original_backup')
        self.assertEqual(job['error_code'], 'mobile_network_off')
        self.assertFalse(job['commit_outcome_unknown'])
        self.assertTrue(WORKER.resumable_job(job))

    def test_radio_off_does_not_hide_an_already_committed_activation(self):
        manager = mock.Mock(BASE='/owned')
        manager.management_lock.return_value = contextlib.nullcontext()
        manager.manage.return_value = {'installed': True, 'reboot_required': True, 'already_committed': True}
        job = {'id': 'a' * 32, 'action': 'install', 'request': {}, 'bundle': '/verified'}
        existing = {'/owned/activation.json', '/owned/payload.json'}
        with mock.patch.object(ENTRY, 'private_directory'), mock.patch.object(ENTRY, 'read_bundle'), \
             mock.patch.object(WORKER, 'engine', return_value=manager), \
             mock.patch.object(WORKER, 'mobile_radio_state', return_value='OFF'), \
             mock.patch.object(WORKER, 'stage_payload') as stage, \
             mock.patch.object(WORKER.os.path, 'isfile', side_effect=lambda path: path in existing):
            result = WORKER.run_operation(job)
        self.assertTrue(result['already_committed'])
        manager.manage.assert_called_once_with('activate', operation_id=job['id'])
        stage.assert_not_called()

    def test_backup_failure_can_resume_same_job_with_explicit_new_destination(self):
        job = {'id': 'a' * 32, 'action': 'install', 'phase': 'exporting_original_backup',
               'state': 'failed', 'boot': ['current'], 'request': {'backup_location': 'sdcard'},
               'error_code': 'backup_location_unavailable', 'commit_outcome_unknown': False,
               'worker_safety': WORKER.SAFE_JOB_GUARD, 'bundle': '/verified'}
        with mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
             mock.patch.object(WORKER, 'load', return_value=job), \
             mock.patch.object(WORKER, 'active_job', return_value=job), \
             mock.patch.object(WORKER, 'boot', return_value=['current']), \
             mock.patch.object(ENTRY, 'read_bundle', return_value=({'capabilities': [WORKER.SAFE_JOB_GUARD]},)), \
             mock.patch.object(WORKER, 'save'), mock.patch.object(WORKER, 'spawn') as spawn:
            self.assertEqual(WORKER.job_response(job, {})['primary_action'], 'resume')
            WORKER.resume({'job_id': job['id'], 'backup_location': 'internal'})
            self.assertEqual(job['id'], 'a' * 32)
            self.assertEqual(job['request']['backup_location'], 'internal')
            self.assertEqual(job['state'], 'queued')
            spawn.assert_called_once()

    def test_nontransactional_failures_do_not_hide_live_management_state(self):
        for action in ('export', 'update'):
            job = {'id': 'a' * 32, 'action': action, 'state': 'failed', 'phase': 'verifying_update',
                   'commit_outcome_unknown': False, 'worker_safety': WORKER.SAFE_JOB_GUARD}
            with mock.patch.object(ENTRY, 'private_directory'), \
                 mock.patch.object(WORKER, 'active_job', return_value=job), \
                 mock.patch.object(WORKER, 'inspect', return_value={'state': 'disabled'}) as inspect:
                response = WORKER.dispatch('inspect', {'language': 'zh'}, '/verified')
                self.assertEqual(response['state'], 'disabled')
                inspect.assert_called_once()
                self.assertFalse(WORKER.resumable_job(job))

    def test_update_after_verified_snapshot_keeps_recovery_target(self):
        job = {'action': 'update', 'state': 'failed', 'phase': 'updating_payload', 'candidate': '/verified-candidate'}
        self.assertTrue(WORKER.resumable_job(job))

    def test_rollback_failure_after_entering_engine_remains_unknown(self):
        manager = mock.Mock(BASE='/owned')
        manager.manage.side_effect = FileNotFoundError('last-update.json')
        manager.management_lock.return_value = contextlib.nullcontext()
        job = {'id': 'a' * 32, 'action': 'rollback', 'phase': 'checking', 'state': 'running',
               'request': {}, 'bundle': '/verified'}
        with mock.patch.object(ENTRY, 'private_directory'), mock.patch.object(ENTRY, 'read_bundle'), \
             mock.patch.object(WORKER, 'engine', return_value=manager), \
             mock.patch.object(WORKER, 'progress'), mock.patch.object(WORKER.os.path, 'isfile', return_value=False):
            with self.assertRaises(FileNotFoundError):
                WORKER.run_operation(job)
        job['state'] = 'failed'
        self.assertFalse(WORKER.resumable_job(job))
        with mock.patch.object(ENTRY, 'private_directory'), \
             mock.patch.object(WORKER, 'active_job', return_value=job), \
             mock.patch.object(WORKER, 'inspect', return_value={'state': 'disabled'}) as inspect:
            self.assertEqual(WORKER.dispatch('inspect', {}, '/verified')['state'], 'job_outcome_unknown')
            inspect.assert_not_called()


@unittest.skipIf(os.name == 'nt', 'POSIX record locks required')
class CurrentSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = str(Path(self.temp.name).resolve() / 'mobile')
        os.mkdir(self.root, 0o700)
        for owner, name, value in ((ENTRY, 'ROOT', self.root), (WORKER, 'ROOT', self.root),
                                   (WORKER, 'JOBS', self.root + '/jobs'),
                                   (ENTRY, 'FOREGROUND_ACTIVE_POINTER', (False, b''))):
            patch = mock.patch.object(owner, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.folder = self.root + '/snapshots/' + 'a' * 64

    def switch_pointer(self):
        path = Path(self.root) / 'active.json'
        path.write_bytes(b'{"manifest_sha256":"' + b'b' * 64 + b'"}')
        os.chmod(str(path), 0o600)

    def test_changed_active_pointer_rejects_new_submit_confirm_and_resume_before_writes(self):
        self.switch_pointer()
        request = {'operation_id': 'a' * 32}
        with mock.patch.object(WORKER, 'save') as save, mock.patch.object(WORKER, 'spawn') as spawn, \
             mock.patch.object(WORKER, 'engine') as engine:
            with self.assertRaisesRegex(ENTRY.MobileError, 'runtime_selection_changed'):
                WORKER.submit('enable', request, self.folder)
            with self.assertRaisesRegex(ENTRY.MobileError, 'runtime_selection_changed'):
                WORKER.dispatch('confirm-calls', {'language': 'zh'}, self.folder)
            with self.assertRaisesRegex(ENTRY.MobileError, 'runtime_selection_changed'):
                WORKER.resume({'job_id': 'c' * 32}, self.folder)
            save.assert_not_called()
            spawn.assert_not_called()
            engine.assert_not_called()

    def test_existing_submission_is_observed_without_creating_another_job(self):
        self.switch_pointer()
        operation = 'a' * 32
        request = {'operation_id': operation}
        jobs = Path(self.root) / 'jobs'
        jobs.mkdir(mode=0o700)
        prior = {'id': operation, 'action': 'enable', 'request': request}
        path = Path(WORKER.job_path(operation))
        path.write_text(json.dumps(prior), encoding='utf-8')
        os.chmod(str(path), 0o600)
        with mock.patch.object(WORKER, 'job_response', return_value={'prior': True}) as response, \
             mock.patch.object(WORKER, 'save') as save, mock.patch.object(WORKER, 'spawn') as spawn:
            self.assertEqual(WORKER.submit('enable', request, self.folder), {'prior': True})
            response.assert_called_once()
            save.assert_not_called()
            spawn.assert_not_called()

    def test_old_entry_rechecks_selection_under_the_existing_lock(self):
        with mock.patch.object(ENTRY, 'FOREGROUND_ACTIVE_POINTER', None), \
             mock.patch.object(ENTRY, 'FALLBACK_MANIFEST_SHA', 'f' * 64, create=True), \
             mock.patch.object(ENTRY, 'active_bundle', return_value=self.folder) as selection:
            with WORKER.job_lock():
                WORKER.require_current_selection(self.folder)
            selection.assert_called_once_with(self.root + '/snapshots/' + 'f' * 64)
            selection.return_value = self.root + '/snapshots/' + 'e' * 64
            with WORKER.job_lock():
                with self.assertRaisesRegex(ENTRY.MobileError, 'runtime_selection_changed'):
                    WORKER.require_current_selection(self.folder)

    def test_changed_selection_does_not_rewrite_an_existing_journal_during_inspection(self):
        self.switch_pointer()
        old_boot = ['owner', '1' * 48]
        new_boot = ['owner', '2' * 48]
        job = {'id': 'a' * 32, 'action': 'enable', 'state': 'running', 'phase': 'enable',
               'boot': old_boot, 'created': 1, 'updated': 1}
        with mock.patch.object(WORKER, 'load', return_value=job), \
             mock.patch.object(WORKER, 'boot', return_value=new_boot), \
             mock.patch.object(WORKER, 'progress') as progress:
            with self.assertRaisesRegex(ENTRY.MobileError, 'runtime_selection_changed'):
                WORKER.recover_job(dict(job), self.folder)
            progress.assert_not_called()
        job.update(state='waiting_reboot', result={'enabled': True})
        manager = mock.Mock()
        manager.manage.return_value = {'enabled': True, 'manager_alive': True}
        manager.management_lock.return_value = contextlib.nullcontext()
        with mock.patch.object(WORKER, 'active_job', return_value=job), \
             mock.patch.object(WORKER, 'boot', return_value=new_boot), \
             mock.patch.object(WORKER, 'engine', return_value=manager), \
             mock.patch.object(WORKER, 'progress') as progress:
            with self.assertRaisesRegex(ENTRY.MobileError, 'runtime_selection_changed'):
                WORKER.observed_job_response(dict(job), {}, self.folder)
            progress.assert_not_called()


class AutomaticRebootObservationTests(unittest.TestCase):
    def setUp(self):
        self.old = ['bb10-unified-carriers-v1', '1' * 48]
        self.new = ['bb10-unified-carriers-v1', '2' * 48]
        self.job = {'id': 'a' * 32, 'action': 'enable', 'state': 'waiting_reboot',
                    'phase': 'awaiting_reboot', 'boot': self.old,
                    'result': {'enabled': True, 'reboot_required': True},
                    'worker_safety': WORKER.SAFE_JOB_GUARD, 'bundle': '/verified'}
        self.manager = mock.Mock()
        self.manager.manage.return_value = {'enabled': True, 'manager_alive': True}
        self.manager.management_lock.return_value = contextlib.nullcontext()
        self.locked = False

        @contextlib.contextmanager
        def lock():
            self.assertFalse(self.locked, 'POSIX job locks must not be nested')
            self.locked = True
            try:
                yield
            finally:
                self.locked = False

        def save(path, value):
            self.assertTrue(self.locked, 'Completion must be persisted under the job lock')

        patches = {
            'job_lock': mock.Mock(side_effect=lock),
            'require_current_selection': mock.Mock(),
            'active_job': mock.Mock(side_effect=lambda: self.job),
            'load': mock.Mock(side_effect=lambda path: self.job),
            'boot': mock.Mock(return_value=self.new),
            'engine': mock.Mock(return_value=self.manager),
            'save': mock.Mock(side_effect=save),
            'inspect': mock.Mock(side_effect=lambda *args: {'schema': 2, 'state': 'waiting', 'call_context': ''}),
            'spawn': mock.Mock(side_effect=AssertionError('Observation may not launch a worker')),
        }
        self.mocks = patches
        for name, value in patches.items():
            patch = mock.patch.object(WORKER, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def observe(self):
        return WORKER.observed_job_response(dict(self.job), {}, '/verified')

    def test_committed_actions_finish_once_with_fresh_status_and_terminal_id(self):
        for action, result in (('enable', {'enabled': True}), ('disable', {'disabled': True}),
                               ('install', {'installed': True}), ('install', {'activated': True}),
                               ('update', {'updated': True})):
            with self.subTest(action=action, result=result):
                self.job.update(action=action, result=result, state='waiting_reboot')
                self.manager.manage.return_value = {'enabled': action == 'enable', 'manager_alive': False}
                self.mocks['save'].reset_mock()
                response = self.observe()
                self.assertEqual(response['state'], 'waiting')  # Never infer IMS or call acceptance.
                self.assertEqual(response['job']['state'], 'completed')
                self.assertEqual(response['job_id'], self.job['id'])
                self.assertTrue(response['live_status'])
                self.assertEqual(self.job['boot'], self.old)
                self.mocks['save'].assert_called_once()
                self.assertEqual(self.observe()['job']['state'], 'completed')  # Lost response retry.
                self.mocks['save'].assert_called_once()
        self.mocks['spawn'].assert_not_called()
        self.assertTrue(all(call == mock.call('status') for call in self.manager.manage.call_args_list))

    def test_same_unknown_or_invalid_boot_never_completes(self):
        for old, new in ((self.old, self.old), (None, self.new), ([], self.new),
                         (['unknown'], self.new), (self.old, None), (self.old, []),
                         (self.old, ['different-owner', '2' * 48])):
            with self.subTest(old=old, new=new):
                self.job['boot'] = old
                self.mocks['boot'].return_value = new
                self.assertEqual(self.observe()['job']['state'], 'waiting_reboot')
        self.mocks['save'].assert_not_called()
        self.manager.manage.assert_not_called()

    def test_failed_interrupted_and_multi_phase_actions_need_explicit_recovery(self):
        for action, state in (('enable', 'failed'), ('disable', 'interrupted')):
            self.job.update(action=action, state=state)
            self.assertEqual(self.observe()['job']['state'], state)
        self.mocks['boot'].assert_not_called()
        for action in ('rollback', 'uninstall', 'legacy-install'):
            self.job.update(action=action, state='waiting_reboot')
            response = self.observe()
            self.assertEqual(response['state'], 'continue_after_reboot')
            self.assertEqual(response['primary_action'], 'resume')
            self.assertEqual(response['job']['state'], 'waiting_reboot')
        self.mocks['save'].assert_not_called()
        self.mocks['spawn'].assert_not_called()

    def test_multistage_job_never_offers_resume_before_a_valid_changed_boot(self):
        for action in ('rollback', 'uninstall', 'legacy-install'):
            self.job.update(action=action, state='waiting_reboot', boot=self.old)
            for candidate in (self.old, None, [], ['other-owner', '2' * 48], ['owner', 'bad']):
                with self.subTest(action=action, boot=candidate):
                    self.mocks['boot'].return_value = candidate
                    response = self.observe()
                    self.assertEqual(response['primary_action'], 'poll')
                    self.assertNotIn('resume', response['actions'])
        self.mocks['save'].assert_not_called()
        self.mocks['spawn'].assert_not_called()

    def test_resume_requires_valid_matching_owner_and_rechecks_original_identity(self):
        self.job.update(action='uninstall', state='waiting_reboot')
        for old, new in ((None, self.new), ([], self.new), (self.old, None),
                         (self.old, ['other-owner', '2' * 48]), (self.old, self.old)):
            with self.subTest(old=old, new=new):
                self.job['boot'] = old
                self.mocks['boot'].return_value = new
                with mock.patch.object(WORKER, 'load', return_value=self.job):
                    with self.assertRaises(ENTRY.MobileError):
                        WORKER.resume({'job_id': self.job['id']})
        self.mocks['save'].assert_not_called()
        self.mocks['spawn'].assert_not_called()

    def test_failed_enable_is_not_declared_complete_from_a_matching_status(self):
        self.job.update(action='enable', state='failed', phase='enable', request={}, commit_outcome_unknown=False)
        self.job.pop('result')
        self.mocks['spawn'].side_effect = None
        with mock.patch.object(WORKER, 'load', return_value=self.job), \
             mock.patch.object(ENTRY, 'read_bundle', return_value=({'capabilities': [WORKER.SAFE_JOB_GUARD]},)):
            response = WORKER.resume({'job_id': self.job['id']})
        self.assertEqual(response['job']['state'], 'queued')
        self.manager.manage.assert_not_called()
        self.mocks['spawn'].assert_called_once()

    def test_uncommitted_or_truthy_results_do_not_finish_install_or_update(self):
        for action, result in (('install', {}), ('install', {'installed': 1}),
                               ('install', {'updated': True}), ('update', {'updated': 'true'}),
                               ('update', {'installed': True})):
            self.job.update(action=action, result=result)
            self.assertEqual(self.observe()['job']['state'], 'waiting_reboot')
        self.mocks['save'].assert_not_called()

    def test_service_state_must_match_and_disable_must_finish_restoring(self):
        for action, status in (('enable', {'enabled': False}), ('enable', {}),
                               ('disable', {'enabled': True, 'manager_alive': False}),
                               ('disable', {'enabled': False, 'manager_alive': True}),
                               ('disable', {'enabled': False})):
            self.job['action'] = action
            self.manager.manage.return_value = status
            self.assertEqual(self.observe()['job']['state'], 'waiting_reboot')
        self.mocks['save'].assert_not_called()

    def test_reboot_status_failure_preserves_the_original_task(self):
        self.manager.manage.side_effect = RuntimeError('management_busy')
        response = self.observe()
        self.assertEqual(response['state'], 'task_service_busy')
        self.assertEqual(response['job_id'], self.job['id'])
        self.assertEqual(response['job']['state'], 'waiting_reboot')
        self.assertEqual(response['primary_action'], 'poll')
        self.mocks['save'].assert_not_called()

    def test_completed_task_with_failed_live_render_keeps_terminal_identity(self):
        self.job['state'] = 'completed'
        self.mocks['inspect'].side_effect = RuntimeError('management_busy')
        response = self.observe()
        self.assertEqual(response['job_id'], self.job['id'])
        self.assertEqual(response['job']['state'], 'completed')
        self.assertEqual(response['state'], 'error')
        self.assertEqual(response['error']['code'], 'management_busy')
        self.assertTrue(response['live_status'])

    def test_reloads_under_lock_and_never_overwrites_new_active_job(self):
        stale = dict(self.job)
        self.job.update(id='b' * 32, action='disable', state='running')
        response = WORKER.observed_job_response(stale, {}, '/verified')
        self.assertEqual(response['job_id'], 'a' * 32)
        self.assertEqual(response['job']['state'], 'waiting_reboot')
        self.assertNotIn('resume', response['actions'])
        self.mocks['save'].assert_not_called()
        self.mocks['boot'].assert_not_called()

    def test_lock_contention_is_observation_only(self):
        self.mocks['job_lock'].side_effect = ENTRY.MobileError('operation_in_progress')
        for language, title in (('zh', '暂时无法核对原任务'),
                                ('en', 'Task status is temporarily unavailable')):
            response = WORKER.observed_job_response(dict(self.job), {'language': language}, '/verified')
            self.assertEqual(response['state'], 'task_status_unavailable')
            self.assertEqual(response['display']['title'], title)
            self.assertEqual(response['job_id'], self.job['id'])
            self.assertEqual(response['job']['state'], 'waiting_reboot')
            self.assertEqual(response['primary_action'], 'poll')
            self.assertNotIn('resume', response['actions'])
        self.mocks['save'].assert_not_called()
        self.mocks['boot'].assert_not_called()

    def test_all_read_entries_reconcile_and_return_live_terminal_job(self):
        for action in ('inspect', 'status', 'poll'):
            self.job['state'] = 'waiting_reboot'
            with mock.patch.object(ENTRY, 'private_directory'), mock.patch.object(WORKER, 'load', return_value=self.job), \
                 mock.patch.object(WORKER.os.path, 'isfile', return_value=True):
                response = WORKER.dispatch(action, {'job_id': self.job['id']}, '/verified')
            self.assertEqual(response['job']['state'], 'completed')
            self.assertTrue(response['live_status'])

    def test_plain_status_does_not_replay_old_update_completion(self):
        self.job.update(action='update', state='completed', result={'updated': True})
        for action in ('inspect', 'status'):
            with mock.patch.object(ENTRY, 'private_directory'), \
                 mock.patch.object(WORKER, 'load', return_value=self.job), \
                 mock.patch.object(WORKER.os.path, 'isfile', return_value=True):
                self.assertNotIn('job', WORKER.dispatch(action, {}, '/verified'))
                response = WORKER.dispatch(action, {'job_id': self.job['id']}, '/verified')
                self.assertEqual(response['job']['state'], 'completed')
        self.mocks['save'].assert_not_called()

    def test_exact_old_terminal_job_does_not_hide_another_active_task(self):
        old = dict(self.job, state='completed')
        self.job.update(id='b' * 32, state='running')
        with mock.patch.object(ENTRY, 'private_directory'), \
             mock.patch.object(WORKER.os.path, 'isfile', return_value=True), \
             mock.patch.object(WORKER, 'load', return_value=old):
            response = WORKER.dispatch('inspect', {'job_id': old['id'], 'operation_id': old['id']}, '/verified')
        self.assertEqual(response['job_id'], old['id'])
        self.assertEqual(response['job']['state'], 'completed')
        self.assertFalse(response.get('live_status', False))
        self.mocks['inspect'].assert_not_called()
        self.mocks['save'].assert_not_called()

    def test_missing_exact_job_remains_unknown_even_if_another_is_active(self):
        for action in ('inspect', 'status', 'poll'):
            with self.subTest(action=action), mock.patch.object(ENTRY, 'private_directory'), \
                 mock.patch.object(WORKER.os.path, 'isfile', return_value=False), \
                 mock.patch.object(WORKER, 'load') as load:
                response = WORKER.dispatch(action, {'job_id': 'a' * 32, 'operation_id': 'a' * 32}, '/verified')
                self.assertEqual(response['state'], 'recovery_required')
                self.assertNotIn('job_id', response)
                load.assert_not_called()
        self.mocks['spawn'].assert_not_called()

    def test_mismatched_job_or_operation_identity_cannot_be_resumed(self):
        old = dict(self.job)
        self.job.update(id='b' * 32, state='running')
        with mock.patch.object(WORKER, 'load', return_value=old):
            with self.assertRaisesRegex(ENTRY.MobileError, 'operation_in_progress'):
                WORKER.resume({'job_id': old['id']})
        with mock.patch.object(ENTRY, 'private_directory'):
            with self.assertRaisesRegex(ENTRY.MobileError, 'operation_id_reused'):
                WORKER.dispatch('poll', {'job_id': old['id'], 'operation_id': self.job['id']}, '/verified')
        with mock.patch.object(WORKER, 'load', return_value=self.job):
            with self.assertRaisesRegex(ENTRY.MobileError, 'operation_id_reused'):
                WORKER.resume({'job_id': old['id']})
        self.mocks['spawn'].assert_not_called()
        self.mocks['save'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
