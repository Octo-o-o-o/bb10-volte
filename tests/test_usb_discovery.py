"""Stock first-boot DHCP, ambiguous interfaces and bounded anonymous discovery."""
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import root_setup as r


def link(address='169.254.237.210', prefix=30, active=True, index=19):
    return {'index': index, 'active': active, 'ipv4': [address], 'prefixes': {address: prefix}}


class USBDiscoveryTests(unittest.TestCase):
    def test_stock_dhcp_peer_is_derived_only_from_single_blackberry_link(self):
        with patch.object(r.sys, 'platform', 'win32'):
            self.assertEqual(r.usb_discovery_targets({'usb_count': 1, 'network_interfaces': [link()]}),
                             [('169.254.237.209', '169.254.237.210', 19)])
            for interface in (link(prefix=16), link(active=False), link(index=None),
                              link(address='192.168.1.2'), link(address='169.254.237.209'),
                              link(address='invalid')):
                self.assertEqual(r.usb_discovery_targets({'usb_count': 1, 'network_interfaces': [interface]}), [])
            for count in (0, 2, None):
                self.assertEqual(r.usb_discovery_targets({'usb_count': count, 'network_interfaces': [link()]}), [])

    def test_local_inventory_does_not_choose_between_two_active_networks(self):
        state = {'usb_count': 1, 'network_interfaces': [link(), link('169.254.5.2', index=20)]}
        with patch.object(r.sys, 'platform', 'win32'), patch.object(r, 'powershell', return_value='powershell.exe'), patch.object(r.subprocess, 'run',
                return_value=MagicMock(returncode=0, stdout=json.dumps(state))), patch.object(r, 'discovery') as query:
            self.assertEqual(r.local_usb_state()['device'], {})
            query.assert_not_called()

    def test_query_is_interface_bound_and_only_returns_allowlisted_metadata(self):
        response = MagicMock(status=200)
        response.read.return_value = b'<d><ModelName>SQW100-4</ModelName><OobeCompleted>0</OobeCompleted><PIN>private</PIN></d>'
        connection, sock = MagicMock(), MagicMock()
        connection.getresponse.return_value = response
        with patch.object(r.sys, 'platform', 'win32'), patch.object(r.http.client, 'HTTPConnection', return_value=connection), \
                patch.object(r.socket, 'socket', return_value=sock):
            self.assertEqual(r.discovery('169.254.237.209', '169.254.237.210', 19),
                             {'ModelName': 'SQW100-4', 'OobeCompleted': '0'})
        sock.setsockopt.assert_called_once_with(r.socket.IPPROTO_IP, 31, struct.pack('!I', 19))
        sock.bind.assert_called_once_with(('169.254.237.210', 0))
        sock.connect.assert_called_once_with(('169.254.237.209', 80))
        response.read.assert_called_once_with(131073)
        connection.close.assert_called_once()

    def test_redirect_oversize_and_malformed_responses_are_rejected(self):
        for status, data in [(302, b'<d/>'), (200, b'x' * 131073), (200, b'not xml')]:
            connection = MagicMock()
            connection.getresponse.return_value = MagicMock(status=status, read=MagicMock(return_value=data))
            with patch.object(r.http.client, 'HTTPConnection', return_value=connection):
                self.assertEqual(r.discovery(), {})
            self.assertEqual(connection.request.call_count, 1)
            connection.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
