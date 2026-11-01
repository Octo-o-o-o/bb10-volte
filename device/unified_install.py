"""Two-phase installer shared by the Windows and macOS desktop programs."""
import ctypes
import binascii
import contextlib
import errno
import hashlib
import json
import os
import re
import stat
import sys
import time
import native as n
import profiles
import device_info
import carrier_policy as policy
import service as s
import unified_service as u
import unified_migrate as migration
import telecom_dca as dca
import telecom_native as radio

BASE = policy.BASE
MANAGEMENT = '/var/bb10_volte-management'
MANAGEMENT_SCHEMA = 2
_lock_depth = 0
_lock_pid = None
PREVIOUS_PAYLOADS = ('f1575fe455b23edac0ce0a315ec3d4b364d668df65fae213e5aaa9404270580f',
                    'b7ee1d25881b3334fbeb5179a4dfd2d24cb0394de9901311543c1dc713242294',
                    'ae6527a3324d7745751776cae35cb02cb5e088406fb3ee8a55bad215c438e3da',
                    '99ff0c8b1c3118bbb15b0177a9177e2f592b4d0711fb1c59698eddfb3942b4f2',
                     '69820d4e94e09adbf71078eb8d1b2f6c946303424001e0d3760b530c2cd1f318',
                     'bab5ee0e0496b8694265b9df3300e140bf44a3433e0fdf65ac56420d3066fddc',
                     '7352686da4a229135d7685ffc58c2aae8b1c5c588bcb72fe733799b2336b3a90',
                     '4f92bfe1a7182b1b03f0aa875b864c27e15572b5d9a06aa5d8503d3f2cbab99b',
                     '93ed64504ccf1845bce246e35dbbeea9a04912c72ceb005be2f863a3ffa222a5',
                     '5c2d9d893f88d40b6fde943f85722471da8cd3aa3a61ece7e403e03a48c84943',
                     'e179d971012e0013caf692fc51273c4f62ebaab861af1e36570400515c02382f',
                     'a9a1609e31b8477e01c2c30511b6dfdc5914a4df5bff521f227f3deab77a963b',
                     'f0c4a5002dc41b8de7113db680936240d564e87ddae67793b79e27a45e8c9a2f',
                     '7de370bc3b3a9a646714336aa5e45de89026a50012e986f43a0d228d6dc638ff',
                     '40b98d3bab3f36d1e550b42db3f45185b0a179e64da96f8cc870af4a561cd9cc')
UPDATE_FILES = ('device/unified_dca.py', 'device/unified_install.py',
                'device/unified_service.py', 'device/carrier_policy.py', 'device/unified_own_number.py',
                'device/service.py', 'device/ims_image.py', 'device/profiles.py', 'device/compatibility.py')
UPDATE_PENDING = BASE + '/update-pending.json'
ADDON = '/var/addons/bb10-unified-volte'
BTOOL = '/apps/sys.android.gYABgKAOw1czN6neiAT72SGO.ns/native/system/xbin/btool'
ROOT_V2_HASHES = ('d56cdb880878198f8fc3d5114313d3f0c880136a9bde6bdc2faecb63da098cc4',
                  'bdcd111afbbfe802e4489a85a4c6eb2e0ba0b8dbe8a429f01ea88045e8b4d501')
HOOK = (b'\n# bb10-unified-carriers-v1\n'
        b'if [ -f /var/bb10_volte/enabled ]; then\n'
        b'    ( /proc/boot/pathtrust !/var/bb10_volte/device/unified_boot.sh && '
        b'/bin/sh /var/bb10_volte/device/unified_boot.sh ) &\nfi\n')


def nonce():
    return binascii.hexlify(os.urandom(16)).decode('ascii')


def persist(path, raw, mode=0o600):
    """Use the phone atomic primitive, with equivalent replacement on Windows.

    Device operations still require QNX identity. This fallback allows desktop
    fault-injection tests to exercise the same journal on real temporary files.
    """
    try:
        n.atomic(path, raw, mode)
    except OSError as error:
        if os.name != 'nt' or getattr(error, 'winerror', None) != 183:
            raise
        assert not os.path.islink(path) and not os.path.islink(path + '.new')
        assert n.read(path + '.new') == raw
        os.replace(path + '.new', path)


def safe_id(value):
    assert isinstance(value, str) and re.match(r'\A[a-f0-9]{32}\Z', value), 'invalid_operation_id'
    return value


def unlinked_path(path):
    return (not os.path.islink(path) and os.path.normcase(os.path.realpath(path)) ==
            os.path.normcase(os.path.abspath(path)))


def private_directory(path):
    assert os.path.realpath(path) == path and not os.path.islink(path), 'management_path_changed'
    if not os.path.lexists(path):
        try:
            os.mkdir(path, 0o700)
        except OSError as error:
            if error.errno != errno.EEXIST:
                raise
    info = os.lstat(path)
    assert stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid(), 'management_owner_changed'
    assert info.st_mode & 0o077 == 0, 'management_permissions_changed'


