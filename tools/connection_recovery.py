"""Local owner-controlled SSH recovery; never guesses credentials or host trust."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

from desktop_paths import private_root, resource_root
from workflow import Client, WorkflowError, CREATE_NO_WINDOW
from phone_pairing import public_key


class RecoveryError(ValueError):
    pass


def keygen():
    # Reuse the verified SSH installation selected for normal connections.
    client = Client()
    path = Path(client.ssh).with_name('ssh-keygen.exe' if sys.platform == 'win32' else 'ssh-keygen')
    if not path.is_absolute():
        found = shutil.which(str(path))
        path = Path(found) if found else path
    if not path.is_file():
        raise RecoveryError('keygen_missing')
    return str(path)


def run_keygen(args):
    try:
        result = subprocess.run([keygen()] + args, input='', capture_output=True, text=True,
                                timeout=30, creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise RecoveryError('key_unreadable') from None
    if result.returncode:
        raise RecoveryError('key_unreadable')
    return result.stdout


def new_folder():
    folder = private_root() / ('recovery-' + uuid.uuid4().hex[:12])
    folder.mkdir(parents=True, mode=0o700)
    protect(folder, directory=True)
    return folder


def protect(path, directory=False):
    if os.name == 'nt':
        account = subprocess.check_output(['whoami'], text=True, creationflags=CREATE_NO_WINDOW).strip()
        permission = ':(OI)(CI)F' if directory else ':F'
        subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r',
                        account + permission, 'SYSTEM' + permission,
                        '/remove:g', '*S-1-3-4'], check=True,
                       capture_output=True, creationflags=CREATE_NO_WINDOW)
    else:
        path.chmod(0o700 if directory else 0o600)


def fingerprint(key):
    data = base64.b64decode(public_key(key).split()[1])
    return 'SHA256:' + base64.b64encode(hashlib.sha256(data).digest()).decode('ascii').rstrip('=')


def read_host_key(path):
    path = Path(path)
    if path.stat().st_size > 65536:
        raise RecoveryError('host_key_invalid')
    keys = set()
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        words = line.split()
        if words and words[0] == 'ssh-rsa':
            candidate = line
        elif len(words) >= 3 and words[0] in ('169.254.0.1', '[169.254.0.1]:22') and words[1] == 'ssh-rsa':
            candidate = ' '.join(words[1:])
        else:
            continue
        try:
            keys.add(public_key(candidate))
        except (ValueError, UnicodeError):
            raise RecoveryError('host_key_invalid') from None
    if len(keys) != 1:
        raise RecoveryError('host_key_invalid')
    return keys.pop()


def write_config(folder, host_public):
    folder = Path(folder).resolve()
    host_public = public_key(host_public)
    (folder / 'known_hosts').write_text('169.254.0.1 ' + host_public + '\n', encoding='ascii')
    # Percent expansion in OpenSSH paths must not interpret a user folder name.
    def quoted(path):
        value = path.as_posix().replace('%', '%%')
        if any(char in value for char in ('"', '\n', '\r')):
            raise RecoveryError('path_unsupported')
        return '"' + value + '"'
    config = folder / 'ssh_config'
    config.write_text('Host bb10-root q10-root\n    HostName 169.254.0.1\n    User root\n'
                      '    IdentityFile ' + quoted(folder / 'identity') + '\n'
                      '    UserKnownHostsFile ' + quoted(folder / 'known_hosts') + '\n'
                      '    IdentitiesOnly yes\n    StrictHostKeyChecking yes\n'
                      '    PasswordAuthentication no\n    BatchMode yes\n', encoding='utf-8')
    return {'host': 'bb10-root', 'config': str(config)}


def import_identity(identity, host_public, confirmed=False):
    if confirmed is not True:
        raise RecoveryError('host_confirmation_required')
    identity = Path(identity)
    if identity.name.startswith(('ssh_host_', 'q10_host_')) or identity.stat().st_size > 65536:
        raise RecoveryError('login_key_required')
    raw = identity.read_bytes()
    if raw.startswith(b'PuTTY-User-Key-File-'):
        raise RecoveryError('putty_conversion_required')
    if b'PRIVATE KEY' not in raw[:100]:
        raise RecoveryError('login_key_required')
    host_public = public_key(host_public)
    folder = new_folder()
    target = folder / 'identity'
    target.write_bytes(raw)
    protect(target)
    # Empty passphrase is explicit; never prompt invisibly or put a password in
    # process arguments. Encrypted keys have a separate, actionable GUI message.
    derived = run_keygen(['-y', '-P', '', '-f', str(target)])
    try:
        public_key(derived)
    except ValueError:
        raise RecoveryError('rsa_key_required') from None
    return write_config(folder, host_public)


def prepare_pairing():
    folder = new_folder()
    request_id = folder.name.removeprefix('recovery-')
    identity = folder / 'identity'
    run_keygen(['-q', '-t', 'rsa', '-b', '3072', '-m', 'PEM', '-N', '', '-f', str(identity)])
    key = public_key(identity.with_suffix('.pub').read_text(encoding='ascii'))
    template = (resource_root() / 'tools/phone_pairing.py').read_text(encoding='utf-8')
    script = template.replace('PAIR_PUBLIC_KEY = None', 'PAIR_PUBLIC_KEY = ' + repr(key), 1)
    script = script.replace('PAIR_REQUEST_ID = None', 'PAIR_REQUEST_ID = ' + repr(request_id), 1)
    output = folder / ('bb10-pair-' + request_id + '.py')
    output.write_text(script, encoding='utf-8', newline='\n')
    save_pairing_step(output, 1)
    return output


def save_pairing_step(script, step):
    script = Path(script).resolve()
    folder = script.parent
    if (step not in (1, 2, 3) or folder.parent != private_root().resolve() or
            not re.fullmatch(r'recovery-[a-f0-9]{12}', folder.name) or
            script.name != 'bb10-pair-' + folder.name[9:] + '.py' or not script.is_file()):
        raise RecoveryError('pairing_result_invalid')
    temporary = folder / ('progress-' + uuid.uuid4().hex + '.json')
    temporary.write_text(json.dumps({'step': step}) + '\n', encoding='utf-8')
    temporary.replace(folder / 'pairing-progress.json')


def pending_pairings():
    """Resume by request ID, never substitute a different computer's identity."""
    result = []
    for folder in sorted(private_root().glob('recovery-*')):
        if folder.is_symlink() or folder.is_junction() or not re.fullmatch(r'recovery-[a-f0-9]{12}', folder.name):
            continue
        script = folder / ('bb10-pair-' + folder.name[9:] + '.py')
        if (folder / 'pairing-complete.json').exists():
            continue
        if not all(path.is_file() and not path.is_symlink() for path in (script, folder / 'identity', folder / 'identity.pub')):
            continue
        try:
            public_key((folder / 'identity.pub').read_text(encoding='ascii'))
        except (OSError, ValueError, UnicodeError):
            continue
        try:
            progress_path = folder / 'pairing-progress.json'
            if progress_path.stat().st_size > 65536:
                raise ValueError('invalid progress')
            progress = json.loads(progress_path.read_text(encoding='utf-8'))
            step = progress.get('step', 1)
        except (OSError, ValueError, UnicodeError, AttributeError):
            step = 1
        result.append({'script': script, 'step': step if type(step) is int and step in (1, 2, 3) else 1})
    return result


