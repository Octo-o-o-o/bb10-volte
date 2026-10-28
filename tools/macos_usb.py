"""Read-only BlackBerry USB/network facts from the macOS IOService ancestry.

Never guess an enX name or return USB serial numbers, MACs or raw registry data.
An active USB interface is distinct from an authenticated phone connection.
"""
import ipaddress
import plistlib
import re
import subprocess

VENDOR = 0x0FCA
CHILDREN = 'IORegistryEntryChildren'


def entries(data):
    value = plistlib.loads(data)
    if not isinstance(value, list) or any(not isinstance(node, dict) for node in value):
        raise ValueError('Invalid IORegistry roots')
    return value


def children(node):
    value = node.get(CHILDREN, [])
    if not isinstance(value, list) or any(not isinstance(child, dict) for child in value):
        raise ValueError('Invalid IORegistry children')
    return value


def device_roots(nodes):
    return [node for node in nodes
            if node.get('IOObjectClass') == 'IOUSBHostDevice' and node.get('idVendor') == VENDOR]


def interfaces(device):
    found = {}
    def walk(node, driver=''):
        # A nested USB device owns its own descendants, even under a USB hub.
        if node is not device and node.get('IOObjectClass') == 'IOUSBHostDevice':
            return
        bundle = node.get('CFBundleIdentifier')
        if isinstance(bundle, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', bundle):
            driver = bundle
        name = node.get('BSD Name')
        if node.get('IOObjectClass') == 'IOEthernetInterface' and isinstance(name, str) and re.fullmatch(r'en[0-9]+', name):
            found[name] = {'name': name, 'driver': driver or None}
        for child in children(node):
            walk(child, driver)
    walk(device)
    return list(found.values())


def interface_state(name, output):
    if not re.match(re.escape(name) + r':\s+flags=', output):
        raise ValueError('Unexpected interface response')
    match = re.search(r'^\s*status:\s*(active|inactive)\s*$', output, re.M)
    if not match:
        raise ValueError('Interface link status unavailable')
    addresses = []
    for address in re.findall(r'^\s*inet\s+(\S+)\s+', output, re.M):
        addresses.append(str(ipaddress.IPv4Address(address)))
    return {'active': match.group(1) == 'active', 'ipv4': addresses}


def read_state():
    result = {'usb_present': None, 'usb_count': None, 'usb_network': None,
              'driver_ready': None, 'usb_address_ready': None, 'network_interfaces': []}
    try:
        # Depth 1 lists each USB device exactly once, without unrelated subtrees.
        raw = subprocess.run(['/usr/sbin/ioreg', '-a', '-l', '-r', '-c', 'IOUSBHostDevice', '-d', '1'],
                             capture_output=True, timeout=12, check=True)
        devices = device_roots(entries(raw.stdout))
        result.update(usb_present=bool(devices), usb_count=len(devices))
        if not devices:
            result.update(driver_ready=False, usb_network=False, usb_address_ready=False)
            return result
        linked = {}
        # Query only already identified devices; match entry IDs again because
        # names can be duplicated. No registry identifiers leave this function.
        for name in dict.fromkeys(device.get('IORegistryEntryName') for device in devices):
            if not isinstance(name, str) or not name or len(name) > 200 or '\x00' in name:
                raise ValueError('USB registry name unavailable')
            raw = subprocess.run(['/usr/sbin/ioreg', '-a', '-l', '-r', '-n', name, '-d', '12'],
                                 capture_output=True, timeout=12, check=True)
            roots = device_roots(entries(raw.stdout))
            expected = {device.get('IORegistryEntryID') for device in devices if device.get('IORegistryEntryName') == name}
            if None in expected:
                raise ValueError('USB registry identity unavailable')
            matched = [device for device in roots if device.get('IORegistryEntryID') in expected]
            if {device.get('IORegistryEntryID') for device in matched} != expected:
                raise ValueError('USB device changed during detection')
            for device in matched:
                for interface in interfaces(device):
                    linked[interface['name']] = interface
        result['driver_ready'] = bool(linked)
        if not linked:
            result.update(usb_network=False, usb_address_ready=False)
            return result
        for name, interface in sorted(linked.items()):
            raw = subprocess.run(['/sbin/ifconfig', name], capture_output=True,
                                 text=True, timeout=5, check=True)
            interface.update(interface_state(name, raw.stdout))
            result['network_interfaces'].append(interface)
        result['usb_network'] = any(interface['active'] for interface in result['network_interfaces'])
        result['usb_address_ready'] = any(interface['active'] and '169.254.0.2' in interface['ipv4']
                                          for interface in result['network_interfaces'])
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException, subprocess.SubprocessError):
        # Successful earlier facts remain valid, but unavailable later layers
        # stay unknown. Do not label a missing tool or parse failure as no USB.
        pass
    return result
