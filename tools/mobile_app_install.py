"""Install the pinned native phone GUI through an already authorized connection."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import uuid
import zipfile

from desktop_paths import private_root, resource_root
from workflow import ENV, WorkflowError

ROOT = resource_root()
PIN = 'materials/mobile-app-artifact.json'
HELPER = 'tools/mobile_app_device.py'
BUNDLED_BAR = 'assets/mobile/bb10-volte.bar'


def release():
    try:
        value = json.loads((ROOT / PIN).read_text(encoding='ascii'))
        helper = ROOT / HELPER
        if (value.get('schema') != 1 or helper.is_symlink() or
                hashlib.sha256(helper.read_bytes()).hexdigest() != value['helper_sha256'] or
                not re.fullmatch(r'[0-9]+(?:\.[0-9]+){3}', value['version']) or
                not re.fullmatch(r'[a-f0-9]{64}', value['bar_sha256']) or
                type(value['bar_size']) is not int or not 0 < value['bar_size'] <= 16 * 1024 * 1024):
            raise ValueError('release')
        return value
    except (OSError, ValueError, KeyError, TypeError):
        raise WorkflowError('mobile_app_release_invalid') from None


def verify_bar(path, pin=None):
    pin = pin or release()
    path = Path(path)
    try:
        if path.is_symlink() or path.stat().st_size != pin['bar_size']:
            raise ValueError('size')
        blob = path.read_bytes()
        if len(blob) != pin['bar_size'] or hashlib.sha256(blob).hexdigest() != pin['bar_sha256']:
            raise ValueError('hash')
        return blob
    except (OSError, ValueError):
        raise WorkflowError('mobile_app_bar_mismatch') from None


def bundled_bar(pin=None):
    """Use the same verified artifact offline in both desktop packages."""
    path = ROOT / BUNDLED_BAR
    verify_bar(path, pin)
    return path


def make_release_pin(bar, destination):
    """Explicit maintainer operation; never invoked by the installer GUI."""
    from mobile_app_device import headers
    data = Path(bar).read_bytes()
    with zipfile.ZipFile(bar) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or any(name.startswith('/') or '..' in name.split('/') or '\\' in name for name in names):
            raise ValueError('Unsafe BAR members')
        raw = archive.read('META-INF/MANIFEST.MF')
        info = headers(raw)
        identity_keys = ('Package-Name', 'Package-Id', 'Package-Author-Id', 'Package-Architecture',
                         'Package-Version', 'Application-Id', 'Application-Version')
        identity = {key: info[key] for key in identity_keys}
        if (identity['Package-Name'] != 'com.octolab.bb10volte' or
                identity['Package-Author-Id'] != 'gYAOctoLabBB10VoLTE20261102' or
                identity['Package-Id'] != 'testDev_b_bb10volte7b237e48' or
                identity['Application-Id'] != identity['Package-Id'] or
                identity['Package-Architecture'] != 'armle-v7' or
                identity['Package-Version'] != identity['Application-Version']):
            raise ValueError('Unexpected native application identity')
        files = {name: {'sha256': hashlib.sha256(archive.read(name)).hexdigest(), 'size': archive.getinfo(name).file_size}
                 for name in names if not name.endswith('/')}
    value = {'schema': 1, 'version': identity['Package-Version'], 'identity': identity,
             'filename': Path(bar).name, 'bar_sha256': hashlib.sha256(data).hexdigest(), 'bar_size': len(data),
             'platform_manifest_sha256': hashlib.sha256(raw).hexdigest(), 'installed_files': files,
             'helper_sha256': hashlib.sha256((ROOT / HELPER).read_bytes()).hexdigest(),
             'installer_sha256': 'b5b98e0ad73c944810bd4d9135386f9d83b01a630fcbd077d9c2a2de9b65e740'}
    Path(destination).write_text(json.dumps(value, indent=2) + '\n', encoding='ascii', newline='\n')
    return value


class MobileAppInstaller:
    def __init__(self, client):
        self.client = client
        self.pin = release()
        self.helper = (ROOT / HELPER).read_bytes()
        if hashlib.sha256(self.helper).hexdigest() != self.pin['helper_sha256']:
            raise WorkflowError('mobile_app_release_invalid')

    def upload(self, local, remote):
        c = self.client
        c.process([c.scp, '-S', c.ssh, '-O', '-q'] + c.options + [str(local), c.host + ':' + remote], 60)

    def _run(self, action, *, bar=None, device_id=None):
        if action not in ('inspect', 'install'):
            raise WorkflowError('invalid_action')
        if action == 'install' and not re.fullmatch(r'[a-f0-9]{32}', device_id or ''):
            raise WorkflowError('mobile_app_check_required')
        # Validate/copy the complete BAR before creating anything on the phone.
        blob = verify_bar(bar, self.pin) if action == 'install' else None
        identifier = uuid.uuid4().hex
        local = private_root() / 'mobile-app-install' / identifier
        local.mkdir(parents=True, exist_ok=False)
        remote = '/var/bb10_volte_app_stage_' + identifier
        descriptor = local / 'release.json'
        descriptor.write_text(json.dumps(self.pin, sort_keys=True), encoding='ascii')
        record = {'schema': 1, 'id': identifier, 'action': action, 'remote_stage': remote,
                  'device_id': device_id, 'target_version': self.pin['version'],
                  'bar_sha256': self.pin['bar_sha256'], 'state': 'before_transfer'}
        def save():
            with (local / 'receipt.json').open('w', encoding='ascii') as output:
                json.dump(record, output, sort_keys=True, indent=2)
                output.flush()
                os.fsync(output.fileno())
        save()
        self.client.remote('test ! -e ' + shlex.quote(remote) + ' && mkdir -m 700 ' + shlex.quote(remote))
        (local / 'agent.py').write_bytes(self.helper)
        self.upload(local / 'agent.py', remote + '/agent.py')
        self.upload(descriptor, remote + '/release.json')
        names = ['agent.py', 'release.json']
        if blob is not None:
            (local / 'application.bar').write_bytes(blob)
            self.upload(local / 'application.bar', remote + '/application.bar')
            names.append('application.bar')
        self.client.remote('chmod 600 ' + ' '.join(shlex.quote(remote + '/' + name) for name in names))
        args = action + (' ' + identifier + ' ' + device_id if action == 'install' else '')
        record['state'] = 'submitted_query_same_phone_job' if action == 'install' else 'observing'
        save()
        try:
            raw = self.client.remote('/proc/boot/pathtrust ' + shlex.quote('!' + remote + '/agent.py') +
                ' && ' + ENV + '/usr/bin/python3.2 -B ' + shlex.quote(remote + '/agent.py') + ' ' + args, 160 if action == 'install' else 40)
            result = json.loads(raw)
        except (WorkflowError, ValueError):
            record['state'] = 'result_unconfirmed_check_device'
            save()
            raise WorkflowError('mobile_app_result_unconfirmed') from None
        if not isinstance(result, dict) or result.get('schema') != 1:
            raise WorkflowError('invalid_device_response')
        record.update(state=result.get('state', 'unknown'), result=result)
        save()
        # Keep private inputs and transaction receipts until explicit maintenance.
        # A lost SSH response never deletes a live installer's source package.
        return result

    def inspect(self):
        return self._run('inspect')

    def install(self, bar, device_id):
        return self._run('install', bar=bar, device_id=device_id)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Maintainer: pin a reviewed complete native BAR for the desktop installer')
    parser.add_argument('--pin-bar', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / PIN)
    arguments = parser.parse_args()
    print(json.dumps({k: v for k, v in make_release_pin(arguments.pin_bar, arguments.output).items()
                      if k != 'installed_files'}, indent=2))
