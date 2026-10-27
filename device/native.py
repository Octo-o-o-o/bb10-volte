"""Verified BB10 native primitives. Python 3.2; no operations on import."""
import ctypes as C
import errno
import hashlib
import json
import os
import re
import select
import struct
import subprocess
import tempfile
import time

STOCK_HASHES = {
    '/radio/bin/ims_rrm': '043d38b0f08cf6a9696ef405f3976679e32ff9ad943ec35294c3d3da69a12b67',
    '/sbin/io-pkt-v6-hc': '17d2bb5b641b3acd1ffac2e98fbd86c881633263598db983db4819702df3d222',
    '/radio/lib/libradiocontrol.so.0.1': '0d0acc34656c16300db8a1b3341174d3749b8d50fe6081350805e05998d3ee8a',
    '/etc/carrier/config/36.xml': '929e5e6e92ecadd48c641ec77f93f34e4a8d494ce213ab71d6422d6f5bba3fe4',
}
HELPER_HASH = '504a6f5bdfb55f03aaf64b1a73f423e1a802e4786433f2621cd701c993224254'
UUID = r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}'
VPN_CONFIGS = ('/etc/vpn_pps.conf', '/etc/vpn_pps_system.conf')


def read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        return os.read(fd, 16777216)
    finally:
        os.close(fd)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data, mode=0o600):
    assert not os.path.islink(path) and not os.path.islink(path + '.new')
    fd = os.open(path + '.new', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(path + '.new', mode)
    os.rename(path + '.new', path)


def attrs(data):
    if isinstance(data, bytes):
        data = data.decode('utf-8', 'replace')
    result = {}
    for line in data.splitlines():
        line = re.sub(r'^\[[^]]*\]', '', line)
        if not line.startswith('@') and ':' in line:
            key, value = line.split(':', 1)
            result[key] = value
    return result


def value(mapping, key, default=None):
    raw = mapping.get(key)
    if raw is None:
        return default
    kind, val = raw.split(':', 1)
    return json.loads(val) if kind in ('json', 'n', 'b') else val


def update_pps(path, updates):
    blob = ''.join('-' + k + '\n' if v is None else '[n]' + k + ':' + v + '\n'
                   for k, v in sorted(updates.items())).encode('utf-8')
    fd = os.open(path, os.O_WRONLY)
    try:
        assert os.write(fd, blob) == len(blob)
    finally:
        os.close(fd)


def command(argv, timeout=15):
    # QNX pipes are small. Waiting before communicate() can block pidin on a full
    # stdout pipe. Anonymous private files permit bounded waits without that cycle.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        child = subprocess.Popen(argv, stdout=out, stderr=err)
        deadline = time.time() + timeout
        while child.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        if child.poll() is None:
            child.kill()
            child.wait()
            raise RuntimeError('Command timed out; inspect state before retry: ' + argv[0])
        assert child.returncode == 0, 'Native command failed: ' + argv[0] + ' rc=' + str(child.returncode)
        assert out.tell() <= 16777216, 'Native output exceeds the diagnostic bound'
        out.seek(0)
        return out.read()


def ims_pids():
    text = command(['/bin/pidin', '-p', 'ims_rrm', '-f', 'a']).decode('ascii')
    return sorted(set(int(x) for x in re.findall(r'^\s*(\d+)\s*$', text, re.M)))


def verify_stock():
    assert os.geteuid() == 0 and C.sizeof(C.c_void_p) == 4, 'Root QNX ARM32 required'
    assert os.path.exists('/tmp/root.done'), 'AutoRoot is not ready'
    for path, expected in STOCK_HASHES.items():
        assert digest(read(path)) == expected, 'Unsupported native build: ' + path


def voice_policy():
    """Read only the one-byte voice_domain_pref using native RIM QMI32/3."""
    path = b'/nv/item_files/modem/mmode/voice_domain_pref'
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


def crypto_policy():
    text = command(['/bin/pidin', '-p', 'io-pkt-v6-hc', 'mem']).decode('ascii', 'replace')
    pids = set(re.findall(r'^\s*(\d+)\s+\d+\s+/sbin/io-pkt-v6-hc\s', text, re.M))
    assert len(pids) == 1
    match = re.search(r'^\s+io-pkt-v6-hc\s+@\s*([0-9a-fA-F]+)', text, re.M)
    assert match
    base = int(match.group(1), 16)
    fd = os.open('/proc/' + pids.pop() + '/as', os.O_RDONLY)
    try:
        os.lseek(fd, base, os.SEEK_SET)
        assert os.read(fd, 4) == b'\x7fELF'
        result = {}
        for name, offset in [('swcr_id', 0xe12e0), ('crypto_support', 0xe9ea0)]:
            os.lseek(fd, base + offset, os.SEEK_SET)
            result[name] = struct.unpack('<i', os.read(fd, 4))[0]
        return result
    finally:
        os.close(fd)


def active_vpn_sessions():
    active = []
    for i in range(1, 11):
        item = attrs(read('/pps/services/vpn/session' + str(i)))
        if value(item, 'status') not in ('Not connected', 'Timeout'):
            active.append(i)
    return active


def vpn_configs():
    return {p: read(p) for p in VPN_CONFIGS}


def vpn_ids(configs):
    return set().union(*(set(re.findall(UUID.encode('ascii'), data)) for data in configs.values()))


def vpn_delete(uid):
    assert re.match('^' + UUID + '$', uid)
    identifier = 'q10-volte-delete-' + str(os.getpid()) + '-' + str(int(time.time()*1000))
    request = ('msg::vpn_delete\nid::' + identifier + '\ndat:json:' + json.dumps({'uid': uid}) + '\n').encode('ascii')
    fd = os.open('/pps/services/vpn/control?wait', os.O_RDWR | os.O_NONBLOCK)
    try:
        assert os.write(fd, request) == len(request)
        deadline = time.time() + 8
        while time.time() < deadline:
            ready, _, _ = select.select([fd], [], [], max(0, deadline-time.time()))
            if not ready:
                break
            try:
                reply = os.read(fd, 262144).decode('utf-8', 'replace')
            except OSError as error:
                if error.errno == errno.EAGAIN:
                    continue
                raise
            if 'id::' + identifier in reply and ('res::' in reply or 'err:' in reply):
                assert 'res::vpn_delete' in reply and 'err:' not in reply, 'Native VPN delete rejected'
                return
        raise RuntimeError('Native VPN delete timed out; recheck current state')
    finally:
        os.close(fd)
