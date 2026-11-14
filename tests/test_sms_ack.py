"""Protocol cases executed as compiled ARM/Thumb instructions, not a Python clone."""
from contextlib import ExitStack
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'device'), str(ROOT / 'tools')]
import build_sms_ack
try:
    from sms_ack_emulator import Emulator, decode_tlv
except ModuleNotFoundError as error:
    if error.name != 'unicorn':
        raise
    Emulator = None
    decode_tlv = None


class SmsAckArtifactTests(unittest.TestCase):
    def test_library_constructor_requires_explicit_sms_opt_in(self):
        import ims_image
        with patch.object(ims_image, '_voice_binary', return_value=(b'accepted', [])), \
                patch.object(ims_image, 'sms_ack_binary', return_value=(b'candidate', [])) as shim:
            self.assertEqual(ims_image.temporary_binary(b'stock', True), (b'accepted', []))
            shim.assert_not_called()
            self.assertEqual(ims_image.temporary_binary(b'stock', True, sms_ack=True), (b'candidate', []))
            shim.assert_called_once_with(b'accepted', [])
            self.assertEqual(
                ims_image.temporary_binary(b'stock', True, sms_ack=True, telecom_mo_ack=True),
                (b'candidate', []),
            )
            shim.assert_called_with(b'accepted', [], telecom_mo_ack=True)
            with self.assertRaisesRegex(AssertionError, 'explicit'):
                ims_image.temporary_binary(b'stock', True, sms_ack='true')
            with self.assertRaisesRegex(AssertionError, 'explicit'):
                ims_image.temporary_binary(b'stock', True, sms_ack=True, telecom_mo_ack='true')
            with self.assertRaisesRegex(AssertionError, 'requires SMS shim'):
                ims_image.temporary_binary(b'stock', True, sms_ack=False, telecom_mo_ack=True)

    def test_service_configure_selects_telecom_mo_ack_only_for_460_03_and_460_11(self):
        import service
        saved = (service.ACTIVE_REQUEST, service.ACTIVE_PROFILE, dict(service.UPDATES), service.j, service.temporary_binary)
        calls = []

        def fake_temp(original, normal_voice=False, sms_ack=False, telecom_mo_ack=False):
            calls.append((normal_voice, sms_ack, telecom_mo_ack))
            return b'patched', [{'telecom_mo_ack': telecom_mo_ack}]

        try:
            for mnc, sms_enabled, expected_telecom in (
                ('11', True, True),
                ('03', True, True),
                ('11', False, False),
                ('01', True, False),
                ('00', True, False),
                ('07', True, False),
            ):
                calls.clear()
                service.ACTIVE_REQUEST = {'id': 'test'}
                service.ACTIVE_PROFILE = {
                    'id': 'test',
                    'carrier': {'mcc': '460', 'mncs': [mnc]},
                    'ims': {'sms': sms_enabled},
                    'apn': {'name': 'ims'},
                }
                service.UPDATES = {}
                service.j = {'crypto_boot': ['boot'], 'provider': 1, 'restore_completed': True}
                service.temporary_binary = fake_temp
                imsi = '460' + mnc + '1234567890'
                network = {'mcc': '460', 'mnc': mnc, 'imsi': imsi}
                with self.subTest(mnc=mnc, sms=sms_enabled), ExitStack() as stack:
                    for ctx in (
                        patch.object(service, 'ready', return_value=True),
                        patch.object(service, 'current_usim', return_value=imsi),
                        patch.object(service.compatibility, 'read_network', return_value=network),
                        patch.object(service.profiles, 'identity_matches', return_value=True),
                        patch.object(service.profiles, 'carrier_template',
                                     return_value=({'path': '/etc/carrier/config/446.xml', 'sha256': '0' * 64}, b'<xml/>')),
                        patch.object(service, 'profile_updates', return_value={}),
                        patch.object(service, 'init_journal'),
                        patch.object(service, 'journal_sms_policy'),
                        patch.object(service.profiles, 'fingerprint', return_value='f' * 64),
                        patch.object(service.n, 'ims_pids', return_value=[]),
                        patch.object(service, 'collect_vpn_evidence'),
                        patch.object(service, 'cleanup_vpn'),
                        patch.object(service, 'boot_token', return_value=['boot']),
                        patch.object(service.n, 'vpn_ids', return_value=set()),
                        patch.object(service.n, 'vpn_configs', return_value={}),
                        patch.object(service, 'save_journal'),
                        patch.object(service.n, 'read', side_effect=lambda p: b'IMS_platform::common\n' if p == service.CFG else b'stock'),
                        patch.object(service, 'write_owned'),
                        patch.object(service.os.path, 'exists', return_value=True),
                        patch.object(service.os.path, 'islink', return_value=False),
                        patch.object(service.os, 'listdir', return_value=['ims']),
                        patch.object(service.os, 'chmod'),
                        patch.object(service.n, 'attrs', return_value={'IMS_platform': ':common'}),
                        patch.object(service.n, 'update_pps'),
                        patch.object(service.profiles, 'home_domain', return_value='ims.mnc011.mcc460.3gppnetwork.org'),
                        patch.object(service.n, 'voice_policy', return_value=3),
                        patch.object(service, 'apply_fields'),
                        patch.object(service.n, 'crypto_policy', return_value={'swcr_id': 1, 'crypto_support': 1}),
                        patch.object(service, 'wait_for_ims_apn'),
                        patch.object(service.n, 'command'),
                    ):
                        stack.enter_context(ctx)
                    service.configure()
                self.assertEqual(calls, [(True, True, expected_telecom)])
        finally:
            service.ACTIVE_REQUEST, service.ACTIVE_PROFILE, service.UPDATES, service.j, service.temporary_binary = saved

    def test_generated_payload_matches_pinned_source_and_manifest(self):
        build_sms_ack.check_generated()

    def test_native_image_guard_rejects_unknown_or_already_modified_firmware(self):
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

    def test_telecom_mo_2xx_emits_rp_pdu_status_then_synthetic_3gpp_rp_ack(self):
        emu = Emulator(telecom_mo_ack=True)
        mo_msg = emu.send_mo(ref=0x38, call='mo-telecom-1@invalid', pdu_id=7)
        self.assertNotIn('in-reply-to', mo_msg['headers'])
        self.assertEqual(mo_msg['target'], 'sip:stock.invalid')
        pdu_id, rc = emu.deliver_mo_success(
            call='mo-telecom-1@invalid', ipc=0x4444, out1_used=True, out2_used=True
        )
        self.assertEqual((pdu_id, rc), (7, 0))
        self.assertEqual(len(emu.ipc_sent), 2)
        self.assertEqual((emu.ipc_sent[0][0], emu.ipc_sent[0][2]), (0x4444, 0))
        self.assertEqual(decode_tlv(emu.ipc_sent[0][1])[0], 0x1014)
        self.assertEqual((emu.ipc_sent[1][0], emu.ipc_sent[1][2]), (0x4444, 0))
        self.assertEqual(
            emu.ipc_sent[1][1].hex(),
            '15100600411001000338000042100100020000004410010000000000',
        )
        # Single-consumption guarantee: re-registering the same Call-ID without a
        # new MO capture must not synthesize a second RP-ACK.
        emu.ipc_sent.clear()
        emu.pending_mo[(0x2000, 'mo-telecom-1@invalid')] = (7, 0xaa, 0xbb)
        pdu_id_again, rc_again = emu.deliver_mo_success(call='mo-telecom-1@invalid', ipc=0x4444)
        self.assertEqual((pdu_id_again, rc_again), (7, 0))
        self.assertEqual([decode_tlv(item[1])[0] for item in emu.ipc_sent], [0x1014])

    def test_telecom_mo_interleaved_and_multipart_preserve_each_rp_reference(self):
        emu = Emulator(telecom_mo_ack=True)
        for idx, ref in enumerate((0xa1, 0xa2, 0xa3), start=1):
            emu.send_mo(ref=ref, call='seg-%d@invalid' % idx, pdu_id=idx)
        for idx, ref in ((2, 0xa2), (3, 0xa3), (1, 0xa1)):
            emu.ipc_sent.clear()
            pdu_id, rc = emu.deliver_mo_success(call='seg-%d@invalid' % idx)
            self.assertEqual((pdu_id, rc), (idx, 0))
            self.assertEqual([decode_tlv(item[1])[0] for item in emu.ipc_sent], [0x1014, 0x1015])
            _, items = decode_tlv(emu.ipc_sent[1][1])
            self.assertEqual(items[0], (0x1041, bytes([0x03, ref, 0, 0])))

    def test_non_telecom_tx_hook_ignores_mo_rp_data(self):
        emu = Emulator(telecom_mo_ack=False)
        emu.send_mo(ref=0x44, call='unicom-mo@invalid', pdu_id=3)
        pdu_id, rc = emu.deliver_mo_success(call='unicom-mo@invalid')
        self.assertEqual((pdu_id, rc), (3, 0))
        self.assertEqual([decode_tlv(item[1])[0] for item in emu.ipc_sent], [0x1014])

    def test_telecom_mo_guards_skip_synthesis_on_unmatched_expired_or_ipc_failure(self):
        # 1) Unknown pending SMS (pdu_id == 0xff)
        emu = Emulator(telecom_mo_ack=True)
        emu.send_mo(ref=0x51, call='orphan@invalid', pdu_id=None)
        self.assertEqual(emu.deliver_mo_success(call='orphan@invalid'), (0xff, None))
        self.assertEqual(emu.ipc_sent, [])

        # 2) Expired, backwards clock, clock failure, or status ipc_send error
        for reason in ('expired', 'backwards', 'clock_failure', 'ipc_error', 'conflict'):
            with self.subTest(reason=reason):
                emu = Emulator(telecom_mo_ack=True)
                emu.send_mo(ref=0x52, call='case@invalid', pdu_id=9)
                if reason == 'conflict':
                    emu.send_mo(ref=0x53, call='case@invalid', pdu_id=9)
                elif reason == 'expired':
                    emu.time += 180
                elif reason == 'backwards':
                    emu.time -= 1
                elif reason == 'clock_failure':
                    emu.clock_error = True
                elif reason == 'ipc_error':
                    emu.ipc_error = True
                pdu_id, rc = emu.deliver_mo_success(call='case@invalid')
                self.assertEqual(pdu_id, 9)
                if reason == 'ipc_error':
                    self.assertEqual(rc, 0xffffffff)
                    self.assertEqual(emu.ipc_sent, [])
                else:
                    self.assertEqual(rc, 0)
                    self.assertEqual([decode_tlv(item[1])[0] for item in emu.ipc_sent], [0x1014])

    def test_telecom_mo_and_mt_correlation_coexist_across_aslr_bases(self):
        for base in (0, 0x10000000, 0x28000000):
            with self.subTest(base=hex(base)):
                emu = Emulator(base, telecom_mo_ack=True)
                emu.receive(ref=0xe3, call='mt-1@invalid', gateway='sip:ipsmgw.telecom.invalid;user=phone')
                emu.send_mo(ref=0x2a, call='mo-1@invalid', pdu_id=2)
                mt_report = emu.send(ref=0xe3, kind=2)
                self.assertEqual(mt_report['headers']['in-reply-to'], ['mt-1@invalid'])
                self.assertEqual(mt_report['target'], 'sip:ipsmgw.telecom.invalid;user=phone')
                pdu_id, rc = emu.deliver_mo_success(call='mo-1@invalid')
                self.assertEqual((pdu_id, rc), (2, 0))
                self.assertEqual([decode_tlv(item[1])[0] for item in emu.ipc_sent], [0x1014, 0x1015])


if __name__ == '__main__':
    unittest.main()
