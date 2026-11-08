"""Registration gating, durable deduplication and the BB10 system notification protocol."""
import copy
import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'device'))
import unified_service as u
import unified_install as install


def ready():
    return dict(enabled=True, status_from_current_boot=True, selected_this_boot=True,
                current_sim_matches=True, manager_alive=True, native_alive=True,
                phase='running', current=dict(ims='connected', register_status='200 OK',
                                             ran='LTE', radio=['lte']))


class ConnectionNotificationTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        if os.name == 'nt':
            # QNX/POSIX rename replaces atomically; Windows rename does not.
            stack.enter_context(patch.object(u.n.os, 'rename', os.replace))
            stack.enter_context(patch.object(u.n.os, 'O_NONBLOCK', 0, create=True))
        self.directory = stack.enter_context(tempfile.TemporaryDirectory())
        Path(self.directory, 'state').mkdir()
        self.token = ['test-owner', 'boot-one']
        self.selection = dict(boot=self.token, sim_sha256='current-sim')
        self.state = ready()
        self.child = Mock(pid=42)
        self.child.poll.return_value = None
        values = [patch.object(u, 'BASE', self.directory),
                  patch.object(u, 'notification_boot', None),
                  patch.object(u, 'selected', self.selection),
                  patch.object(u, 'boot_token', side_effect=lambda create=False: self.token),
                  patch.object(u.s, 'stopping', return_value=False),
                  patch.object(u.s, 'child', self.child),
                  patch.object(u.s, 'j', dict(boot=self.token, native_pid=42)),
                  patch.object(u.s, 'read_status', side_effect=lambda: copy.deepcopy(self.state)),
                  patch.object(u.policy, 'select', side_effect=lambda *args: self.selection),
                  patch.object(u.device_info, 'read_identity', return_value={}),
                  patch.object(u, 'card', return_value={})]
        for value in values:
            stack.enter_context(value)
        self.deliver = stack.enter_context(patch.object(u.n, 'command',
            return_value=b'{"hub":"accepted","popup":"accepted","popup_dismissal":"accepted"}'))
        self.receipt = Path(self.directory, 'state/connection-notification.json')

    def test_only_live_current_registration_qualifies(self):
        self.assertTrue(u.notification_ready(ready()))
        for name in ('enabled', 'status_from_current_boot', 'selected_this_boot',
                     'current_sim_matches', 'manager_alive', 'native_alive'):
            for value in (False, None, 1, 'true'):
                with self.subTest(name=name, value=value):
                    state = ready()
                    state[name] = value
                    self.assertFalse(u.notification_ready(state))
        for name, value in (('ims', 'disconnected'), ('register_status', '403 Forbidden'),
                            ('ran', 'WLAN'), ('radio', ['umts']), ('radio', ['lte', 'umts'])):
            state = ready()
            state['current'][name] = value
            self.assertFalse(u.notification_ready(state))
        self.assertFalse(u.notification_ready(dict(ready(), phase='registering')))
        self.assertFalse(u.notification_ready({}))

    def test_notifies_once_across_polling_reconnection_and_process_restart(self):
        u.notify_connection()
        self.assertEqual(self.deliver.call_count, 1)
        receipt = json.loads(self.receipt.read_text())
        self.assertEqual(receipt['result'], dict(hub='accepted', popup='accepted', popup_dismissal='accepted'))
        self.assertNotIn('current-sim', self.receipt.read_text())
        for connected in (True, False, True):
            self.state['current']['ims'] = 'connected' if connected else 'disconnected'
            u.notification_boot = None  # Simulate a new manager process too.
            u.notify_connection()
        self.assertEqual(self.deliver.call_count, 1)
        self.assertEqual(self.deliver.call_args.kwargs['timeout'], 5)

    def test_next_boot_can_notify_after_new_registration(self):
        u.notify_connection()
        self.token = ['test-owner', 'boot-two']
        self.selection['boot'] = self.token
        u.s.j['boot'] = self.token
        u.notify_connection()
        self.assertEqual(self.deliver.call_count, 2)
        first, second = [call.args[0][-1] for call in self.deliver.call_args_list]
        self.assertNotEqual(first, second)

    def test_waiting_ims_and_root_alone_do_not_notify(self):
        self.state['phase'] = 'registering'
        u.notify_connection()
        self.deliver.assert_not_called()
        self.assertFalse(self.receipt.exists())
        self.state = ready()
        u.notify_connection()
        self.deliver.assert_called_once()

    def test_sim_boot_native_exit_and_stop_are_rechecked(self):
        cases = [patch.object(u.policy, 'select', return_value=dict(sim_sha256='different')),
                 patch.object(u, 'selected', dict(self.selection, boot=['old'])),
                 patch.object(u.s, 'j', dict(boot=['old'], native_pid=42)),
                 patch.object(u.s, 'j', dict(boot=self.token, native_pid=77)),
                 patch.object(u.s, 'stopping', return_value=True),
                 patch.object(self.child, 'poll', return_value=0)]
        for case in cases:
            with case:
                u.notify_connection()
        self.deliver.assert_not_called()
        self.assertFalse(self.receipt.exists())

    def test_failed_delivery_is_recorded_without_repeated_popup(self):
        def timeout(*args, **kwargs):
            self.assertEqual(json.loads(self.receipt.read_text())['state'], 'attempted')
            raise RuntimeError('private native output must not reach the receipt')
        self.deliver.side_effect = timeout
        u.notify_connection()
        u.notification_boot = None
        u.notify_connection()
        self.deliver.assert_called_once()
        receipt = json.loads(self.receipt.read_text())
        self.assertEqual(receipt['state'], 'unconfirmed')
        self.assertEqual(receipt['error_type'], 'RuntimeError')
        self.assertNotIn('private native', self.receipt.read_text())

    def test_notification_failure_does_not_escape_into_service_recovery(self):
        with patch.object(u, 'core_status') as status, \
                patch.object(u, 'notify_connection', side_effect=OSError('UI unavailable')) as notify:
            u.status('running')
            u.status('registering')
            u.status('stopped')
        self.assertEqual(status.call_count, 3)
        notify.assert_called_once()

    def test_receipt_is_an_owned_diagnostic_for_uninstall(self):
        self.assertTrue(install.known_uninstall_member('state/connection-notification.json', {'files': {}}))
        self.assertFalse(install.known_uninstall_member('state/connection-notification.py', {'files': {}}))


