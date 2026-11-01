"""Verified local entry point. Keep compatible with the phone's Python 3.2.

Only this file is started by the native bridge. Its hash is compiled into the
native executable. Product modules are imported only from a verified root-owned
snapshot. The release builder substitutes RELEASE_KEY; no private key is bundled.
"""
import sys
if sys.platform.startswith('qnx'):
    sys.path[:] = ['/usr/lib/python32.zip', '/usr/lib/python3.2',
                   '/usr/lib/python3.2/lib-dynload']
import base64
import binascii
import hashlib
import io
import json
import os
import re
import stat
import struct
import subprocess
import zipfile

RELEASE_KEY = None  # substituted by tools/package_mobile.py
ROOT = '/var/bb10_volte-mobile'
MAX_TOTAL = 32 * 1024 * 1024
MAX_FILE = 16 * 1024 * 1024
MAX_MEMBERS = 160
ALGORITHM = 'RSASSA-PKCS1-v1_5-SHA256'
SAFE_NAME = re.compile(r'\A(?:runtime|payload|profiles|materials)/[a-zA-Z0-9_.\-/]+\Z')
ACTIONS = ('inspect', 'status', 'poll', 'resume', 'install', 'enable', 'disable',
           'update', 'rollback', 'uninstall', 'export', 'compatibility',
           'confirm-calls', 'legacy-inspect', 'legacy-install', 'legacy-start',
           'legacy-stop')


class MobileError(Exception):
    pass


def require(value, code):
    if not value:
        raise MobileError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True).encode('ascii')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def decode64(value):
    require(isinstance(value, str) and len(value) <= 16384 and
            len(value) % 4 == 0 and re.match(r'\A[A-Za-z0-9+/]*={0,2}\Z', value),
            'invalid_encoding')
    try:
        result = base64.b64decode(value.encode('ascii'))
    except (ValueError, binascii.Error):
        raise MobileError('invalid_encoding')
    require(base64.b64encode(result).decode('ascii') == value, 'invalid_encoding')
    return result


def json_bytes(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=pairs)
    except (ValueError, UnicodeError):
        raise MobileError('invalid_json')


def verify_signature(data, envelope, key=None):
    key = RELEASE_KEY if key is None else key
    require(isinstance(key, dict) and key.get('e') == 65537, 'release_key_missing')
    require(isinstance(envelope, dict) and set(envelope) == {'algorithm', 'key_id', 'signature'},
            'invalid_signature')
    require(envelope['algorithm'] == ALGORITHM and envelope['key_id'] == key.get('key_id'),
            'untrusted_publisher')
    try:
        modulus = int(key['n'], 16)
        require(2048 <= modulus.bit_length() <= 4096, 'invalid_key')
        size = (modulus.bit_length() + 7) // 8
        signature = decode64(envelope['signature'])
        require(len(signature) == size, 'invalid_signature')
        number = int(binascii.hexlify(signature), 16)
        require(number < modulus, 'invalid_signature')
        decoded = pow(number, key['e'], modulus).to_bytes(size, 'big')
        der = binascii.unhexlify(b'3031300d060960864801650304020105000420')
        tail = der + hashlib.sha256(data).digest()
        expected = b'\x00\x01' + b'\xff' * (size - len(tail) - 3) + b'\x00' + tail
        require(decoded == expected, 'invalid_signature')
    except (KeyError, TypeError, ValueError, OverflowError):
        raise MobileError('invalid_signature')


def valid_name(name):
    return (isinstance(name, str) and len(name) <= 180 and SAFE_NAME.match(name)
            and all(part not in ('', '.', '..') for part in name.split('/')))


