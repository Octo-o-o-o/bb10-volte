"""Verified BB10 RadioControl API adapter; main is attach-only, no setter call.

Exact stock library and native ims_rrm call site establish the 20-byte by-value
EPS settings ABI. Mask2 encodes only TLV0x0c3d (voice preference). Native enums
1/4 map to original qct_rrm's EFS03/00, respectively. No arbitrary values.
"""
import ctypes as C
import hashlib
import json
import os

PATH = '/radio/lib/libradiocontrol.so.0.1'
DIGEST = '0d0acc34656c16300db8a1b3341174d3749b8d50fe6081350805e05998d3ee8a'

class Settings(C.Structure):
    _fields_ = [('mask', C.c_uint32), ('usage', C.c_uint32),
                ('voice_preference', C.c_uint32), ('mode', C.c_uint32),
                ('sms_over_ip', C.c_uint32)]

def attach():
    assert os.geteuid() == 0 and C.sizeof(C.c_void_p) == 4 and C.sizeof(Settings) == 20
    with open(PATH, 'rb') as f:
        assert hashlib.sha256(f.read()).hexdigest() == DIGEST
    lib = C.CDLL(PATH, mode=C.RTLD_GLOBAL)
    lib.RadioGetProviderList.argtypes = [C.POINTER(C.c_void_p)]
    lib.RadioGetProviderList.restype = C.c_int
    lib.RadioFreeProviderList.argtypes = [C.c_void_p]
    lib.RadioFreeProviderList.restype = C.c_int
    lib.RadioAttachProvider.argtypes = [C.c_void_p]
    lib.RadioAttachProvider.restype = C.c_int
    lib.RadioDetachProvider.argtypes = [C.c_int]
    lib.RadioDetachProvider.restype = C.c_int
    lib.RadioControlSetEpsOpModeSettings.argtypes = [C.c_int, Settings]
    lib.RadioControlSetEpsOpModeSettings.restype = C.c_int
    head = C.c_void_p()
    count = lib.RadioGetProviderList(C.byref(head))
    assert count == 1 and head.value, 'Unexpected native radio provider inventory'
    try:
        fd = lib.RadioAttachProvider(head)
    finally:
        lib.RadioFreeProviderList(head)
    assert fd >= 0, 'Native radio attach failed'
    return lib, fd, count

def set_voice_preference(native_value):
    assert native_value in (1, 4), 'Only tested IMS-preferred and original CS-only values allowed'
    lib, fd, count = attach()
    try:
        settings = Settings(2, 0, native_value, 0, 0)
        rc = lib.RadioControlSetEpsOpModeSettings(fd, settings)
        return {'api': 'RadioControlSetEpsOpModeSettings', 'mask': 2,
                'native_voice_preference': native_value, 'rc': rc}
    finally:
        lib.RadioDetachProvider(fd)

if __name__ == '__main__':
    lib, fd, count = attach()
    rc = lib.RadioDetachProvider(fd)
    print(json.dumps({'attach_succeeded': True, 'provider_count': count,
                      'detach_rc': rc, 'library_sha256': DIGEST,
                      'settings_bytes': C.sizeof(Settings), 'setter_calls': 0}))