@contextlib.contextmanager
def management_lock(blocking=False):
    """One permanent lock inode, outside the removable installation directory.

    QNX/POSIX record locks are released by the kernel on process exit. Never
    unlink this file, including during uninstall. A fork must acquire its own
    lock; an inherited Python depth counter is not ownership.
    """
    global _lock_depth, _lock_pid
    pid = os.getpid()
    if _lock_pid == pid and _lock_depth:
        _lock_depth += 1
        try:
            yield
        finally:
            _lock_depth -= 1
        return
    import fcntl
    assert os.geteuid() == 0, 'root_required'
    private_directory(MANAGEMENT)
    path = MANAGEMENT + '/lock'
    assert not os.path.islink(path), 'management_lock_changed'
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        opened, current = os.fstat(fd), os.lstat(path)
        assert stat.S_ISREG(opened.st_mode) and opened.st_uid == 0 and opened.st_nlink == 1
        assert opened.st_mode & 0o077 == 0 and (opened.st_dev, opened.st_ino) == (current.st_dev, current.st_ino)
        try:
            fcntl.lockf(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except IOError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN):
                raise RuntimeError('management_busy')
            raise
        _lock_pid, _lock_depth = pid, 1
        try:
            yield
        finally:
            _lock_depth, _lock_pid = 0, None
            fcntl.lockf(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def device_binding(create=False):
    path = MANAGEMENT + '/device.json'
    if create and not os.path.lexists(path):
        persist(path, profiles.canonical({'owner': policy.OWNER, 'id': nonce()}))
    value = s.load(path)
    assert value['owner'] == policy.OWNER and not os.path.islink(path), 'device_binding_changed'
    return safe_id(value['id'])


def management_identity(facts, create=False, engine_schema=2):
    path = BASE + '/management.json'
    if create and not os.path.lexists(path):
        persist(path, profiles.canonical({'schema': 2, 'owner': policy.OWNER,
            'installation_id': nonce(), 'variant': facts['variant'], 'engine_schema': engine_schema, 'device': device_binding(True)}))
    value = s.load(path)
    assert value['schema'] == 2 and value['owner'] == policy.OWNER
    safe_id(value['installation_id'])
    assert value['variant'] == facts['variant'] and value['device'] == device_binding(), 'installation_device_changed'
    return value


def validate_backup_receipt(receipt, backup, manifest_hash, installation_id=None):
    assert isinstance(receipt, dict) and receipt.get('owner') == policy.OWNER, 'backup_receipt_owner'
    assert receipt.get('all_original_hashes_verified') is True, 'backup_not_verified'
    assert receipt.get('backup_manifest_sha256') == manifest_hash, 'backup_receipt_changed'
    if receipt.get('schema') == 2:
        assert receipt.get('installation_id') == installation_id, 'backup_installation_changed'
        safe_id(receipt.get('operation_id'))
        assert receipt.get('variant') == backup['variant'], 'backup_device_changed'
        assert receipt.get('files') == backup['files'] and receipt.get('readback') == backup['files'], 'backup_readback_incomplete'
        target = receipt.get('destination')
        assert isinstance(target, dict) and set(target) == {'type', 'id'}, 'backup_destination_invalid'
        assert isinstance(target['id'], str) and 0 < len(target['id']) <= 1024
        assert not any(ord(c) < 32 for c in target['id']), 'backup_destination_invalid'
        allowed = {'desktop': ('desktop',), 'mobile': ('same_device', 'removable')}
        assert receipt.get('source') in allowed and target['type'] in allowed[receipt['source']], 'backup_source_invalid'
    else:
        assert 'schema' not in receipt or receipt['schema'] == 1, 'backup_schema_unsupported'
    return receipt


def verify_backup_receipt():
    raw = n.read(BASE + '/backup/manifest.json')
    backup = json.loads(raw.decode('ascii'))
    assert backup['owner'] == policy.OWNER
    required = set(name + '.original' for name in dca.SOURCES)
    assert set(backup['files']) in (required, required | {'btool.original'}), 'backup_members_incomplete'
    for name, expected in backup['files'].items():
        assert re.match(r'\A(?:ims|ims_defaults|omadm|test|btool)\.original\Z', name), 'backup_member_invalid'
        assert not os.path.islink(BASE + '/backup/' + name)
        assert n.digest(n.read(BASE + '/backup/' + name)) == expected, 'original_backup_changed'
    path = BASE + '/backup-receipt.json'
    if os.path.lexists(path):
        assert not os.path.islink(path), 'backup_receipt_changed'
        value = s.load(path)
        assert value.get('schema') == 2, 'backup_schema_unsupported'
        identity_value = management_identity({'variant': backup['variant']})
        return validate_backup_receipt(value, backup, n.digest(raw), identity_value['installation_id'])
    # Historic receipts are read under their actual desktop name and provenance.
    return validate_backup_receipt(s.load(BASE + '/desktop-backup-receipt.json'), backup, n.digest(raw))


def record_backup_receipt(receipt):
    facts, unused = identity()
    assert os.path.isfile(BASE + '/payload.json') and not os.path.isfile(BASE + '/uninstalled.json'), 'installation_uninstalled'
    identity_value = management_identity(facts)
    raw = n.read(BASE + '/backup/manifest.json')
    backup = json.loads(raw.decode('ascii'))
    assert receipt.get('schema') == 2, 'backup_schema_unsupported'
    validate_backup_receipt(receipt, backup, n.digest(raw), identity_value['installation_id'])
    for name, expected in backup['files'].items():
        assert '/' not in name and '\\' not in name and not os.path.islink(BASE + '/backup/' + name)
        assert n.digest(n.read(BASE + '/backup/' + name)) == expected, 'original_backup_changed'
    persist(BASE + '/backup-receipt.json', profiles.canonical(receipt))
    verify_backup_receipt()
    return {'backup_verified': True, 'backup_source': receipt['source'], 'installation_id': identity_value['installation_id']}


def identity():
    assert os.geteuid() == 0 and os.uname()[0] == 'QNX' and ctypes.sizeof(ctypes.c_void_p) == 4
    facts = device_info.read_identity()
    family = policy.model(facts)
    assert device_info.identify(facts)['identity_conflict'] is False
    u.verify_native()
    return facts, family


def addon_parent(create=False):
    parent = os.path.dirname(ADDON)
    # Fresh AutoRoot v4 has no addon directory until the first addon is installed.
    # Probe stays read-only; activation may create only this missing directory.
    assert os.path.realpath(parent) == parent and not os.path.islink(parent), 'root_addon_directory_changed'
    if os.path.lexists(parent):
        assert os.path.isdir(parent), 'root_addon_directory_changed'
    elif create:
        os.mkdir(parent, 0o755)
    return parent


def root_kind(facts):
    if os.path.isfile('/tmp/root.done'):
        addon_parent()
        return 'autoroot-v4'
    assert facts['variant'] == 'SQC100-2' and not os.path.islink(BTOOL), 'root_scheme_not_supported'
    assert n.digest(n.read(BTOOL)) in ROOT_V2_HASHES, 'root_boot_script_changed'
    return 'autoroot-v2'


def blocked_probe(observed, code):
    variant = observed.get('variant')
    if not isinstance(variant, str) or not re.match(r'\ASQ[NCW]100-[0-9]{1,2}\Z', variant):
        variant = 'unknown'
    return {'schema': 1, 'variant': variant, 'scope_error': code,
            'installed': False, 'can_install': False, 'can_update': False,
            'sim_supported': False}


def probe():
    # Report model/OS limits before native probing, legacy migration or backups.
    # This path is read-only and never grants an unknown model permission.
    assert os.geteuid() == 0 and os.uname()[0] == 'QNX' and ctypes.sizeof(ctypes.c_void_p) == 4
    observed = device_info.read_identity()
    try:
        policy.model(observed)
    except ValueError as error:
        code = ('os_not_supported' if observed.get('variant') in policy.MODELS and
                observed.get('os_version') != policy.OS_VERSION else str(error))
        return blocked_probe(observed, code)
    try:
        facts, family = identity()
    except AssertionError as error:
        if str(error) != 'unknown_native_image':
            raise
        return blocked_probe(observed, 'unknown_native_image')
    for filename in ('uninstall-pending.json', 'uninstalled.json'):
        if os.path.isfile(BASE + '/' + filename):
            pending = s.load(BASE + '/' + filename)
            assert pending['owner'] == policy.OWNER
            finished = filename == 'uninstalled.json' and pending['uninstalled'] is True
            phase = 'uninstalled' if finished else pending.get('phase', 'awaiting_final_reboot')
            result = {'schema': 1, 'management_schema': 2, 'variant': facts['variant'], 'family': family,
                'os_version': facts['os_version'], 'installed': os.path.isfile(BASE + '/payload.json'),
                'installed_stage': 'uninstalled' if finished else 'pending', 'installed_management_schema': 2,
                'phase': phase, 'pending_phase': phase, 'uninstalled': finished, 'can_install': finished,
                'can_update': False, 'reboot_required': not finished and phase in ('awaiting_reboot', 'awaiting_final_reboot')}
            return with_sim_status(result, facts) if finished else result
    result = {'schema': 1, 'management_schema': 2,
              'installed_management_schema': installed_management_schema(),
              'variant': facts['variant'], 'family': family, 'os_version': facts['os_version'],
              'installed': os.path.isfile(BASE + '/payload.json'), 'call_idle': s.phone_idle(),
              'normal_reboot_after_sim_change': True, 'validation': 'candidate_pending_device_acceptance'}
    result['installed_stage'] = 'managed' if result['installed_management_schema'] == 2 else 'legacy'
    if not result['installed']:
        result['installed_stage'] = 'uninstalled' if os.path.isfile(BASE + '/uninstalled.json') else 'absent'
    if result['installed']:
        result['installation_pending'] = os.path.isfile(BASE + '/install-pending.json')
        if result['installation_pending']:
            result['installed_stage'] = 'pending'
            pending = s.load(BASE + '/install-pending.json')
            result['pending_phase'] = pending['phase']
            result['can_install'] = pending['phase'] in ('awaiting_desktop_backup', 'awaiting_backup', 'activating') and result['call_idle']
            result['installation_id'] = pending.get('installation_id')
        else:
            u.setup()
            current = s.load(BASE + '/payload.json')
            candidate = s.load(os.path.dirname(os.path.dirname(__file__)) + '/payload.json')
            pending = s.load(UPDATE_PENDING) if os.path.isfile(UPDATE_PENDING) else None
            result['update_pending'] = pending is not None
            if pending is None:
                result['status'] = u.public_status()
            else:
                assert pending['owner'] == policy.OWNER and pending['after'] == candidate
                raw = s.read_status() if u.boot_token(False) is not None else {}
                result['status'] = {k: raw.get(k) for k in ('phase', 'enabled', 'manager_alive',
                    'native_alive', 'status_from_current_boot', 'current')}
            known = n.digest(profiles.canonical(current['files'])) in PREVIOUS_PAYLOADS
            result['update_available'] = known and current['files'] != candidate['files'] or pending is not None
            finished = pending is not None and pending['phase'] == 'files_verified'
            result['can_update'] = bool(result['update_available'] and (finished or
                result['call_idle'] and not result['status'].get('manager_alive') and
                n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}))
            if result['installed_management_schema'] == 1 and os.path.isfile(BASE + '/enabled'):
                result['can_update'] = False
    else:
        result['root_kind'] = root_kind(facts)
        entry = migration.inspect(facts)
        result['legacy_detected'] = entry is not None
        result['can_install'] = result['call_idle']
    return with_sim_status(result, facts)


