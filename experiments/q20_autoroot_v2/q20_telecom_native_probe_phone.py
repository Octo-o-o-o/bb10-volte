"""Q20-only read-only native/EFS candidate preflight; no setter operations."""
import ctypes as C
import struct
import json
import q20_volte_phone as q

QCT_HASH = '71835f701affcb9254eadb4ee299e8f7d07547543b3e0f61519456b8241dcb3b'

def ue_usage_policy():
    """Read only the one-byte UE usage setting with the verified RIM QMI ABI."""
    path = b'/nv/item_files/modem/mmode/ue_usage_setting'
    libs = [C.CDLL(n, mode=C.RTLD_GLOBAL) for n in
            ('stp-handler-dc-qct.so', 'libqmi_rim_vs.so', 'libqcci_ext.so')]
    rim, qcci = libs[1:]
    get = rim.qmi_vs_rim_service_get_service_object_internal_v01
    get.argtypes, get.restype = [C.c_int, C.c_int, C.c_int], C.c_void_p
    listing = qcci.qmi_client_get_service_list
    listing.argtypes = [C.c_void_p, C.c_void_p, C.POINTER(C.c_uint32), C.POINTER(C.c_uint32)]
    listing.restype = C.c_int
    init = qcci.qmi_client_init
    init.argtypes, init.restype = [C.c_void_p] * 5 + [C.POINTER(C.c_uint32)], C.c_int
    release = qcci.qmi_client_release
    release.argtypes, release.restype = [C.c_uint32], C.c_int
    send = qcci.qmi_client_send_msg_sync
    send.argtypes = [C.c_uint32, C.c_int, C.c_void_p, C.c_int, C.c_void_p, C.c_int, C.c_int]
    send.restype = C.c_int
    handle = C.c_uint32()
    try:
        obj = get(1, 2, 5)
        assert obj
        info = C.create_string_buffer(256)
        entries, total = C.c_uint32(1), C.c_uint32(1)
        assert listing(obj, info, C.byref(entries), C.byref(total)) == 0 and entries.value == 1
        assert init(info, obj, None, None, None, C.byref(handle)) == 0 and handle.value

        def query(msg, blob, length):
            assert msg in (32, 3)
            req = C.create_string_buffer(blob, len(blob))
            resp = C.create_string_buffer(length)
            assert send(handle.value, msg, req, len(blob), resp, length, 5000) == 0
            return resp.raw

        status, size = struct.unpack('<II', query(32, struct.pack('<I128s', len(path), path), 8))
        assert status == 0 and size == 1, 'Unexpected voice policy size'
        blob = struct.pack('<I128sHBBBBBBHH', len(path), path, 1, 1, 240, 1, 0, 1, 0, 1, 0)
        response = query(3, blob, 2060)
        count = struct.unpack_from('<I', response, 0)[0]
        assert struct.unpack_from('<h', response, 2052)[0] == 0 and response[2054] == 0
        assert count == 1 or (count == 2048 and struct.unpack_from('<H', response, 2058)[0] == 1)
        return response[4]
    finally:
        if handle.value:
            release(handle.value)

def main():
    q.setup()
    q.verify()
    digest = q.n.digest(q.n.read('/radio/bin/qct_rrm'))
    assert digest == QCT_HASH, 'Q20 qct_rrm differs from the offline native mapping'
    print(json.dumps({'variant': 'SQC100-2', 'qct_rrm_sha256': digest,
        'voice_policy': q.n.voice_policy(), 'ue_usage_setting': ue_usage_policy(),
        'configuration_writes': 0}))


if __name__ == '__main__':
    main()
