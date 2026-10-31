"""Two-phase installer shared by the Windows and macOS desktop programs."""
import ctypes
import json
import os
import re
import stat
import sys
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
PREVIOUS_PAYLOADS = ('7352686da4a229135d7685ffc58c2aae8b1c5c588bcb72fe733799b2336b3a90',
                     '4f92bfe1a7182b1b03f0aa875b864c27e15572b5d9a06aa5d8503d3f2cbab99b',
                     '93ed64504ccf1845bce246e35dbbeea9a04912c72ceb005be2f863a3ffa222a5',
                     '5c2d9d893f88d40b6fde943f85722471da8cd3aa3a61ece7e403e03a48c84943',
                     'e179d971012e0013caf692fc51273c4f62ebaab861af1e36570400515c02382f',
                     'a9a1609e31b8477e01c2c30511b6dfdc5914a4df5bff521f227f3deab77a963b',
                     'f0c4a5002dc41b8de7113db680936240d564e87ddae67793b79e27a45e8c9a2f')
UPDATE_FILES = ('device/unified_dca.py', 'device/unified_install.py',
                'device/unified_service.py', 'device/carrier_policy.py', 'device/unified_own_number.py')
UPDATE_PENDING = BASE + '/update-pending.json'
ADDON = '/var/addons/bb10-unified-volte'
BTOOL = '/apps/sys.android.gYABgKAOw1czN6neiAT72SGO.ns/native/system/xbin/btool'
ROOT_V2_HASHES = ('d56cdb880878198f8fc3d5114313d3f0c880136a9bde6bdc2faecb63da098cc4',
                  'bdcd111afbbfe802e4489a85a4c6eb2e0ba0b8dbe8a429f01ea88045e8b4d501')
HOOK = (b'\n# bb10-unified-carriers-v1\n'
        b'if [ -f /var/bb10_volte/enabled ]; then\n'
        b'    ( /proc/boot/pathtrust !/var/bb10_volte/device/unified_boot.sh && '
        b'/bin/sh /var/bb10_volte/device/unified_boot.sh ) &\nfi\n')


def identity():
    assert os.geteuid() == 0 and os.uname()[0] == 'QNX' and ctypes.sizeof(ctypes.c_void_p) == 4
    facts = device_info.read_identity()
    family = policy.model(facts)
    assert device_info.identify(facts)['identity_conflict'] is False
    u.verify_native()
    return facts, family


def root_kind(facts):
    if os.path.isfile('/tmp/root.done'):
        assert os.path.isdir('/var/addons') and not os.path.islink('/var/addons')
        return 'autoroot-v4'
    assert facts['variant'] == 'SQC100-2' and not os.path.islink(BTOOL), 'root_scheme_not_supported'
    assert n.digest(n.read(BTOOL)) in ROOT_V2_HASHES, 'root_boot_script_changed'
    return 'autoroot-v2'


