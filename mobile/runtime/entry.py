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
RELEASE_VERSION = None  # substituted by tools/package_mobile.py
RELEASE_CORE_SHA256 = None  # substituted by tools/package_mobile.py
ROOT = '/var/bb10_volte-mobile'
MAX_TOTAL = 32 * 1024 * 1024
MAX_FILE = 16 * 1024 * 1024
MAX_MEMBERS = 160
BRIDGE_PROGRESS = False
FOREGROUND_ACTIVE_POINTER = None
SAFE_JOB_GUARD = 'safe_job_outcome_v1'
SELECTION_GUARD = 'active_selection_guard_v1'
ALGORITHM = 'RSASSA-PKCS1-v1_5-SHA256'
SAFE_NAME = re.compile(r'\A(?:runtime|payload|profiles|materials)/[a-zA-Z0-9_.\-/]+\Z')
ACTIONS = ('inspect', 'status', 'poll', 'resume', 'install', 'enable', 'disable',
           'update', 'rollback', 'uninstall', 'export', 'compatibility',
           'confirm-calls', 'legacy-inspect', 'legacy-install', 'legacy-start',
           'legacy-stop', 'legacy-update', 'legacy-uninstall')


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


def bridge_progress():
    # Only the foreground bridge emits these markers; detached jobs retain
    # their existing output protocol and never expose file or device data.
    global BRIDGE_PROGRESS
    if BRIDGE_PROGRESS:
        try:
            sys.stdout.write('BB10_PROGRESS:1\n')
            sys.stdout.flush()
        except (IOError, OSError, ValueError):
            # Progress is observational. A closed UI pipe cannot cancel or
            # change a task that may already have entered a transaction.
            BRIDGE_PROGRESS = False


def supports_job_guard(manifest):
    capabilities = manifest.get('capabilities') if isinstance(manifest, dict) else None
    return isinstance(capabilities, list) and SAFE_JOB_GUARD in capabilities


def supports_selection_guard(manifest):
    capabilities = manifest.get('capabilities') if isinstance(manifest, dict) else None
    return isinstance(capabilities, list) and SELECTION_GUARD in capabilities


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


def read_bundle_manifest(folder, key=None):
    require(os.path.realpath(folder) == folder and os.path.isdir(folder), 'unsafe_bundle_path')
    raw = regular(folder + '/manifest.json', 131072)
    signature = regular(folder + '/manifest.sig.json', 4096)
    manifest = validate_manifest(raw, signature, key)
    return manifest, raw, signature


def read_bundle(folder, key=None):
    manifest, raw, signature = read_bundle_manifest(folder, key)
    blobs = {}
    for name, item in manifest['files'].items():
        path = folder + '/' + name
        require(os.path.realpath(path) == path, 'unsafe_member_path')
        blob = regular(path)
        require(len(blob) == item['size'] and digest(blob) == item['sha256'], 'package_changed')
        blobs[name] = blob
        bridge_progress()
    return manifest, raw, signature, blobs


def read_archive(path, key=None, expected_sha256=None):
    require(os.path.realpath(path) == path, 'unsafe_package_path')
    # Parse one bounded immutable byte string, never a changing shared file.
    data = regular(path, MAX_TOTAL)
    require(data, 'package_too_large')
    if expected_sha256 is not None:
        require(isinstance(expected_sha256, str) and re.match(r'\A[a-f0-9]{64}\Z', expected_sha256),
                'invalid_update_expectation')
        require(digest(data) == expected_sha256, 'package_changed')
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
                bridge_progress()
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


def verify_private_directory(path):
    info = os.lstat(path)
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid() and
            info.st_mode & 0o077 == 0 and os.path.realpath(path) == path, 'unsafe_private_directory')


def private_directory(path):
    if not os.path.lexists(path):
        os.mkdir(path, 0o700)
    verify_private_directory(path)


def write_new(path, blob, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, 'wb') as output:
        output.write(blob)
        output.flush()
        os.fsync(output.fileno())


