"""Exercise actual monitoring with a virtual clock and no radio/device writes."""
from contextlib import ExitStack
from pathlib import Path
import copy
import json
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'device'))
import service as s


CONNECTED = dict(ims='connected', register_status='200 OK', ran='LTE', radio=['lte'], power='ON')


class MonitorTests(unittest.TestCase):
    def run_monitor(self, seconds=600, observation=None, exit_at=None,
                    collection_error=None, status_error=None, events=None):
        self.now, self.sleeps = 0, []
        def sleep(delay):
            self.sleeps.append((self.now, delay))
            self.now += delay
        child = Mock()
        child.poll.side_effect = lambda: 0 if exit_at is not None and self.now >= exit_at else None
        def observe():
            value = observation(self.now) if observation else CONNECTED
            if isinstance(value, Exception):
                raise value
            return copy.deepcopy(value)
        with ExitStack() as stack:
            for item in (
                patch.object(s, 'child', child),
                patch.object(s, 'stopping', side_effect=lambda: self.now >= seconds),
                patch.object(s.time, 'time', side_effect=lambda: self.now),
                patch.object(s.time, 'sleep', side_effect=sleep),
                patch.object(s, 'ACTIVE_PROFILE', {'runtime': {'poll_seconds': 3}}),
            ):
                stack.enter_context(item)
            self.live = stack.enter_context(patch.object(s, 'live', side_effect=observe))
            self.collect = stack.enter_context(patch.object(s, 'collect_vpn_evidence', side_effect=collection_error))
            self.status = stack.enter_context(patch.object(s, 'status', side_effect=status_error))
            self.restore = stack.enter_context(patch.object(s, 'restore'))
            if events is not None:
                waiter = object.__new__(s.MonitorWaiter)
                waiter.streams = {7: (('status',), ('initial',))}
                events = list(events)
                def select(fds, write, error, timeout):
                    if events and events[0] <= self.now + timeout:
                        self.now = events.pop(0)
                        return ([7], [], [])
                    self.now += timeout
                    return ([], [], [])
                for item in (patch.object(s, 'MonitorWaiter', return_value=waiter),
                             patch.object(waiter, 'snapshot', side_effect=lambda *args: (str(self.now),)),
                             patch.object(s.select, 'select', side_effect=select),
                             patch.object(s.os, 'close')):
                    stack.enter_context(item)
            result = s.monitor_native()
            self.restore.assert_not_called()
            return result

    def test_only_stable_lte_enters_slow_observation_and_stop_remains_bounded(self):
        self.assertTrue(self.run_monitor())
        self.assertTrue(all(delay == 3 for at, delay in self.sleeps if at < 60))
        self.assertTrue(all(delay == 30 for at, delay in self.sleeps if at >= 60))
        self.assertLess(len(self.sleeps), 45)
        self.assertLess(self.collect.call_count, 15)
        self.assertLessEqual(self.now, 630)
        self.assertTrue(all(call.kwargs['observation'] == CONNECTED for call in self.status.call_args_list))

    def test_registering_missing_evidence_and_radio_off_never_back_off(self):
        for changes in ({'ims': 'disconnected'}, {'register_status': '401 Unauthorized'},
                        {'radio': ['umts']}, {'power': None}, {'power': 'OFF'}):
            with self.subTest(changes=changes):
                self.run_monitor(120, lambda now: dict(CONNECTED, **changes))
                self.assertTrue(all(delay == 3 for at, delay in self.sleeps))

    def test_observed_loss_resumes_fast_checks_without_restarting_native(self):
        self.run_monitor(180, lambda now: dict(CONNECTED, ims='disconnected') if now >= 120 else CONNECTED)
        self.assertTrue(any(delay == 30 for at, delay in self.sleeps))
        self.assertTrue(all(delay == 3 for at, delay in self.sleeps if at >= 120))
        self.assertEqual(self.status.call_args.args[0], 'registering')

    def test_native_exit_collects_final_evidence_and_does_not_reload_radio(self):
        self.assertFalse(self.run_monitor(exit_at=100))
        self.assertLessEqual(self.now, 130)
        self.assertEqual(self.status.call_args.args[0], 'native_exited')

    def test_unknown_reads_or_diagnostic_and_status_write_failures_do_not_restore_ims(self):
        self.assertTrue(self.run_monitor(observation=lambda now: OSError('PPS unavailable'),
                                        collection_error=OSError('logs unavailable'),
                                        status_error=OSError('storage full')))
        self.assertEqual(self.status.call_args.args[0], 'monitoring_unknown')
        self.assertTrue(all(delay == 30 for at, delay in self.sleeps if at >= 120))

    def test_long_registration_or_radio_off_stops_fast_polling_without_retrying_activation(self):
        for changes in ({'ims': 'disconnected'}, {'power': 'OFF'}, {'register_status': None}):
            with self.subTest(changes=changes):
                self.assertTrue(self.run_monitor(observation=lambda now: dict(CONNECTED, **changes)))
                self.assertTrue(all(delay == 30 for at, delay in self.sleeps if at >= 120))
                self.assertLess(self.collect.call_count, 12)

    def test_event_mode_does_not_rescan_status_at_each_30_second_guard(self):
        self.assertTrue(self.run_monitor(seconds=3600, events=[]))
        self.assertLess(self.live.call_count, 35)
        self.assertLess(self.collect.call_count, 18)
        self.assertLessEqual(self.now, 3630)

    def test_event_mode_detects_changes_and_native_exit_without_waiting_five_minutes(self):
        self.assertTrue(self.run_monitor(seconds=240, events=[120],
            observation=lambda now: dict(CONNECTED, ims='disconnected') if now >= 120 else CONNECTED))
        self.assertTrue(any(at == 120 and delay == 3 for at, delay in self.sleeps))
        self.assertEqual(self.status.call_args.args[0], 'registering')
        self.assertFalse(self.run_monitor(events=[], exit_at=100))
        self.assertLessEqual(self.now, 130)


