"""Owner-run BB10 pairing helper. Python 3.2 compatible; exports public data only."""
import base64
import hashlib
import json
import os
import re
import stat
import struct
import subprocess

PAIR_PUBLIC_KEY = None
PAIR_REQUEST_ID = None


def public_key(value):
    parts = value.strip().split()
    if len(parts) < 2 or parts[0] != 'ssh-rsa':
        raise ValueError('Expected an RSA public key')
    if not re.match(r'^[A-Za-z0-9+/]+={0,2}$', parts[1]):
        raise ValueError('Invalid RSA public key')
    raw = base64.b64decode(parts[1].encode('ascii'))
    if len(raw) < 128 or len(raw) > 8192 or raw[:11] != b'\x00\x00\x00\x07ssh-rsa':
        raise ValueError('Invalid RSA public key')
    offset = 11
    for minimum in (1, 128):
        if offset + 4 > len(raw):
            raise ValueError('Invalid RSA public key')
        length = struct.unpack('>I', raw[offset:offset + 4])[0]
        offset += 4
        if length < minimum or offset + length > len(raw):
            raise ValueError('Invalid RSA public key')
        offset += length
    if offset != len(raw):
        raise ValueError('Invalid RSA public key')
    return ' '.join(parts[:2])


def settings(path):
    result = {}
    with open(path, 'r') as stream:
        for line in stream:
            words = line.split('#', 1)[0].replace('=', ' ', 1).split()
            if words:
                name = words[0].lower()
                if name in ('match', 'include'):
                    raise ValueError('Conditional SSH configuration needs manual review')
                result.setdefault(name, []).extend(words[1:])
    return result


def authorize(key, request_id, ssh_dir='/var/etc/ssh', root_dir='/var/rootdata',
              result_dir='/accounts/1000/shared/downloads'):
    if os.geteuid() != 0:
        raise ValueError('ROOT_REQUIRED: enter an existing Root terminal first')
    if not re.match(r'^[a-f0-9]{12}$', request_id or ''):
        raise ValueError('Invalid pairing request')
    key = public_key(key)
    ssh_dir = os.path.realpath(ssh_dir)
    config = settings(os.path.join(ssh_dir, 'sshd_config'))
    target = os.path.join(ssh_dir, 'authorized_keys2')
    authorized = [os.path.realpath(path) for path in config.get('authorizedkeysfile', [])]
    host_paths = [os.path.realpath(path) for path in config.get('hostkey', [])]
    host = os.path.join(ssh_dir, 'ssh_host_rsa_key')
    if target not in authorized or host not in host_paths or not os.path.isdir(root_dir):
        raise ValueError('UNSUPPORTED_SSH_LAYOUT: original Root configuration needs review')
    if os.path.islink(target) or not os.path.isfile(target):
        raise ValueError('Existing authorization file is required')
    info = os.stat(target)
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022 or info.st_size > 1024 * 1024:
        raise ValueError('Unexpected authorization file owner, mode or size')
    with open(host + '.pub', 'r') as stream:
        host_key = public_key(stream.read(16384))
    if not os.path.isdir(result_dir):
        raise ValueError('Phone Downloads directory is unavailable')
    result = {'schema': 1, 'request_id': request_id, 'computer_public_key': key,
              'host_public_key': host_key, 'root_verified_locally': True,
              'ssh_startup_configured': any(os.path.isfile(os.path.join(root_dir, name))
                                            for name in ('use.sshd', 'use.ssh'))}
    output = os.path.join(result_dir, 'bb10-pair-' + request_id + '-result.json')
    if os.path.lexists(output):
        if os.path.islink(output):
            raise ValueError('Existing result must not be a symbolic link')
        with open(output, 'r') as stream:
            previous = json.load(stream)
        if previous != result:
            raise ValueError('Existing pairing result differs; preserve it for review')
    lock = target + '.bb10-pair.lock'
    lock_fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(lock_fd)
    try:
        with open(target, 'rb') as stream:
            before = stream.read()
        authorized_lines = [line for line in before.splitlines() if not line.lstrip().startswith(b'#')]
        if not any(key.encode('ascii') in line for line in authorized_lines):
            backup = target + '.bb10-backup-' + request_id
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(before)
            entry = ('no-agent-forwarding,no-port-forwarding,no-X11-forwarding ' + key + ' bb10-pair-' + request_id + '\n').encode('ascii')
            with open(target, 'ab') as stream:
                if before and not before.endswith(b'\n'):
                    stream.write(b'\n')
                stream.write(entry)
            with open(target, 'rb') as stream:
                if key.encode('ascii') not in stream.read():
                    raise ValueError('Authorization readback failed')
    finally:
        os.unlink(lock)
    if not os.path.exists(output):
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, 'w') as stream:
            json.dump(result, stream, indent=2)
    return output


def main():
    if os.geteuid() != 0:
        raise ValueError('ROOT_REQUIRED: use the existing __root / u_root terminal; no files changed')
    print('This adds this computer to the existing SSH authorization file. Existing keys are preserved.')
    if input('Type PAIR to authorize this computer: ').strip() != 'PAIR':
        print('Cancelled; no files changed.')
        return
    output = authorize(PAIR_PUBLIC_KEY, PAIR_REQUEST_ID)
    print('Public pairing result saved: ' + output)
    print('Copy this result back to the desktop app, then test the connection.')
    print('If SSH is disabled, you may start the existing server for the USB link now.')
    if input('Type START only if SSH is not already running (Enter to skip): ').strip() == 'START':
        # Start the existing server once; do not rewrite its config, stop other
        # sessions, change boot flags or infer success from a listening port.
        code = subprocess.call(['/usr/sbin/sshd', '-f', '/etc/ssh/sshd_config',
                                '-o', 'ListenAddress=169.254.0.1'])
        print('SSH start exit code: ' + str(code) + '. The desktop app must verify Root access.')
        print('This does not enable SSH at boot. If needed, enable it using the existing Root tools.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        print(str(error))
        raise SystemExit(1)
