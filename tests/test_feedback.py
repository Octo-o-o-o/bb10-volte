"""Feedback survives retries/restarts without exporting connection material."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from feedback import Journal, FeedbackQueue, project, scrub, write_bundle, build_failure_excerpt, MAX_EVENTS


class FeedbackTests(unittest.TestCase):
    def test_candidate_metadata_survives_export_without_unknown_paths(self):
        source = {'preflight': {'variant_trial': {'variant': 'SQC100-3', 'operator': 'unicom',
            'automatic_start': False, 'hardware_acceptance': 'not_established',
            'observed_board': 'CLASSICVZW', 'raw': 'secret',
            'native_sha256': {'/usr/sbin/dca': 'a' * 64, '/private/key': 'b' * 64,
                              '/radio/bin/qct_rrm': 'invalid'}}}}
        result = project(source)
        trial = result['preflight']['variant_trial']
        self.assertEqual(trial['variant'], 'SQC100-3')
        self.assertEqual(trial['native_sha256'], {'/usr/sbin/dca': 'a' * 64})
        self.assertFalse(trial['automatic_start'])
        self.assertNotIn('secret', json.dumps(result))
        self.assertEqual(project(result), result)

    def test_scope_sim_and_trial_blockers_are_attention_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(tmp)
            class Widget:
                _feedback_journal = journal
                def _root(self): return self
            channel = FeedbackQueue(Widget(), 'preflight')
            for snapshot in ({'scope_error': 'unsupported_model_or_os'},
                             {'sim_supported': False, 'sim_reason': 'unsupported_hplmn'},
                             {'outcome': 'unsupported'}, {'outcome': 'needs_adaptation'},
                             {'checks': [{'id': 'native', 'status': 'block'}]},
                             {'checks': [{'id': 'provider_lifecycle', 'status': 'adapt'}]}):
                channel.put(('result', ('preflight', {'preflight': snapshot})))
                self.assertEqual(journal.events[-1]['outcome'], 'needs_attention', snapshot)
                self.assertEqual(journal.events[-1]['details']['preflight'], snapshot)

    def test_projection_keeps_diagnostic_facts_but_drops_private_fields(self):
        source = {'variant': 'SQC100-2', 'os': '10.3.3.3216', 'host': 'private-host',
                  'config': 'secret-config', 'private_key': 'secret-key', 'imsi': ('46001' + '1234567890'),
                  'usb': {'usb_present': True, 'usb_network': False, 'ip': '169.254.0.1'},
                  'checks': [{'id': 'root', 'status': 'fail', 'note': 'root_not_ready', 'raw': 'secret'}]}
        result = project(source)
        self.assertEqual(result['checks'][0]['note'], 'root_not_ready')
        self.assertEqual(result['os'], '10.3.3.3216')
        self.assertEqual(result['usb'], {'usb_present': True, 'usb_network': False})
        self.assertNotIn('secret', json.dumps(result))
        self.assertNotIn(('46001' + '1234567890'), json.dumps(result))

    def test_messages_scrub_credentials_identifiers_addresses_and_paths(self):
        raw = ('connection_refused\npassword=topsecret\nAPI_KEY=short-token\n'
               'C:\\Users\\Alice\\secret-kit\\root-build.log\n/home/alice/.ssh/id_rsa\n'
               'https://private.example/path?token=abcd\n13812' + '345678\n'
               'IMSI: 46001' + '1234567890\nPIN: aabb1122\n169.254.0.1\n'
               'owner@example.org\n-----BEGIN RSA ' + 'PRIVATE KEY-----\nkeybytes\n-----END RSA PRIVATE KEY-----')
        safe = scrub(raw)
        self.assertIn('connection_refused', safe)
        for secret in ('topsecret', 'short-token', 'Alice', 'alice', 'private.example', '13812' + '345678',
                       ('46001' + '1234567890'), 'aabb1122', '169.254.0.1', 'owner@example.org', 'keybytes'):
            self.assertNotIn(secret, safe)

    def test_retry_restart_and_zip_keep_first_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Journal(tmp)
            first.record('connect', 'detect', 'failed', message='authentication_failed')
            first.record('connect', 'detect', 'finished', details={'usb': {'usb_present': True}})
            second = Journal(tmp)
            payload = second.bundle('install', 'retry succeeded')
            write_bundle(Path(tmp) / 'feedback.zip', payload)
            with zipfile.ZipFile(Path(tmp) / 'feedback.zip') as archive:
                self.assertEqual(set(archive.namelist()), {'feedback.json', 'timeline.txt', 'README.txt'})
                self.assertIn('authentication_failed', archive.read('timeline.txt').decode())
                report = json.loads(archive.read('feedback.json'))
                self.assertEqual(len(report['sessions']), 2)
                self.assertEqual(report['step'], 'install')
                self.assertFalse(report['limits']['automatic_upload'])

    def test_corrupt_or_oversized_history_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ('session-' + 'a' * 32 + '.json')).write_text('{broken')
            journal = Journal(tmp)
            self.assertEqual(len(journal.history()), 1)

    def test_disk_failure_does_not_drop_queue_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(tmp)
            class Widget:
                _feedback_journal = journal
                def _root(self): return self
            channel = FeedbackQueue(Widget(), 'root')
            event = ('error', 'root_build_failed')
            with patch.object(Path, 'write_text', side_effect=OSError('disk full')):
                channel.begin('prepare')
                channel.put(event)
            self.assertEqual(channel.get_nowait(), event)
            self.assertFalse(journal.persistence_ok)
            self.assertEqual(journal.events[-1]['outcome'], 'failed')

    def test_queue_formats_capture_failure_before_successful_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(tmp)
            class Widget:
                _feedback_journal = journal
                def _root(self): return self
            channel = FeedbackQueue(Widget(), 'install')
            channel.begin('install')
            channel.put(('install', None, 'connection_timeout_state_unknown'))
            channel.begin('probe')
            channel.put(('probe', {'installed': True}, None))
            channel.put(('result', ('detect', {'error': 'root_not_ready'})))
            self.assertEqual([e['outcome'] for e in journal.events][-1], 'failed')
            self.assertIn('connection_timeout_state_unknown', json.dumps(list(journal.events)))

    def test_history_is_bounded_and_reports_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(tmp)
            with patch.object(Path, 'write_text'), patch.object(Path, 'replace'):
                for _ in range(MAX_EVENTS + 2):
                    journal.record('root', 'prepare', 'progress')
            self.assertEqual(len(journal.events), MAX_EVENTS)
            self.assertTrue(journal.history()[-1]['truncated'])

    def test_build_excerpt_only_reads_known_failure_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'root-build.log').write_text(
                'normal output\nprivate key=do-not-share\nERROR missing image C:\\Users\\Alice\\kit\n'
                'ERROR Bearer short-secret\n', encoding='utf-8')
            (Path(tmp) / 'ssh_config').write_text('unrelated secret')
            result = build_failure_excerpt(tmp)
            self.assertIn('missing image', result)
            for secret in ('normal output', 'do-not-share', 'Alice', 'short-secret', 'unrelated secret'):
                self.assertNotIn(secret, result)

    def test_nested_blocker_and_registered_install_are_distinguished(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(tmp)
            class Widget:
                _feedback_journal = journal
                def _root(self): return self
            channel = FeedbackQueue(Widget(), 'preflight')
            channel.put(('result', ('preflight', {'preflight': {'outcome': 'not_ready',
                'checks': [{'id': 'root', 'status': 'wait', 'code': 'root_qnx_arm32_required'}]}})))
            self.assertEqual(journal.events[-1]['outcome'], 'needs_attention')
            self.assertEqual(journal.events[-1]['details']['preflight']['checks'][0]['code'], 'root_qnx_arm32_required')
            self.assertEqual(journal.events[-1]['details']['preflight']['checks'][0]['status'], 'wait')
            channel.put(('probe', {'installed': True, 'can_install': False, 'status': {'phase': 'running'}}, None))
            self.assertEqual(journal.events[-1]['outcome'], 'finished')


if __name__ == '__main__':
    unittest.main()
