import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from sms_diagnostics import analyze


def message(direction, start, call, cseq, branch, extra='', body=''):
    return ('%s\n%s\nVia: SIP/2.0/UDP host.invalid;branch=%s\nCall-ID: %s\n'
            'CSeq: %s MESSAGE\n%s\n\n%s\n') % (
                '<<<<<< IN' if direction == 'in' else '>>>>>> OUT', start, branch, call, cseq, extra, body)


def exchange(reply='mt-private-id', ack_ref='e3', response=202):
    return (message('in', 'MESSAGE sip:subscriber@home.invalid SIP/2.0', 'mt-private-id', 8, 'in-branch',
                    'P-Asserted-Identity: <sip:gateway.invalid>\nContent-Type: application/vnd.3gpp.sms', '01 e3 00 00') +
            message('out', 'MESSAGE sip:gateway.invalid SIP/2.0', 'ack-private-id', 9, 'ack-branch',
                    'To: <sip:gateway.invalid>\nContent-Type: application/vnd.3gpp.sms\nIn-Reply-To: ' + reply, '02 ' + ack_ref) +
            message('in', 'SIP/2.0 %s Accepted' % response, 'ack-private-id', 9, 'ack-branch'))


class SmsDiagnosticsTests(unittest.TestCase):
    def test_ack_uses_new_call_id_but_links_to_mt_and_matches_rp_reference(self):
        result = analyze(exchange())
        ack = result['messages'][1]
        self.assertEqual(ack['related_incoming_index'], 1)
        self.assertTrue(ack['ack_target_matches_p_asserted_identity'])
        self.assertTrue(ack['ack_to_matches_p_asserted_identity'])
        self.assertTrue(ack['rp_reference_matches'])
        self.assertEqual(ack['sip_response_codes'], [202])
        self.assertFalse(result['sms_delivery_verified'])

    def test_wrong_reference_and_wrong_gateway_are_visible_without_payload(self):
        text = exchange(ack_ref='fa').replace('MESSAGE sip:gateway.invalid', 'MESSAGE sip:wrong.invalid')
        ack = analyze(text)['messages'][1]
        self.assertIs(ack['rp_reference_matches'], False)
        self.assertIs(ack['ack_target_matches_p_asserted_identity'], False)

    def test_ack_to_header_is_checked_separately_from_request_uri(self):
        text = exchange().replace('To: <sip:gateway.invalid>', 'To: <sip:wrong.invalid>')
        ack = analyze(text)['messages'][1]
        self.assertIs(ack['ack_target_matches_p_asserted_identity'], True)
        self.assertIs(ack['ack_to_matches_p_asserted_identity'], False)

    def test_pii_is_unknown_and_not_an_invalid_correlation(self):
        ack = analyze(exchange(reply='PII'))['messages'][1]
        self.assertEqual(ack['in_reply_to'], 'redacted')
        self.assertIsNone(ack['related_incoming_index'])
        self.assertIsNone(ack['rp_reference_matches'])

    def test_filtered_header_and_unmatched_header_are_distinct(self):
        missing = analyze(exchange().replace('In-Reply-To: mt-private-id\n', ''))['messages'][1]
        outside = analyze(exchange(reply='outside-capture'))['messages'][1]
        self.assertEqual(missing['in_reply_to'], 'not_visible')
        self.assertEqual(outside['in_reply_to'], 'unmatched_in_capture')

    def test_compact_headers_and_file_logger_spacing(self):
        text = exchange().replace('Call-ID:', 'i :').replace('Content-Type:', 'c :')
        self.assertEqual(analyze(text)['messages'][1]['related_incoming_index'], 1)

    def test_responses_require_call_id_cseq_branch_and_opposite_direction(self):
        original = exchange(response=400)
        for text in (original.replace('CSeq: 9 MESSAGE\n\n', 'CSeq: 10 MESSAGE\n\n'),
                     original.replace('SIP/2.0 400 Accepted\nVia: SIP/2.0/UDP host.invalid;branch=ack-branch',
                                      'SIP/2.0 400 Accepted\nVia: SIP/2.0/UDP host.invalid;branch=unrelated'),
                     original.replace('<<<<<< IN\nSIP/2.0 400', '>>>>>> OUT\nSIP/2.0 400')):
            self.assertEqual(analyze(text)['messages'][1]['sip_response_codes'], [])

    def test_two_processes_are_never_correlated(self):
        parts = exchange().split('>>>>>> OUT')
        first = '\n'.join('Nov 01 00:00:00.000 ims_rrm.1 sip 3261  ' + line for line in parts[0].splitlines())
        rest = '\n'.join('Nov 01 00:00:00.000 ims_rrm.2 sip 3261  ' + line
                         for line in ('>>>>>> OUT' + parts[1]).splitlines())
        self.assertIsNone(analyze(first + '\n' + rest)['messages'][1]['related_incoming_index'])

    def test_reused_mt_call_id_is_ambiguous(self):
        text = exchange()
        inbound = text.split('>>>>>> OUT')[0]
        self.assertIsNone(analyze(inbound + text)['messages'][2]['related_incoming_index'])

    def test_native_reason_and_domain_are_reported_without_claiming_same_root_cause(self):
        text = ('Nov 01 00:00:00.000 ims_rrm.42 main 0  ImsApiSms.cpp process 124 domain 1\n'
                'Nov 01 00:00:00.001 ims_rrm.42 main 0  ImsApiSms.cpp ImsApiSmsSend 60 cs has already been attempted: [1], no retry default\n')
        text += exchange(response=400).replace('400 Accepted', '400 Cannot find In-Reply-To')
        result = analyze(text)
        self.assertEqual(result['events']['cs_domain'], 1)
        self.assertEqual(result['events']['no_retry_default'], 1)
        self.assertTrue(result['messages'][1]['gateway_correlation_rejected'])

    def test_no_identities_bodies_unknown_headers_or_reason_text_escape(self):
        number = '+86' + '138' + '0' * 8
        text = exchange() + '\nSECRET-SMS-CONTENT ' + number + '\n'
        text = text.replace('202 Accepted', '202 private-error-detail')
        text = text.replace('CSeq: 8 MESSAGE', 'CSeq: 8 MESSAGE\nX-Private: hidden-auth-token')
        encoded = json.dumps(analyze(text))
        for private in ('subscriber', 'gateway.invalid', 'private-id', 'SECRET-SMS-CONTENT',
                        number, 'private-error-detail', 'hidden-auth-token', '01 e3 00'):
            self.assertNotIn(private, encoded)

    def test_empty_or_partial_logs_do_not_pass_acceptance(self):
        for text in ('', 'SIP/2.0 200 OK\n', 'imsAttempts [0]'):
            result = analyze(text)
            self.assertEqual(result['messages'], [])
            self.assertFalse(result['sms_delivery_verified'])


if __name__ == '__main__':
    unittest.main()
