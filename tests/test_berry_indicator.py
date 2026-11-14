"""Verify automatic QNX Navigator BlackBerry status-bar indicator lifecycle."""
from contextlib import ExitStack
import copy
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'device'))
import native as n
import service as s
import unified_service as u


CONNECTED = {
    'ims': 'connected',
    'register_status': '200 OK',
    'ran': 'LTE',
    'radio': ['lte'],
    'power': 'ON',
}


class FakeBerryPps:
    """In-memory QNX /pps/system/navigator/status/bb_service(?critical) model."""

    def __init__(self, initial=b'@bb_service\n', fail_open=None, short_write=False):
        self.raw = initial
        self.noncritical = initial
        self.fail_open = fail_open
        self.short_write = short_write
        self.next_fd = 900
        self.open_fds = {}
        self.cloexec_fds = set()
        self.writes = []
        self.opens = []

    def open(self, path, flags, *args):
        self.opens.append((path, flags))
        if self.fail_open is not None:
            raise self.fail_open
        fd = self.next_fd
        self.next_fd += 1
        if path == s.BB_SERVICE:
            self.open_fds[fd] = {'kind': 'read', 'offset': 0, 'data': self.raw}
            return fd
        if path == s.BB_SERVICE + '?critical':
            if flags & os.O_CREAT:
                raise AssertionError('Must not pass O_CREAT to Navigator PPS')
            self.open_fds[fd] = {'kind': 'critical', 'wrote_critical': False}
            return fd
        raise OSError('unexpected_path:' + path)

    def read(self, fd, size):
        entry = self.open_fds[fd]
        chunk = entry['data'][entry['offset']:entry['offset'] + size]
        entry['offset'] += len(chunk)
        return chunk

    def write(self, fd, payload):
        entry = self.open_fds[fd]
        assert entry['kind'] == 'critical'
        self.writes.append(payload)
        if self.short_write:
            return 3
        assert payload == s.BB_SERVICE_ON
        entry['wrote_critical'] = True
        self.raw = b'@bb_service\n' + payload
        return len(payload)

    def close(self, fd):
        entry = self.open_fds.pop(fd)
        self.cloexec_fds.discard(fd)
        if entry['kind'] == 'critical' and entry['wrote_critical']:
            self.raw = b'@bb_service\n'

    def set_cloexec(self, fd):
        assert fd in self.open_fds
        self.cloexec_fds.add(fd)


