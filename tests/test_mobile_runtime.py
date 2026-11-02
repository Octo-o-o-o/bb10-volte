"""User-visible success and transaction boundaries; no phone required."""
import contextlib
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

    def test_pending_restore_and_restart_remain_ahead_of_upgrade_prompt(self):
        manager = mock.Mock(BASE='/owned')
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

    def test_shareable_errors_never_include_raw_native_messages(self):
        self.assertEqual(WORKER.safe_error(RuntimeError('private identity: example')), 'preflight_or_recovery_check_failed')
        self.assertEqual(WORKER.safe_error(RuntimeError('call_active')), 'call_active')

    def test_background_launch_failure_remains_an_explicit_recoverable_job(self):
        job = {'id': 'a' * 32, 'attempt': 'b' * 32, 'action': 'install',
               'state': 'queued', 'phase': 'checking', 'bundle': '/var/snapshot'}
        native = types.SimpleNamespace(command=mock.Mock(side_effect=RuntimeError('spawn denied')))
        with mock.patch.dict(sys.modules, {'native': native}), \
             mock.patch.object(ENTRY, 'trusted_python'), mock.patch.object(WORKER, 'save'):
            WORKER.spawn(job)
        self.assertEqual(job['state'], 'interrupted')
        self.assertEqual(job['error_code'], 'background_launch_failed')
        self.assertTrue(WORKER.resumable_job(job))

    def test_background_launch_uses_only_validated_job_arguments(self):
        for operation in ('a' * 32, '../escape'):
            job = {'id': operation, 'attempt': 'b' * 32, 'action': 'install',
                   'state': 'queued', 'phase': 'checking', 'bundle': '/var/snapshot'}
            native = types.SimpleNamespace(command=mock.Mock(return_value=b'12345\n'))
            with mock.patch.dict(sys.modules, {'native': native}), \
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
        self.assertEqual(response['primary_action'], 'resume')
        self.assertEqual(response['job_id'], job['id'])
        self.assertNotIn('secret', str(response))

    def test_stale_fork_cannot_execute_after_recovery_invalidates_attempt(self):
        job = {'state': 'queued', 'attempt': 'new'}
        with mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
             mock.patch.object(WORKER, 'load', return_value=job), \
             mock.patch.object(WORKER, 'run_operation') as execute:
            WORKER.run_job('a' * 32, 'old')
            execute.assert_not_called()

    def test_same_boot_resume_does_not_repeat_mutation(self):
        job = {'action': 'uninstall', 'state': 'waiting_reboot', 'boot': ['same']}
        with mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
             mock.patch.object(WORKER, 'load', return_value=job), \
             mock.patch.object(WORKER, 'boot', return_value=['same']), \
             mock.patch.object(WORKER, 'spawn') as spawn:
            with self.assertRaisesRegex(ENTRY.MobileError, 'normal_reboot_required'):
                WORKER.resume({'job_id': 'a' * 32})
            spawn.assert_not_called()

    def test_successful_install_after_reboot_only_closes_job(self):
        job = {'id': 'a' * 32, 'action': 'install', 'phase': 'awaiting_reboot',
               'state': 'waiting_reboot', 'boot': ['old'], 'result': {'installed': True}}
        with mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
             mock.patch.object(WORKER, 'load', return_value=job), \
             mock.patch.object(WORKER, 'boot', return_value=['new']), \
             mock.patch.object(WORKER, 'save'), \
             mock.patch.object(WORKER, 'spawn') as spawn:
            WORKER.resume({'job_id': 'a' * 32})
            self.assertEqual(job['state'], 'completed')
            spawn.assert_not_called()

    def test_legacy_dangerous_jobs_are_not_blindly_resumed(self):
        with mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
             mock.patch.object(WORKER, 'load', return_value={'action': 'legacy-start'}), \
             mock.patch.object(WORKER, 'spawn') as spawn:
            with self.assertRaisesRegex(ENTRY.MobileError, 'manual_recovery_required'):
                WORKER.resume({'job_id': 'a' * 32})
            spawn.assert_not_called()

    def test_enable_and_disable_close_after_real_reboot_without_repeating_write(self):
        for action in ('enable', 'disable'):
            job = {'id': 'a' * 32, 'action': action, 'phase': 'awaiting_reboot',
                   'state': 'waiting_reboot', 'boot': ['old']}
            manager = mock.Mock()
            manager.manage.return_value = {'enabled': action == 'enable', 'manager_alive': action == 'enable'}
            with self.subTest(action=action), \
                 mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
                 mock.patch.object(WORKER, 'load', return_value=job), \
                 mock.patch.object(WORKER, 'boot', return_value=['new']), \
                 mock.patch.object(WORKER, 'engine', return_value=manager), \
                 mock.patch.object(WORKER, 'save'), mock.patch.object(WORKER, 'spawn') as spawn:
                self.assertEqual(WORKER.job_response(job, {})['primary_action'], 'resume')
                WORKER.resume({'job_id': job['id']})
                self.assertEqual(job['state'], 'completed')
                manager.manage.assert_called_once_with('status')
                spawn.assert_not_called()

    def test_disable_does_not_claim_restored_while_manager_still_running(self):
        job = {'id': 'a' * 32, 'action': 'disable', 'phase': 'awaiting_reboot',
               'state': 'waiting_reboot', 'boot': ['old']}
        manager = mock.Mock()
        manager.manage.return_value = {'enabled': False, 'manager_alive': True}
        with mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
             mock.patch.object(WORKER, 'load', return_value=job), \
             mock.patch.object(WORKER, 'boot', return_value=['new']), \
             mock.patch.object(WORKER, 'engine', return_value=manager), \
             mock.patch.object(WORKER, 'save') as save:
            with self.assertRaisesRegex(ENTRY.MobileError, 'restoration_still_pending'):
                WORKER.resume({'job_id': job['id']})
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

    def test_backup_failure_can_resume_same_job_with_explicit_new_destination(self):
        job = {'id': 'a' * 32, 'action': 'install', 'phase': 'exporting_original_backup',
               'state': 'failed', 'boot': ['current'], 'request': {'backup_location': 'sdcard'},
               'error_code': 'backup_location_unavailable'}
        with mock.patch.object(WORKER, 'job_lock', return_value=contextlib.nullcontext()), \
             mock.patch.object(WORKER, 'load', return_value=job), \
             mock.patch.object(WORKER, 'boot', return_value=['current']), \
             mock.patch.object(WORKER, 'save'), mock.patch.object(WORKER, 'spawn') as spawn:
            self.assertEqual(WORKER.job_response(job, {})['primary_action'], 'resume')
            WORKER.resume({'job_id': job['id'], 'backup_location': 'internal'})
            self.assertEqual(job['id'], 'a' * 32)
            self.assertEqual(job['request']['backup_location'], 'internal')
            self.assertEqual(job['state'], 'queued')
            spawn.assert_called_once()

    def test_nontransactional_failures_do_not_hide_live_management_state(self):
        for action in ('export', 'update'):
            job = {'id': 'a' * 32, 'action': action, 'state': 'failed', 'phase': 'verifying_update'}
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

    def test_missing_rollback_archive_failure_returns_to_live_state(self):
        manager = mock.Mock(BASE='/owned')
        manager.manage.side_effect = FileNotFoundError('last-update.json')
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
            self.assertEqual(WORKER.dispatch('inspect', {}, '/verified')['state'], 'disabled')
            inspect.assert_called_once()