def with_sim_status(result, facts):
    try:
        selection = policy.select(facts, u.card())
        result['operator'] = selection['operator']
        profile = selection['request']['profile']
        template, unused = profiles.carrier_template(profile, '460', profile['carrier']['mncs'][0])
        result['stock_template_verified'] = True
        result['stock_template'] = template
        result['sim_supported'] = True
    except ValueError as error:
        result['sim_supported'], result['sim_reason'] = False, str(error)
        result['can_install'] = False
    return result


def update(stage):
    """Upgrade only a known inactive Python payload; retain its backup.

    The boot marker is removed before replacing bytes, and the new manifest is
    written last. A stopped partial update resumes only its recorded old/new
    hashes. Native binaries, original DCA backups and boot hooks never change.
    """
    facts, unused = identity()
    assert re.match(r'\A/var/bb10_auto_stage_[a-f0-9]{12}\Z', stage) and os.path.realpath(stage) == stage
    after = s.load(stage + '/payload.json')
    assert after['owner'] == policy.OWNER and after['schema'] == 1
    assert set(after['files']) == set(u.PAYLOAD_FILES)
    for name, expected in after['files'].items():
        assert not os.path.islink(stage + '/' + name) and n.digest(n.read(stage + '/' + name)) == expected
    u.setup()
    pending = s.load(UPDATE_PENDING) if os.path.isfile(UPDATE_PENDING) else None
    before = pending['before'] if pending else s.load(BASE + '/payload.json')
    assert before['owner'] == policy.OWNER and before['schema'] == 1
    assert set(before['files']) == set(u.PAYLOAD_FILES)
    assert n.digest(profiles.canonical(before['files'])) in PREVIOUS_PAYLOADS, 'unrecognized_previous_payload'
    changed = sorted(name for name in after['files'] if before['files'][name] != after['files'][name])
    assert changed and set(changed) <= set(UPDATE_FILES), 'update_scope_changed'
    if pending:
        assert pending['owner'] == policy.OWNER and pending['after'] == after
        assert pending['variant'] == facts['variant'] and pending['changed'] == changed
        folder = pending['backup']
        assert re.match(r'\A' + re.escape(BASE) + r'/archive/update-[a-f0-9]{12}\Z', folder)
        assert os.path.realpath(folder) == folder
        assert s.load(folder + '/payload.before.json') == before
        assert s.load(BASE + '/payload.json') in (before, after), 'installed_manifest_changed'
        for name in changed:
            assert n.digest(n.read(folder + '/' + name)) == before['files'][name]
    for name, expected in before['files'].items():
        allowed = (expected, after['files'][name]) if pending else (expected,)
        assert not os.path.islink(BASE + '/' + name) and n.digest(n.read(BASE + '/' + name)) in allowed, 'installed_payload_changed'
    if not pending or pending['phase'] != 'files_verified':
        assert s.phone_idle() and not s.read_status().get('manager_alive'), 'update_service_active'
        assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}, 'update_reboot_required'
        u.handoff()
        assert not n.ims_pids() and not n.active_vpn_sessions()
        if pending is None:
            u.verify()
            import binascii
            folder = BASE + '/archive/update-' + binascii.hexlify(os.urandom(6)).decode('ascii')
            os.mkdir(folder, 0o700)
            os.mkdir(folder + '/device', 0o700)
            persist(folder + '/payload.before.json', n.read(BASE + '/payload.json'))
            for name in changed:
                persist(folder + '/' + name, n.read(BASE + '/' + name))
                assert n.digest(n.read(folder + '/' + name)) == before['files'][name]
            pending = {'owner': policy.OWNER, 'phase': 'backed_up', 'variant': facts['variant'],
                       'before': before, 'after': after, 'backup': folder, 'changed': changed,
                       'was_enabled': os.path.isfile(BASE + '/enabled')}
            persist(UPDATE_PENDING, profiles.canonical(pending))
        if os.path.isfile(BASE + '/enabled'):
            os.unlink(BASE + '/enabled')
        for name in changed:
            persist(BASE + '/' + name, n.read(stage + '/' + name), 0o600)
            assert n.digest(n.read(BASE + '/' + name)) == after['files'][name]
        persist(BASE + '/payload.json', profiles.canonical(after))
        u.verify()
        pending['phase'] = 'files_verified'
        persist(UPDATE_PENDING, profiles.canonical(pending))
    else:
        assert s.load(BASE + '/payload.json') == after
        u.verify()
    result = {'owner': policy.OWNER, 'updated': True, 'reboot_required': True, 'automatic_carrier_selection': True,
              'before': before, 'after': after, 'changed': changed, 'was_enabled': pending['was_enabled'],
              'phone_backup': folder, 'backup_files': {'payload.before.json': n.digest(n.read(folder + '/payload.before.json'))}}
    result['backup_files'].update({name: before['files'][name] for name in changed})
    persist(folder + '/update-result.json', profiles.canonical(result))
    persist(BASE + '/last-update.json', profiles.canonical(result))
    if pending['was_enabled'] and not os.path.isfile(BASE + '/enabled'):
        persist(BASE + '/enabled', b'automatic selection preserved after verified update\n')
    os.unlink(UPDATE_PENDING)
    return result