def validate_manifest(raw, signature, key=None):
    require(len(raw) <= 131072 and len(signature) <= 4096, 'manifest_too_large')
    verify_signature(raw, json_bytes(signature), key)
    manifest = json_bytes(raw)
    require(isinstance(manifest, dict) and manifest.get('schema') == 2 and
            manifest.get('kind') == 'bb10-volte-mobile' and manifest.get('protocol') == 2,
            'package_protocol_unsupported')
    require(isinstance(manifest.get('version'), str) and
            re.match(r'\A[0-9][0-9a-zA-Z.\-]{0,39}\Z', manifest['version']), 'invalid_version')
    files = manifest.get('files')
    require(isinstance(files, dict) and 3 <= len(files) <= MAX_MEMBERS, 'invalid_file_set')
    total = 0
    for name, item in files.items():
        require(valid_name(name) and isinstance(item, dict) and set(item) == {'sha256', 'size'},
                'invalid_member')
        require(isinstance(item['sha256'], str) and
                re.match(r'\A[0-9a-f]{64}\Z', item['sha256']), 'invalid_hash')
        require(type(item['size']) is int and 0 <= item['size'] <= MAX_FILE, 'invalid_member_size')
        total += item['size']
    require(total <= MAX_TOTAL, 'package_too_large')
    require({'runtime/entry.py', 'runtime/worker.py', 'payload/payload.json'} <= set(files),
            'incomplete_package')
    return manifest


def regular(path, maximum=MAX_FILE):
    info = os.lstat(path)
    require(stat.S_ISREG(info.st_mode) and info.st_size <= maximum, 'unsafe_file')
    with open(path, 'rb') as source:
        opened = os.fstat(source.fileno())
        require((info.st_dev, info.st_ino) == (opened.st_dev, opened.st_ino), 'file_changed')
        data = source.read(maximum + 1)
    require(len(data) <= maximum, 'file_too_large')
    return data


def read_bundle(folder, key=None):
    require(os.path.realpath(folder) == folder and os.path.isdir(folder), 'unsafe_bundle_path')
    raw = regular(folder + '/manifest.json', 131072)
    signature = regular(folder + '/manifest.sig.json', 4096)
    manifest = validate_manifest(raw, signature, key)
    blobs = {}
    for name, item in manifest['files'].items():
        path = folder + '/' + name
        require(os.path.realpath(path) == path, 'unsafe_member_path')
        blob = regular(path)
        require(len(blob) == item['size'] and digest(blob) == item['sha256'], 'package_changed')
        blobs[name] = blob
    return manifest, raw, signature, blobs


def read_archive(path, key=None):
    require(os.path.realpath(path) == path, 'unsafe_package_path')
    # Parse one bounded immutable byte string, never a changing shared file.
    data = regular(path, MAX_TOTAL)
    require(data, 'package_too_large')
    bounded_directory(data)
    with io.BytesIO(data) as stream:
        with zipfile.ZipFile(stream) as archive:
            members = archive.infolist()
            require(len(members) <= MAX_MEMBERS + 2, 'too_many_members')
            names = [item.filename for item in members]
            require(len(set(names)) == len(names), 'duplicate_member')
            require('manifest.json' in names and 'manifest.sig.json' in names, 'incomplete_package')
            for item in members:
                require(item.filename in ('manifest.json', 'manifest.sig.json') or valid_name(item.filename),
                        'invalid_member')
                mode = item.external_attr >> 16
                require(not stat.S_ISLNK(mode) and (stat.S_IFMT(mode) in (0, stat.S_IFREG)), 'unsafe_member')
                limit = 131072 if item.filename == 'manifest.json' else 4096 if item.filename == 'manifest.sig.json' else MAX_FILE
                require(0 <= item.file_size <= limit and item.flag_bits & 1 == 0, 'invalid_member_size')
                require(item.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'unsupported_compression')
            require(sum(item.file_size for item in members) <= MAX_TOTAL + 135168, 'package_too_large')
            raw = bounded_member(archive, 'manifest.json', 131072)
            signature = bounded_member(archive, 'manifest.sig.json', 4096)
            manifest = validate_manifest(raw, signature, key)
            require(set(names) == set(manifest['files']) | {'manifest.json', 'manifest.sig.json'}, 'unexpected_member')
            blobs = {}
            for name, item in manifest['files'].items():
                require(archive.getinfo(name).file_size == item['size'], 'package_changed')
                blob = bounded_member(archive, name, item['size'])
                require(len(blob) == item['size'] and digest(blob) == item['sha256'], 'package_changed')
                blobs[name] = blob
    return manifest, raw, signature, blobs