@unittest.skipIf(os.name == 'nt', 'PPS descriptor fixtures require POSIX pipes and fcntl')
class EventWaitTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.fds = [os.pipe() for unused in s.MonitorWaiter.WATCHES]
        def close_pipes():
            for pair in self.fds:
                for fd in pair:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
        self.addCleanup(close_pipes)
        self.initial = b'@state\nstatus::connected\nregister_status::200 OK\ndefault_ran::LTE\n'
        for index, (fd, writer) in enumerate(self.fds):
            # Observed BB10 radioctrl status is nonpersistent, unlike IMS.
            os.write(writer, (b'[n]' if index == 2 else b'') + self.initial)
        with patch.object(s.os, 'uname', return_value=('QNX',)), \
                patch.object(s.os, 'open', side_effect=[pair[0] for pair in self.fds]) as opened:
            self.waiter = s.MonitorWaiter()
        self.assertEqual(len(self.waiter.streams), len(self.fds))
        self.assertTrue(all(call.args[1] == os.O_RDONLY | os.O_NONBLOCK for call in opened.call_args_list))
        self.addCleanup(self.waiter.close)
        self.now = 0
        stack.enter_context(patch.object(s.time, 'time', side_effect=lambda: self.now))
        self.sleep = stack.enter_context(patch.object(s.time, 'sleep', side_effect=self.advance))
        stack.enter_context(patch.object(s, 'stopping', return_value=False))
        stack.enter_context(patch.object(s, 'child', Mock(poll=Mock(return_value=None))))
        stack.enter_context(patch.object(s, 'ACTIVE_PROFILE', {'runtime': {'poll_seconds': 3}}))

    def advance(self, seconds):
        self.now += seconds

    def test_real_select_reads_a_changed_subscription_and_keeps_it_open(self):
        os.write(self.fds[0][1], b'@state\nstatus::disconnected\ndefault_ran::LTE\n')
        self.waiter.wait(300)
        self.sleep.assert_called_once_with(3)
        self.assertEqual(self.waiter.streams[self.fds[0][0]][1], (':disconnected', ':LTE'))

    def test_qualified_header_and_attributes_are_valid_but_deleted_objects_are_not(self):
        for header in (b'@status_public', b'[n]@status_public'):
            with patch.object(s.os, 'read', return_value=header + b'\n[n]status::connected\n'):
                self.assertEqual(self.waiter.snapshot(7, ('status',)), (':connected',))
        for data in (b'', b'-@status_public\n', b'[n]status::connected\n'):
            with patch.object(s.os, 'read', return_value=data), self.assertRaises(ValueError):
                self.waiter.snapshot(7, ('status',))

    def test_idle_timeout_checks_stop_at_most_30_seconds_apart(self):
        def timeout(fds, write, error, seconds):
            self.advance(seconds)
            return ([], [], [])
        with patch.object(s.select, 'select', side_effect=timeout), \
                patch.object(s, 'stopping', side_effect=lambda: self.now >= 31):
            self.waiter.wait(300)
        self.assertEqual(self.now, 60)
        self.sleep.assert_not_called()

    def test_eof_select_failure_and_repeated_unchanged_publications_fall_back(self):
        # EOF must not turn the manager into a busy loop or tear down IMS.
        fd, writer = self.fds[0]
        os.close(writer)
        self.fds[0] = (fd, -1)
        self.waiter.wait(300)
        self.assertFalse(self.waiter.streams)
        self.sleep.assert_called_once_with(30)

    def test_select_failure_closes_all_streams_and_uses_bounded_fallback(self):
        with patch.object(s.select, 'select', side_effect=OSError('unsupported notification')):
            self.waiter.wait(300)
        self.assertFalse(self.waiter.streams)
        self.sleep.assert_called_once_with(30)

    def test_repeated_identical_events_cannot_create_a_busy_loop(self):
        def publish(fds, write, error, seconds):
            os.write(self.fds[0][1], self.initial)
            return ([self.fds[0][0]], [], [])
        with patch.object(s.select, 'select', side_effect=publish) as select:
            self.waiter.wait(300)
        self.assertEqual(select.call_count, 8)
        self.assertFalse(self.waiter.streams)
        self.sleep.assert_called_once_with(30)

    def test_clock_rollback_does_not_extend_a_wait_indefinitely(self):
        def rollback(*args):
            self.now = -3600
            return ([], [], [])
        with patch.object(s.select, 'select', side_effect=rollback):
            self.waiter.wait(300)
        self.assertTrue(self.waiter.streams)
        self.sleep.assert_not_called()


