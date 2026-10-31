"""Authenticated display identity, SIM isolation and reversible PPS updates."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'device'))
import native
import unified_own_number as number
import unified_service as service

PID = 4321
BOOT = ['test-boot']
# Synthetic fixtures are assembled so release scanning cannot mistake them for
# identifiers copied from a device or an owner's real telephone number.
IMSI = '460' + '01' + '12345' * 2
NUMBER = '+86' + '138' + '0' * 7 + '1'
SECOND = '+86' + '139' + '0' * 7 + '2'


def response(value=NUMBER, pid=PID, code=200, method='REGISTER', inbound=True, associated=True):
    bodies = ['<<<< IN' if inbound else '>>>> OUT', 'SIP/2.0 ' + str(code) + ' response',
              'CSeq: 9 ' + method, ('P-Associated-URI: ' if associated else 'To: ') + '<tel:' + value + '>']
    return '\n'.join('Oct 31 12:00:00.000 ims_rrm.%s sip 3261 %s' % (pid, body) for body in bodies)


class FakeNative:
    def __init__(self):
        self.files = {path: b'@cellular\naddress::\n' for path in number.PATHS}
        self.log = response().encode()
        self.pps_writes = []
        self.fail_next_write = False

    attrs = staticmethod(native.attrs)

    def read(self, path):
        return self.files[path]

    def atomic(self, path, blob):
        self.files[path] = blob

    def command(self, args, timeout):
        assert args == ['/bin/slog2info', '-b', 'ims_rrm']
        return self.log

    def update_pps(self, path, updates):
        assert path in number.PATHS and set(updates) == {'address'}
        if self.fail_next_write:
            self.fail_next_write = False
            raise OSError('interrupted display update')
        value = updates['address']
        self.files[path] = ('@cellular\n' + ('address:' + value + '\n' if value is not None else '')).encode()
        self.pps_writes.append(path)


class OwnNumberTests(unittest.TestCase):
    def setUp(self):
        self.n = FakeNative()
        for replacement in (patch.object(number.os.path, 'isfile', side_effect=lambda p: p in self.n.files),
                            patch.object(number.os.path, 'isdir', return_value=True)):
            replacement.start()
            self.addCleanup(replacement.stop)

    def sync(self, boot=BOOT, imsi=IMSI, **kwargs):
        return number.synchronize(self.n, PID, boot, imsi, hashlib.sha256(imsi.encode()).hexdigest(), **kwargs)

    def addresses(self):
        return [self.n.attrs(self.n.read(path)).get('address') for path in number.PATHS]

    def test_only_current_pid_inbound_REGISTER_200_associated_identity_is_accepted(self):
        for invalid in (response(pid=PID + 1), response(code=401), response(method='INVITE'),
                        response(inbound=False), response(associated=False)):
            with self.subTest(invalid=invalid):
                self.assertEqual(number.registered_numbers(invalid, PID), set())
        self.assertEqual(number.registered_numbers(response() + '\n' + response(NUMBER[3:]), PID), {NUMBER})

    def test_blank_display_is_filled_with_redacted_result_and_restored(self):
        result = self.sync()
        self.assertTrue(result['readback_verified'])
        self.assertEqual(self.addresses(), [':' + NUMBER] * 2)
        self.assertNotIn(NUMBER, json.dumps(result))
        self.assertEqual((result['sim_write_requests'], result['radio_setting_write_requests']), (0, 0))
        number.restore(self.n, BOOT, IMSI)
        self.assertEqual(self.addresses(), [':'] * 2)

    def test_missing_or_ambiguous_authenticated_numbers_do_not_write_display(self):
        for log in (b'', (response() + '\n' + response(SECOND)).encode()):
            self.n.log = log
            self.assertFalse(self.sync()['display_updated'])
        self.assertFalse(self.n.pps_writes)
        self.assertNotIn(number.JOURNAL, self.n.files)

    def test_changed_sim_cannot_reuse_current_process_identity(self):
        with self.assertRaisesRegex(AssertionError, 'SIM changed'):
            number.synchronize(self.n, PID, BOOT, IMSI, 'different')
        self.assertFalse(self.n.pps_writes)

    def test_current_boot_cache_survives_log_rotation_and_repairs_cleared_field(self):
        self.sync()
        self.n.log = b''
        self.n.files[number.PATHS[1]] = b'@cellular\naddress::\n'
        self.assertTrue(self.sync()['readback_verified'])
        self.assertEqual(self.addresses(), [':' + NUMBER] * 2)

    def test_new_boot_requires_fresh_authentication_even_for_same_sim(self):
        self.sync()
        self.n.log = b''
        count = len(self.n.pps_writes)
        self.assertFalse(self.sync(boot=['next-boot'])['display_updated'])
        self.assertEqual(len(self.n.pps_writes), count)

    def test_switching_sim_never_restores_the_previous_sim_owned_number(self):
        self.sync()
        self.n.log = response(SECOND).encode()
        second_imsi, second_boot = '460' + '00' + '12345' * 2, ['next-boot']
        self.sync(boot=second_boot, imsi=second_imsi)
        self.assertEqual(self.addresses(), [':' + SECOND] * 2)
        number.restore(self.n, second_boot, second_imsi)
        self.assertEqual(self.addresses(), [':'] * 2)

    def test_independent_nonempty_number_is_preserved(self):
        self.n.files[number.PATHS[0]] = ('@cellular\naddress::' + SECOND + '\n').encode()
        result = self.sync()
        self.assertEqual(result['reason'], 'different_existing_address_preserved')
        self.assertFalse(self.n.pps_writes)

    def test_existing_correct_number_caches_proof_without_claiming_the_fields(self):
        for path in number.PATHS:
            self.n.files[path] = ('@cellular\naddress::' + NUMBER + '\n').encode()
        self.sync()
        journal = json.loads(self.n.files[number.JOURNAL])
        self.assertEqual(journal['changed_paths'], [])
        self.n.log = b''
        self.assertTrue(self.sync()['readback_verified'])
        number.restore(self.n, BOOT, IMSI)
        self.assertFalse(self.n.pps_writes)

    def test_later_cache_repair_records_newly_owned_fields_for_restore(self):
        self.n.files[number.PATHS[0]] = ('@cellular\naddress::' + NUMBER + '\n').encode()
        self.sync()
        self.n.files[number.PATHS[0]] = b'@cellular\naddress::\n'
        self.n.log = b''
        self.sync()
        self.assertEqual(set(json.loads(self.n.files[number.JOURNAL])['changed_paths']), set(number.PATHS))
        number.restore(self.n, BOOT, IMSI)
        self.assertEqual(self.addresses(), [':' + NUMBER, ':'])

    def test_interrupted_write_resumes_with_original_rollback_values(self):
        original = self.n.update_pps
        def interrupt_after_first(path, updates):
            original(path, updates)
            self.n.fail_next_write = True
        with patch.object(self.n, 'update_pps', side_effect=interrupt_after_first):
            with self.assertRaises(OSError):
                self.sync()
        self.n.fail_next_write = False
        self.n.log = b''
        self.sync()
        number.restore(self.n, BOOT, IMSI)
        self.assertEqual(self.addresses(), [':'] * 2)

    def test_restore_requires_same_boot_and_same_sim(self):
        self.sync()
        for boot, imsi in ((['other'], IMSI), (BOOT, '460' + '00' + '12345' * 2)):
            with self.assertRaises(AssertionError):
                number.restore(self.n, boot, imsi)


class UnifiedDisplayIntegrationTests(unittest.TestCase):
    def test_all_three_models_update_only_from_owned_registered_boot(self):
        for family in ('q10', 'classic', 'passport'):
            for owned, registered in ((True, True), (False, True), (True, False)):
                with self.subTest(family=family, owned=owned, registered=registered):
                    import unified_operator_name
                    with patch.object(service, 'core_collect'), patch.object(service, 'boot_token', return_value=BOOT), \
                         patch.object(service, 'selected', {'family': family, 'sim_sha256': 'expected'}), \
                         patch.object(service.s, 'j', {'boot': BOOT if owned else ['old'], 'native_pid': PID}), \
                         patch.object(unified_operator_name, 'synchronize'), patch.object(service, 'save'), \
                         patch.object(service, 'live', return_value={'ims': 'connected' if registered else 'disconnected', 'register_status': '200 OK'}), \
                         patch.object(service.s, 'current_usim', return_value=IMSI), \
                         patch.object(number, 'synchronize', return_value={'actual_number_exported': False}) as synchronize:
                        service.collect()
                        self.assertEqual(synchronize.call_count, int(owned and registered))
                        if owned and registered:
                            synchronize.assert_called_once_with(service.n, PID, BOOT, IMSI, 'expected')


if __name__ == '__main__':
    unittest.main()
