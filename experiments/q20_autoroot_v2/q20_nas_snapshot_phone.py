"""Read three QMI NAS GET messages on the verified Q20; Python 3.2.

ABI: NAS v1.107.6, service 3. Field layouts follow the locally pinned libqmi
1.34.0 qmi-service-nas.json. Raw modem replies remain in a private diagnostic.
"""
import ctypes as C
import json
import os
import struct
import time
import native as n


def unpack_tlvs(wire):
    result = {}
    offset = 0
    while offset < len(wire):
        assert len(wire) - offset >= 3
        kind, size = struct.unpack_from('<BH', wire, offset)
        offset += 3
        assert size <= len(wire) - offset and kind not in result
        result[kind] = wire[offset:offset + size]
        offset += size
    return result


def number(values, key, fmt):
    value = values.get(key)
    return struct.unpack(fmt, value)[0] if value is not None and len(value) == struct.calcsize(fmt) else None


def decode(message, values):
    result = {'result': None, 'error': None, 'tlv_types': sorted(values)}
    if 2 in values and len(values[2]) == 4:
        result['result'], result['error'] = struct.unpack('<HH', values[2])
    if result['result'] != 0:
        return result
    if message == 0x33:
        return result
    if message == 0x24:
        value = values.get(1, b'')
        if len(value) >= 5 and len(value) == 5 + value[4]:
            result.update(registration_state=value[0], cs_attach_state=value[1],
                          ps_attach_state=value[2], selected_network=value[3],
                          radio_interfaces=list(value[5:]))
    elif message == 0x34:
        for key, name, fmt in ((0x11, 'mode_preference_mask', '<H'),
                               (0x15, 'lte_band_preference_mask', '<Q'),
                               (0x16, 'network_selection_preference', '<B'),
                               (0x18, 'service_domain_preference', '<I'),
                               (0x1d, 'network_registration_restriction', '<I'),
                               (0x1f, 'usage_preference', '<I'),
                               (0x22, 'disabled_rat_modes', '<H'),
                               (0x20, 'voice_domain_preference', '<I')):
            result[name] = number(values, key, fmt)
    else:
        value = values.get(0x14, b'')
        if len(value) == 3:
            result['lte_service'] = {'status': value[0], 'true_status': value[1],
                                     'preferred_data_path': bool(value[2])}
        value = values.get(0x19, b'')
        if len(value) >= 29:
            result['lte_system'] = {
                'domain': value[1] if value[0] == 1 else None,
                'service_capability': value[3] if value[2] == 1 else None,
                'roaming': value[5] if value[4] == 1 else None,
                'forbidden': bool(value[7]) if value[6] == 1 else None,
                'reject_valid': bool(value[16]),
                'reject_domain': value[17] if value[16] == 1 else None,
                'reject_cause': value[18] if value[16] == 1 else None,
                'mcc': value[20:23].decode('ascii', 'replace') if value[19] == 1 else None,
                'mnc': value[23:26].replace(b'\xff', b'').decode('ascii', 'replace') if value[19] == 1 else None,
            }
        for key, name, fmt in ((0x21, 'lte_voice_support', '<B'),
                               (0x29, 'ims_voice_support', '<B'),
                               (0x2a, 'lte_voice_domain', '<I'),
                               (0x31, 'lte_registration_domain', '<I')):
            result[name] = number(values, key, fmt)
    return result


def main():
    assert os.geteuid() == 0 and C.sizeof(C.c_void_p) == 4
    assert n.read('/etc/os.version').decode('ascii').strip() == '10.3.3.3216'
    props = n.attrs(n.read('/pps/services/deviceproperties'))
    assert n.value(props, 'modelnumber') == 'SQC100-2'
    for path, expected in n.STOCK_HASHES.items():
        assert n.digest(n.read(path)) == expected
    report = {'captured_unix': time.time(), 'modem_set_requests': 0,
              'pps_configuration_writes': 0, 'messages': {}}
    raw = {}
    handle = C.c_uint32(0)
    release = None
    try:
        libs = [C.CDLL(name, mode=C.RTLD_GLOBAL) for name in
                ('stp-handler-dc-qct.so', 'libqmi_common.so', 'libqmi_nas.so', 'libqcci_ext.so')]
        getter = libs[2].nas_get_service_object_internal_v01
        getter.argtypes, getter.restype = [C.c_int] * 3, C.c_void_p
        service = getter(1, 107, 6)
        assert service and C.cast(service, C.POINTER(C.c_uint32 * 4)).contents[2] == 3
        qcci = libs[3]
        get_list = qcci.qmi_client_get_service_list
        get_list.argtypes = [C.c_void_p, C.c_void_p, C.POINTER(C.c_uint32), C.POINTER(C.c_uint32)]
        get_list.restype = C.c_int
        init = qcci.qmi_client_init
        init.argtypes, init.restype = [C.c_void_p] * 5 + [C.POINTER(C.c_uint32)], C.c_int
        release = qcci.qmi_client_release
        release.argtypes, release.restype = [C.c_uint32], C.c_int
        send = qcci.qmi_client_send_raw_msg_sync
        send.argtypes = [C.c_uint32, C.c_uint32, C.c_void_p, C.c_uint32,
                         C.c_void_p, C.c_uint32, C.POINTER(C.c_uint32), C.c_uint32]
        send.restype = C.c_int
        info = C.create_string_buffer(256)
        entries, total = C.c_uint32(1), C.c_uint32(1)
        assert get_list(service, info, C.byref(entries), C.byref(total)) == 0 and entries.value == 1
        assert init(info, service, None, None, None, C.byref(handle)) == 0 and handle.value
        for message, label in ((0x24, 'serving_system'), (0x34, 'selection_preference'), (0x4d, 'system_info')):
            buffer, length = C.create_string_buffer(16384), C.c_uint32(0)
            rc = send(handle.value, message, None, 0, buffer, len(buffer), C.byref(length), 5000)
            assert length.value <= len(buffer)
            wire = buffer.raw[:length.value]
            raw[label] = ''.join('%02x' % value for value in wire)
            report['messages'][label] = dict(decode(message, unpack_tlvs(wire)) if rc == 0 else {}, transport_rc=rc)
    finally:
        if release is not None and handle.value:
            report['release_rc'] = release(handle.value)
    filename = 'nas-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '.json'
    fd = os.open('/var/q20_volte/state/' + filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump({'summary': report, 'private_wire_hex': raw}, stream, indent=2)
    report['private_report'] = filename
    print(json.dumps(report))


if __name__ == '__main__':
    main()