def probe():
    facts, family = identity()
    result = {'schema': 1, 'variant': facts['variant'], 'family': family, 'os_version': facts['os_version'],
              'installed': os.path.isfile(BASE + '/payload.json'), 'call_idle': s.phone_idle(),
              'normal_reboot_after_sim_change': True, 'validation': 'candidate_pending_device_acceptance'}
    if result['installed']:
        result['installation_pending'] = os.path.isfile(BASE + '/install-pending.json')
        if result['installation_pending']:
            pending = s.load(BASE + '/install-pending.json')
            result['pending_phase'] = pending['phase']
            result['can_install'] = pending['phase'] == 'awaiting_desktop_backup' and result['call_idle']
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
                raw = s.read_status()
                result['status'] = {k: raw.get(k) for k in ('phase', 'enabled', 'manager_alive',
                    'native_alive', 'status_from_current_boot', 'current')}
            known = n.digest(profiles.canonical(current['files'])) in PREVIOUS_PAYLOADS
            result['update_available'] = known and current['files'] != candidate['files'] or pending is not None
            finished = pending is not None and pending['phase'] == 'files_verified'
            result['can_update'] = bool(result['update_available'] and (finished or
                result['call_idle'] and not result['status'].get('manager_alive') and
                n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}))
    else:
        result['root_kind'] = root_kind(facts)
        entry = migration.inspect(facts)
        result['legacy_detected'] = entry is not None
        result['can_install'] = result['call_idle']
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
            n.atomic(folder + '/payload.before.json', n.read(BASE + '/payload.json'))
            for name in changed:
                n.atomic(folder + '/' + name, n.read(BASE + '/' + name))
                assert n.digest(n.read(folder + '/' + name)) == before['files'][name]
            pending = {'owner': policy.OWNER, 'phase': 'backed_up', 'variant': facts['variant'],
                       'before': before, 'after': after, 'backup': folder, 'changed': changed,
                       'was_enabled': os.path.isfile(BASE + '/enabled')}
            n.atomic(UPDATE_PENDING, profiles.canonical(pending))
        if os.path.isfile(BASE + '/enabled'):
            os.unlink(BASE + '/enabled')
        for name in changed:
            n.atomic(BASE + '/' + name, n.read(stage + '/' + name), 0o600)
            assert n.digest(n.read(BASE + '/' + name)) == after['files'][name]
        n.atomic(BASE + '/payload.json', profiles.canonical(after))
        u.verify()
        pending['phase'] = 'files_verified'
        n.atomic(UPDATE_PENDING, profiles.canonical(pending))
    else:
        assert s.load(BASE + '/payload.json') == after
        u.verify()
    result = {'updated': True, 'reboot_required': True, 'automatic_carrier_selection': True,
              'phone_backup': folder, 'backup_files': {'payload.before.json': n.digest(n.read(folder + '/payload.before.json'))}}
    result['backup_files'].update({name: before['files'][name] for name in changed})
    n.atomic(folder + '/update-result.json', profiles.canonical(result))
    if pending['was_enabled'] and not os.path.isfile(BASE + '/enabled'):
        n.atomic(BASE + '/enabled', b'automatic selection preserved after verified update\n')
    os.unlink(UPDATE_PENDING)
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
    if os.path.lexists(BASE):
        pending = s.load(BASE + '/install-pending.json')
        assert pending['owner'] == policy.OWNER and pending['phase'] == 'awaiting_desktop_backup'
        assert s.load(BASE + '/payload.json') == manifest, 'pending_payload_differs'
        for name, expected in manifest['files'].items():
            assert not os.path.islink(BASE + '/' + name) and n.digest(n.read(BASE + '/' + name)) == expected
        backup = s.load(BASE + '/backup/manifest.json')
        assert backup['owner'] == policy.OWNER and backup['variant'] == facts['variant']
        for name, expected in backup['files'].items():
            assert '/' not in name and n.digest(n.read(BASE + '/backup/' + name)) == expected
        return {'prepared': True, 'backup_manifest_sha256': n.digest(n.read(BASE + '/backup/manifest.json')),
                'backup_files': backup['files']}
    kind = root_kind(facts)
    legacy = migration.inspect(facts)
    originals = {name: original_source(name, legacy) for name in dca.SOURCES}
    if legacy is None:
        assert n.voice_policy() == 0 and radio.ue_usage_policy() == 0
        assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
        assert not os.path.lexists(s.XML) and not os.path.lexists(s.CFG_DIR)
    os.mkdir(BASE, 0o755)
    for suffix in ('device', 'driver', 'state', 'runtime', 'runtime/carrier', 'backup', 'archive'):
        os.mkdir(BASE + '/' + suffix, 0o755 if suffix.startswith('runtime') else 0o700)
    n.atomic(BASE + '/install-pending.json', profiles.canonical({'owner': policy.OWNER, 'phase': 'preparing'}))
    for name in u.PAYLOAD_FILES:
        n.atomic(BASE + '/' + name, n.read(stage + '/' + name), 0o700 if name.endswith('.sh') else 0o600)
    n.atomic(BASE + '/payload.json', profiles.canonical(manifest))
    backup = {'owner': policy.OWNER, 'variant': facts['variant'], 'dca': {}, 'files': {}, 'legacy': legacy}
    for name, original in originals.items():
        path = dca.source_path(name)
        info = os.lstat(path)
        assert stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
        backup['dca'][name] = {'path': path, 'original_sha256': n.digest(original),
                              'identity': [info.st_ino, info.st_mode & 0o7777, info.st_uid, info.st_gid]}
        n.atomic(BASE + '/backup/' + name + '.original', original)
        backup['files'][name + '.original'] = n.digest(original)
    if kind == 'autoroot-v2':
        raw = n.read(BTOOL)
        n.atomic(BASE + '/backup/btool.original', raw)
        backup['files']['btool.original'] = n.digest(raw)
    n.atomic(BASE + '/backup/manifest.json', profiles.canonical(backup))
    n.atomic(BASE + '/install-pending.json', profiles.canonical({'owner': policy.OWNER,
        'phase': 'awaiting_desktop_backup', 'root_kind': kind, 'variant': facts['variant']}))
    return {'prepared': True, 'backup_manifest_sha256': n.digest(n.read(BASE + '/backup/manifest.json')),
            'backup_files': backup['files']}