class _SnapshotProof(object):
    """Evidence for one verified private snapshot in this process only."""
    def __init__(self, folder, manifest, raw, identity):
        self.folder = folder
        self.manifest = manifest
        self.raw = raw
        self.identity = identity
        self.pid = os.getpid()


def _snapshot_layout(folder, manifest):
    # Only signed modules may be imported from a snapshot. In particular,
    # stale .pyc files or extra modules cannot become an alternate import path.
    expected_files = set(manifest['files']) | set(('manifest.json', 'manifest.sig.json'))
    expected_dirs = set()
    for name in manifest['files']:
        parts = name.split('/')[:-1]
        for count in range(1, len(parts) + 1):
            expected_dirs.add('/'.join(parts[:count]))
    files, directories = set(), set()
    def walk_error(error):
        raise MobileError('unsafe_snapshot_member')
    for parent, names, members in os.walk(folder, onerror=walk_error, followlinks=False):
        for name in names + members:
            path = parent + '/' + name
            relative = path[len(folder) + 1:]
            info = os.lstat(path)
            require(info.st_uid == os.geteuid() and info.st_mode & 0o077 == 0 and
                    os.path.realpath(path) == path, 'unsafe_snapshot_member')
            if name in names:
                require(stat.S_ISDIR(info.st_mode), 'unsafe_snapshot_member')
                directories.add(relative)
            else:
                require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'unsafe_snapshot_member')
                files.add(relative)
    require(files == expected_files and directories == expected_dirs, 'unexpected_snapshot_member')


def _snapshot_identity(folder):
    name = os.path.basename(folder)
    require(os.path.dirname(folder) == ROOT + '/snapshots' and
            re.match(r'\A[a-f0-9]{64}\Z', name) and os.path.lexists(folder), 'unsafe_bundle_path')
    verify_private_directory(ROOT)
    verify_private_directory(ROOT + '/snapshots')
    verify_private_directory(folder)
    identities = []
    for path in (ROOT, ROOT + '/snapshots', folder):
        info = os.lstat(path)
        identities.append((info.st_dev, info.st_ino))
    return tuple(identities)


def _verified_snapshot(folder, expected_raw=None):
    identity = _snapshot_identity(folder)
    name = os.path.basename(folder)
    manifest, raw, signature, blobs = read_bundle(folder)
    require(digest(raw) == name and (expected_raw is None or raw == expected_raw), 'snapshot_changed')
    _snapshot_layout(folder, manifest)
    require(_snapshot_identity(folder) == identity, 'snapshot_changed')
    # Do not retain the verified file bodies alongside the source bundle.
    del signature, blobs
    return _SnapshotProof(folder, manifest, raw, identity)


def _check_snapshot_proof(folder, proof):
    require(isinstance(proof, _SnapshotProof) and proof.pid == os.getpid() and
            proof.folder == folder and digest(proof.raw) == os.path.basename(folder), 'snapshot_changed')
    require(_snapshot_identity(folder) == proof.identity, 'snapshot_changed')


def snapshot(bundle, _return_proof=False):
    manifest, raw, signature, blobs = bundle
    private_directory(ROOT)
    private_directory(ROOT + '/snapshots')
    folder = ROOT + '/snapshots/' + digest(raw)
    if os.path.lexists(folder):
        proof = _verified_snapshot(folder, raw)
        return (folder, proof) if _return_proof else folder
    temporary = folder + '.stage-' + binascii.hexlify(os.urandom(6)).decode('ascii')
    private_directory(temporary)
    for name, blob in sorted(blobs.items()):
        parent = temporary
        for part in name.split('/')[:-1]:
            parent += '/' + part
            private_directory(parent)
        write_new(temporary + '/' + name, blob)
        bridge_progress()
    write_new(temporary + '/manifest.json', raw)
    write_new(temporary + '/manifest.sig.json', signature)
    read_bundle(temporary)
    try:
        os.rename(temporary, folder)
    except OSError:
        if not os.path.isdir(folder):
            raise
        # A concurrent successful copy is usable; the uniquely owned staging
        # directory is retained for diagnosis rather than recursively deleted.
    proof = _verified_snapshot(folder, raw)
    return (folder, proof) if _return_proof else folder