class AttentionNotificationTests(unittest.TestCase):
    def setUp(self):
        ConnectionNotificationTests.setUp(self)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(u, 'attention_boot', None))
        stack.enter_context(patch.object(u, 'core_stopping', return_value=False))
        stack.enter_context(patch.object(u.s, 'shutdown', False))
        self.state.update(phase='carrier_reboot_required', native_alive=False)
        self.state['current'].update(ims='disconnected', power='ON')
        self.attention = Path(self.directory, 'state/attention-notification.json')

    def test_confirmed_terminal_reboot_notifies_once_even_after_manager_restart(self):
        u.notify_attention('carrier_reboot_required')
        u.attention_boot = None
        u.notify_attention('carrier_reboot_required')
        self.deliver.assert_called_once()
        self.assertEqual(self.deliver.call_args.args[0][-1], 'restart')
        self.assertEqual(json.loads(self.attention.read_text())['state'], 'finished')
        self.assertNotIn('current-sim', self.attention.read_text())

    def test_timeouts_waits_and_unknown_errors_are_silent(self):
        for phase, error in (('registering', '403 Forbidden'), ('waiting_for_sim', None),
                             ('native_exited', None), ('error', 'network_mode_rejected'),
                             ('error_restored', 'Timeout: LTE'), ('error_restored', 'unknown')):
            self.state['phase'] = phase
            u.notify_attention(phase, error)
        self.deliver.assert_not_called()
        self.assertFalse(self.attention.exists())

    def test_confirmed_failed_configuration_requires_completed_restore(self):
        self.state['phase'] = 'error_restored'
        u.notify_attention('error_restored', 'network_mode_rejected')
        self.deliver.assert_not_called()
        u.s.j['configuration_restored'] = True
        u.notify_attention('error_restored', 'network_mode_rejected')
        self.assertEqual(self.deliver.call_args.args[0][-1], 'activation_failed')

    def test_missing_boot_sim_power_or_manager_evidence_never_notifies(self):
        for key in ('enabled', 'status_from_current_boot', 'manager_alive'):
            for value in (False, None, 1, 'true'):
                with self.subTest(key=key, value=value):
                    original = self.state[key]
                    self.state[key] = value
                    u.notify_attention('carrier_reboot_required')
                    self.state[key] = original
        for power in ('OFF', None):
            self.state['current']['power'] = power
            u.notify_attention('carrier_reboot_required')
        self.state['current']['power'] = 'ON'
        for gate in (patch.object(u.s, 'shutdown', True),
                     patch.object(u, 'core_stopping', return_value=True),
                     patch.object(u.s, 'j', {'boot': ['old']}),
                     patch.object(u.policy, 'select', return_value={'sim_sha256': 'other'})):
            with gate:
                u.notify_attention('carrier_reboot_required')
        self.deliver.assert_not_called()

    def test_a_success_this_boot_suppresses_later_attention_and_ambiguous_delivery_is_not_retried(self):
        self.receipt.write_text(json.dumps({'boot': self.token}))
        u.notify_attention('carrier_reboot_required')
        self.deliver.assert_not_called()
        self.receipt.unlink()
        u.attention_boot = None
        self.deliver.side_effect = RuntimeError('private details')
        u.notify_attention('carrier_reboot_required')
        u.attention_boot = None
        u.notify_attention('carrier_reboot_required')
        self.deliver.assert_called_once()
        self.assertEqual(json.loads(self.attention.read_text())['state'], 'unconfirmed')
        self.assertNotIn('private details', self.attention.read_text())

    def test_notice_failure_cannot_enter_radio_recovery(self):
        with patch.object(u, 'core_status') as write, patch.object(u, 'notify_attention', side_effect=OSError):
            u.status('carrier_reboot_required')
        write.assert_called_once()
        self.assertTrue(install.known_uninstall_member('state/attention-notification.json', {'files': {}}))


class SimChangeNoticeTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.directory = stack.enter_context(tempfile.TemporaryDirectory())
        Path(self.directory, 'state').mkdir()
        Path(self.directory, 'enabled').write_bytes(b'enabled')
        self.token = ['owner', 'a' * 48]
        self.previous = {'boot': list(self.token), 'sim_sha256': 'f' * 64}
        self.snapshot = dict(state='READY', imsi='46000' + '1' * 10, mcc='460', mnc='00')
        self.child = Mock()
        self.child.poll.return_value = None
        for gate in (patch.object(u, 'BASE', self.directory),
                     patch.object(u.s, 'STOP', str(Path(self.directory, 'state/stop-request'))),
                     patch.object(u, 'sim_notice_boot', None),
                     patch.object(u, 'core_stopping', return_value=False), patch.object(u.s, 'shutdown', False),
                     patch.object(u.s, 'phone_idle', return_value=True), patch.object(u.s, 'child', self.child),
                     patch.object(u, 'selected', self.previous),
                     patch.object(u, 'boot_token', side_effect=lambda create=False: self.token),
                     patch.object(u, 'card', side_effect=lambda: dict(self.snapshot)),
                     patch.object(u.device_info, 'read_identity', return_value={}),
                     patch.object(u.policy, 'select', side_effect=lambda *args: {'sim_sha256': u.ready_sim_hash(self.snapshot)})):
            stack.enter_context(gate)
        if os.name == 'nt':
            stack.enter_context(patch.object(u.n.os, 'rename', os.replace))
            stack.enter_context(patch.object(u.n.os, 'O_NONBLOCK', 0, create=True))
        self.deliver = stack.enter_context(patch.object(u.n, 'command',
            return_value=b'{"hub":"accepted","popup":"accepted","popup_dismissal":"accepted"}'))
        self.receipt = Path(self.directory, 'state/sim-notification.json')

    def test_known_hot_swap_requests_reboot_once_from_existing_stop_check(self):
        self.assertTrue(u.stopping())
        self.assertEqual(self.deliver.call_args.args[0][-1], 'sim_restart')
        u.sim_notice_boot = None
        u.notify_sim_change(self.previous, self.snapshot)
        self.deliver.assert_called_once()
        self.assertTrue(Path(u.s.STOP).exists())
        self.assertNotIn(self.snapshot['imsi'], self.receipt.read_text())
        self.assertNotIn(self.previous['sim_sha256'], self.receipt.read_text())

    def test_different_card_after_real_reboot_requests_app_review_not_another_reboot(self):
        self.previous['boot'] = ['owner', 'b' * 48]
        u.notify_sim_change(self.previous, self.snapshot, after_reboot=True)
        self.assertEqual(self.deliver.call_args.args[0][-1], 'sim_review')
        u.sim_notice_boot = None
        u.notify_sim_change(self.previous, self.snapshot, after_reboot=True)
        self.deliver.assert_called_once()

    def test_ordinary_reboot_first_install_missing_or_changed_readback_are_silent(self):
        u.notify_sim_change(None, self.snapshot, after_reboot=True)
        u.notify_sim_change(dict(self.previous, sim_sha256=u.ready_sim_hash(self.snapshot)), self.snapshot)
        u.notify_sim_change(self.previous, self.snapshot, after_reboot=True)
        for snapshot in ({}, dict(self.snapshot, state='NOT_READY'), dict(self.snapshot, imsi='unknown'),
                         dict(self.snapshot, mnc='01')):
            u.notify_sim_change(self.previous, snapshot)
        with patch.object(u, 'card', return_value=dict(self.snapshot, imsi='46000' + '2' * 10)):
            u.notify_sim_change(self.previous, self.snapshot)
        self.deliver.assert_not_called()

    def test_unknown_sim_never_stops_a_working_service_even_after_a_long_wait(self):
        for snapshot in ({}, dict(self.snapshot, state='NOT_READY'),
                         dict(self.snapshot, imsi='unknown'), dict(self.snapshot, mnc='01')):
            with patch.object(u, 'card', return_value=snapshot):
                for now in (0, 40, 600, 86400):
                    with patch.object(u.time, 'time', return_value=now):
                        self.assertFalse(u.stopping())
        for failure in (OSError('read failed'), ValueError('bad PPS'), TypeError('missing identity')):
            with patch.object(u, 'card', side_effect=failure):
                self.assertFalse(u.stopping())
        self.assertFalse(Path(u.s.STOP).exists())
        self.deliver.assert_not_called()

    def test_same_card_conflicting_readback_and_active_call_preserve_service(self):
        same = dict(self.previous, sim_sha256=u.ready_sim_hash(self.snapshot))
        with patch.object(u, 'selected', same):
            self.assertFalse(u.stopping())
        with patch.object(u, 'card', side_effect=[self.snapshot, dict(self.snapshot, imsi='46000' + '2' * 10)]):
            self.assertFalse(u.stopping())
        for gate in (patch.object(u.s, 'phone_idle', return_value=False),
                     patch.object(u.s, 'phone_idle', side_effect=[True, False]),
                     patch.object(u.s, 'phone_idle', side_effect=OSError('unreadable call state'))):
            with gate:
                self.assertFalse(u.stopping())
        self.assertFalse(Path(u.s.STOP).exists())
        self.deliver.assert_not_called()

    def test_call_starting_during_notification_defers_stop(self):
        def deliver(*args, **kwargs):
            self.idle = False
            return b'{"hub":"accepted","popup":"accepted","popup_dismissal":"accepted"}'
        self.idle = True
        self.deliver.side_effect = deliver
        with patch.object(u.s, 'phone_idle', side_effect=lambda: self.idle):
            self.assertFalse(u.stopping())
        self.assertFalse(Path(u.s.STOP).exists())
        self.deliver.assert_called_once()

    def test_unchanged_auxiliary_receipts_do_not_write_again(self):
        path = str(Path(self.directory, 'state/auxiliary.json'))
        value = {'display_updated': True}
        with patch.object(u.n, 'atomic', wraps=u.n.atomic) as write:
            u.save_if_changed(path, value)
            u.save_if_changed(path, value)
            self.assertEqual(write.call_count, 1)
            u.save_if_changed(path, {'display_updated': False})
            self.assertEqual(write.call_count, 2)

    def test_known_unsupported_replacement_still_requires_normal_restart(self):
        self.snapshot.update(imsi='00101' + '1' * 10, mcc='001', mnc='01')
        with patch.object(u.policy, 'select', side_effect=ValueError('unsupported carrier')):
            self.assertTrue(u.stopping())
        self.assertEqual(self.deliver.call_args.args[0][-1], 'sim_restart')

    def test_busy_shutdown_disabled_or_lost_delivery_never_triggers_repeated_alerts(self):
        for gate in (patch.object(u.s, 'phone_idle', return_value=False),
                     patch.object(u.s, 'shutdown', True), patch.object(u, 'core_stopping', return_value=True)):
            with gate:
                u.notify_sim_change(self.previous, self.snapshot)
        self.deliver.assert_not_called()
        self.deliver.side_effect = OSError('notification unavailable')
        u.notify_sim_change(self.previous, self.snapshot)
        u.sim_notice_boot = None
        u.notify_sim_change(self.previous, self.snapshot)
        self.deliver.assert_called_once()
        self.assertEqual(json.loads(self.receipt.read_text())['state'], 'unconfirmed')
        self.assertTrue(install.known_uninstall_member('state/sim-notification.json', {'files': {}}))