def bounded_member(archive, name, limit):
    # Python 3.2 ZipExtFile.read() does NOT enforce ZipInfo.file_size. Always
    # bound actual decompression before parsing even the unsigned manifest.
    with archive.open(name, 'r') as source:
        data = source.read(limit + 1)
    require(len(data) <= limit, 'expanded_member_too_large')
    require(len(data) == archive.getinfo(name).file_size, 'member_size_changed')
    return data


def bounded_directory(data):
    # Bound parser allocations BEFORE ZipFile constructs its ZipInfo list.
    # Our <=32 MiB release bundles need neither multi-disk nor ZIP64 records.
    end = data.rfind(b'PK\x05\x06', max(0, len(data) - 65557))
    require(end >= 0 and end + 22 <= len(data), 'invalid_zip_directory')
    disk, start_disk, disk_entries, entries, size, offset, comment = struct.unpack('<4H2IH', data[end + 4:end + 22])
    require(disk == start_disk == 0 and disk_entries == entries and entries <= MAX_MEMBERS + 2,
            'too_many_members')
    require(size <= 131072 and offset + size <= end and end + 22 + comment == len(data), 'invalid_zip_directory')
    require(end < 20 or data[end - 20:end - 16] != b'PK\x06\x07', 'zip64_not_supported')


def private_directory(path):
    if not os.path.lexists(path):
        os.mkdir(path, 0o700)
    info = os.lstat(path)
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid() and
            info.st_mode & 0o077 == 0 and os.path.realpath(path) == path, 'unsafe_private_directory')


def write_new(path, blob, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, 'wb') as output:
        output.write(blob)
        output.flush()
        os.fsync(output.fileno())


def snapshot(bundle):
    manifest, raw, signature, blobs = bundle
    private_directory(ROOT)
    private_directory(ROOT + '/snapshots')
    folder = ROOT + '/snapshots/' + digest(raw)
    if os.path.lexists(folder):
        private_directory(folder)
        read_bundle(folder)
        return folder
    temporary = folder + '.stage-' + binascii.hexlify(os.urandom(6)).decode('ascii')
    private_directory(temporary)
    for name, blob in sorted(blobs.items()):
        parent = temporary
        for part in name.split('/')[:-1]:
            parent += '/' + part
            private_directory(parent)
        write_new(temporary + '/' + name, blob)
    write_new(temporary + '/manifest.json', raw)
    write_new(temporary + '/manifest.sig.json', signature)
    read_bundle(temporary)
    try:
        os.rename(temporary, folder)
    except OSError:
        if not os.path.isdir(folder):
            raise
        read_bundle(folder)
        # A concurrent successful copy is usable; the uniquely owned staging
        # directory is retained for diagnosis rather than recursively deleted.
    return folder


def trusted_python(folder):
    bundle = read_bundle(folder)
    with open(os.devnull, 'wb') as sink:
        for name in sorted(bundle[0]['files']):
            if name == 'runtime/job-launcher':
                os.chmod(folder + '/' + name, 0o700)
            if name.endswith('.py') or name.endswith('.sh') or name == 'runtime/job-launcher':
                require(subprocess.call(['/proc/boot/pathtrust', '!' + folder + '/' + name],
                                        stdout=sink, stderr=sink) == 0, 'pathtrust_failed')