def complete_pairing(config):
    folder = Path(config).resolve().parent
    if folder.parent == private_root().resolve() and re.fullmatch(r'recovery-[a-f0-9]{12}', folder.name):
        (folder / 'pairing-complete.json').write_text('{"verified": true}\n', encoding='utf-8')


def read_pairing_result(path):
    path = Path(path)
    if path.stat().st_size > 65536:
        raise RecoveryError('pairing_result_invalid')
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        request_id = data['request_id']
        if (data.get('schema') != 1 or data.get('root_verified_locally') is not True or
                not re.fullmatch(r'[a-f0-9]{12}', request_id)):
            raise ValueError()
        folder = private_root() / ('recovery-' + request_id)
        own_key = public_key((folder / 'identity.pub').read_text(encoding='ascii'))
        if public_key(data['computer_public_key']) != own_key or not (folder / 'identity').is_file():
            raise ValueError()
        host_key = public_key(data['host_public_key'])
    except (KeyError, OSError, ValueError, TypeError, UnicodeError):
        raise RecoveryError('pairing_result_invalid') from None
    return folder, host_key, data.get('ssh_startup_configured') is True


def finish_pairing(path, confirmed=False):
    if confirmed is not True:
        raise RecoveryError('host_confirmation_required')
    folder, host_key, _ = read_pairing_result(path)
    config = folder / 'ssh_config'
    # A later import cannot silently replace a previously pinned host identity.
    if config.is_file() and read_host_key(folder / 'known_hosts') != host_key:
        raise RecoveryError('host_key_changed')
    return write_config(folder, host_key)