def source_snapshot(folder, entry_bytes):
    # The app's source copy is data, not the code we execute. When its signed
    # identity is already materialized as a private snapshot, verify that
    # entire snapshot instead of rereading the unused source file bodies.
    manifest, raw, signature = read_bundle_manifest(folder)
    verify_bridge_bundle((manifest, raw, signature), entry_bytes)
    target = ROOT + '/snapshots/' + digest(raw)
    if os.path.lexists(target):
        proof = _verified_snapshot(target, raw)
        return target, proof
    # A first installation must verify every source byte before creating the
    # private snapshot. Re-read and bind the signed header to the one above.
    bundle = read_bundle(folder)
    require(bundle[1] == raw, 'source_manifest_changed')
    verify_bridge_bundle(bundle, entry_bytes)
    return snapshot(bundle, _return_proof=True)


def trusted_python(folder, _proof=None):
    if _proof is None:
        _proof = _verified_snapshot(folder)
    _check_snapshot_proof(folder, _proof)
    manifest = _proof.manifest
    with open(os.devnull, 'wb') as sink:
        for name in sorted(manifest['files']):
            if name == 'runtime/job-launcher':
                os.chmod(folder + '/' + name, 0o700)
            if name.endswith('.py') or name.endswith('.sh') or name == 'runtime/job-launcher':
                require(subprocess.call(['/proc/boot/pathtrust', '!' + folder + '/' + name],
                                        stdout=sink, stderr=sink) == 0, 'pathtrust_failed')
                bridge_progress()
    return manifest


def active_pointer_observation():
    pointer = ROOT + '/active.json'
    if not os.path.lexists(pointer):
        return (False, b'')
    return (True, regular(pointer, 4096))


def active_bundle(fallback, _fallback_proof=None, _return_proof=False):
    if _fallback_proof is not None:
        _check_snapshot_proof(fallback, _fallback_proof)
    present, pointer_raw = active_pointer_observation()
    if _fallback_proof is not None:
        global FOREGROUND_ACTIVE_POINTER
        FOREGROUND_ACTIVE_POINTER = (present, pointer_raw)
    if not present:
        return (fallback, _fallback_proof) if _return_proof else fallback
    value = json_bytes(pointer_raw)
    require(isinstance(value, dict) and set(value) in ({'manifest_sha256'}, {'manifest_sha256', 'for_bundle'}) and
            re.match(r'\A[a-f0-9]{64}\Z', value['manifest_sha256']), 'active_bundle_changed')
    if 'for_bundle' in value:
        require(isinstance(value['for_bundle'], str) and re.match(r'\A[a-f0-9]{64}\Z', value['for_bundle']), 'active_bundle_changed')
    folder = ROOT + '/snapshots/' + value['manifest_sha256']
    verify_private_directory(folder)
    if _fallback_proof is not None:
        if folder == fallback:
            proof = _fallback_proof
            manifest, raw = proof.manifest, proof.raw
        else:
            # Verify the signed identity first. If its version/capabilities
            # force fallback, none of this snapshot's files are executed.
            # A selected candidate is still completely verified below.
            identity = _snapshot_identity(folder)
            manifest, raw, unused_signature = read_bundle_manifest(folder)
            _snapshot_layout(folder, manifest)
            require(_snapshot_identity(folder) == identity, 'snapshot_changed')
            proof = None
        fallback_manifest, fallback_raw = _fallback_proof.manifest, _fallback_proof.raw
    else:
        bundle = read_bundle(folder)
        manifest, raw = bundle[0], bundle[1]
        fallback_bundle = read_bundle(fallback)
        fallback_manifest, fallback_raw = fallback_bundle[0], fallback_bundle[1]
        proof = None
    require(digest(raw) == value['manifest_sha256'], 'active_bundle_changed')
    # A service rollback may point to a historically signed worker that does
    # not understand unknown outcomes. Never route a guarded BAR back to it.
    if supports_job_guard(fallback_manifest) and not supports_job_guard(manifest):
        return (fallback, _fallback_proof) if _return_proof else fallback
    if supports_selection_guard(fallback_manifest) and not supports_selection_guard(manifest):
        return (fallback, _fallback_proof) if _return_proof else fallback
    fallback_version = fallback_manifest['version']
    if (numeric_version(fallback_version) > numeric_version(manifest['version']) and
            value.get('for_bundle') != digest(fallback_raw)):
        return (fallback, _fallback_proof) if _return_proof else fallback
    if _fallback_proof is not None and proof is None:
        proof = _verified_snapshot(folder, raw)
    return (folder, proof) if _return_proof else folder


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


