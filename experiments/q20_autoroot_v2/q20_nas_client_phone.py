"""Q20-only NAS GETs and two explicitly temporary selection preferences.

Wire layouts: pinned libqmi 1.34.0 qmi-service-nas.json. SET 0x33 uses
duration TLV 0x17=0 (until power cycle), never permanent duration 1.
"""
import ctypes as C
import struct
import time
from q20_nas_snapshot_phone import unpack_tlvs, decode


def decode_scan(values):
    result = {'tlv_types': sorted(values), 'networks': [], 'radio_access': []}
    assert len(values[2]) == 4
    result['result'], result['error'] = struct.unpack('<HH', values[2])
    if result['result']:
        return result
    wire = values.get(0x10, b'')
    if wire:
        assert len(wire) >= 2
        count, offset = struct.unpack_from('<H', wire)[0], 2
        assert count <= 256
        for unused in range(count):
            assert offset + 6 <= len(wire)
            mcc, mnc, status, size = struct.unpack_from('<HHBB', wire, offset)
            offset += 6
            assert offset + size <= len(wire)
            offset += size  # Carrier description is not needed for this test.
            result['networks'].append({'mcc': mcc, 'mnc': mnc, 'status': status,
                'home': bool(status & 4), 'forbidden': bool(status & 16),
                'current': bool(status & 1), 'available': bool(status & 2)})
        assert offset == len(wire)
    wire = values.get(0x11, b'')
    if wire:
        assert len(wire) >= 2
        count = struct.unpack_from('<H', wire)[0]
        assert count <= 256 and len(wire) == 2 + count * 5
        for offset in range(2, len(wire), 5):
            mcc, mnc, rat = struct.unpack_from('<HHb', wire, offset)
            result['radio_access'].append({'mcc': mcc, 'mnc': mnc, 'rat': rat})
    if 0x13 in values:
        assert len(values[0x13]) == 4
        result['scan_result'] = struct.unpack('<I', values[0x13])[0]
    return result


class NasClient:
    def __enter__(self):
        self.handle = C.c_uint32(0)
        self.libs = [C.CDLL(name, mode=C.RTLD_GLOBAL) for name in
                     ('stp-handler-dc-qct.so', 'libqmi_common.so', 'libqmi_nas.so', 'libqcci_ext.so')]
        getter = self.libs[2].nas_get_service_object_internal_v01
        getter.argtypes, getter.restype = [C.c_int] * 3, C.c_void_p
        service = getter(1, 107, 6)
        assert service and C.cast(service, C.POINTER(C.c_uint32 * 4)).contents[2] == 3
        qcci = self.libs[3]
        listing = qcci.qmi_client_get_service_list
        listing.argtypes = [C.c_void_p, C.c_void_p, C.POINTER(C.c_uint32), C.POINTER(C.c_uint32)]
        listing.restype = C.c_int
        init = qcci.qmi_client_init
        init.argtypes, init.restype = [C.c_void_p] * 5 + [C.POINTER(C.c_uint32)], C.c_int
        self.release = qcci.qmi_client_release
        self.release.argtypes, self.release.restype = [C.c_uint32], C.c_int
        self.send = qcci.qmi_client_send_raw_msg_sync
        self.send.argtypes = [C.c_uint32, C.c_uint32, C.c_void_p, C.c_uint32,
                             C.c_void_p, C.c_uint32, C.POINTER(C.c_uint32), C.c_uint32]
        self.send.restype = C.c_int
        info = C.create_string_buffer(256)
        entries, total = C.c_uint32(1), C.c_uint32(1)
        assert listing(service, info, C.byref(entries), C.byref(total)) == 0 and entries.value == 1
        assert init(info, service, None, None, None, C.byref(self.handle)) == 0 and self.handle.value
        return self

    def request(self, message, payload=None):
        assert message in (0x24, 0x34, 0x4d) and payload is None or message == 0x33 and payload in (
            bytes.fromhex('110200100017010000'), bytes.fromhex('1102001c0017010000'),
            bytes.fromhex('2104000100000017010000'), bytes.fromhex('2104000200000017010000'),
            bytes.fromhex('1804000100000017010000'), bytes.fromhex('1804000200000017010000')) or (
            message == 0x21 and payload == b'\x10\x01\x00\x04') or (message == 0x22 and payload in (
            bytes.fromhex('01010002100500cc010b00081101000012010000'),
            bytes.fromhex('0101000111010000')))
        request = C.create_string_buffer(payload, len(payload)) if payload else None
        buffer, length = C.create_string_buffer(16384), C.c_uint32(0)
        rc = self.send(self.handle.value, message, request, len(payload) if payload else 0,
                       buffer, len(buffer), C.byref(length),
                       90000 if message == 0x21 else 15000 if message == 0x22 else 5000)
        assert rc == 0 and length.value <= len(buffer), 'NAS transport failed'
        values = unpack_tlvs(buffer.raw[:length.value])
        result = decode_scan(values) if message == 0x21 else decode(message, values)
        assert result.get('result') == 0, 'NAS request rejected: ' + str(result.get('error'))
        return result

    def set_preference(self, field, value):
        assert (field == 'mode_preference_mask' and value in (16, 28) or
                field in ('usage_preference', 'service_domain_preference') and value in (1, 2))
        if field == 'mode_preference_mask':
            prefix = b'\x11\x02\x00' + struct.pack('<H', value)
        else:
            prefix = (b'\x21' if field == 'usage_preference' else b'\x18') + b'\x04\x00' + struct.pack('<I', value)
        payload = prefix + b'\x17\x01\x00\x00'
        result = self.request(0x33, payload)
        for unused in range(12):
            observed = self.request(0x34)
            if observed[field] == value:
                result.update(field=field, value=value, readback_verified=True, duration='until_power_cycle')
                return result
            time.sleep(0.5)
        raise RuntimeError('Temporary NAS selection acknowledged; readback pending')

    def __exit__(self, kind, value, traceback):
        if self.handle.value:
            self.release(self.handle.value)
