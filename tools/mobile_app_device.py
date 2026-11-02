"""Native QNX-only BAR provisioning agent. Python 3.2; no wireless operations.

The trusted desktop uploads this fixed helper and its pinned release descriptor
to a private directory. Android processes never invoke this agent or __root.
"""
import contextlib
try:
    import fcntl
except ImportError:  # Host-only manifest parsing/tests on Windows.
    fcntl = None
import hashlib
import json
import os
import re
import stat
import struct
import subprocess
import sys
import time
import zipfile

BASE = '/var/bb10_volte-app-install'
APP_ROOT = '/apps'
INSTALLER = '/var/rootdata/installer'
PPS = '/pps/system/installer/upd/current'
TERMINAL = ('completed', 'failed', 'conflict')


class InstallError(Exception):
    pass


def require(condition, code):
    if not condition:
        raise InstallError(code)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular(path, limit=16777216, private=False):
    info = os.lstat(path)
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
            os.path.realpath(path) == path and info.st_size <= limit, 'unsafe_file')
    if private:
        require(info.st_uid == os.geteuid() and info.st_mode & 0o077 == 0, 'unsafe_private_file')
    with open(path, 'rb') as stream:
        data = stream.read(limit + 1)
    require(len(data) == info.st_size and len(data) <= limit, 'file_changed')
    return data


def private_directory(path, create=False):
    if create and not os.path.lexists(path):
        os.mkdir(path, 0o700)
    info = os.lstat(path)
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid() and
            info.st_mode & 0o077 == 0 and os.path.realpath(path) == path, 'unsafe_private_directory')


def load(path):
    return json.loads(regular(path, 131072, True).decode('ascii'))