class StatusWriteTests(unittest.TestCase):
    def test_unchanged_status_is_not_a_heartbeat_and_only_transitions_are_saved(self):
        with ExitStack() as stack:
            self.now = 0
            for item in (patch.object(s, 'last_status_snapshot', None),
                         patch.object(s, 'last_status_write', None),
                         patch.object(s, 'startup_timing', {}), patch.object(s, 'startup_handoff', {}),
                         patch.object(s, 'j', {'native_pid': 42}),
                         patch.object(s, 'boot_token', return_value=['boot']),
                         patch.object(s.time, 'time', side_effect=lambda: self.now),
                         patch.object(s.os.path, 'isfile', return_value=True)):
                stack.enter_context(item)
            write = stack.enter_context(patch.object(s.n, 'atomic'))
            live = stack.enter_context(patch.object(s, 'live', return_value=CONNECTED))
            s.status('running', observation=CONNECTED)
            self.now = 30
            s.status('running', observation=CONNECTED)
            self.assertEqual(write.call_count, 1)
            self.now = 86400
            s.status('running', observation=CONNECTED)
            self.assertEqual(write.call_count, 1)
            self.now += 1
            s.status('registering', observation=dict(CONNECTED, ims='disconnected'))
            self.assertEqual(write.call_count, 2)
            self.assertEqual(json.loads(write.call_args.args[1])['phase'], 'registering')
            live.assert_not_called()
            self.now = 1  # A clock correction alone does not rewrite unchanged state.
            s.status('registering', observation=dict(CONNECTED, ims='disconnected'))
            self.assertEqual(write.call_count, 2)
            with patch.object(s.os.path, 'isfile', return_value=False):
                s.status('registering', observation=dict(CONNECTED, ims='disconnected'))
            self.assertEqual(write.call_count, 3)


if __name__ == '__main__':
    unittest.main()
