"""Offline call diagnostics preserve uncertainty and exclude private input."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import analyze_call_rejection as diagnostic


class CallRejectionDiagnosticsTests(unittest.TestCase):
    def test_errors_and_end_events_are_observations_not_a_success_or_root_cause(self):
        text = '\n'.join((
            'qct_rrm PHONE: [IMS] Calling Reject',
            'ims_rrm rejectCall(): Cannot reject call, mgr state Idle, call state Idle',
            'ims_rrm answerCall(): Cannot answer call, mgr state Idle, call state Idle',
            'ims_rrm hangupCall(user, cid): Call not hung up',
            'qct_rrm PHONE: [IMS] tlvRet not success (1)',
            'qct_rrm PHONE: [IMS] Already have an INCOMING call',
            'ims_rrm Busy, do not send DISCONNECT now, will send later',
            'ims_rrm dialog is NULL or incoming call',
            'qct_rrm Notification 1 (NOTIFY_PHONE_INCOMING) Rx',
            'qct_rrm Notification 5 (NOTIFY_PHONE_DISCONNECTED) Rx',
            'ims_rrm callEnded ... callId secret.invalid status code 486 endReason 4',
            'ims_rrm bb.eng.cmgr:444 state=0, reason=4, code=603, stackState=0',
        ))
        report = diagnostic.analyze(io.StringIO(text))
        self.assertTrue(all(count == 1 for count in report['events'].values()))
        self.assertEqual(report['end_status_observations'], {'486': 1, '603': 1})
        self.assertEqual(report['root_cause'], 'not_determined')
        self.assertEqual(report['call_acceptance'], 'not_assessed')
        self.assertIn('events_not_correlated_between_calls', report['limitations'])
        self.assertNotIn('secret.invalid', json.dumps(report))

    def test_missing_disconnect_in_a_partial_log_does_not_mean_failure(self):
        report = diagnostic.analyze(io.StringIO('PHONE: [IMS] Calling Reject\n'))
        self.assertEqual(report['observations'], ['insufficient_evidence'])
        self.assertEqual(report['events']['disconnected_notification'], 0)
        self.assertEqual(report['root_cause'], 'not_determined')
        self.assertIn('missing_events_do_not_prove_failure', report['limitations'])

    def test_arbitrary_text_identifiers_and_invalid_codes_never_leave_the_parser(self):
        # Construct synthetic identifiers; never use a device or subscriber's data.
        phone, imsi, imei = '+12025550123', '01234' * 3, '98765' * 3
        text = ('sip:' + phone + '@example.invalid\nIMSI=' + imsi + ' IMEI=' + imei + '\n'
                'password=synthetic-private-value C:\\private\\unique-file.log\n'
                'bb.eng.cmgr:444 state=0, reason=4, code=999, stackState=0\n'
                'Notification 5 (NOTIFY_PHONE_DISCONNECTED) Tx\n')
        report = diagnostic.analyze(io.StringIO(text))
        self.assertFalse(any(report['events'].values()))
        self.assertEqual(report['end_status_observations'], {})
        output = json.dumps(report)
        for secret in (phone, 'example.invalid', imsi, imei,
                       'synthetic-private-value', 'unique-file.log'):
            self.assertNotIn(secret, output)

    def test_large_or_overlong_input_is_bounded_and_marked_incomplete(self):
        for limit, value, text in (('MAX_LINE_CHARACTERS', 20, 'x' * 21),
                                    ('MAX_CHARACTERS', 10, 'x\n' * 10),
                                    ('MAX_LINES', 2, 'x\n' * 4)):
            with self.subTest(limit=limit), patch.object(diagnostic, limit, value):
                report = diagnostic.analyze(io.StringIO(text))
                self.assertTrue(report['input']['truncated'])
                self.assertEqual(report['root_cause'], 'not_determined')

    def test_cli_refuses_to_overwrite_input_or_existing_output_and_keeps_paths_private(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'private.log'
            target = Path(directory) / 'summary.json'
            source.write_text('secret source', encoding='utf-8')
            target.write_text('preserve me', encoding='utf-8')
            for destination in (source, target):
                with self.subTest(destination=destination.name), patch('sys.stderr', new_callable=io.StringIO) as err:
                    code = diagnostic.main(['--input', str(source), '--output', str(destination)])
                    self.assertEqual(code, 1)
                    self.assertNotIn(directory, err.getvalue())
            self.assertEqual(source.read_text(), 'secret source')
            self.assertEqual(target.read_text(), 'preserve me')
            output = Path(directory) / 'new.json'
            self.assertEqual(diagnostic.main(['--input', str(source), '--output', str(output)]), 0)
            self.assertEqual(json.loads(output.read_text())['root_cause'], 'not_determined')


if __name__ == '__main__':
    unittest.main()