class AutomaticRebootObservationTests(unittest.TestCase):
    def setUp(self):
        self.old = ['bb10-unified-carriers-v1', '1' * 48]
        self.new = ['bb10-unified-carriers-v1', '2' * 48]
        self.job = {'id': 'a' * 32, 'action': 'enable', 'state': 'waiting_reboot',
                    'phase': 'awaiting_reboot', 'boot': self.old,
                    'result': {'enabled': True, 'reboot_required': True}}
        self.manager = mock.Mock()
        self.manager.manage.return_value = {'enabled': True, 'manager_alive': True}
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
            'active_job': mock.Mock(side_effect=lambda: self.job),
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
        for action, state in (('enable', 'failed'), ('disable', 'interrupted'),
                              ('rollback', 'waiting_reboot'), ('uninstall', 'waiting_reboot'),
                              ('legacy-install', 'waiting_reboot')):
            self.job.update(action=action, state=state)
            self.assertEqual(self.observe()['job']['state'], state)
        self.mocks['save'].assert_not_called()
        self.mocks['boot'].assert_not_called()
        self.mocks['spawn'].assert_not_called()

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

    def test_reloads_under_lock_and_never_overwrites_new_active_job(self):
        stale = dict(self.job)
        self.job.update(id='b' * 32, action='disable', state='running')
        response = WORKER.observed_job_response(stale, {}, '/verified')
        self.assertEqual(response['job_id'], 'b' * 32)
        self.assertEqual(response['job']['state'], 'running')
        self.mocks['save'].assert_not_called()
        self.mocks['boot'].assert_not_called()

    def test_lock_contention_is_observation_only(self):
        self.mocks['job_lock'].side_effect = ENTRY.MobileError('operation_in_progress')
        self.assertEqual(self.observe()['job']['state'], 'waiting_reboot')
        self.mocks['save'].assert_not_called()
        self.mocks['boot'].assert_not_called()

    def test_all_read_entries_reconcile_and_return_live_terminal_job(self):
        for action in ('inspect', 'status', 'poll'):
            self.job['state'] = 'waiting_reboot'
            with mock.patch.object(ENTRY, 'private_directory'), mock.patch.object(WORKER, 'load', return_value=self.job):
                response = WORKER.dispatch(action, {'job_id': self.job['id']}, '/verified')
            self.assertEqual(response['job']['state'], 'completed')
            self.assertTrue(response['live_status'])

    def test_plain_status_does_not_replay_old_update_completion(self):
        self.job.update(action='update', state='completed', result={'updated': True})
        for action in ('inspect', 'status'):
            with mock.patch.object(ENTRY, 'private_directory'):
                self.assertNotIn('job', WORKER.dispatch(action, {}, '/verified'))
                response = WORKER.dispatch(action, {'job_id': self.job['id']}, '/verified')
                self.assertEqual(response['job']['state'], 'completed')
        self.mocks['save'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
