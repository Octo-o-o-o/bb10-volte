"""Protocol cases executed as compiled ARM/Thumb instructions, not a Python clone."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import build_sms_ack
try:
    from sms_ack_emulator import Emulator
except ModuleNotFoundError as error:
    if error.name != 'unicorn':
        raise
    Emulator = None


class SmsAckArtifactTests(unittest.TestCase):
    def test_normal_startup_does_not_enable_unaccepted_native_sms_hooks(self):
        import ims_image
        with patch.object(ims_image, '_voice_binary', return_value=(b'accepted', [])), \
                patch.object(ims_image, 'sms_ack_binary', return_value=(b'candidate', [])) as shim:
            self.assertEqual(ims_image.temporary_binary(b'stock', True), (b'accepted', []))
            shim.assert_not_called()
            self.assertEqual(ims_image.temporary_binary(b'stock', True, sms_ack=True), (b'candidate', []))
            shim.assert_called_once_with(b'accepted', [])
            with self.assertRaisesRegex(AssertionError, 'explicit'):
                ims_image.temporary_binary(b'stock', True, sms_ack='true')

    def test_generated_payload_matches_pinned_source_and_manifest(self):
        build_sms_ack.check_generated()

    def test_native_image_guard_rejects_unknown_or_already_modified_firmware(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'device'))
        import ims_image
        for raw in (b'', b'\x7fELF' + bytes(100), bytes(1000)):
            with self.assertRaisesRegex(AssertionError, 'Unknown IMS'):
                ims_image.sms_ack_binary(raw)


@unittest.skipIf(Emulator is None, 'Install optional unicorn==2.1.4 for native SMS shim checks')
class SmsAckMachineCodeTests(unittest.TestCase):
    def test_ack_and_error_preserve_new_call_id_rpdu_and_add_correlation(self):
        emu = Emulator()
        emu.receive()
        for kind in (2, 4):
            result = emu.send(kind=kind)
            self.assertEqual(result['headers']['in-reply-to'], ['mt-first@invalid'])
            self.assertEqual(result['headers']['call-id'], ['fresh-ack@invalid'])
            self.assertEqual(result['headers']['to'], ['<sip:gw.invalid>'])
            self.assertEqual(result['target'], 'sip:gw.invalid')
            self.assertEqual(result['rp'], bytes([kind, 0xe3]))

    def test_four_redeliveries_bind_to_each_current_call_id(self):
        emu = Emulator()
        for i, ref in enumerate((0xe3, 0xfa, 0xfb, 0x0c)):
            emu.time += 30
            call = 'mt-%d@invalid' % i
            emu.receive(ref=ref, call=call)
            self.assertEqual(emu.send(ref=ref)['headers']['in-reply-to'], [call])

    def test_interleaved_messages_do_not_use_the_last_gateway_or_call_id(self):
        emu = Emulator()
        emu.receive(ref=1, call='first@invalid', gateway='sip:first.invalid')
        emu.receive(ref=2, call='second@invalid', gateway='sip:second.invalid')
        for ref, name in ((1, 'first'), (2, 'second')):
            result = emu.send(ref=ref)
            self.assertEqual(result['headers']['in-reply-to'], [name + '@invalid'])
            self.assertEqual(result['target'], 'sip:' + name + '.invalid')

    def test_gateway_uri_parameters_stay_inside_to_name_addr(self):
        for gateway in ('sip:service@gw.invalid;user=phone', 'sips:gw.invalid:5061;transport=tls',
                        'tel:123;phone-context=gw.invalid'):
            with self.subTest(gateway=gateway):
                emu = Emulator()
                emu.receive(gateway='"Gateway" <' + gateway + '>')
                result = emu.send()
                self.assertEqual(result['target'], gateway)
                self.assertEqual(result['headers']['to'], ['<' + gateway + '>'])

    def test_manager_identity_separates_equal_references(self):
        emu = Emulator()
        emu.receive(owner=1, call='one@invalid')
        emu.receive(owner=2, call='two@invalid')
        self.assertEqual(emu.send(owner=1)['headers']['in-reply-to'], ['one@invalid'])
        self.assertEqual(emu.send(owner=2)['headers']['in-reply-to'], ['two@invalid'])

    def test_live_reference_collision_is_ambiguous_even_after_ack(self):
        emu = Emulator()
        emu.receive()
        emu.send()
        emu.receive(call='another@invalid')
        self.assertNotIn('in-reply-to', emu.send()['headers'])

    def test_changed_body_with_same_reference_and_call_id_is_ambiguous(self):
        emu = Emulator()
        emu.receive()
        emu.receive(rp=bytes([1, 0xe3, 1, 0]))
        self.assertNotIn('in-reply-to', emu.send()['headers'])

    def test_identical_retransmission_does_not_extend_expiry(self):
        emu = Emulator()
        emu.receive()
        emu.time += 179
        emu.receive()
        self.assertIn('in-reply-to', emu.send()['headers'])
        emu.time += 1
        self.assertNotIn('in-reply-to', emu.send()['headers'])
        emu.receive(call='new-after-expiry@invalid')
        self.assertEqual(emu.send()['headers']['in-reply-to'], ['new-after-expiry@invalid'])

    def test_malformed_new_context_invalidates_old_reference(self):
        for bad in ({'Call-ID': 'other@invalid'},
                    {'Call-ID': ['one@invalid', 'two@invalid'], 'P-Asserted-Identity': 'sip:gw.invalid'},
                    {'Call-ID': 'one\r\nInjected: yes', 'P-Asserted-Identity': 'sip:gw.invalid'},
                    {'Call-ID': 'one@invalid', 'P-Asserted-Identity': 'sip:one.invalid, <sip:two.invalid>'}):
            emu = Emulator()
            emu.receive()
            emu.receive(headers=bad)
            self.assertNotIn('in-reply-to', emu.send()['headers'])

    def test_missing_expired_and_clock_failure_leave_stock_message(self):
        for reason in ('missing', 'expired', 'backwards', 'clock_failure'):
            emu = Emulator()
            if reason != 'missing': emu.receive()
            if reason == 'expired': emu.time += 180
            if reason == 'backwards': emu.time -= 1
            if reason == 'clock_failure': emu.clock_error = True
            result = emu.send()
            self.assertNotIn('in-reply-to', result['headers'])
            self.assertEqual(result['target'], 'sip:stock.invalid')

    def test_non_report_rpdus_are_untouched(self):
        emu = Emulator()
        emu.receive()
        for kind in (0, 1, 3, 5, 6, 0x82):
            self.assertNotIn('in-reply-to', emu.send(kind=kind)['headers'])
        for raw in (b'', b'\x02', b'\x02\xe3' + b'\0' * 254):
            self.assertNotIn('in-reply-to', emu.send(rp=raw)['headers'])

    def test_shared_raw_receiver_ignores_3gpp2_and_other_content_types(self):
        for content_type in ('application/vnd.3gpp2.sms', 'text/plain',
                             'application/vnd.3gpp.sms+xml', 'application/vnd.3gpp.sms-other', ''):
            with self.subTest(content_type=content_type):
                emu = Emulator()
                emu.receive(content_type=content_type)
                self.assertNotIn('in-reply-to', emu.send()['headers'])
                emu.receive(call='real-3gpp@invalid')
                emu.receive(content_type=content_type, call='other-protocol@invalid')
                self.assertEqual(emu.send()['headers']['in-reply-to'], ['real-3gpp@invalid'])
        for content_type in ('APPLICATION/VND.3GPP.SMS', 'application/vnd.3gpp.sms; charset=binary'):
            emu = Emulator()
            emu.receive(content_type=content_type)
            self.assertIn('in-reply-to', emu.send()['headers'])

    def test_missed_capture_cannot_reuse_stale_reference_after_recovery(self):
        for reason in ('busy', 'busy_malformed', 'clock', 'oversized'):
            with self.subTest(reason=reason):
                emu = Emulator()
                emu.receive()
                emu.set_cache_busy(reason.startswith('busy'))
                emu.clock_error = reason == 'clock'
                emu.receive(call='new@invalid',
                            headers={} if reason == 'busy_malformed' else None,
                            rp=bytes([1, 0xe3]) + bytes(254) if reason == 'oversized' else None)
                emu.set_cache_busy(False)
                emu.clock_error = False
                self.assertNotIn('in-reply-to', emu.send()['headers'])
                emu.receive(ref=9, call='recover@invalid')
                self.assertEqual(emu.send(ref=9)['headers']['in-reply-to'], ['recover@invalid'])

    def test_busy_report_keeps_stock_behavior_and_retains_pending_context(self):
        emu = Emulator()
        emu.receive()
        emu.set_cache_busy(True)
        self.assertNotIn('in-reply-to', emu.send()['headers'])
        emu.set_cache_busy(False)
        self.assertIn('in-reply-to', emu.send()['headers'])

    def test_existing_correlation_and_invalid_native_uri_are_preserved(self):
        emu = Emulator()
        emu.receive()
        result = emu.send(headers={'In-Reply-To': 'preexisting@invalid'})
        self.assertEqual(result['headers']['in-reply-to'], ['preexisting@invalid'])
        self.assertEqual(result['target'], 'sip:stock.invalid')
        emu.reject_uri = True
        self.assertNotIn('in-reply-to', emu.send()['headers'])

    def test_cache_full_does_not_evict_live_messages(self):
        emu = Emulator()
        for ref in range(33): emu.receive(ref=ref, call='mt-%d@invalid' % ref)
        self.assertIn('in-reply-to', emu.send(ref=0)['headers'])
        self.assertNotIn('in-reply-to', emu.send(ref=32)['headers'])
        emu.time += 180
        emu.receive(ref=32)
        self.assertIn('in-reply-to', emu.send(ref=32)['headers'])

    def test_bounded_headers_and_native_length_limit(self):
        for call, gateway, rp in (('x'*512, 'sip:gw.invalid', None),
                                  ('id', 'sip:' + 'x'*512, None),
                                  ('id', 'sip:gw.invalid', bytes([1, 0xe3]) + bytes(254))):
            emu = Emulator()
            emu.receive(call=call, gateway=gateway, rp=rp)
            self.assertNotIn('in-reply-to', emu.send()['headers'])

    def test_aslr_and_abi_at_multiple_load_addresses(self):
        for base in (0, 0x10000000, 0x28000000):
            emu = Emulator(base)
            emu.receive()
            self.assertIn('in-reply-to', emu.send()['headers'])


if __name__ == '__main__':
    unittest.main()