def rollback(archive=None):
    facts, unused = identity()
    u.setup()
    record_path = BASE + '/rollback-pending.json'
    pending = s.load(record_path) if os.path.isfile(record_path) else None
    if pending:
        assert pending['owner'] == policy.OWNER
        if archive is not None:
            assert pending['archive'] == archive, 'rollback_target_changed'
        archive = pending['archive']
    if archive is None:
        archive = s.load(BASE + '/last-update.json')['phone_backup']
    assert re.match(r'\A' + re.escape(BASE) + r'/archive/update-[a-f0-9]{12}\Z', archive), 'rollback_archive_invalid'
    assert os.path.realpath(archive) == archive, 'rollback_archive_changed'
    if os.path.isfile(UPDATE_PENDING):
        update_record = s.load(UPDATE_PENDING)
        assert update_record['owner'] == policy.OWNER and update_record['backup'] == archive
        record = dict(update_record, phone_backup=archive)
    else:
        record = s.load(archive + '/update-result.json')
    assert record['owner'] == policy.OWNER and record['phone_backup'] == archive
    before, after = record['before'], record['after']
    assert set(before['files']) == set(after['files']) == set(u.PAYLOAD_FILES)
    changed = sorted(name for name in before['files'] if before['files'][name] != after['files'][name])
    assert changed == record['changed'] and set(changed) <= set(UPDATE_FILES)
    assert s.load(archive + '/payload.before.json') == before
    for name in changed:
        assert not os.path.islink(archive + '/' + name)
        assert n.digest(n.read(archive + '/' + name)) == before['files'][name], 'rollback_backup_changed'
    assert s.load(BASE + '/payload.json') in (before, after), 'installed_manifest_changed'
    for name in before['files']:
        assert not os.path.islink(BASE + '/' + name)
        assert n.digest(n.read(BASE + '/' + name)) in (before['files'][name], after['files'][name]), 'installed_payload_changed'
    if pending is None and os.path.isfile(archive + '/rollback-result.json') and s.load(BASE + '/payload.json') == before:
        assert all(n.digest(n.read(BASE + '/' + name)) == expected for name, expected in before['files'].items())
        result = s.load(archive + '/rollback-result.json')
        assert result['owner'] == policy.OWNER and result['rolled_back'] is True
        committed_boot = result.pop('committed_boot')
        return dict(result, already_committed=True, reboot_required=committed_boot == u.boot_token())
    # Older code cannot consume a mobile receipt. Never invent a desktop copy.
    prior_service = archive + '/device/unified_service.py' if 'device/unified_service.py' in changed else BASE + '/device/unified_service.py'
    prior_schema = 2 if b'verify_backup_receipt' in n.read(prior_service) else 1
    if prior_schema == 1:
        backup = s.load(BASE + '/backup/manifest.json')
        validate_backup_receipt(s.load(BASE + '/desktop-backup-receipt.json'), backup,
            n.digest(n.read(BASE + '/backup/manifest.json')))
    assert s.phone_idle() and not s.read_status().get('manager_alive'), 'rollback_service_active'
    assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}, 'rollback_reboot_required'
    u.handoff()
    assert not n.ims_pids() and not n.active_vpn_sessions()
    if pending is None:
        pending = {'schema': 2, 'owner': policy.OWNER, 'phase': 'restoring_files', 'archive': archive,
            'variant': facts['variant'], 'device': device_binding(), 'before': before, 'after': after}
        persist(record_path, profiles.canonical(pending))
    assert pending['variant'] == facts['variant'] and pending['device'] == device_binding()
    assert pending['before'] == before and pending['after'] == after
    if os.path.isfile(BASE + '/enabled'):
        os.unlink(BASE + '/enabled')
    for name in changed:
        persist(BASE + '/' + name, n.read(archive + '/' + name), 0o600)
    persist(BASE + '/payload.json', profiles.canonical(before))
    u.verify()
    identity_value = management_identity(facts)
    identity_value['engine_schema'] = prior_schema
    persist(BASE + '/management.json', profiles.canonical(identity_value))
    result = {'rolled_back': True, 'reboot_required': True, 'phone_backup': archive,
        'installed_management_schema': prior_schema, 'retained_original_backup': True}
    persist(archive + '/rollback-result.json', profiles.canonical(dict(result,
        owner=policy.OWNER, committed_boot=u.boot_token())))
    if record['was_enabled']:
        persist(BASE + '/enabled', b'enabled state restored after verified rollback\n')
    if os.path.isfile(UPDATE_PENDING):
        os.unlink(UPDATE_PENDING)
    os.unlink(record_path)
    return result


def original_source(name, legacy):
    actual = n.read(dca.source_path(name))
    if actual in (b'', dca.HEADER):
        return actual
    assert legacy is not None, 'unowned_dca_source'
    base = legacy['base']
    q20 = base == migration.BASES['SQC100-2']
    pointer = s.load(base + '/state/' + ('dca-usage-plan.json' if q20 else 'telecom-plan.json'))
    folder = pointer['folder']
    prefix = base + '/state/' + ('dca-usage-' if q20 else 'telecom-attach-')
    assert folder.startswith(prefix) and os.path.realpath(folder) == folder
    plan = s.load(folder + '/plan.json')
    assert plan['original_usage'] == 0 and plan['original_voice'] == 0
    item = plan['files'][name]
    original = n.read(folder + '/' + name + '.original')
    assert n.digest(original) == item['original_sha256']
    assert actual in (original, dca.payload(original, 'data_centric'), dca.payload(original, 'voice_centric'))
    mobile_path = folder + '/backup-receipt.json'
    if not q20 and os.path.isfile(mobile_path):
        assert not os.path.islink(mobile_path), 'legacy_backup_receipt_changed'
        receipt = s.load(mobile_path)
        assert plan.get('owner') == pointer.get('owner') == receipt.get('owner') == 'bb10-telecom-attach-v1'
        assert receipt.get('schema') == 2 and receipt.get('source') == 'mobile', 'legacy_backup_source_invalid'
        safe_id(receipt.get('operation_id'))
        assert set(plan['files']) == set(dca.SOURCES), 'legacy_backup_incomplete'
        hashes = {member + '.original': item['original_sha256'] for member, item in plan['files'].items()}
        assert receipt.get('files') == receipt.get('readback') == hashes, 'legacy_backup_incomplete'
        target = receipt.get('destination', {})
        assert target.get('type') in ('same_device', 'removable')
        assert isinstance(target.get('id'), str) and 0 < len(target['id']) <= 1024
        for member, expected in hashes.items():
            assert not os.path.islink(folder + '/' + member)
            assert n.digest(n.read(folder + '/' + member)) == expected, 'original_backup_changed'
    else:
        receipt = s.load(folder + '/desktop-backup-receipt.json')
    assert receipt['all_original_hashes_verified'] is True and receipt['plan_sha256'] == n.digest(n.read(folder + '/plan.json'))
    return original


