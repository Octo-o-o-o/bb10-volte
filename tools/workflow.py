"""Bounded, deterministic desktop workflow; no AI, telemetry or license server."""
import contextlib
import datetime
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'device'))
import compatibility as compat
import profiles

BASE = compat.BASE
ENV = ('LD_LIBRARY_PATH=/base/usr/lib:/base/lib:/base/lib/dll:/radio/lib:/radio/lib/dll:/radio/usr/lib:/proc/boot '
       'PYTHONDONTWRITEBYTECODE=1 PYTHONHOME=/usr PYTHONPATH=/usr/lib/python32.zip:/usr/lib/python3.2/lib-dynload ')
FILES = sorted(compat.FILES)
MANIFEST = 'materials/payload-manifest.json'
CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class WorkflowError(RuntimeError):
    def __init__(self, code, report=None):
        self.code, self.report = code, report
        super().__init__(code)


def write_manifest():
    """Explicit maintainer operation. Normal commands NEVER bless local changes."""
    project = json.loads((ROOT / 'project.json').read_text(encoding='utf-8'))
    manifest = {'owner': compat.OWNER, 'version': project['version'],
                'files': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in FILES}}
    (ROOT / MANIFEST).write_text(json.dumps(manifest, indent=2) + '\n', encoding='ascii', newline='\n')
    return manifest


def verify_package():
    try:
        manifest = json.loads((ROOT / MANIFEST).read_text(encoding='utf-8'))
        project = json.loads((ROOT / 'project.json').read_text(encoding='utf-8'))
        if (manifest['owner'] != compat.OWNER or set(manifest['files']) != set(FILES) or
                manifest['version'] != project['version']):
            raise ValueError('manifest')
        for name, expected in manifest['files'].items():
            path = ROOT / name
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('hash')
        return manifest
    except (OSError, ValueError, KeyError, TypeError):
        raise WorkflowError('package_mismatch') from None


def registered(status):
    current = status.get('current', {})
    return (status.get('phase') == 'running' and status.get('manager_alive') is True and status.get('native_alive') is True and
            current.get('ims') == 'connected' and current.get('register_status') == '200 OK' and
            current.get('ran') == 'LTE' and current.get('radio') == ['lte'])


def public_status(raw):
    """Whitelist fields; old status files may contain private exception text."""
    current = raw.get('current', {})
    result = {'phase': raw.get('phase', 'unknown'), 'enabled': raw.get('enabled') is True,
            'manager_alive': raw.get('manager_alive') is True,
            'native_alive': raw.get('native_alive') is True,
            'current': {k: current.get(k) for k in ('ims', 'register_status', 'ran', 'radio', 'power')}}
    result['status_from_current_boot'] = raw.get('status_from_current_boot') is True
    scope = raw.get('ims_observation_scope')
    result['ims_observation_scope'] = scope if scope in ('owned_native', 'system_status_only') else 'unknown'
    wait = raw.get('startup_wait', {})
    result['startup_wait'] = {k: wait[k] for k in ('attempt', 'max_attempts', 'seconds_per_attempt', 'sim_ready', 'lte_ready')
                              if isinstance(wait, dict) and type(wait.get(k)) in (int, bool)}
    return result


