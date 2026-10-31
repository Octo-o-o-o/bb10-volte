"""Cross-platform desktop transport for the unified phone service."""
import contextlib
import hashlib
import json
import re
import shlex
import sys
import uuid
from pathlib import Path
from desktop_paths import private_root, resource_root
from workflow import ENV, WorkflowError

ROOT = resource_root()
sys.path.insert(0, str(ROOT / 'device'))
import carrier_policy as policy
from unified_service import PAYLOAD_FILES
from unified_install import PREVIOUS_PAYLOADS, UPDATE_FILES

MANIFEST = 'materials/unified-payload.json'
BASE = policy.BASE


def verify_package():
    value = json.loads((ROOT / MANIFEST).read_text(encoding='ascii'))
    if value.get('owner') != policy.OWNER or value.get('schema') != 1 or set(value['files']) != set(PAYLOAD_FILES):
        raise WorkflowError('unified_package_mismatch')
    for name, expected in value['files'].items():
        if (ROOT / name).is_symlink() or hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise WorkflowError('unified_package_mismatch')
    return value


def write_manifest():
    from desktop_paths import frozen
    if frozen():
        raise WorkflowError('package_readonly')
    project = json.loads((ROOT / 'project.json').read_text(encoding='utf-8'))
    value = {'schema': 1, 'owner': policy.OWNER, 'version': project['version'],
             'desktop_revision': project['desktop_revision'],
             'files': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in PAYLOAD_FILES}}
    (ROOT / MANIFEST).write_text(json.dumps(value, indent=2) + '\n', encoding='ascii', newline='\n')
    return value