def prepare(stage):
    facts, family = identity()
    assert s.phone_idle(), 'call_active'
    assert re.match(r'\A/var/bb10_auto_stage_[a-f0-9]{12}\Z', stage) and os.path.realpath(stage) == stage
    manifest = s.load(stage + '/payload.json')
    assert manifest['owner'] == policy.OWNER and manifest['schema'] == 1
    assert set(manifest['files']) == set(u.PAYLOAD_FILES)
    for name, expected in manifest['files'].items():
        assert not os.path.islink(stage + '/' + name) and n.digest(n.read(stage + '/' + name)) == expected
    recover_retirement()
    if os.path.isfile(BASE + '/uninstalled.json'):
        retire_uninstalled()
    if os.path.lexists(BASE):
        assert os.path.realpath(BASE) == BASE and not os.path.islink(BASE), 'installation_path_changed'
        pending = s.load(BASE + '/install-pending.json')
        assert pending['owner'] == policy.OWNER and pending['phase'] in ('awaiting_desktop_backup', 'awaiting_backup', 'activating')
        assert s.load(BASE + '/payload.json') == manifest, 'pending_payload_differs'
        for name, expected in manifest['files'].items():
            assert not os.path.islink(BASE + '/' + name) and n.digest(n.read(BASE + '/' + name)) == expected
        backup = s.load(BASE + '/backup/manifest.json')
        assert backup['owner'] == policy.OWNER and backup['variant'] == facts['variant']
        for name, expected in backup['files'].items():
            assert '/' not in name and n.digest(n.read(BASE + '/backup/' + name)) == expected
        identity_value = management_identity(facts, create=True)
        if pending.get('schema') == 2:
            os.chmod(BASE, 0o755)
        return {'prepared': True, 'installation_id': identity_value['installation_id'],
                'backup_manifest_sha256': n.digest(n.read(BASE + '/backup/manifest.json')), 'backup_files': backup['files']}
    # Build the complete owned directory before publishing it as BASE. A crash
    # never exposes an empty BASE with no ownership record to the old desktop.
    private_directory(MANAGEMENT)
    intent_path = MANAGEMENT + '/install-intent.json'
    intent = s.load(intent_path) if os.path.isfile(intent_path) else None
    if intent is not None and intent.get('phase') == 'retired':
        intent = None
    if intent is None:
        kind, legacy = root_kind(facts), migration.inspect(facts)
        originals = {name: original_source(name, legacy) for name in dca.SOURCES}
        if legacy is None:
            assert n.voice_policy() == 0 and radio.ue_usage_policy() == 0
            assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
            assert not os.path.lexists(s.XML) and not os.path.lexists(s.CFG_DIR)
        backup = {'owner': policy.OWNER, 'variant': facts['variant'], 'dca': {}, 'files': {}, 'legacy': legacy}
        contents = {}
        for name, original in originals.items():
            path, info = dca.source_path(name), os.lstat(dca.source_path(name))
            assert stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
            backup['dca'][name] = {'path': path, 'original_sha256': n.digest(original),
                'identity': [info.st_ino, info.st_mode & 0o7777, info.st_uid, info.st_gid]}
            contents[name + '.original'] = binascii.hexlify(original).decode('ascii')
            backup['files'][name + '.original'] = n.digest(original)
        if kind == 'autoroot-v2':
            raw = n.read(BTOOL)
            contents['btool.original'] = binascii.hexlify(raw).decode('ascii')
            backup['files']['btool.original'] = n.digest(raw)
        intent = {'schema': 2, 'owner': policy.OWNER, 'phase': 'preparing-v2', 'operation_id': nonce(),
            'installation_id': nonce(), 'variant': facts['variant'], 'device': device_binding(True),
            'root_kind': kind, 'manifest': manifest, 'backup': backup, 'originals': contents}
        persist(intent_path, profiles.canonical(intent))
    assert intent['owner'] == policy.OWNER and intent['phase'] in ('preparing-v2', 'published')
    assert intent['variant'] == facts['variant'] and intent['device'] == device_binding(), 'installation_device_changed'
    assert intent['manifest'] == manifest, 'pending_payload_differs'
    safe_id(intent['operation_id'])
    work = MANAGEMENT + '/prepare-' + intent['operation_id']
    private_directory(work)
    for suffix in ('device', 'driver', 'state', 'runtime', 'runtime/carrier', 'backup', 'archive'):
        path = work + '/' + suffix
        if not os.path.lexists(path):
            os.mkdir(path, 0o755 if suffix.startswith('runtime') else 0o700)
        assert os.path.isdir(path) and os.path.realpath(path) == path, 'prepared_directory_changed'
    def put(name, raw, mode=0o600):
        path = work + '/' + name
        if os.path.lexists(path):
            assert not os.path.islink(path) and n.read(path) == raw, 'prepared_file_changed'
        else:
            persist(path, raw, mode)
    for name in u.PAYLOAD_FILES:
        put(name, n.read(stage + '/' + name), 0o700 if name.endswith('.sh') else 0o600)
    put('payload.json', profiles.canonical(manifest))
    backup = intent['backup']
    for name, encoded in intent['originals'].items():
        assert '/' not in name and '\\' not in name
        raw = binascii.unhexlify(encoded.encode('ascii'))
        assert n.digest(raw) == backup['files'][name]
        put('backup/' + name, raw)
    put('backup/manifest.json', profiles.canonical(backup))
    put('management.json', profiles.canonical({key: intent[key] for key in
        ('schema', 'owner', 'installation_id', 'variant', 'device')}))
    pending = {key: intent[key] for key in ('owner', 'operation_id', 'installation_id', 'root_kind', 'variant', 'device')}
    pending.update(schema=2, phase='awaiting_backup')
    put('install-pending.json', profiles.canonical(pending))
    expected = set(u.PAYLOAD_FILES) | {'payload.json', 'management.json', 'install-pending.json', 'backup/manifest.json'}
    expected.update('backup/' + name for name in backup['files'])
    actual = set()
    for folder, directories, files in os.walk(work):
        for name in directories + files:
            assert not os.path.islink(folder + '/' + name), 'prepared_file_changed'
        actual.update((folder + '/' + name)[len(work) + 1:] for name in files)
    assert actual == expected, 'prepared_contents_changed'
    assert not os.path.lexists(BASE), 'installation_target_claimed'
    # The native IMS child runs under UID 453 and must traverse BASE to read its
    # public runtime configuration. Device code, originals and state stay 0700.
    os.rename(work, BASE)
    os.chmod(BASE, 0o755)
    intent['phase'] = 'published'
    persist(intent_path, profiles.canonical(intent))
    return {'prepared': True, 'backup_manifest_sha256': n.digest(n.read(BASE + '/backup/manifest.json')),
            'backup_files': backup['files'], 'installation_id': intent['installation_id']}


