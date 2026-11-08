"""Only the original detached worker notifies about known completed outcomes."""
from contextlib import ExitStack
import copy
import types
import sys
import unittest
from unittest.mock import Mock, patch
from test_mobile_runtime import WORKER as w


class FinishedTaskNoticeTests(unittest.TestCase):
    def setUp(self):
        self.token = ['owner', 'a' * 48]
        self.job = dict(id='b' * 32, boot=self.token, bundle='/signed', action='install',
                        state='waiting_reboot', result={'reboot_required': True}, commit_outcome_unknown=False)
        self.saved = []
        self.native = types.SimpleNamespace(command=Mock())
        stack = ExitStack()
        self.addCleanup(stack.close)
        for gate in (patch.object(w, 'boot', return_value=self.token),
                     patch.object(w.e, 'read_bundle'),
                     patch.object(w, 'save', side_effect=lambda path, job: self.saved.append(copy.deepcopy(job))),
                     patch.dict(sys.modules, {'native': self.native,
                         'unified_service': types.SimpleNamespace(__file__='/signed/payload/device/unified_service.py')})):
            stack.enter_context(gate)

    def test_closed_ui_setup_result_notifies_once_after_persisting_reservation(self):
        self.native.command.side_effect = lambda *args: self.assertEqual(self.saved[-1]['notification_attempted_boot'], self.token)
        w.notify_finished_job(self.job)
        w.notify_finished_job(self.job)
        self.native.command.assert_called_once()
        self.assertEqual(self.native.command.call_args.args[0][-1], 'restart')
        self.assertEqual(self.native.command.call_args.args[1], 5)
        self.assertEqual(self.job['state'], 'waiting_reboot')

    def test_ambiguous_stale_waiting_or_opaque_failures_do_not_notify(self):
        for changes in ({'commit_outcome_unknown': True}, {'commit_outcome_unknown': None},
                        {'boot': ['owner', 'c' * 48]}, {'state': 'running'}, {'state': 'interrupted'},
                        {'result': {'reboot_required': 'true'}}, {'state': 'completed'},
                        {'state': 'failed', 'error_code': 'preflight_or_recovery_check_failed'}):
            w.notify_finished_job(dict(self.job, **changes))
        self.native.command.assert_not_called()
        self.assertFalse(self.saved)

    def test_known_failed_backup_can_request_review_but_does_not_claim_activation(self):
        self.job.update(state='failed', result={}, error_code='backup_readback_failed')
        w.notify_finished_job(self.job)
        self.assertEqual(self.native.command.call_args.args[0][-1], 'task_failed')

    def test_uncertain_delivery_is_not_repeated_and_cannot_change_job_result(self):
        self.native.command.side_effect = OSError('UI unavailable')
        w.notify_finished_job(self.job)
        w.notify_finished_job(self.job)
        self.native.command.assert_called_once()
        self.assertEqual(self.job['result'], {'reboot_required': True})

    def test_missing_signature_or_failed_reservation_stays_silent(self):
        with patch.object(w.e, 'read_bundle', side_effect=ValueError('signature')):
            w.notify_finished_job(self.job)
        with patch.object(w, 'save', side_effect=OSError('storage')):
            w.notify_finished_job(self.job)
        self.native.command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
