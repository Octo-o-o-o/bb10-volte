"""Q20 isolation, boot ownership and independent SIP evidence regressions."""
import ast
import binascii
import json
import os
from pathlib import Path
import tempfile
import time
import types
import unittest

import q20_call_evidence as evidence
import q20_own_number_auto as own_number

SOURCE = Path(__file__).with_name('q20_volte_phone.py')
FUNCTIONS = ast.Module(body=[item for item in ast.parse(SOURCE.read_text()).body
                            if isinstance(item, ast.FunctionDef)], type_ignores=[])


class BootTests(unittest.TestCase):
    def namespace(self, directory):
        fake_os = types.SimpleNamespace(path=os.path, open=os.open, fdopen=os.fdopen,
            O_WRONLY=os.O_WRONLY, O_CREAT=os.O_CREAT, O_EXCL=os.O_EXCL,
            urandom=os.urandom, geteuid=lambda: 0, uname=lambda: ('QNX',))
        def load(path):
            return json.loads(Path(path).read_text())
        s = types.SimpleNamespace(load=load, MODULE='module', ACTIVE_REQUEST={})
        values = {'os': fake_os, 's': s, 'BOOT': str(Path(directory) / 'boot.json'),
            'BASE': str(Path(directory) / 'payload'), 'binascii': binascii,
            'json': json, 'time': time,
            'ctypes': types.SimpleNamespace(sizeof=lambda value: 4, c_void_p=object()),
            'device_info': types.SimpleNamespace(read_identity=lambda: {
                'variant': 'SQW100-4', 'board_type': 'WINDERMERE4ROW', 'os_version': '10.3.3.3216'})}
        exec(compile(FUNCTIONS, str(SOURCE), 'exec'), values)
        return values

    def test_nonce_is_stable_only_within_this_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            g = self.namespace(directory)
            first = g['boot_token']()
            self.assertEqual(first, g['boot_token']())
            os.unlink(g['BOOT'])
            self.assertNotEqual(first, g['boot_token']())

    def test_read_only_lookup_does_not_create_a_cookie(self):
        with tempfile.TemporaryDirectory() as directory:
            g = self.namespace(directory)
            with self.assertRaises(AssertionError):
                g['boot_token'](False)
            self.assertFalse(os.path.exists(g['BOOT']))

    def test_passport_is_rejected_before_payload_and_native_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            g = self.namespace(directory)
            g['s'].load = lambda path: self.fail('Passport must be rejected first')
            with self.assertRaises(AssertionError):
                g['verify']()

    def test_foreign_marker_is_preserved_and_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            g = self.namespace(directory)
            path = Path(g['BOOT'])
            path.write_text(json.dumps({'owner': 'other', 'nonce': 'a' * 48}))
            before = path.read_bytes()
            with self.assertRaises(AssertionError):
                g['boot_token']()
            self.assertEqual(before, path.read_bytes())

    def test_truthy_strings_do_not_authorize_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            g = self.namespace(directory)
            g['verify'] = lambda: None
            base = Path(g['BASE'])
            (base / 'state').mkdir(parents=True)
            (base / 'enabled').touch()
            receipt = {'owner': 'q20-call-acceptance-v1', 'variant': 'SQC100-2',
                'profile_sha256': 'profile', 'incoming': 'true', 'outgoing': True,
                'audio_both_directions': True, 'lte': True, 'sip_dialogs_verified': True}
            (base / 'state/manual-call-acceptance.json').write_text(json.dumps(receipt))
            g['profiles'] = types.SimpleNamespace(fingerprint=lambda request: 'profile')
            with self.assertRaises(AssertionError):
                g['launch'](True)
            self.assertFalse(Path(g['BOOT']).exists())