def activate():
    facts, family = identity()
    if not os.path.isfile(BASE + '/install-pending.json'):
        installed = s.load(BASE + '/installation.json')
        assert installed['owner'] == policy.OWNER and installed['phase'] == 'active_next_boot'
        u.setup()
        u.verify()
        return {'installed': True, 'reboot_required': True, 'already_committed': True}
    pending = s.load(BASE + '/install-pending.json')
    assert pending['owner'] == policy.OWNER and pending['phase'] in ('awaiting_desktop_backup', 'awaiting_backup', 'activating')
    assert pending['variant'] == facts['variant'] and s.phone_idle()
    if pending.get('schema') == 2:
        assert management_identity(facts)['installation_id'] == pending['installation_id']
    u.setup()
    u.verify()
    backup = s.load(BASE + '/backup/manifest.json')
    journal_path = BASE + '/activation.json'
    journal = s.load(journal_path) if os.path.isfile(journal_path) else None
    script = BASE + '/device/unified_boot.sh'
    if journal is None:
        journal = {'schema': 2, 'owner': policy.OWNER, 'phase': 'quiescing',
            'variant': facts['variant'], 'root_kind': pending['root_kind'], 'script_sha256': n.digest(n.read(script))}
        # Save intent before touching the legacy service or either boot hook.
        if pending['root_kind'] == 'autoroot-v2':
            before = n.read(BTOOL)
            assert before == n.read(BASE + '/backup/btool.original')
            anchor = b'. /base/scripts/sudtools.sh\n'
            assert before.count(anchor) == 1 and HOOK not in before
            after = before.replace(anchor, HOOK + anchor, 1)
            info = os.lstat(BTOOL)
            assert stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
            journal.update(before_sha256=n.digest(before), after_sha256=n.digest(after),
                identity=[info.st_ino, info.st_mode, info.st_uid, info.st_gid])
        else:
            assert root_kind(facts) == 'autoroot-v4', 'root_scheme_changed'
            assert not os.path.lexists(ADDON), 'boot_addon_exists'
        persist(journal_path, profiles.canonical(journal))
        pending['phase'] = 'activating'
        persist(BASE + '/install-pending.json', profiles.canonical(pending))
    assert journal['owner'] == policy.OWNER and journal['variant'] == facts['variant']
    assert journal['root_kind'] == pending['root_kind'] and journal['script_sha256'] == n.digest(n.read(script))
    if journal['phase'] == 'committed' and os.path.isfile(BASE + '/enabled'):
        installed = s.load(BASE + '/installation.json')
        assert installed['owner'] == policy.OWNER and installed['phase'] == 'active_next_boot'
        target = BTOOL if pending['root_kind'] == 'autoroot-v2' else ADDON + '/init/start.sh'
        expected = journal['after_sha256'] if pending['root_kind'] == 'autoroot-v2' else journal['script_sha256']
        assert not os.path.islink(target) and n.digest(n.read(target)) == expected, 'root_hook_changed'
        os.unlink(BASE + '/install-pending.json')
        return {'installed': True, 'already_committed': True, 'reboot_required': True, 'backup_verified': True}
    if journal['phase'] == 'quiescing':
        journal['legacy'] = migration.quiesce(backup.get('legacy'))
        journal['phase'] = 'installing_hook'
        persist(journal_path, profiles.canonical(journal))
    assert journal['phase'] in ('installing_hook', 'committed'), 'activation_phase_unknown'
    entry = journal['legacy']
    n.command(['/proc/boot/pathtrust', '!' + script])
    n.command(['/bin/sh', '-n', script])
    if pending['root_kind'] == 'autoroot-v2':
        before = n.read(BASE + '/backup/btool.original')
        after = before.replace(b'. /base/scripts/sudtools.sh\n', HOOK + b'. /base/scripts/sudtools.sh\n', 1)
        assert n.digest(before) == journal['before_sha256'] and n.digest(after) == journal['after_sha256']
        persist(BASE + '/root-v2', b'verified root-v2 hook\n')
        info = os.lstat(BTOOL)
        assert not stat.S_ISLNK(info.st_mode)
        assert [info.st_ino, info.st_mode, info.st_uid, info.st_gid] == journal['identity'], 'root_hook_identity_changed'
        with open(BTOOL, 'r+b') as output:
            opened = os.fstat(output.fileno())
            assert (opened.st_ino, opened.st_mode, opened.st_uid, opened.st_gid) == (
                info.st_ino, info.st_mode, info.st_uid, info.st_gid)
            actual = output.read()
            assert actual in (before, after), 'root_hook_changed'
            if actual == before:
                output.seek(0)
                assert output.write(after) == len(after)
                output.truncate(len(after))
                output.flush()
                os.fsync(output.fileno())
        assert n.read(BTOOL) == after and os.stat(BTOOL).st_ino == info.st_ino
        persist(BASE + '/boot-install.json', profiles.canonical({'owner': policy.OWNER,
            'before_sha256': n.digest(before), 'after_sha256': n.digest(after)}))
    else:
        addon_parent(create=True)
        for path in (ADDON, ADDON + '/data', ADDON + '/init'):
            if not os.path.lexists(path):
                os.mkdir(path, 0o755)
            assert unlinked_path(path) and os.path.isdir(path), 'boot_addon_changed'
        assert set(os.listdir(ADDON)) == {'data', 'init'} and not os.listdir(ADDON + '/data'), 'boot_addon_changed'
        assert set(os.listdir(ADDON + '/init')) <= {'start.sh', 'start.sh.new'}, 'boot_addon_changed'
        temporary_hook = ADDON + '/init/start.sh.new'
        if os.path.lexists(temporary_hook):
            info = os.lstat(temporary_hook)
            # atomic() may have stopped after creating or partially writing its
            # exact journal-owned temporary file. Only a prefix of the expected
            # script is resumable; foreign bytes/links are never overwritten.
            assert stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
            assert info.st_uid == 0 and info.st_nlink == 1, 'boot_addon_changed'
            assert n.read(script).startswith(n.read(temporary_hook)), 'boot_addon_changed'
        if os.path.lexists(ADDON + '/init/start.sh'):
            assert not os.path.islink(ADDON + '/init/start.sh') and n.read(ADDON + '/init/start.sh') == n.read(script), 'boot_addon_changed'
        persist(ADDON + '/init/start.sh', n.read(script), 0o700)
        n.command(['/proc/boot/pathtrust', '!' + ADDON + '/init/start.sh'])
    record = {'owner': policy.OWNER, 'installed_boot': u.boot_token(), 'legacy': entry, 'completed': False}
    persist(BASE + '/migration.json', profiles.canonical(record))
    pending['phase'] = 'active_next_boot'
    persist(BASE + '/installation.json', profiles.canonical(pending))
    journal['phase'] = 'committed'
    persist(journal_path, profiles.canonical(journal))
    persist(BASE + '/enabled', b'automatic SIM selection installed by owner\n')
    os.unlink(BASE + '/install-pending.json')
    return {'installed': True, 'reboot_required': True, 'automatic_carrier_selection': True,
            'backup_verified': True, 'legacy_payload_retained': entry is not None}


def cleanup_stage(stage):
    assert re.match(r'\A/var/bb10_auto_stage_[a-f0-9]{12}\Z', stage)
    assert os.path.realpath(stage) == stage and not os.path.islink(stage)
    expected = set(u.PAYLOAD_FILES) | {'payload.json'}
    actual = set()
    for folder, directories, files in os.walk(stage):
        for name in directories + files:
            assert not os.path.islink(folder + '/' + name)
        for name in files:
            actual.add((folder + '/' + name)[len(stage) + 1:])
    assert actual == expected
    assert set(os.listdir(stage)) == {'device', 'driver', 'payload.json'}
    for name in sorted(expected):
        os.unlink(stage + '/' + name)
    for name in ('device', 'driver'):
        os.rmdir(stage + '/' + name)
    os.rmdir(stage)
    return {'stage_removed': True}


def inventory(base=None):
    """Inventory retained data; reject symlinks and non-regular members."""
    base = BASE if base is None else base
    result = {}
    for folder, directories, files in os.walk(base):
        for name in directories + files:
            path = folder + '/' + name
            info = os.lstat(path)
            assert not stat.S_ISLNK(info.st_mode), 'uninstall_unknown_member'
            assert stat.S_ISDIR(info.st_mode) if name in directories else stat.S_ISREG(info.st_mode)
            if name in directories:
                relative = path[len(base) + 1:].replace(os.sep, '/')
                assert relative in ('device', 'driver', 'state', 'runtime', 'runtime/carrier',
                    'runtime/operator-name', 'backup', 'archive', 'state/own-number-history') or re.match(
                    r'\Aarchive/update-[a-f0-9]{12}(?:/device)?\Z', relative), 'uninstall_unknown_directory'
        for name in files:
            path = folder + '/' + name
            digest = hashlib.sha256()
            with open(path, 'rb') as stream:
                while True:
                    block = stream.read(65536)
                    if not block:
                        break
                    digest.update(block)
            result[path[len(base) + 1:].replace(os.sep, '/')] = digest.hexdigest()
    return result


def known_uninstall_member(name, payload):
    if name in payload['files']:
        return True
    if name in ('payload.json', 'management.json', 'backup-receipt.json', 'desktop-backup-receipt.json',
                'activation.json', 'installation.json', 'boot-install.json', 'root-v2', 'migration.json',
                'last-update.json', 'uninstall-pending.json', 'uninstalled.json', 'enabled', 'conservative-start'):
        return True
    if re.match(r'\Abackup/(?:manifest\.json|legacy-journal\.json|(?:ims|ims_defaults|omadm|test|btool)\.original)\Z', name):
        return True
    if name in ('runtime/ims_rrm', 'runtime/carrier/36-ims.xml', 'runtime/carrier/emergency.xml'):
        journal_path = BASE + '/state/journal.json'
        if not os.path.isfile(journal_path):
            return False
        journal = s.load(journal_path)
        path = BASE + '/' + name
        return (journal.get('owner') == 'q10-unicom-volte-v1' and
                journal.get('managed_files', {}).get(path) == n.digest(n.read(path)))
    # These bounded exact names are diagnostic output, retained with originals;
    # accepting a diagnostic never authorizes an executable or modem write.
    if re.match(r'\Abackup/dca-auto-(?:usage|explicit-original|original-files|republish-original|republish-data)\.log\Z', name):
        return True
    state = ('journal.json', 'status.json', 'lock.json', 'stop-request', 'native.log', 'native-previous.log',
             'owned-ims-events.log', 'boot.log', 'last-error.txt', 'selection.json', 'native-attempt.json',
             'stock-handoff.json', 'operator-name-status.json', 'operator-name-original.txt', 'operator-name.json',
             'own-number-display.json', 'own-number-status.json', 'dca.json', 'radio-mode.json')
    if name.startswith('state/') and name[6:] in state:
        return True
    if re.match(r'\Astate/own-number-history/before-[0-9]+\.json\Z', name):
        return True
    if re.match(r'\Aarchive/journal-[a-f0-9]{16}\.json\Z', name):
        return True
    found = re.match(r'\Aarchive/update-[a-f0-9]{12}/(.+)\Z', name)
    if found and found.group(1) in set(UPDATE_FILES) | {'payload.before.json', 'update-result.json', 'rollback-result.json'}:
        return True
    return name == 'runtime/operator-name/table.txt'