class AutoClient:
    def __init__(self, client):
        self.client = client
        self.variant = None

    def upload(self, local, remote):
        c = self.client
        return c.process([c.scp, '-S', c.ssh, '-O', '-q'] + c.options + [str(local), c.host + ':' + remote], 60)

    def download(self, remote, local):
        c = self.client
        return c.process([c.scp, '-S', c.ssh, '-O', '-q'] + c.options + [c.host + ':' + remote, str(local)], 60)

    def execute(self, base, script, args=(), timeout=90):
        if script not in ('unified_install.py', 'unified_service.py'):
            raise WorkflowError('invalid_action')
        trust = ' && '.join('/proc/boot/pathtrust ' + shlex.quote('!' + base + '/' + name)
                            for name in PAYLOAD_FILES if name.endswith('.py'))
        command = trust + ' && ' + ENV + '/usr/bin/python3.2 ' + shlex.quote(base + '/device/' + script)
        command += ' ' + ' '.join(shlex.quote(arg) for arg in args)
        if self.variant is not None:
            if self.variant not in policy.MODELS:
                raise WorkflowError('unsupported_model_or_os')
            command = ('case "$(cat /pps/services/deviceproperties)" in *"modelnumber::' + self.variant +
                       '"*) ' + command + ' ;; *) exit 93 ;; esac')
        output = self.client.remote(command, timeout)
        try:
            return json.loads(output)
        except ValueError:
            raise WorkflowError('invalid_device_response') from None

    @contextlib.contextmanager
    def stage(self):
        verify_package()
        stage = '/var/bb10_auto_stage_' + uuid.uuid4().hex[:12]
        self.client.remote('test ! -e ' + stage + ' && mkdir -m 700 ' + stage +
                           ' && mkdir -m 700 ' + stage + '/device ' + stage + '/driver')
        complete = False
        try:
            for name in PAYLOAD_FILES:
                self.upload(ROOT / name, stage + '/' + name)
            self.upload(ROOT / MANIFEST, stage + '/payload.json')
            yield stage
            complete = True
        finally:
            # A failed/timeout operation may still use its input. Retain it for
            # diagnosis; never delete or re-run an operation of unknown outcome.
            if complete:
                self.execute(stage, 'unified_install.py', ('cleanup-stage', stage))

    def probe(self):
        with self.stage() as stage:
            report = self.execute(stage, 'unified_install.py', ('probe',))
        self.variant = report['variant']
        return report

    def install(self):
        with self.stage() as stage:
            before = self.execute(stage, 'unified_install.py', ('probe',))
            self.variant = before['variant']
            if before.get('installed') and not before.get('installation_pending'):
                if not before.get('can_update'):
                    raise WorkflowError('unified_update_needs_stop_and_reboot' if before.get('update_available')
                                        else 'unified_already_installed')
                result = self.execute(stage, 'unified_install.py', ('update', stage), 420)
                backup = result['phone_backup']
                if not re.fullmatch(re.escape(BASE) + r'/archive/update-[a-f0-9]{12}', backup):
                    raise WorkflowError('unified_backup_not_verified')
                folder = private_root() / 'automatic-carrier-updates' / uuid.uuid4().hex
                folder.mkdir(parents=True, exist_ok=False)
                for name, expected in result['backup_files'].items():
                    if name not in ('payload.before.json',) + UPDATE_FILES:
                        raise WorkflowError('unified_backup_not_verified')
                    destination = folder / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    self.download(backup + '/' + name, destination)
                    if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
                        raise WorkflowError('unified_backup_not_verified')
                result['desktop_backup'] = str(folder)
                return result
            prepared = self.execute(stage, 'unified_install.py', ('prepare', stage), 180)
            folder = private_root() / 'automatic-carrier-backups' / uuid.uuid4().hex
            folder.mkdir(parents=True, exist_ok=False)
            manifest_file = folder / 'manifest.json'
            self.download(BASE + '/backup/manifest.json', manifest_file)
            manifest_sha = hashlib.sha256(manifest_file.read_bytes()).hexdigest()
            if manifest_sha != prepared['backup_manifest_sha256']:
                raise WorkflowError('unified_backup_not_verified')
            backup = json.loads(manifest_file.read_text(encoding='ascii'))
            if backup['owner'] != policy.OWNER or backup['files'] != prepared['backup_files']:
                raise WorkflowError('unified_backup_not_verified')
            for name, expected in backup['files'].items():
                if name not in ('ims.original', 'ims_defaults.original', 'omadm.original', 'test.original', 'btool.original'):
                    raise WorkflowError('unified_backup_not_verified')
                self.download(BASE + '/backup/' + name, folder / name)
                if hashlib.sha256((folder / name).read_bytes()).hexdigest() != expected:
                    raise WorkflowError('unified_backup_not_verified')
            receipt = {'owner': policy.OWNER, 'all_original_hashes_verified': True,
                       'backup_manifest_sha256': manifest_sha}
            receipt_file = folder / 'desktop-backup-receipt.json'
            receipt_file.write_bytes(policy.profiles.canonical(receipt))
            self.upload(receipt_file, BASE + '/desktop-backup-receipt.json')
            result = self.execute(BASE, 'unified_install.py', ('activate',), 240)
            result['desktop_backup'] = str(folder)
        return result

    def action(self, action):
        if action not in ('status', 'start', 'enable', 'disable'):
            raise WorkflowError('invalid_action')
        expected = verify_package()
        try:
            installed = json.loads(self.client.remote('cat ' + BASE + '/payload.json'))
            if any(installed.get(key) != expected[key] for key in ('owner', 'schema')):
                raise ValueError('payload')
            if installed.get('files') != expected['files']:
                prior = hashlib.sha256(policy.profiles.canonical(installed.get('files'))).hexdigest()
                if prior not in PREVIOUS_PAYLOADS:
                    raise ValueError('payload')
        except (ValueError, TypeError, AttributeError):
            raise WorkflowError('unified_package_mismatch') from None
        if action == 'enable':
            state = self.execute(BASE, 'unified_service.py', ('status',), 180)
            if state.get('manager_alive'):
                raise WorkflowError('restore_pending')
        return self.execute(BASE, 'unified_service.py', (action,), 180)


def main():
    import argparse
    from workflow import Client
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('manifest', 'probe', 'install', 'status', 'start', 'enable', 'disable'))
    parser.add_argument('--host', default='bb10-root')
    parser.add_argument('--ssh-config')
    args = parser.parse_args()
    if args.action == 'manifest':
        print(json.dumps({'manifest_written': True, 'files': len(write_manifest()['files'])}))
        return
    client = AutoClient(Client(args.host, args.ssh_config))
    result = client.probe() if args.action == 'probe' else client.install() if args.action == 'install' else client.action(args.action)
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