def active_bundle(fallback):
    pointer = ROOT + '/active.json'
    if not os.path.lexists(pointer):
        return fallback
    value = json_bytes(regular(pointer, 4096))
    require(isinstance(value, dict) and set(value) in ({'manifest_sha256'}, {'manifest_sha256', 'for_bundle'}) and
            re.match(r'\A[a-f0-9]{64}\Z', value['manifest_sha256']), 'active_bundle_changed')
    if 'for_bundle' in value:
        require(isinstance(value['for_bundle'], str) and re.match(r'\A[a-f0-9]{64}\Z', value['for_bundle']), 'active_bundle_changed')
    folder = ROOT + '/snapshots/' + value['manifest_sha256']
    private_directory(folder)
    bundle = read_bundle(folder)
    require(digest(bundle[1]) == value['manifest_sha256'], 'active_bundle_changed')
    fallback_bundle = read_bundle(fallback)
    fallback_version = fallback_bundle[0]['version']
    if (numeric_version(fallback_version) > numeric_version(bundle[0]['version']) and
            value.get('for_bundle') != digest(fallback_bundle[1])):
        return fallback
    return folder


def numeric_version(value):
    require(isinstance(value, str) and re.match(r'\A[0-9]{1,5}(?:\.[0-9]{1,5}){3}\Z', value), 'invalid_version')
    return tuple(int(part) for part in value.split('.'))


def cleanup_entry():
    """Remove only this exact private bridge copy; BB10 has no rmdir utility."""
    path = os.path.abspath(__file__)
    folder = os.path.dirname(path)
    require(os.geteuid() == 0 and os.path.basename(path) == 'entry.py' and
            re.match(r'\A/var/bb10_mobile_entry_[a-f0-9]{32}\Z', folder), 'unsafe_entry_cleanup')
    require(os.path.realpath(path) == path, 'unsafe_entry_cleanup')
    private_directory(folder)
    info = os.lstat(path)
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and
            info.st_mode & 0o077 == 0 and info.st_nlink == 1 and
            os.listdir(folder) == ['entry.py'], 'unsafe_entry_cleanup')
    os.unlink(path)
    os.rmdir(folder)


def main():
    require(sys.flags.optimize == 0, 'optimized_python_not_supported')
    require(os.geteuid() == 0 and os.uname()[0] == 'QNX', 'root_required')
    require(len(sys.argv) in (2, 3, 4) and sys.argv[1] in ACTIONS, 'invalid_action')
    request = json_bytes(decode64(sys.argv[2])) if len(sys.argv) >= 3 else {'schema': 2}
    require(isinstance(request, dict) and request.get('schema') == 2, 'invalid_request')
    require(set(request) <= {'schema', 'language', 'backup_location', 'package_path', 'job_id',
            'operation_id', 'experimental', 'profile_id', 'confirmed', 'incoming', 'outgoing',
            'audio', 'lte', 'call_context', 'export_kind'}, 'invalid_request_field')
    # The native bridge runs a root-private copy of the already hash-pinned
    # entry bytes. The source bundle is data until signature verification.
    folder = (os.path.realpath(sys.argv[3]) if len(sys.argv) == 4 else
              os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    fallback = snapshot(read_bundle(folder))
    global FALLBACK_MANIFEST_SHA
    FALLBACK_MANIFEST_SHA = os.path.basename(fallback)
    verified = active_bundle(fallback)
    trusted_python(verified)
    sys.path.insert(0, verified + '/payload/device')
    sys.path.insert(0, verified + '/runtime')
    sys.modules['entry'] = sys.modules[__name__]
    import worker
    result = worker.dispatch(sys.argv[1], request, verified)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))


if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['--cleanup']:
            cleanup_entry()
        else:
            main()
    except Exception as error:
        code = str(error) if isinstance(error, MobileError) else 'local_operation_failed'
        print(json.dumps({'schema': 2, 'ok': False, 'state': 'error', 'error': {'code': code}}))
        sys.exit(1)