def recover_retirement():
    path = MANAGEMENT + '/retire-intent.json'
    if not os.path.isfile(path):
        return
    record = s.load(path)
    assert record['owner'] == policy.OWNER and record['phase'] in ('moving', 'completed')
    if record['phase'] == 'completed' or os.path.lexists(BASE):
        return
    destination = MANAGEMENT + '/retained-' + safe_id(record['installation_id'])
    assert record['destination'] == destination and unlinked_path(destination) and os.path.isdir(destination), 'retired_archive_missing'
    assert inventory(destination) == record['files'], 'retained_data_changed'
    intent_path = MANAGEMENT + '/install-intent.json'
    if os.path.isfile(intent_path):
        intent = s.load(intent_path)
        assert intent['owner'] == policy.OWNER
        intent['phase'] = 'retired'
        persist(intent_path, profiles.canonical(intent))
    record['phase'] = 'completed'
    persist(path, profiles.canonical(record))


def retire_uninstalled():
    record = s.load(BASE + '/uninstalled.json')
    assert record['owner'] == policy.OWNER and record['uninstalled'] is True
    pending_path = BASE + '/uninstall-pending.json'
    if os.path.isfile(pending_path):
        pending = s.load(pending_path)
        assert pending['owner'] == policy.OWNER and pending['phase'] == 'removing_payload'
        assert pending['installation_id'] == record['installation_id']
        os.unlink(pending_path)
    actual = inventory()
    actual.pop('uninstalled.json')
    assert actual == record['retained_files'], 'retained_data_changed'
    destination = MANAGEMENT + '/retained-' + safe_id(record['installation_id'])
    assert not os.path.lexists(destination), 'retained_archive_exists'
    persist(MANAGEMENT + '/retire-intent.json', profiles.canonical({'owner': policy.OWNER, 'phase': 'moving',
        'installation_id': record['installation_id'], 'destination': destination, 'files': inventory()}))
    os.rename(BASE, destination)
    recover_retirement()
    return destination


def uninstall():
    facts, unused = identity()
    u.setup()
    if os.path.isfile(BASE + '/uninstalled.json'):
        result = s.load(BASE + '/uninstalled.json')
        assert result['owner'] == policy.OWNER and type(result['uninstalled']) is bool
        pending_path = BASE + '/uninstall-pending.json'
        if os.path.isfile(pending_path):
            old = s.load(pending_path)
            assert old['owner'] == policy.OWNER and old['phase'] == 'removing_payload'
            assert old['installation_id'] == result['installation_id']
            os.unlink(pending_path)
        if not result['uninstalled']:
            if result['removed_boot'] == u.boot_token():
                return {'uninstalled': False, 'payload_removed': True, 'phase': 'awaiting_final_reboot', 'reboot_required': True}
            assert s.phone_idle() and not s.read_status().get('manager_alive'), 'uninstall_resources_active'
            assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}, 'uninstall_reboot_required'
            verify_backup_receipt()
            for name in dca.SOURCES:
                assert n.read(dca.source_path(name)) == n.read(BASE + '/backup/' + name + '.original'), 'restore_readback_failed'
            assert n.voice_policy() == 0 and radio.ue_usage_policy() == 0
            result['uninstalled'], result['reboot_required'] = True, False
            persist(BASE + '/uninstalled.json', profiles.canonical(result))
        return {'uninstalled': True, 'retained_backup': BASE + '/backup', 'already_committed': True, 'reboot_required': False}
    path = BASE + '/uninstall-pending.json'
    pending = s.load(path) if os.path.isfile(path) else None
    if pending is None:
        assert not os.path.isfile(UPDATE_PENDING) and not os.path.isfile(BASE + '/rollback-pending.json'), 'update_recovery_required'
        assert not os.path.isfile(BASE + '/install-pending.json'), 'activation_recovery_required'
        u.verify()
        assert s.phone_idle(), 'call_active'
        identity_value = management_identity(facts)
        pending = {'schema': 2, 'owner': policy.OWNER, 'phase': 'stop_requested',
            'variant': facts['variant'], 'device': device_binding(), 'installation_id': identity_value['installation_id'],
            'boot': u.boot_token(), 'payload': s.load(BASE + '/payload.json'),
            'root_kind': s.load(BASE + '/installation.json')['root_kind']}
        # Detect unknown members before even requesting service changes.
        assert all(known_uninstall_member(name, pending['payload']) for name in inventory()), 'uninstall_unknown_member'
        persist(path, profiles.canonical(pending))
    assert pending['owner'] == policy.OWNER and pending['variant'] == facts['variant']
    assert pending['device'] == device_binding(), 'installation_device_changed'
    assert s.phone_idle(), 'call_active'
    if pending['phase'] == 'stop_requested':
        u.service_action('disable')
        pending['phase'] = 'awaiting_reboot'
        persist(path, profiles.canonical(pending))
    if pending['phase'] == 'awaiting_reboot':
        if pending['boot'] == u.boot_token() or s.read_status().get('manager_alive'):
            return {'uninstalled': False, 'phase': 'awaiting_reboot', 'reboot_required': True}
        assert not os.path.isfile(BASE + '/enabled'), 'uninstall_service_reenabled'
        assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}, 'uninstall_reboot_required'
        u.handoff()
        assert not n.ims_pids() and not n.active_vpn_sessions(), 'uninstall_resources_active'
        migration.finish_previous_boot()
        u.reconcile()
        import unified_dca
        unified_dca.restore_original()
        backup = s.load(BASE + '/backup/manifest.json')
        for name in dca.SOURCES:
            assert n.read(dca.source_path(name)) == n.read(BASE + '/backup/' + name + '.original'), 'restore_readback_failed'
        assert n.voice_policy() == 0 and radio.ue_usage_policy() == 0
        assert not os.path.lexists(s.XML) and not os.path.lexists(s.CFG_DIR), 'uninstall_configuration_remains'
        import unified_operator_name
        assert unified_operator_name.target() is None, 'uninstall_operator_overlay_remains'
        pending['phase'] = 'removing_hook'
        persist(path, profiles.canonical(pending))
    assert pending['phase'] in ('removing_hook', 'removing_payload'), 'uninstall_phase_unknown'
    assert not s.read_status().get('manager_alive') and not os.path.isfile(BASE + '/enabled')
    assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}, 'uninstall_reboot_required'
    present = inventory()
    assert all(known_uninstall_member(name, pending['payload']) for name in present), 'uninstall_unknown_member'
    for name, expected in pending['payload']['files'].items():
        if name in present:
            assert present[name] == expected, 'installed_payload_changed'
        else:
            assert pending['phase'] == 'removing_payload', 'installed_payload_missing'
    if pending['phase'] == 'removing_hook':
        if pending['root_kind'] == 'autoroot-v2':
            before = n.read(BASE + '/backup/btool.original')
            hook = s.load(BASE + '/boot-install.json')
            assert hook['owner'] == policy.OWNER and n.digest(before) == hook['before_sha256']
            info = os.lstat(BTOOL)
            assert stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
            with open(BTOOL, 'r+b') as output:
                opened = os.fstat(output.fileno())
                assert (opened.st_ino, opened.st_mode, opened.st_uid, opened.st_gid) == (info.st_ino, info.st_mode, info.st_uid, info.st_gid)
                current = output.read()
                assert n.digest(current) in (hook['before_sha256'], hook['after_sha256']), 'root_hook_changed'
                if current != before:
                    output.seek(0)
                    assert output.write(before) == len(before)
                    output.truncate(len(before))
                    output.flush()
                    os.fsync(output.fileno())
            assert n.read(BTOOL) == before and os.stat(BTOOL).st_ino == info.st_ino
        else:
            if os.path.lexists(ADDON):
                assert os.path.realpath(ADDON) == ADDON and set(os.listdir(ADDON)) <= {'data', 'init'}, 'boot_addon_changed'
                for suffix in ('data', 'init'):
                    directory = ADDON + '/' + suffix
                    if os.path.lexists(directory):
                        assert os.path.realpath(directory) == directory and os.path.isdir(directory)
                        assert set(os.listdir(directory)) <= ({'start.sh'} if suffix == 'init' else set()), 'boot_addon_changed'
                hook_path = ADDON + '/init/start.sh'
                if os.path.lexists(hook_path):
                    assert not os.path.islink(hook_path)
                    assert n.digest(n.read(hook_path)) == pending['payload']['files']['device/unified_boot.sh'], 'boot_addon_changed'
                    os.unlink(hook_path)
                for suffix in ('init', 'data'):
                    if os.path.isdir(ADDON + '/' + suffix):
                        os.rmdir(ADDON + '/' + suffix)
                os.rmdir(ADDON)
        pending['phase'] = 'removing_payload'
        persist(path, profiles.canonical(pending))
    if pending['root_kind'] == 'autoroot-v4':
        assert not os.path.lexists(ADDON), 'boot_addon_changed'
    else:
        assert n.read(BTOOL) == n.read(BASE + '/backup/btool.original'), 'root_hook_changed'
    for name, expected in pending['payload']['files'].items():
        target = BASE + '/' + name
        if os.path.lexists(target):
            assert not os.path.islink(target) and n.digest(n.read(target)) == expected
            os.unlink(target)
    if os.path.isfile(BASE + '/payload.json'):
        assert s.load(BASE + '/payload.json') == pending['payload']
        os.unlink(BASE + '/payload.json')
    retained = inventory()
    retained.pop('uninstall-pending.json')
    result = {'owner': policy.OWNER, 'uninstalled': False, 'reboot_required': True, 'removed_boot': u.boot_token(),
        'installation_id': pending['installation_id'], 'retained_backup': BASE + '/backup',
        'retained_files': retained}
    persist(BASE + '/uninstalled.json', profiles.canonical(result))
    os.unlink(path)
    return {'uninstalled': False, 'payload_removed': True, 'phase': 'awaiting_final_reboot', 'reboot_required': True,
        'retained_backup': BASE + '/backup', 'diagnostics_retained': True}