def save(path, value):
    temporary = path + '.tmp-' + nonce()[:16]
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii'))
        stream.flush()
        os.fsync(stream.fileno())
    os.rename(temporary, path)
    # QNX6 fsync commits a filesystem snapshot. Commit after rename as well:
    # flushing the temporary inode alone does not commit the active pointer.
    # QNX fsync requires a descriptor opened for writing (no truncation).
    descriptor = os.open(path, os.O_WRONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def nonce():
    import binascii
    return binascii.hexlify(os.urandom(16)).decode('ascii')


def operation_id(value):
    require(isinstance(value, str) and re.match(r'\A[a-f0-9]{32}\Z', value), 'invalid_operation')
    return value


def version(value):
    require(isinstance(value, str) and re.match(r'\A[0-9]{1,5}(?:\.[0-9]{1,5}){3}\Z', value), 'invalid_version')
    return tuple(int(part) for part in value.split('.'))


def headers(raw):
    values = {}
    for line in raw.decode('utf-8').splitlines():
        if not line:
            continue
        if ': ' in line and not line.startswith(' '):
            key, value = line.split(': ', 1)
            if key.startswith(('Package-', 'Application-')):
                require(key not in values, 'ambiguous_app_identity')
                values[key] = value
    return values


def installed(release):
    matches = [name for name in os.listdir(APP_ROOT) if name.startswith(release['identity']['Package-Name'] + '.')]
    if not matches:
        return {'state': 'absent', 'can_install': True}
    require(len(matches) == 1, 'app_identity_conflict')
    path = APP_ROOT + '/' + matches[0]
    require(os.path.realpath(path) == path and os.path.isdir(path), 'app_identity_conflict')
    raw = regular(path + '/META-INF/MANIFEST.MF', 131072)
    info = headers(raw)
    for key, expected in release['identity'].items():
        if key not in ('Package-Version', 'Application-Version'):
            require(info.get(key) == expected, 'app_identity_conflict')
    current = version(info.get('Package-Version'))
    target = version(release['version'])
    require(info.get('Application-Version') == info.get('Package-Version'), 'app_identity_conflict')
    if current > target:
        return {'state': 'newer_installed', 'can_install': False, 'version': info['Package-Version']}
    if current < target:
        return {'state': 'upgrade_available', 'can_install': True, 'version': info['Package-Version']}
    require(digest(raw) == release['platform_manifest_sha256'], 'same_version_conflict')
    # SUD success and a matching metadata file cannot substitute for actual
    # native executable/QML/runtime byte verification.
    for member, expected in release['installed_files'].items():
        require(member.startswith(('native/', 'META-INF/')) and '..' not in member.split('/') and
                '\\' not in member, 'invalid_release')
        blob = regular(path + '/' + member, expected['size'] + 1)
        require(len(blob) == expected['size'] and digest(blob) == expected['sha256'], 'same_version_conflict')
    return {'state': 'installed', 'can_install': False, 'version': info['Package-Version'],
            'all_files_verified': True}


@contextlib.contextmanager
def locked():
    require(fcntl is not None, 'native_lock_unavailable')
    path = BASE + '/lock'
    if os.path.lexists(path):
        regular(path, 64, True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.lockf(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            raise InstallError('app_install_busy')
        yield
    finally:
        os.close(descriptor)


def job_path(identifier):
    return BASE + '/jobs/' + operation_id(identifier)


def current_job():
    pointer = BASE + '/active.json'
    if not os.path.lexists(pointer):
        # A lost pointer must not erase a prior submitted operation. Keep
        # orphan records observable; never infer permission to install again.
        pending = []
        for identifier in os.listdir(BASE + '/jobs'):
            directory = job_path(identifier)
            private_directory(directory)
            path = directory + '/record.json'
            if os.path.lexists(path) and load(path).get('state') != 'completed':
                pending.append(identifier)
        require(len(pending) <= 1, 'orphaned_install_records')
        if not pending:
            return None
        identifier = pending[0]
    else:
        identifier = operation_id(load(pointer)['id'])
    directory = job_path(identifier)
    private_directory(directory)
    value = load(directory + '/record.json')
    require(value['id'] == identifier and value['owner'] == 'bb10-volte-app-installer-v1', 'job_record_changed')
    require(value['sud_job'] == PPS + '/job.bb10-volte-app-' + identifier, 'job_record_changed')
    return value


def read_pps(path):
    # PPS objects are live snapshots, not disk files: st_size/nlink and the
    # length of a later read are not an integrity contract. Never use ?wait.
    require(path.startswith('/pps/') and '?' not in path and os.path.realpath(path) == path and
            not os.path.islink(path), 'unsafe_pps_path')
    descriptor = os.open(path, os.O_RDONLY)
    try:
        raw = os.read(descriptor, 131073)
    finally:
        os.close(descriptor)
    require(len(raw) <= 131072, 'pps_response_too_large')
    return raw.decode('utf-8')


def pps(path):
    if not os.path.lexists(path):
        return {}
    raw = read_pps(path)
    return dict(line.split('::', 1) for line in raw.splitlines() if '::' in line)


def reconcile(job, release):
    if not job or job['state'] in TERMINAL:
        return job
    require(job['bar_sha256'] == release['bar_sha256'], 'pending_release_differs')
    values = pps(job['sud_job'])
    # No PPS result after disconnect/reboot never authorizes resubmission.
    if not values.get('result'):
        return job
    if values['result'] != 'success':
        job.update(state='failed', error='sud_install_failed')
    else:
        identity = release['identity']
        expected = {'actual_name': identity['Package-Name'], 'actual_id': identity['Package-Id'],
                    'actual_author_id': identity['Package-Author-Id'], 'actual_version': release['version']}
        if any(values.get(key) != value for key, value in expected.items()):
            job.update(state='conflict', error='sud_identity_mismatch')
        else:
            try:
                result = installed(release)
                require(result.get('all_files_verified') is True, 'registered_app_mismatch')
                job.update(state='completed', error=None, sud_success=True, all_files_verified=True)
            except (InstallError, OSError, ValueError):
                job.update(state='conflict', error='registered_app_mismatch')
    job['updated'] = int(time.time())
    save(job_path(job['id']) + '/record.json', job)
    return job


def summary(release, device_id, job=None):
    try:
        app = installed(release)
    except (InstallError, OSError, ValueError) as error:
        app = {'state': 'conflict', 'can_install': False,
               'error': str(error) if isinstance(error, InstallError) else 'app_read_failed'}
    if job and job['state'] != 'completed':
        app.update(state='pending' if job['state'] not in TERMINAL else job['state'], can_install=False)
    if app.get('can_install'):
        try:
            require(digest(regular(INSTALLER, 1048576)) == release['installer_sha256'], 'installer_unverified')
        except (OSError, InstallError):
            app.update(state='error', error='installer_unverified', can_install=False)
    if job:
        app['job'] = dict((key, job.get(key)) for key in ('id', 'state', 'error', 'target_version', 'sud_success', 'all_files_verified'))
    properties = read_pps('/pps/services/deviceproperties')
    model = re.search(r'^modelnumber::([A-Za-z0-9-]{1,40})$', properties, re.M)
    app.update(schema=1, device_id=device_id, variant=model.group(1) if model else 'unknown',
               target_version=release['version'], root_verified=True)
    return app


def provision(release, stage, identifier, expected_device):
    identifier = operation_id(identifier)
    with locked():
        device = load(BASE + '/device.json')['id']
        require(device == expected_device, 'device_changed')
        prior = reconcile(current_job(), release)
        require(not prior or prior['state'] == 'completed', 'app_install_unresolved')
        before = installed(release)
        if before['state'] == 'installed':
            return summary(release, device, prior)
        require(before['can_install'], 'newer_app_installed')
        installer_bytes = regular(INSTALLER, 1048576)
        require(digest(installer_bytes) == release['installer_sha256'], 'installer_unverified')
        bar = regular(stage + '/application.bar', release['bar_size'] + 1, True)
        require(len(bar) == release['bar_size'] and digest(bar) == release['bar_sha256'], 'bar_hash_mismatch')
        directory = job_path(identifier)
        require(not os.path.lexists(directory), 'operation_already_exists')
        private_directory(directory, True)
        executable = directory + '/native-installer'
        descriptor = os.open(executable, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(installer_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        require(digest(regular(executable, 1048576, True)) == release['installer_sha256'], 'installer_snapshot_changed')
        with open('/dev/null', 'wb') as sink:
            require(subprocess.call(['/proc/boot/pathtrust', '!' + executable], stdout=sink, stderr=sink) == 0,
                    'installer_pathtrust_failed')
        package_id = 'bb10-volte-app-' + identifier
        package = directory + '/package.zip'
        # Only these two members are ever fed to the generic AutoRoot installer.
        # No addon, patch, permissions or startup script is accepted from a file.
        manifest = ('Package-Id: ' + package_id + '\nPackage-Name: BB10 VoLTE\nPackage-Version: ' + release['version'] + '\n').encode('ascii')
        with zipfile.ZipFile(package, 'w', zipfile.ZIP_STORED) as archive:
            archive.writestr('MANIFEST', manifest)
            archive.writestr('pkg.bar', bar)
        os.chmod(package, 0o600)
        job = {'schema': 1, 'owner': 'bb10-volte-app-installer-v1', 'id': identifier,
               'device_id': device, 'bar_sha256': release['bar_sha256'], 'target_version': release['version'],
               'sud_job': PPS + '/job.' + package_id, 'state': 'submitted', 'created': int(time.time()),
               'sud_success': False, 'all_files_verified': False}
        require(not os.path.lexists(job['sud_job']), 'sud_job_exists')
        require(not os.path.lexists('/var/addons/' + package_id), 'addon_path_exists')
        save(directory + '/record.json', job)
        save(BASE + '/active.json', {'id': identifier})
        # From this durable point onward, even launch failure is reconciled
        # rather than retried. The detached native installer can finish if SSH
        # disappears; its private inputs remain available for that same job.
        with open(directory + '/installer.log', 'wb') as log, open('/dev/null', 'rb') as source:
            try:
                environment = {'PATH': '/proc/boot:/bin:/usr/bin:/base/bin:/base/usr/bin',
                               'LD_LIBRARY_PATH': '/base/usr/lib:/base/lib:/base/lib/dll:/radio/lib:/radio/lib/dll:/radio/usr/lib:/proc/boot'}
                process = subprocess.Popen([executable, package], stdin=source, stdout=log, stderr=log,
                                           close_fds=True, preexec_fn=os.setsid, env=environment)
                job['installer_pid'] = process.pid
                save(directory + '/record.json', job)
                # Do not hold the transaction lock for an unbounded installer
                # lifetime. A stalled child remains the same submitted job;
                # later inspection can reconcile its PPS result independently.
                # Use a bounded count: Python 3.2 has no monotonic clock.
                for unused in range(30):
                    if process.poll() is not None:
                        break
                    time.sleep(0.25)
                job['installer_exit'] = process.poll()
            except OSError:
                job['error'] = 'installer_start_unknown'
            save(directory + '/record.json', job)
        return summary(release, device, reconcile(job, release))


def main():
    require(os.geteuid() == 0 and os.uname()[0] == 'QNX' and struct.calcsize('P') == 4, 'root_qnx_required')
    require(regular('/etc/os.version', 128).strip() == b'10.3.3.3216', 'os_not_supported')
    stage = os.path.dirname(os.path.abspath(__file__))
    require(re.match(r'\A/var/bb10_volte_app_stage_[a-f0-9]{32}\Z', stage), 'invalid_stage')
    private_directory(stage)
    release = load(stage + '/release.json')
    require(release.get('schema') == 1 and release['identity']['Package-Name'] == 'com.octolab.bb10volte', 'invalid_release')
    version(release['version'])
    private_directory(BASE, True)
    private_directory(BASE + '/jobs', True)
    if not os.path.lexists(BASE + '/device.json'):
        with locked():
            if not os.path.lexists(BASE + '/device.json'):
                save(BASE + '/device.json', {'id': nonce()})
    device_id = operation_id(load(BASE + '/device.json')['id'])
    require(len(sys.argv) >= 2 and sys.argv[1] in ('inspect', 'install'), 'invalid_action')
    if sys.argv[1] == 'install':
        require(len(sys.argv) == 4, 'invalid_request')
        return provision(release, stage, sys.argv[2], sys.argv[3])
    require(len(sys.argv) == 2, 'invalid_request')
    try:
        with locked():
            job = reconcile(current_job(), release)
    except InstallError as error:
        if str(error) != 'app_install_busy':
            raise
        job = current_job()
    return summary(release, device_id, job)


def cleanup_stage():
    stage = os.path.dirname(os.path.abspath(__file__))
    require(re.match(r'\A/var/bb10_volte_app_stage_[a-f0-9]{32}\Z', stage), 'invalid_stage')
    private_directory(stage)
    names = set(os.listdir(stage))
    require({'agent.py', 'release.json'} <= names <= {'agent.py', 'release.json', 'application.bar'}, 'stage_changed')
    for name in names:
        regular(stage + '/' + name, private=True)
    for name in names:
        os.unlink(stage + '/' + name)
    os.rmdir(stage)


if __name__ == '__main__':
    os.umask(0o077)
    try:
        result = main()
        cleanup_stage()
        result['stage_removed'] = True
        print(json.dumps(result, sort_keys=True))
    except Exception as error:
        print(json.dumps({'schema': 1, 'state': 'error', 'can_install': False,
                          'error': str(error) if isinstance(error, InstallError) else 'app_install_check_failed'}))