class PpsDeliveryTests(unittest.TestCase):
    ITEM = 'bb10volte_' + 'a' * 24

    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(u.os, 'O_NONBLOCK', 0, create=True))
        self.open = stack.enter_context(patch.object(u.os, 'open', return_value=7))
        self.close = stack.enter_context(patch.object(u.os, 'close'))
        self.write = stack.enter_context(patch.object(u.os, 'write', side_effect=lambda fd, data: len(data)))
        self.replies = [b'@control\n', self.reply()]
        self.read = stack.enter_context(patch.object(u.os, 'read',
            side_effect=lambda *args: self.replies.pop(0) if self.replies else b''))
        self.select = stack.enter_context(patch('select.select', return_value=([7], [], [])))
        self.toast = stack.enter_context(patch.object(u, 'connection_toast',
            return_value=dict(popup='accepted', popup_dismissal='accepted')))

    def reply(self, item=None, result='dat::ok', operation='notify'):
        return ('@control\nid::' + (item or self.ITEM + '_hub') + '\nres::' + operation +
                '\n' + result + '\n').encode('ascii')

    def test_hub_contains_details_without_a_persistent_modal_popup(self):
        self.assertEqual(u.deliver_connection_notification(self.ITEM),
                         dict(hub='accepted', popup='accepted', popup_dismissal='accepted'))
        self.open.assert_called_once_with('/pps/system/notify/control', os.O_RDWR | os.O_NONBLOCK)
        self.write.assert_called_once()
        packet = self.write.call_args.args[1].decode('ascii')
        data = json.loads(next(line[9:] for line in packet.splitlines() if line.startswith('dat:json:')))
        self.assertEqual(data['AppId'], 'sys.service')
        self.assertEqual(data['Type'], 'uib')
        self.assertEqual(data['ItemId'], self.ITEM + '_hub')
        self.assertIn('测试通话和声音', data['Subtitle'])
        self.assertNotIn('Cancel', packet)
        self.assertNotIn('Delete', packet)

    def test_attention_uses_the_same_short_toast_and_never_claims_connection(self):
        u.deliver_connection_notification(self.ITEM, 'activation_failed')
        packet = self.write.call_args.args[1].decode('ascii')
        data = json.loads(next(line[9:] for line in packet.splitlines() if line.startswith('dat:json:')))
        self.assertIn('启动未完成', data['Title'])
        self.assertNotIn('已连接', data['Title'])
        self.toast.assert_called_once_with('activation_failed')
        self.toast.assert_called_once()
        self.close.assert_called_once_with(7)

    def test_hub_rejection_does_not_prevent_toast(self):
        self.replies[1] = self.reply(result='err::MISSING_SETTINGS')
        result = u.deliver_connection_notification(self.ITEM)
        self.assertEqual(result['hub'], 'error')
        self.assertEqual(result['popup'], 'accepted')

    def test_toast_failure_does_not_undo_the_hub_notification(self):
        self.toast.side_effect = OSError('UI unavailable')
        result = u.deliver_connection_notification(self.ITEM)
        self.assertEqual(result['hub'], 'accepted')
        self.assertEqual(result['popup'], 'error')
        self.write.assert_called_once()

    def test_unrelated_id_or_wrong_operation_cannot_confirm_delivery(self):
        self.replies = [b'@control\n', self.reply(item='another_request'), self.reply(operation='cancel')]
        result = u.deliver_connection_notification(self.ITEM)
        self.assertEqual(result['hub'], 'unconfirmed')
        self.assertEqual(self.select.call_count, 20)
        self.toast.assert_called_once()

    def test_missing_hub_ack_is_bounded_and_does_not_delay_toast_indefinitely(self):
        self.select.return_value = ([], [], [])
        self.assertEqual(u.deliver_connection_notification(self.ITEM)['hub'], 'unconfirmed')
        self.assertEqual(self.select.call_count, 20)
        self.assertTrue(all(call.args[-1] == 0.05 for call in self.select.call_args_list))
        self.toast.assert_called_once()
        self.write.assert_called_once()

    def test_short_write_and_read_failure_do_not_prevent_toast(self):
        self.write.side_effect = lambda fd, data: len(data) - 1
        self.assertEqual(u.deliver_connection_notification(self.ITEM)['hub'], 'error')
        self.toast.assert_called_once()
        self.select.assert_not_called()
        self.toast.reset_mock()
        self.read.side_effect = OSError('unavailable')
        self.assertEqual(u.deliver_connection_notification(self.ITEM)['hub'], 'error')
        self.toast.assert_called_once()

    def test_invalid_id_cannot_open_notification_channel(self):
        with self.assertRaises(AssertionError):
            u.deliver_connection_notification('bad\nmsg::Notify')
        self.open.assert_not_called()
        self.toast.assert_not_called()