def bridge_entry_bytes():
    """Read the same root-private bridge copy the native app hash-pinned."""
    path = os.path.abspath(__file__)
    folder = os.path.dirname(path)
    require(os.path.basename(path) == 'entry.py' and
            re.match(r'\A/var/bb10_mobile_entry_[a-f0-9]{32}\Z', folder) and
            os.path.realpath(path) == path, 'unsafe_bridge_entry')
    private_directory(folder)
    info = os.lstat(path)
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and
            info.st_mode & 0o077 == 0 and info.st_nlink == 1 and
            os.listdir(folder) == ['entry.py'], 'unsafe_bridge_entry')
    return regular(path)


def verify_bridge_bundle(bundle, entry_bytes):
    manifest = bundle[0]
    core = dict(manifest)
    core['files'] = dict((name, item) for name, item in manifest['files'].items()
                         if name != 'runtime/entry.py')
    require(isinstance(RELEASE_VERSION, str) and manifest['version'] == RELEASE_VERSION and
            supports_job_guard(manifest) and supports_selection_guard(manifest) and
            isinstance(RELEASE_CORE_SHA256, str) and digest(canonical(core)) == RELEASE_CORE_SHA256 and
            digest(entry_bytes) == manifest['files']['runtime/entry.py']['sha256'],
            'bridge_bundle_changed')


def main():
    require(sys.flags.optimize == 0, 'optimized_python_not_supported')
    require(os.geteuid() == 0 and os.uname()[0] == 'QNX', 'root_required')
    require(len(sys.argv) in (2, 3, 4) and sys.argv[1] in ACTIONS, 'invalid_action')
    request = json_bytes(decode64(sys.argv[2])) if len(sys.argv) >= 3 else {'schema': 2}
    require(isinstance(request, dict) and request.get('schema') == 2, 'invalid_request')
    require(set(request) <= {'schema', 'language', 'backup_location', 'package_path', 'job_id',
            'operation_id', 'experimental', 'profile_id', 'confirmed', 'incoming', 'outgoing',
            'audio', 'lte', 'call_context', 'export_kind', 'expected_version', 'expected_sha256'}, 'invalid_request_field')
    global BRIDGE_PROGRESS
    BRIDGE_PROGRESS = True
    bridge_progress()
    expects_update = 'expected_version' in request or 'expected_sha256' in request
    if expects_update:
        require(sys.argv[1] == 'update' and isinstance(request.get('package_path'), str) and
                isinstance(request.get('expected_version'), str) and
                re.match(r'\A[0-9]{1,5}(?:\.[0-9]{1,5}){3}\Z', request['expected_version']) and
                isinstance(request.get('expected_sha256'), str) and
                re.match(r'\A[a-f0-9]{64}\Z', request['expected_sha256']), 'invalid_update_expectation')
    # The native bridge runs a root-private copy of the already hash-pinned
    # entry bytes. The source bundle is data until signature verification.
    folder = (os.path.realpath(sys.argv[3]) if len(sys.argv) == 4 else
              os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    fallback, fallback_proof = source_snapshot(folder, bridge_entry_bytes())
    global FALLBACK_MANIFEST_SHA
    FALLBACK_MANIFEST_SHA = os.path.basename(fallback)
    verified, proof = active_bundle(fallback, fallback_proof, _return_proof=True)
    verified_manifest = trusted_python(verified, proof)
    if expects_update:
        capabilities = verified_manifest.get('capabilities')
        require(isinstance(capabilities, list) and 'expected_update_version_v1' in capabilities,
                'update_runtime_upgrade_required')
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
