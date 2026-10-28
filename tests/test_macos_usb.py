"""USB ancestry and link state fixtures; never modify host networking."""
import json
import plistlib
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import macos_usb as m


def device(vendor=m.VENDOR, identity=1, children=()):
    return {'IOObjectClass': 'IOUSBHostDevice', 'idVendor': vendor, 'idProduct': 0x8017,
            'IORegistryEntryID': identity, 'IORegistryEntryName': 'BlackBerry',
            'USB Serial Number': 'private-device-serial', m.CHILDREN: list(children)}


def network(name='en37'):
    return {'IOObjectClass': 'AppleUSBNCMData', 'CFBundleIdentifier': 'com.apple.driver.usb.cdc.ncm',
            m.CHILDREN: [{'IOObjectClass': 'IOEthernetInterface', 'BSD Name': name,
                          'IOMACAddress': b'private-hardware-address'}]}


def plist(value):
    return SimpleNamespace(stdout=plistlib.dumps(value))


def link(name='en37', address='169.254.0.2', active=True):
    return SimpleNamespace(stdout=name + ': flags=8863<UP,BROADCAST,RUNNING> mtu 1500\n' +
                           ('\tinet ' + address + ' netmask 0xfffffffc\n' if address else '') +
                           '\tstatus: ' + ('active' if active else 'inactive') + '\n')


class MacUSBTests(unittest.TestCase):
    def test_links_only_interfaces_under_blackberry_and_returns_public_facts(self):
        child = device(0x1234, 3, [network('en2')])
        roots = [device(children=[network(), child]), device(0x1234, 2, [network('en1')])]
        with patch.object(m.subprocess, 'run', side_effect=[plist([device()]), plist(roots), link()]) as run:
            state = m.read_state()
        self.assertTrue(state['usb_present'])
        self.assertTrue(state['driver_ready'])
        self.assertTrue(state['usb_network'])
        self.assertTrue(state['usb_address_ready'])
        self.assertEqual(state['usb_count'], 1)
        self.assertEqual(state['network_interfaces'], [{'name': 'en37', 'driver': 'com.apple.driver.usb.cdc.ncm',
                                                       'active': True, 'ipv4': ['169.254.0.2']}])
        self.assertEqual(run.call_args_list[-1].args[0], ['/sbin/ifconfig', 'en37'])
        self.assertNotIn('private-', json.dumps(state))
        self.assertEqual(run.call_args_list[0].args[0][-2:], ['-d', '1'])
        self.assertEqual(run.call_args_list[1].args[0][-2:], ['-d', '12'])

    def test_usb_absent_is_distinct_from_enumerated_without_network_driver(self):
        with patch.object(m.subprocess, 'run', return_value=plist([device(0x1234)])) as run:
            state = m.read_state()
        self.assertFalse(state['usb_present'])
        self.assertEqual(state['usb_count'], 0)
        self.assertFalse(state['usb_network'])
        self.assertEqual(run.call_count, 1)
        with patch.object(m.subprocess, 'run', side_effect=[plist([device()]), plist([device()])]):
            state = m.read_state()
        self.assertTrue(state['usb_present'])
        self.assertFalse(state['driver_ready'])
        self.assertFalse(state['usb_network'])

    def test_bound_inactive_and_wrong_source_address_do_not_claim_address_ready(self):
        for address, active in [('', False), ('169.254.19.20', True)]:
            with self.subTest(address=address), patch.object(m.subprocess, 'run', side_effect=[
                    plist([device()]), plist([device(children=[network()])]), link(address=address, active=active)]):
                state = m.read_state()
            self.assertTrue(state['driver_ready'])
            self.assertEqual(state['usb_network'], active)
            self.assertFalse(state['usb_address_ready'])

    def test_missing_tools_and_invalid_registry_data_stay_unknown(self):
        for response in (FileNotFoundError(), subprocess.TimeoutExpired('ioreg', 12),
                         subprocess.CalledProcessError(1, 'ioreg'), SimpleNamespace(stdout=b'not plist'),
                         plist({'not': 'roots'})):
            with self.subTest(response=repr(response)), patch.object(m.subprocess, 'run', side_effect=[response]):
                state = m.read_state()
            self.assertIsNone(state['usb_present'])
            self.assertIsNone(state['driver_ready'])
            self.assertIsNone(state['usb_network'])

    def test_device_change_or_malformed_subtree_preserves_known_usb_but_unknown_driver(self):
        invalid = device()
        invalid[m.CHILDREN] = 'unexpected'
        for subtree in ([device(identity=2)], [invalid]):
            with self.subTest(subtree=subtree), patch.object(m.subprocess, 'run', side_effect=[plist([device()]), plist(subtree)]):
                state = m.read_state()
            self.assertTrue(state['usb_present'])
            self.assertIsNone(state['driver_ready'])
            self.assertIsNone(state['usb_network'])

    def test_ifconfig_failure_preserves_binding_without_claiming_link_or_address(self):
        for response in (subprocess.CalledProcessError(1, 'ifconfig'),
                         SimpleNamespace(stdout='en2: flags=1<UP>\n\tstatus: active\n'),
                         SimpleNamespace(stdout='en37: flags=1<UP>\n\tstatus: unknown\n')):
            with self.subTest(response=repr(response)), patch.object(m.subprocess, 'run', side_effect=[
                    plist([device()]), plist([device(children=[network()])]), response]):
                state = m.read_state()
            self.assertTrue(state['driver_ready'])
            self.assertIsNone(state['usb_network'])
            self.assertIsNone(state['usb_address_ready'])

    def test_multiple_matching_devices_are_counted_without_guessing_network_names(self):
        roots = [device(children=[network('en18')]), device(identity=2, children=[network('en19')])]
        with patch.object(m.subprocess, 'run', side_effect=[plist(roots), plist(roots),
                                                         link('en18', '', False), link('en19')]):
            state = m.read_state()
        self.assertEqual(state['usb_count'], 2)
        self.assertEqual([item['name'] for item in state['network_interfaces']], ['en18', 'en19'])


if __name__ == '__main__':
    unittest.main()
