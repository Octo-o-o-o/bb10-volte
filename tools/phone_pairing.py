"""Owner-run BB10 pairing helper. Python 3.2 compatible; exports public data only."""
import base64
import hashlib
import json
import os
import re
import stat
import struct
import subprocess
import sys

PAIR_PUBLIC_KEY = None
PAIR_REQUEST_ID = None
PAIR_LANGUAGE = 'zh'

PHONE_MESSAGES_ZH = {
    'This adds this computer to the existing SSH authorization file. Existing keys are preserved.':
        '此操作会将这台电脑加入现有 SSH 授权文件，并保留已有密钥。',
    'Type PAIR to authorize this computer: ': '输入 PAIR 授权这台电脑：',
    'Cancelled; no files changed.': '已取消；没有修改任何文件。',
    'Public pairing result saved: ': '公开授权结果已保存：',
    'Copy this result back to the desktop app, then test the connection.': '请将结果复制回电脑应用，再验证连接。',
    'If SSH is disabled, you may start the existing server for the USB link now.': '如果 SSH 未启动，现在可以为 USB 连接启动已有服务。',
    'Type START only if SSH is not already running (Enter to skip): ': '仅当 SSH 尚未运行时输入 START（按回车跳过）：',
    'SSH start exit code: ': 'SSH 启动退出码：',
    '. The desktop app must verify Root access.': '。电脑应用仍需验证 Root 权限。',
    'This does not enable SSH at boot. If needed, enable it using the existing Root tools.':
        '此操作不会启用开机 SSH。如有需要，请使用现有 Root 工具启用。',
    'ROOT_REQUIRED: use the existing __root / u_root terminal; no files changed':
        '需要 Root：请使用现有 __root / u_root 终端；没有修改文件。',
    'ROOT_REQUIRED: enter an existing Root terminal first': '需要 Root：请先进入已有 Root 终端。',
    'UNSUPPORTED_SSH_LAYOUT: original Root configuration needs review': 'SSH 配置布局不支持：请核对原 Root 配置。',
    'Existing authorization file is required': '需要已有的授权文件。',
    'Unexpected authorization file owner, mode or size': '授权文件的所有者、权限或大小不符合预期。',
    'Phone Downloads directory is unavailable': '手机 Downloads 目录不可用。',
    'Existing result must not be a symbolic link': '已有结果不能是符号链接。',
    'Existing pairing result differs; preserve it for review': '已有授权结果不同；请保留以便检查。',
    'Authorization readback failed': '授权回读校验失败。',
    'Conditional SSH configuration needs manual review': '含条件的 SSH 配置需要人工检查。',
    'Invalid pairing request': '授权请求无效。',
    'Expected an RSA public key': '需要 RSA 公钥。',
    'Invalid RSA public key': 'RSA 公钥无效。',
}


def phone_message(message):
    translated = PHONE_MESSAGES_ZH.get(message, message) if PAIR_LANGUAGE == 'zh' else message
    try:
        translated.encode(sys.stdout.encoding or 'utf-8')
    except (UnicodeError, LookupError):
        # Old phone terminals may expose an ASCII-only output stream. Keep the
        # authorization usable rather than raising before the confirmation.
        return message
    return translated


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
    authorized = config.get('authorizedkeysfile', [])
    host_paths = config.get('hostkey', [])
    host = os.path.join(ssh_dir, 'ssh_host_rsa_key')
    def same_file(path, expected):
        # QNX maps /base/etc/ssh and /var/etc/ssh to the same files without
        # making realpath() return the same spelling. Verify device/inode,
        # never infer equivalence from a similar name or matching contents.
        try:
            return os.path.isabs(path) and os.path.samefile(path, expected)
        except (OSError, ValueError):
            return False
    if (not any(same_file(path, target) for path in authorized) or
            not any(same_file(path, host) for path in host_paths) or not os.path.isdir(root_dir)):
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
    print(phone_message('This adds this computer to the existing SSH authorization file. Existing keys are preserved.'))
    if input(phone_message('Type PAIR to authorize this computer: ')).strip() != 'PAIR':
        print(phone_message('Cancelled; no files changed.'))
        return
    output = authorize(PAIR_PUBLIC_KEY, PAIR_REQUEST_ID)
    print(phone_message('Public pairing result saved: ') + output)
    print(phone_message('Copy this result back to the desktop app, then test the connection.'))
    print(phone_message('If SSH is disabled, you may start the existing server for the USB link now.'))
    if input(phone_message('Type START only if SSH is not already running (Enter to skip): ')).strip() == 'START':
        # Start the existing server once; do not rewrite its config, stop other
        # sessions, change boot flags or infer success from a listening port.
        code = subprocess.call(['/usr/sbin/sshd', '-f', '/etc/ssh/sshd_config',
                                '-o', 'ListenAddress=169.254.0.1'])
        print(phone_message('SSH start exit code: ') + str(code) + phone_message('. The desktop app must verify Root access.'))
        print(phone_message('This does not enable SSH at boot. If needed, enable it using the existing Root tools.'))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        print(phone_message(str(error)))
        raise SystemExit(1)