def activate():
    facts, family = identity()
    pending = s.load(BASE + '/install-pending.json')
    assert pending['owner'] == policy.OWNER and pending['phase'] == 'awaiting_desktop_backup'
    assert pending['variant'] == facts['variant'] and s.phone_idle()
    u.setup()
    u.verify()
    backup = s.load(BASE + '/backup/manifest.json')
    # Pin the original root hook before disabling the existing service.
    if pending['root_kind'] == 'autoroot-v2':
        before = n.read(BTOOL)
        assert before == n.read(BASE + '/backup/btool.original')
        anchor = b'. /base/scripts/sudtools.sh\n'
        assert before.count(anchor) == 1 and HOOK not in before
        after = before.replace(anchor, HOOK + anchor, 1)
    else:
        assert not os.path.lexists(ADDON), 'boot_addon_exists'
    entry = migration.quiesce(backup.get('legacy'))
    record = {'owner': policy.OWNER, 'installed_boot': u.boot_token(), 'legacy': entry, 'completed': False}
    n.atomic(BASE + '/migration.json', profiles.canonical(record))
    script = BASE + '/device/unified_boot.sh'
    n.command(['/proc/boot/pathtrust', '!' + script])
    n.command(['/bin/sh', '-n', script])
    if pending['root_kind'] == 'autoroot-v2':
        n.atomic(BASE + '/root-v2', b'verified root-v2 hook\n')
        info = os.lstat(BTOOL)
        # Preserve inode/ACL/PathTrust metadata, matching the accepted v2 hook.
        assert not stat.S_ISLNK(info.st_mode)
        with open(BTOOL, 'r+b') as output:
            opened = os.fstat(output.fileno())
            assert (opened.st_ino, opened.st_mode, opened.st_uid, opened.st_gid) == (
                info.st_ino, info.st_mode, info.st_uid, info.st_gid)
            assert output.read() == before
            output.seek(0)
            assert output.write(after) == len(after)
            output.truncate(len(after))
            output.flush()
            os.fsync(output.fileno())
        assert n.read(BTOOL) == after and os.stat(BTOOL).st_ino == info.st_ino
        n.atomic(BASE + '/boot-install.json', profiles.canonical({'owner': policy.OWNER,
            'before_sha256': n.digest(before), 'after_sha256': n.digest(after)}))
    else:
        for path in (ADDON, ADDON + '/data', ADDON + '/init'):
            os.mkdir(path, 0o755)
        n.atomic(ADDON + '/init/start.sh', n.read(script), 0o700)
        n.command(['/proc/boot/pathtrust', '!' + ADDON + '/init/start.sh'])
    n.atomic(BASE + '/enabled', b'automatic SIM selection installed by owner\n')
    pending['phase'] = 'active_next_boot'
    n.atomic(BASE + '/installation.json', profiles.canonical(pending))
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


def main():
    action = sys.argv[1]
    if action == 'probe':
        result = probe()
    elif action == 'prepare':
        result = prepare(sys.argv[2])
    elif action == 'activate':
        result = activate()
    elif action == 'update':
        result = update(sys.argv[2])
    elif action == 'cleanup-stage':
        result = cleanup_stage(sys.argv[2])
    else:
        raise ValueError('unknown_action')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