class SipTests(unittest.TestCase):
    def dialog(self, incoming=False, answer=200, ack=True):
        initial = 'IN' if incoming else 'OUT'
        opposite = 'OUT' if incoming else 'IN'
        result = []
        def packet(at, direction, header, seq, method):
            marker = '<<<<<< IN' if direction == 'IN' else '>>>>>> OUT'
            for body in (marker, header, 'Call-ID: private-test-dialog', 'CSeq: %s %s' % (seq, method)):
                result.append('Oct 30 %s ims_rrm.123 sip 3261 %s' % (at, body))
        packet('21:00:01.000', initial, 'INVITE sip:redacted SIP/2.0', 2, 'INVITE')
        packet('21:00:03.000', opposite, 'SIP/2.0 %s response' % answer, 2, 'INVITE')
        if ack:
            packet('21:00:03.100', initial, 'ACK sip:redacted SIP/2.0', 2, 'ACK')
        packet('21:00:23.000', opposite, 'BYE sip:redacted SIP/2.0', 3, 'BYE')
        packet('21:00:23.100', initial, 'SIP/2.0 200 OK', 3, 'BYE')
        return '\n'.join(result)

    def test_both_directions_and_answered_duration(self):
        for incoming in (False, True):
            calls = evidence.dialogs(evidence.packets(self.dialog(incoming), 123))
            self.assertEqual(calls[0]['direction'], 'incoming' if incoming else 'outgoing')
            self.assertEqual(calls[0]['established_seconds_to_bye'], 20)
            self.assertNotIn('Call-ID', json.dumps(calls))

    def test_failed_or_unacknowledged_invites_are_not_accepted(self):
        for text in (self.dialog(answer=487), self.dialog(ack=False)):
            self.assertEqual(evidence.dialogs(evidence.packets(text, 123)), [])

    def test_other_process_and_non_packet_send_noise_are_ignored(self):
        text = self.dialog(True) + '\nOct 30 21:00:01.000 ims_rrm.123 main 1 Send fake\n'
        self.assertEqual(evidence.dialogs(evidence.packets(text, 123))[0]['direction'], 'incoming')
        self.assertEqual(evidence.packets(text, 999), [])


class StartupPlacementTests(unittest.TestCase):
    def patcher(self):
        path = Path(__file__).with_name('q20_volte_boot_install_phone.py')
        tree = ast.parse(path.read_text())
        hook = ast.literal_eval(next(item.value for item in tree.body if isinstance(item, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == 'HOOK' for target in item.targets)))
        function = next(item for item in tree.body if isinstance(item, ast.FunctionDef)
                        and item.name == 'patched_root_script')
        values = {'HOOK': hook}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), values)
        return values['patched_root_script'], hook

    def test_entry_precedes_the_unbounded_legacy_installer(self):
        patch, hook = self.patcher()
        original = b'#!/bin/sh\nsshd\n. /base/scripts/sudtools.sh\nsud_install_package Term49.bar'
        result = patch(original)
        self.assertEqual(result.replace(hook, b'', 1), original)
        self.assertLess(result.index(hook), result.index(b'sud_install_package'))
        self.assertIn(b'2>&1 &\n', hook)

    def test_ambiguous_or_already_modified_scripts_are_rejected(self):
        patch, hook = self.patcher()
        for original in (b'unknown script', b'. /base/scripts/sudtools.sh\n' * 2,
                         hook + b'. /base/scripts/sudtools.sh\n'):
            with self.assertRaises(AssertionError):
                patch(original)


class OwnNumberTests(unittest.TestCase):
    def packet(self, direction='IN', method='REGISTER', number='+86' + '138' + '0' * 8):
        marker = '<<<<<< IN' if direction == 'IN' else '>>>>>> OUT'
        return '\n'.join('Oct 30 22:00:00.000 ims_rrm.123 sip 3261 ' + body for body in
            (marker, 'SIP/2.0 200 OK', 'P-Associated-URI: <tel:' + number + '>', 'CSeq: 2 ' + method))

    def test_only_authenticated_registration_supplies_the_display_number(self):
        text = (self.packet(method='INVITE', number='+86' + '138' + '0' * 7 + '1') + '\n' +
                self.packet(direction='OUT', number='+86' + '138' + '0' * 7 + '2') + '\n' + self.packet())
        self.assertEqual(own_number.registered_numbers(text, 123), {'+86' + '138' + '0' * 8})
        self.assertEqual(own_number.registered_numbers(text, 999), set())

    def test_imsi_is_never_converted_to_a_telephone_number(self):
        self.assertEqual(own_number.phone_numbers('sip:' + '46001' + '0' * 9 + '1@ims.example'), set())

    def test_a_changed_sim_is_rejected_before_any_native_read(self):
        with self.assertRaises(AssertionError):
            own_number.synchronize(None, 123, ['boot', 'nonce'], '46001' + '0' * 9 + '1', 'wrong')