class FakeDialog:
    def __init__(self, clicked=False):
        self.bps_initialize = Mock(return_value=0)
        self.bps_shutdown = Mock()
        self.dialog_request_events = Mock(return_value=0)
        self.dialog_create_toast = Mock(side_effect=self.create)
        for name in ('dialog_set_system', 'dialog_set_toast_position', 'dialog_set_toast_message_text',
                     'dialog_add_button', 'dialog_set_cancel_required', 'dialog_show',
                     'dialog_cancel', 'dialog_destroy'):
            setattr(self, name, Mock(return_value=0))
        self.bps_get_event = Mock(side_effect=(self.click if clicked else lambda *args: 0))
        self.bps_event_get_domain = Mock(return_value=7)
        self.dialog_get_domain = Mock(return_value=7)
        self.dialog_event_get_dialog_instance = Mock(return_value=42)

    def create(self, ref):
        ref._obj.value = 42
        return 0

    def click(self, ref, timeout):
        ref._obj.value = 99
        return 0


class NativeToastTests(unittest.TestCase):
    def show(self, library):
        with patch.object(ctypes, 'CDLL', return_value=library):
            return u.connection_toast()

    def test_bottom_toast_has_short_text_and_immediate_dismiss_button(self):
        fake = FakeDialog(clicked=True)
        self.assertEqual(self.show(fake), dict(popup='accepted', popup_dismissal='accepted'))
        self.assertEqual(fake.dialog_set_toast_position.call_args.args[1], 2)
        self.assertEqual(fake.dialog_set_toast_message_text.call_args.args[1].decode('utf-8'), 'VoLTE 已连接')
        self.assertEqual(fake.dialog_add_button.call_args.args[1:], ('关闭'.encode('utf-8'), True, b'dismiss', True))
        self.assertFalse(fake.dialog_set_cancel_required.call_args.args[1])
        self.assertEqual(fake.bps_get_event.call_count, 1)
        fake.dialog_cancel.assert_called_once()
        fake.dialog_destroy.assert_called_once()
        fake.bps_shutdown.assert_called_once()

    def test_unseen_toast_does_not_wait_for_touch_before_timeout(self):
        fake = FakeDialog()
        self.assertEqual(self.show(fake), dict(popup='accepted', popup_dismissal='accepted'))
        self.assertEqual(fake.bps_get_event.call_count, 15)
        self.assertEqual(sum(call.args[1] for call in fake.bps_get_event.call_args_list), 1500)
        fake.dialog_cancel.assert_called_once()
        fake.dialog_destroy.assert_called_once()

    def test_unrelated_ui_events_cannot_extend_wait_or_close_another_dialog(self):
        fake = FakeDialog(clicked=True)
        fake.dialog_event_get_dialog_instance.return_value = 500
        self.show(fake)
        self.assertEqual(fake.bps_get_event.call_count, 15)
        self.assertEqual(fake.dialog_cancel.call_args.args[0].value, 42)

    def test_elapsed_processing_time_is_included_in_the_deadline(self):
        fake = FakeDialog()
        with patch.object(u.time, 'time', side_effect=[10, 11.45, 11.6]):
            self.show(fake)
        self.assertEqual(fake.bps_get_event.call_count, 1)
        self.assertLessEqual(fake.bps_get_event.call_args.args[1], 50)
        fake.dialog_cancel.assert_called_once()

    def test_event_failure_still_cancels_and_releases_the_visible_toast(self):
        fake = FakeDialog()
        fake.bps_get_event.side_effect = OSError('event failure')
        self.assertEqual(self.show(fake), dict(popup='accepted', popup_dismissal='accepted'))
        fake.dialog_cancel.assert_called_once()
        fake.dialog_destroy.assert_called_once()
        fake.bps_shutdown.assert_called_once()

    def test_cancel_failure_is_reported_and_destroy_is_still_attempted(self):
        fake = FakeDialog()
        fake.dialog_cancel.return_value = -1
        self.assertEqual(self.show(fake), dict(popup='accepted', popup_dismissal='error'))
        fake.dialog_destroy.assert_called_once()
        fake.bps_shutdown.assert_called_once()

    def test_failed_creation_never_claims_a_visible_popup(self):
        fake = FakeDialog()
        fake.dialog_create_toast.side_effect = lambda *args: -1
        self.assertEqual(self.show(fake)['popup'], 'error')
        fake.dialog_show.assert_not_called()
        fake.dialog_cancel.assert_not_called()
        fake.bps_shutdown.assert_called_once()


if __name__ == '__main__':
    unittest.main()