def installed_management_schema():
    path = BASE + '/management.json'
    if not os.path.isfile(path):
        return 1
    value = s.load(path)
    assert value['owner'] == policy.OWNER and value['schema'] == 2
    return value.get('engine_schema', 2)


def manage(action, stage=None, receipt=None, archive=None, operation_id=None):
    """Version 2 entry point for both desktop transports and mobile workers.

    The caller keeps its detached worker and result journal outside the BAR.
    These operations never accept a command string or a caller-selected BASE.
    """
    if sys.flags.optimize or sys.flags.inspect:
        raise RuntimeError('unsafe_python_environment')
    identifier = safe_id(operation_id) if operation_id is not None else nonce()
    if action in ('probe', 'status'):
        if action == 'probe':
            result = probe()
        else:
            pending_name = next((name for name in ('uninstall-pending.json', 'uninstalled.json',
                'install-pending.json', 'update-pending.json', 'rollback-pending.json') if os.path.isfile(BASE + '/' + name)), None)
            if pending_name:
                facts, unused = identity()
                pending = s.load(BASE + '/' + pending_name)
                assert pending['owner'] == policy.OWNER
                phase = pending.get('phase', 'uninstalled' if pending.get('uninstalled') else 'awaiting_final_reboot')
                result = {'phase': phase, 'pending_phase': phase, 'variant': facts['variant'],
                    'installed_stage': 'uninstalled' if pending.get('uninstalled') else 'pending',
                    'installed_management_schema': 2, 'current_sim_matches': None,
                    'reboot_required': phase in ('awaiting_reboot', 'awaiting_final_reboot')}
            else:
                u.setup()
                result = u.public_status()
    else:
        assert action in ('prepare', 'activate', 'record-backup', 'update', 'rollback',
            'uninstall', 'start', 'enable', 'disable', 'cleanup-stage'), 'unknown_action'
        with management_lock():
            if os.path.isfile(BASE + '/uninstall-pending.json'):
                assert action in ('uninstall', 'cleanup-stage'), 'uninstall_pending'
            if action in ('start', 'enable'):
                assert not any(os.path.isfile(BASE + '/' + name) for name in
                    ('install-pending.json', 'update-pending.json', 'rollback-pending.json', 'uninstalled.json')), 'management_transaction_pending'
            if action == 'prepare':
                result = prepare(stage)
            elif action == 'activate':
                result = activate()
            elif action == 'record-backup':
                result = record_backup_receipt(receipt)
            elif action == 'update':
                facts, unused = identity()
                u.setup()
                if not os.path.isfile(BASE + '/management.json'):
                    assert not os.path.isfile(BASE + '/install-pending.json'), 'installation_recovery_required'
                    assert not s.read_status().get('manager_alive') and not os.path.isfile(BASE + '/enabled'), 'management_adoption_requires_disable'
                    assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}, 'management_adoption_requires_reboot'
                    previous = s.load(s.JOURNAL) if os.path.isfile(s.JOURNAL) else s.load(BASE + '/migration.json')
                    assert previous.get('boot', previous.get('installed_boot')) != u.boot_token(), 'management_adoption_requires_reboot'
                    management_identity(facts, create=True, engine_schema=1)
                candidate = s.load(stage + '/payload.json')
                previous_result = s.load(BASE + '/last-update.json') if os.path.isfile(BASE + '/last-update.json') else None
                if previous_result and previous_result.get('after') == candidate and s.load(BASE + '/payload.json') == candidate and not os.path.isfile(UPDATE_PENDING):
                    u.verify()
                    result = dict(previous_result, already_committed=True)
                else:
                    result = update(stage)
                    persist(BASE + '/last-update.json', profiles.canonical(result))
                identity_value = management_identity(facts)
                identity_value['engine_schema'] = 2
                persist(BASE + '/management.json', profiles.canonical(identity_value))
            elif action == 'rollback':
                result = rollback(archive)
            elif action == 'uninstall':
                result = uninstall()
            elif action == 'cleanup-stage':
                result = cleanup_stage(stage)
            else:
                result = u.service_action(action)
    result = dict(result)
    result.update(management_schema=2, action=action, operation_id=identifier)
    return result


def main():
    action = sys.argv[1]
    options = {}
    if action in ('prepare', 'update', 'cleanup-stage'):
        options['stage'] = sys.argv[2]
    elif action == 'rollback' and len(sys.argv) > 2:
        options['archive'] = sys.argv[2]
    elif action == 'record-backup':
        path = sys.argv[2]
        assert re.match(r'\A/var/bb10_auto_stage_[a-f0-9]{12}/backup-receipt\.json\Z', path)
        assert os.path.realpath(path) == path and not os.path.islink(path)
        raw = n.read(path)
        assert len(raw) <= 65536, 'backup_receipt_too_large'
        options['receipt'] = json.loads(raw.decode('ascii'))
    result = manage(action, **options)
    if action == 'record-backup':
        assert n.read(path) == raw
        os.unlink(path)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