class SelectionRollbackTests(unittest.TestCase):
    def restore(self, client):
        path = Path(__file__).with_name('q20_telecom_selection_trial_phone.py')
        function = next(item for item in ast.parse(path.read_text()).body
                        if isinstance(item, ast.FunctionDef) and item.name == 'restore')
        values = {'NasClient': client, 'time': types.SimpleNamespace(sleep=lambda seconds: None)}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), values)
        return values['restore']({'usage_preference': 1, 'mode_preference_mask': 28})

    def test_unreadable_usage_does_not_skip_rat_restoration(self):
        writes = []
        class Client:
            requests = 0
            mode = 16
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def request(self, message):
                Client.requests += 1
                if Client.requests <= 3:
                    raise RuntimeError('Temporary transport error')
                return {'mode_preference_mask': Client.mode, 'usage_preference': 1}
            def set_preference(self, field, value):
                writes.append((field, value))
                Client.mode = value
        result = self.restore(Client)
        self.assertFalse(result['usage_preference']['restored'])
        self.assertTrue(result['mode_preference_mask']['restored'])
        self.assertEqual(writes, [('mode_preference_mask', 28)])

    def test_foreign_selection_is_preserved(self):
        class Client:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def request(self, message):
                return {'usage_preference': 1, 'mode_preference_mask': 99}
            def set_preference(self, *args):
                raise AssertionError('Foreign preference must not be overwritten')
        result = self.restore(Client)
        self.assertTrue(result['usage_preference']['restored'])
        self.assertFalse(result['mode_preference_mask']['restored'])

    def test_permanent_and_unrelated_modem_writes_are_rejected(self):
        path = Path(__file__).with_name('q20_nas_client_phone.py')
        klass = next(item for item in ast.parse(path.read_text()).body if isinstance(item, ast.ClassDef))
        values = {}
        exec(compile(ast.Module(body=[klass], type_ignores=[]), str(path), 'exec'), values)
        client = values['NasClient']()
        for message, payload in ((0x33, bytes.fromhex('110200100017010001')),
                                 (0x33, bytes.fromhex('2304000100000017010000')),
                                 (0x33, bytes.fromhex('1804000100000017010001')),
                                 (0x33, bytes.fromhex('1804000000000017010000')),
                                 (0x22, bytes.fromhex('01010002100500cc010b00081101000112010000')),
                                 (0x22, bytes.fromhex('01010002100500cc010100081101000012010000')),
                                 (0x00, None), (0x33, None)):
            with self.assertRaises(AssertionError):
                client.request(message, payload)


class VoiceRollbackTests(unittest.TestCase):
    def test_missing_initial_read_still_restores_and_verifies_original_policy(self):
        for filename, applied in (('q20_telecom_voice_retry_phone.py', 3),
                                  ('q20_telecom_ps_voice_trial_phone.py', 1)):
            with self.subTest(filename=filename):
                path = Path(__file__).with_name(filename)
                function = next(item for item in ast.parse(path.read_text()).body
                                if isinstance(item, ast.FunctionDef) and item.name == 'restore_voice')
                values = iter(({'value': None, 'error_type': 'AssertionError'},
                               {'value': applied}, {'value': 0}))
                setters = []
                def setter(value):
                    setters.append(value)
                    return {'rc': 0}
                namespace = {'read_policy': lambda: next(values), 'q': types.SimpleNamespace(
                    s=types.SimpleNamespace(set_voice_preference=setter)),
                    'time': types.SimpleNamespace(sleep=lambda seconds: None)}
                exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
                result = namespace['restore_voice']()
                self.assertTrue(result['restored'])
                self.assertEqual(setters, [4])


class DcaSourceTests(unittest.TestCase):
    def functions(self):
        path = Path(__file__).with_name('q20_telecom_dca_usage_phone.py')
        items = [item for item in ast.parse(path.read_text()).body
                 if isinstance(item, ast.FunctionDef) and item.name in ('payload', 'write_existing')]
        namespace = {'HEADER': b'@cellular_protocol_configuration\n', 'os': os,
                     'q': types.SimpleNamespace(n=types.SimpleNamespace(read=lambda p: Path(p).read_bytes()))}
        exec(compile(ast.Module(body=items, type_ignores=[]), str(path), 'exec'), namespace)
        return namespace

    def test_unknown_source_attributes_are_rejected(self):
        g = self.functions()
        with self.assertRaises(AssertionError):
            g['payload'](b'@cellular_protocol_configuration\nother_setting:n:1\n', 'data_centric')

    def test_a_concurrent_source_edit_is_never_truncated(self):
        g = self.functions()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source'
            path.write_bytes(b'changed-by-carrier-manager')
            info = path.stat()
            item = {'identity': [info.st_ino, info.st_mode & 0o7777, info.st_uid, info.st_gid]}
            with self.assertRaises(AssertionError):
                g['write_existing'](str(path), b'our-original', b'our-applied', item)
            self.assertEqual(path.read_bytes(), b'changed-by-carrier-manager')