class Client:
    def __init__(self, host='q10-root', ssh_config=None, progress=None, profile=None, allow_experimental=False):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', host):
            raise WorkflowError('invalid_host')
        self.host = host
        try:
            value = profiles.read_json(str(profile)) if isinstance(profile, (str, Path)) else profile
            self.request = profiles.request(value, allow_experimental)
        except (ValueError, TypeError, OSError):
            raise WorkflowError('invalid_profile') from None
        self.profile = self.request['profile']
        self.progress = progress or (lambda phase, state: None)
        self.options = ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=5',
                        '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2', '-o', 'ClearAllForwardings=yes']
        if ssh_config:
            path = Path(ssh_config).resolve()
            if not path.is_file():
                raise WorkflowError('config_missing')
            self.options += ['-F', str(path)]
        self.ssh = shutil.which('ssh') or shutil.which('ssh.exe')
        self.scp = shutil.which('scp') or shutil.which('scp.exe')
        if not self.ssh or not self.scp:
            raise WorkflowError('openssh_missing')

    def process(self, args, timeout):
        try:
            result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                    timeout=timeout, creationflags=CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise WorkflowError('connection_timeout_state_unknown') from None
        if result.returncode:
            message = result.stderr.lower()
            code = ('host_key_mismatch' if 'host key' in message else
                    'authentication_failed' if 'permission denied' in message else
                    'connection_failed' if result.returncode == 255 else 'remote_operation_failed')
            raise WorkflowError(code)
        return result.stdout

    def remote(self, command, timeout=40):
        return self.process([self.ssh, '-n', '-T'] + self.options + [self.host, command], timeout)

    def execute(self, path, args='', timeout=90):
        parent = path.rsplit('/', 1)[0]
        trust = ' && '.join('(test ! -e ' + shlex.quote(parent + '/' + name) +
                            ' || /proc/boot/pathtrust ' + shlex.quote('!' + parent + '/' + name) + ')'
                            for name in ('native.py', 'profiles.py', 'device_info.py', 'compatibility.py'))
        trust += ' && /proc/boot/pathtrust ' + shlex.quote('!' + path)
        output = self.remote(trust + ' && ' + ENV + '/usr/bin/python3.2 ' + shlex.quote(path) + ' ' + args, timeout)
        try:
            return json.loads(output)
        except ValueError:
            raise WorkflowError('invalid_device_response') from None

    @contextlib.contextmanager
    def stage(self, payload=False):
        self.progress('package', 'working')
        verify_package()
        self.progress('package', 'done')
        path = '/var/rootdata/q10_volte_stage_' + uuid.uuid4().hex[:12]
        names = (FILES + ['payload-manifest.json'] if payload else
                 ['device/native.py', 'device/profiles.py', 'device/device_info.py', 'device/compatibility.py'])
        names += ['profile-request.json', 'stage-cleanup.py']
        local_request = ROOT / 'private' / ('profile-stage-' + uuid.uuid4().hex + '.json')
        local_request.parent.mkdir(parents=True, exist_ok=True)
        local_request.write_bytes(profiles.canonical(self.request))
        created = False
        completed = False
        try:
            self.progress('connection', 'working')
            self.remote('test ! -e ' + shlex.quote(path) + ' && mkdir -m 700 ' + shlex.quote(path) +
                        ' && mkdir ' + shlex.quote(path + '/device') + ' ' + shlex.quote(path + '/driver'))
            created = True
            self.progress('connection', 'done')
            self.progress('transfer', 'working')
            for name in names:
                source = (local_request if name == 'profile-request.json' else
                          ROOT / 'tools/stage_cleanup.py' if name == 'stage-cleanup.py' else
                          ROOT / (MANIFEST if name == 'payload-manifest.json' else name))
                self.process([self.scp, '-O', '-q'] + self.options + [str(source), self.host + ':' + path + '/' + name], 40)
            self.progress('transfer', 'done')
            yield path
            completed = True
        finally:
            local_request.unlink(missing_ok=True)
            if created and not completed:
                # A timed-out SSH child may still be reading this stage. Never
                # remove its inputs or retry a write while the outcome is unknown.
                self.progress('stage_cleanup', 'pending')
            if created and completed:
                try:
                    # BB10 lacks a shell rmdir. The helper verifies the exact
                    # generated tree first, then uses unlink / os.rmdir only.
                    result = self.execute(path + '/stage-cleanup.py', shlex.quote(json.dumps(names)))
                    if result.get('stage_removed') is not True:
                        raise WorkflowError('stage_cleanup_not_verified')
                except WorkflowError:
                    self.progress('stage_cleanup', 'pending')

    def inspect_stage(self, path):
        self.progress('preflight', 'working')
        report = self.execute(path + '/device/compatibility.py', '--request ' + shlex.quote(path + '/profile-request.json'))
        if report.get('schema') != 2 or report.get('profile_sha256') != profiles.fingerprint(self.request):
            raise WorkflowError('invalid_device_response')
        self.progress('preflight', 'done')
        return report

    def preflight(self):
        with self.stage() as path:
            return self.inspect_stage(path)

    def service(self, action):
        if action not in ('status', 'start', 'stop'):
            raise WorkflowError('invalid_action')
        result = self.remote('/proc/boot/pathtrust ' + shlex.quote('!' + BASE + '/device/run.sh') +
                             ' && /bin/sh ' + shlex.quote(BASE + '/device/run.sh') + ' ' + action, 120)
        try:
            return json.loads(result)
        except ValueError:
            raise WorkflowError('invalid_device_response') from None

    def install(self, mode='install', start=False):
        if mode not in ('install', 'update'):
            raise WorkflowError('invalid_action')
        with self.stage(payload=True) as path:
            report = self.inspect_stage(path)
            if not report.get('can_' + mode):
                raise WorkflowError('preflight_blocked', report)
            self.progress('install', 'working')
            installed = self.execute(path + '/device/install.py', mode + ' ' + shlex.quote(path), 120)
            if installed.get('installed') is not True:
                raise WorkflowError('installation_not_verified')
            self.progress('install', 'done')
            self.progress('verify', 'working')
            after = self.inspect_stage(path)
            if (after['installation'].get('payload_verified') is not True or
                    after['installation'].get('version') != verify_package()['version'] or
                    after['installation'].get('carrier_profile_sha256') != profiles.fingerprint(self.request) or
                    after['installation']['state'] != 'stopped'):
                raise WorkflowError('installation_not_verified', after)
            self.progress('verify', 'done')
        result = {'installed': True, 'mode': mode, 'preflight': after, 'call_acceptance': 'pending'}
        if start:
            result.update(self.action('start'))
        return result

    def wait_registration(self, timeout=None):
        timeout = self.profile['runtime']['registration_wait_seconds'] if timeout is None else timeout
        deadline = time.monotonic() + timeout
        self.progress('registration', 'working')
        state = {}
        while time.monotonic() < deadline:
            state = public_status(self.service('status'))
            if registered(state):
                self.progress('registration', 'done')
                return {'registration': 'verified', 'status': state, 'call_acceptance': 'pending'}
            if state['phase'] in ('error', 'error_restored', 'cleanup_required', 'native_exited'):
                raise WorkflowError('service_needs_attention', state)
            time.sleep(self.profile['runtime']['poll_seconds'])
        self.progress('registration', 'pending')
        return {'registration': 'pending', 'status': state, 'call_acceptance': 'pending'}

    def action(self, action):
        if action == 'collect':
            return self.collect()
        if action not in ('status', 'start', 'stop', 'enable', 'disable', 'uninstall'):
            raise WorkflowError('invalid_action')
        report = self.preflight()
        installed = report['installation']['state']
        if installed not in ('stopped', 'busy', 'recovery_required'):
            raise WorkflowError('installation_needs_inspection', report)
        if action == 'status':
            result = public_status(self.service('status'))
            return {'status': result, 'registered': registered(result), 'preflight': report}
        if action in ('start', 'enable'):
            if report['installation'].get('carrier_profile_sha256') != profiles.fingerprint(self.request):
                raise WorkflowError('profile_update_required', report)
            if not report.get('can_start'):
                if action == 'start' and installed == 'busy':
                    state = public_status(self.service('status'))
                    return {'status': state, 'registration': 'verified' if registered(state) else 'pending',
                            'already_started': True, 'call_acceptance': 'pending'}
                raise WorkflowError('preflight_blocked', report)
            self.progress('start', 'working')
            if action == 'enable' or self.profile['runtime']['autostart']:
                self.execute(BASE + '/device/install.py', 'enable')
            if action == 'enable':
                self.progress('start', 'done')
                return {'enabled': True}
            self.service('start')
            self.progress('start', 'done')
            return self.wait_registration()
        self.progress('restore', 'working')
        if action in ('disable', 'uninstall'):
            self.execute(BASE + '/device/install.py', action, 270)
        else:
            self.service('stop')
            deadline = time.monotonic() + 130
            while time.monotonic() < deadline:
                status = public_status(self.service('status'))
                if not status['manager_alive']:
                    break
                time.sleep(2)
            else:
                raise WorkflowError('restore_pending')
        after = self.preflight()
        clean = next(c for c in after['checks'] if c['id'] == 'baseline')['status'] == 'pass'
        if not clean or (action != 'uninstall' and after['installation']['state'] != 'stopped'):
            raise WorkflowError('restore_needs_inspection', after)
        self.progress('restore', 'done')
        return {'action': action, 'restored': True, 'preflight': after}

    def collect(self):
        folder = ROOT / 'private' / datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        folder.mkdir(parents=True, exist_ok=False, mode=0o700)
        if sys.platform == 'win32':
            account = subprocess.check_output(['whoami'], text=True, creationflags=CREATE_NO_WINDOW).strip()
            self.process(['icacls', str(folder), '/inheritance:r', '/grant:r',
                          account + ':(OI)(CI)F', 'SYSTEM:(OI)(CI)F'], 20)
        self.process([self.scp, '-O', '-q', '-r'] + self.options + [self.host + ':' + BASE + '/state', str(folder)], 60)
        self.process([self.scp, '-O', '-q'] + self.options + [self.host + ':' + BASE + '/installation.json', str(folder / 'installation.json')], 30)
        return {'private_logs_saved': str(folder), 'share_publicly': False}