class BerryIndicatorTests(unittest.TestCase):
    def tearDown(self):
        s.berry_fd = None

    def _service_context(self, stack, pps, boot=None, stopping_fn=None, alive=True):
        boot = [1, 2] if boot is None else boot
        child = Mock()
        child.pid = 4321
        child.poll.return_value = None if alive else 0
        stack.enter_context(patch.object(s, 'berry_ready', s.core_berry_ready if hasattr(s, 'core_berry_ready') else u.core_berry_ready))
        stack.enter_context(patch.object(s, 'child', child))
        stack.enter_context(patch.object(s, 'j', {'boot': boot, 'native_pid': 4321}))
        stack.enter_context(patch.object(s, 'boot_token', return_value=boot))
        stack.enter_context(patch.object(s, 'stopping', side_effect=stopping_fn or (lambda: False)))
        stack.enter_context(patch.object(s.os, 'uname', return_value=('QNX',), create=True))
        stack.enter_context(patch.object(s.os, 'open', side_effect=pps.open))
        stack.enter_context(patch.object(s.os, 'read', side_effect=pps.read))
        stack.enter_context(patch.object(s.os, 'write', side_effect=pps.write))
        stack.enter_context(patch.object(s.os, 'close', side_effect=pps.close))
        stack.enter_context(patch.object(s, 'set_cloexec', side_effect=pps.set_cloexec))
        return child

    def test_lights_up_on_connected_lte_and_reverts_immediately_on_loss_without_extra_writes(self):
        pps = FakeBerryPps()
        with ExitStack() as stack:
            self._service_context(stack, pps)
            s.sync_berry_indicator('registering', dict(CONNECTED, ims='connecting'))
            self.assertIsNone(s.berry_fd)
            self.assertEqual(pps.raw, b'@bb_service\n')

            s.sync_berry_indicator('running', CONNECTED)
            self.assertIsNotNone(s.berry_fd)
            self.assertIn(s.berry_fd, pps.cloexec_fds)
            self.assertEqual(pps.raw, b'@bb_service\n[n]dat:json:{"bb_service":{"state":"on"}}\n')
            self.assertEqual(len(pps.writes), 1)

            # Steady-state polls must keep the single ?critical fd without redundant writes.
            s.sync_berry_indicator('running', dict(CONNECTED, ran='lte'))
            self.assertEqual(len(pps.writes), 1)
            self.assertEqual(len(pps.open_fds), 1)

            # Airplane mode / radio OFF extinguishes immediately.
            s.sync_berry_indicator('running', dict(CONNECTED, power='OFF'))
            self.assertIsNone(s.berry_fd)
            self.assertEqual(pps.open_fds, {})
            self.assertEqual(pps.raw, b'@bb_service\n')

            # Re-registration lights up cleanly again.
            s.sync_berry_indicator('running', CONNECTED)
            self.assertIsNotNone(s.berry_fd)
            self.assertEqual(pps.raw, b'@bb_service\n[n]dat:json:{"bb_service":{"state":"on"}}\n')

            # 3G fallback or non-200 REGISTER extinguishes immediately.
            for degraded in (
                dict(CONNECTED, radio=['umts']),
                dict(CONNECTED, ran='UMTS'),
                dict(CONNECTED, ims='disconnected'),
                dict(CONNECTED, register_status='403 Forbidden'),
            ):
                s.sync_berry_indicator('running', CONNECTED)
                self.assertIsNotNone(s.berry_fd)
                s.sync_berry_indicator('running', degraded)
                self.assertIsNone(s.berry_fd)
                self.assertEqual(pps.raw, b'@bb_service\n')

    def test_preserves_external_blackberry_infrastructure_on_state(self):
        external_on = b'@bb_service\ndat:json:{"bb_service":{"state":"on"}}\n'
        pps = FakeBerryPps(initial=external_on)
        with ExitStack() as stack:
            self._service_context(stack, pps)
            s.sync_berry_indicator('running', CONNECTED)
            self.assertIsNone(s.berry_fd)
            self.assertEqual(pps.writes, [])
            self.assertEqual(pps.raw, external_on)
            s.sync_berry_indicator('registering', dict(CONNECTED, ims='disconnected'))
            self.assertEqual(pps.raw, external_on)

    def test_lights_up_when_prior_noncritical_state_is_off(self):
        pps = FakeBerryPps(initial=b'@bb_service\ndat:json:{"bb_service":{"state":"off"}}\n')
        with ExitStack() as stack:
            self._service_context(stack, pps)
            s.sync_berry_indicator('running', CONNECTED)
            self.assertIsNotNone(s.berry_fd)
            self.assertEqual(pps.raw, b'@bb_service\n[n]dat:json:{"bb_service":{"state":"on"}}\n')
            s.close_berry_indicator()
            self.assertIsNone(s.berry_fd)
            self.assertEqual(pps.raw, b'@bb_service\n')

    def test_open_or_write_errors_are_isolated_and_never_leak_descriptors(self):
        for pps in (
            FakeBerryPps(fail_open=OSError('missing_navigator_pps')),
            FakeBerryPps(short_write=True),
        ):
            with ExitStack() as stack:
                self._service_context(stack, pps)
                s.sync_berry_indicator('running', CONNECTED)
                self.assertIsNone(s.berry_fd)
                self.assertEqual(pps.open_fds, {})

    def test_unified_service_requires_enabled_current_boot_and_matching_sim(self):
        pps = FakeBerryPps()
        imsi = '46011' + ('0' * 10)
        other_imsi = '46011' + ('9' * 10)
        sim_hash = n.digest(imsi.encode('ascii'))
        token = ['bb10-unified-carriers-v1', 'a' * 48]
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            enabled_path = Path(tmp) / 'enabled'
            enabled_path.write_bytes(b'enabled\n')
            self._service_context(stack, pps, boot=token)
            stack.enter_context(patch.object(u, 'BASE', tmp))
            stack.enter_context(patch.object(u, 'boot_token', return_value=token))
            stack.enter_context(patch.object(u, 'selected', {'boot': token, 'sim_sha256': sim_hash}))
            card_state = {'state': 'READY', 'kind': 6, 'mcc': '460', 'mnc': '11', 'imsi': imsi}
            stack.enter_context(patch.object(u, 'card', side_effect=lambda: copy.deepcopy(card_state)))
            stack.enter_context(patch.object(s, 'berry_ready', u.berry_ready))

            s.sync_berry_indicator('running', CONNECTED)
            self.assertIsNotNone(s.berry_fd)
            self.assertEqual(pps.raw, b'@bb_service\n[n]dat:json:{"bb_service":{"state":"on"}}\n')

            # SIM ejected -> indicator turns off immediately.
            card_state['state'] = 'ABSENT'
            s.sync_berry_indicator('running', CONNECTED)
            self.assertIsNone(s.berry_fd)
            self.assertEqual(pps.raw, b'@bb_service\n')

            # SIM restored -> indicator lights back up.
            card_state['state'] = 'READY'
            s.sync_berry_indicator('running', CONNECTED)
            self.assertIsNotNone(s.berry_fd)

            # Different SIM -> indicator turns off immediately.
            card_state['imsi'] = other_imsi
            s.sync_berry_indicator('running', CONNECTED)
            self.assertIsNone(s.berry_fd)
            self.assertEqual(pps.raw, b'@bb_service\n')

            # Service disabled -> stays off even with original SIM.
            card_state['imsi'] = imsi
            enabled_path.unlink()
            s.sync_berry_indicator('running', CONNECTED)
            self.assertIsNone(s.berry_fd)

    def test_job_entry_runtime_only_calls_setup_before_verify_and_cleans_stage(self):
        import base64, contextlib, importlib.util, posixpath, types
        spec = importlib.util.spec_from_file_location('mobile_entry_for_berry', ROOT / 'mobile/runtime/entry.py')
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        with patch.dict(sys.modules, {'entry': entry}):
            jspec = importlib.util.spec_from_file_location('mobile_job_entry_for_berry', ROOT / 'mobile/runtime/job_entry.py')
            child = importlib.util.module_from_spec(jspec)
            jspec.loader.exec_module(child)
        raw = b'signed manifest fixture'
        fake_root = posixpath.realpath('/var/test')
        folder = fake_root + '/snapshots/' + entry.digest(raw)
        request = {'action': 'engine-update', 'operation_id': 'a' * 32}
        encoded = base64.b64encode(entry.canonical(request)).decode('ascii')
        calls = []
        fake_worker = types.SimpleNamespace(stage_payload=lambda f, op: '/var/bb10_auto_stage_aaaaaaaaaaaa')
        manager = types.SimpleNamespace(
            BASE='/var/bb10_volte',
            UPDATE_PENDING='/var/bb10_volte/update-pending.json',
            management_lock=lambda: contextlib.nullcontext(),
            installed_management_schema=lambda: 2,
            s=types.SimpleNamespace(load=lambda p: {'files': {'a': '1'}}),
            u=types.SimpleNamespace(
                setup=lambda: calls.append('setup'),
                verify=lambda: calls.append('verify'),
            ),
            cleanup_stage=lambda st: calls.append(('cleanup_stage', st)),
        )
        with patch.object(child, '__file__', folder + '/runtime/job_entry.py'), \
             patch.object(entry, 'ROOT', fake_root), \
             patch.object(entry.os, 'path', posixpath), \
             patch.object(child.os, 'path', posixpath), \
             patch.object(posixpath, 'isfile', return_value=False), \
             patch.object(entry.os, 'geteuid', return_value=0, create=True), \
             patch.object(entry.os, 'uname', return_value=('QNX',), create=True), \
             patch.object(entry, 'private_directory'), \
             patch.object(entry, 'read_bundle', return_value=({}, raw, b'', {})), \
             patch.object(entry.sys, 'argv', ['job_entry.py', encoded]), \
             patch.object(entry.sys, 'path', list(entry.sys.path)), \
             patch.dict(sys.modules, {'worker': fake_worker, 'unified_install': manager}):
            res = child.main()
        self.assertEqual(res, {'updated': True, 'runtime_only': True, 'reboot_required': False, 'ok': True})
        self.assertEqual(calls, ['setup', 'verify', ('cleanup_stage', '/var/bb10_auto_stage_aaaaaaaaaaaa')])

    def test_python32_byte_literal_compatibility(self):
        import tokenize
        for name in ('service.py', 'unified_service.py', 'unified_install.py'):
            with (ROOT / 'device' / name).open('rb') as handle:
                for tok in tokenize.tokenize(handle.readline):
                    if tok.type == tokenize.STRING:
                        prefix = re.match(r'[a-zA-Z]+', tok.string)
                        if prefix is not None:
                            self.assertNotIn(prefix.group(0).lower(), ('rb', 'f', 'rf', 'fr'), name)


if __name__ == '__main__':
    unittest.main()