class RuntimeOwnershipTests(unittest.TestCase):
    def namespace(self, folder):
        import hashlib
        base = Path(folder)
        runtime = base / 'runtime'
        runtime.mkdir()
        binary = runtime / 'ims_rrm'
        binary.write_bytes(b'old-owned-image')
        service = types.SimpleNamespace(j={'managed_files': {}}, RUNTIME=str(runtime),
            BIN=str(binary), APN=str(runtime / 'carrier/36-ims.xml'), save_journal=lambda: None,
            load=lambda path: json.loads(Path(path).read_text()))
        namespace = {'BASE': str(base), 'os': os, 's': service,
                     'n': types.SimpleNamespace(read=lambda path: Path(path).read_bytes(),
                         digest=lambda data: hashlib.sha256(data).hexdigest())}
        function = next(item for item in FUNCTIONS.body if item.name == 'recover_runtime_ownership')
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), 'exec'), namespace)
        return namespace, binary

    def test_unknown_old_runtime_is_preserved_and_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            g, binary = self.namespace(folder)
            with self.assertRaises(AssertionError):
                g['recover_runtime_ownership']()
            self.assertEqual(binary.read_bytes(), b'old-owned-image')
            self.assertEqual(g['s'].j['managed_files'], {})

    def test_completed_epoch_hash_can_restore_runtime_ownership(self):
        with tempfile.TemporaryDirectory() as folder:
            g, binary = self.namespace(folder)
            archive = Path(folder) / 'archive/previous-carrier'
            archive.mkdir(parents=True)
            digest = g['n'].digest(binary.read_bytes())
            (archive / 'journal-original.json').write_text(json.dumps({
                'owner': 'q10-unicom-volte-v1', 'original_voice_policy': 0,
                'native_pid': None, 'configuration_restored': True,
                'managed_files': {str(binary): digest}}))
            g['recover_runtime_ownership']()
            self.assertEqual(g['s'].j['managed_files'], {str(binary): digest})
            self.assertEqual(binary.read_bytes(), b'old-owned-image')


class TelecomScopeTests(unittest.TestCase):
    def test_previous_boot_pid_cannot_be_adopted_into_the_new_boot(self):
        path = Path(__file__).with_name('q20_telecom_carrier.py')
        function = next(item for item in ast.parse(path.read_text()).body
                        if isinstance(item, ast.FunctionDef) and item.name == 'adopt_journal')
        namespace = {'OWNER': 'q20-telecom-carrier-v1'}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
        service = types.SimpleNamespace(j={'original_voice_policy': 0, 'boot': ['old'], 'native_pid': 123},
                                        init_journal=lambda: None, save_journal=lambda: None)
        q = types.SimpleNamespace(s=service, boot_token=lambda: ['new'])
        namespace['adopt_journal'](q, '/owned/plan')
        self.assertIsNone(service.j['native_pid'])
        self.assertEqual(service.j['telecom_previous_native_pid'], 123)
        self.assertEqual(service.j['boot'], ['new'])

    def test_other_operator_is_rejected_before_native_or_source_access(self):
        path = Path(__file__).with_name('q20_telecom_carrier.py')
        functions = [item for item in ast.parse(path.read_text()).body
                     if isinstance(item, ast.FunctionDef) and item.name in ('selected', 'load_plan')]
        namespace = {}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), namespace)
        for mcc, mnc in (('460', '01'), ('460', '00'), ('460', '03'), ('310', '11')):
            q = types.SimpleNamespace(s=types.SimpleNamespace(ACTIVE_PROFILE={
                'carrier': {'mcc': mcc, 'mncs': [mnc]}}))
            with self.assertRaises(AssertionError):
                namespace['load_plan'](q)


if __name__ == '__main__':
    unittest.main()
