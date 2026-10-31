"""Migration of the three identified legacy installations; originals retained.

Migration requests the existing manager's normal stop, never unloads crypto,
and reconciles its journal only after a proven new boot. Unknown edits stop it.
"""
import os
import time
import native as n
import profiles
import service as s
import carrier_policy as policy

BASES = {'SQN100-3': '/var/rootdata/q10_volte', 'SQC100-2': '/var/q20_volte',
         'SQW100-4': '/var/rootdata/passport_volte_research'}


def legacy_boot(base):
    if base == BASES['SQC100-2']:
        path = '/dev/shmem/q20-volte-boot.json'
        if not os.path.isfile(path):
            return None
        value = s.load(path)
        assert value['owner'] == 'q20-volte-boot-v1'
        return ['q20-volte-boot-v1', value['nonce']]
    info = os.stat('/tmp/root.done')
    return [info.st_ino, info.st_mtime]


def inspect(facts):
    base = BASES[facts['variant']]
    if not os.path.exists(base):
        return None
    assert not os.path.islink(base), 'legacy_directory_changed'
    manifest_name = ('installation.json' if facts['variant'] == 'SQN100-3' else
                     'payload-manifest.json' if facts['variant'] == 'SQC100-2' else 'research-manifest.json')
    manifest = s.load(base + '/' + manifest_name)
    # Verify every immutable file before requesting the running legacy manager
    # to stop. SIM-specific requests are checked against their existing manifest.
    if facts['variant'] == 'SQW100-4':
        assert manifest.get('schema') == 1 and manifest.get('lifecycle') == 'retain-provider-until-reboot'
    else:
        assert manifest.get('owner') in ('q10-unicom-volte-v1', 'q20-sqc100-2-volte-v1'), 'unknown_legacy_owner'
    assert isinstance(manifest.get('files'), dict) and manifest['files']
    for name, expected in manifest['files'].items():
        assert not name.startswith('/') and '..' not in name.split('/') and '\\' not in name
        path = base + '/' + name
        assert not os.path.islink(path) and n.digest(n.read(path)) == expected, 'legacy_payload_changed'
    journal = s.load(base + '/state/journal.json') if os.path.isfile(base + '/state/journal.json') else None
    if journal:
        assert journal['owner'] == 'q10-unicom-volte-v1' and journal['original_voice_policy'] == 0
        assert not journal.get('nas_voice_trial'), 'unfinished_nas_trial'
    return {'base': base, 'manifest': manifest_name, 'manifest_sha256': n.digest(n.read(base + '/' + manifest_name)),
            'boot': legacy_boot(base), 'was_enabled': os.path.isfile(base + '/enabled')}


def quiesce(entry):
    if not entry:
        return None
    base = entry['base']
    assert base in BASES.values() and s.phone_idle(), 'call_active'
    assert n.digest(n.read(base + '/' + entry['manifest'])) == entry['manifest_sha256'], 'legacy_changed_after_backup'
    if os.path.isfile(base + '/enabled'):
        os.unlink(base + '/enabled')
    # Independent Passport display addon is retired too; its worker sees this
    # flag and exits without affecting radio or IMS. Files remain for rollback.
    name_base = '/var/rootdata/passport_operator_name'
    if base == BASES['SQW100-4'] and os.path.isfile(name_base + '/enabled'):
        manifest = s.load(name_base + '/manifest.json')
        assert manifest['owner'] == 'passport-operator-name-independent-v1'
        for name, expected in manifest['files'].items():
            assert name in ('name.py', 'native.py', 'device_info.py', 'start.sh')
            assert n.digest(n.read(name_base + '/' + name)) == expected
        os.unlink(name_base + '/enabled')
    lock_path = base + '/state/lock.json'
    if os.path.isfile(lock_path):
        lock = s.load(lock_path)
        if lock.get('boot') == legacy_boot(base) and s.alive(lock['pid']):
            args = n.command(['/bin/pidin', '-p', str(lock['pid']), '-f', 'A']).decode('ascii')
            assert base in args and 'python' in args, 'legacy_manager_identity_changed'
            n.atomic(base + '/state/stop-request', b'unified installation requested normal stop\n')
            deadline = time.time() + 180
            while os.path.exists(lock_path) and time.time() < deadline:
                time.sleep(1)
            assert not os.path.exists(lock_path), 'legacy_stop_pending'
    result = dict(entry)
    result['journal_sha256'] = None
    if os.path.isfile(base + '/state/journal.json'):
        blob = n.read(base + '/state/journal.json')
        result['journal_sha256'] = n.digest(blob)
        n.atomic(policy.BASE + '/backup/legacy-journal.json', blob)
    return result


def finish_previous_boot():
    from unified_service import restore, setup, boot_token
    path = policy.BASE + '/migration.json'
    if not os.path.isfile(path):
        return
    migration = s.load(path)
    assert migration['owner'] == policy.OWNER
    if migration.get('completed'):
        return
    assert migration['installed_boot'] != boot_token(), 'installation_reboot_required'
    entry = migration.get('legacy')
    if entry and entry.get('journal_sha256'):
        base = entry['base']
        assert base in BASES.values() and entry['boot'] != legacy_boot(base), 'legacy_reboot_unconfirmed'
        assert not os.path.isfile(base + '/enabled'), 'legacy_reenabled'
        blob = n.read(base + '/state/journal.json')
        assert n.digest(blob) == entry['journal_sha256'], 'legacy_journal_changed'
        for key, value in {'BASE': base, 'STATE': base + '/state', 'RUNTIME': base + '/runtime',
                'JOURNAL': base + '/state/journal.json', 'STATUS': base + '/state/status.json',
                'LOCK': base + '/state/lock.json', 'STOP': base + '/state/stop-request',
                'BIN': base + '/runtime/ims_rrm', 'APN': base + '/runtime/carrier/36-ims.xml'}.items():
            setattr(s, key, value)
        try:
            s.j = s.load(s.JOURNAL)
            restore(previous_boot=True)
            extra = s.j.get('extra_carrier_settings')
            if extra:
                path_extra = '/var/ims/carrier/imsconfig_404.xml'
                assert extra['path'] == path_extra and extra['before_absent'] is True
                if os.path.exists(path_extra):
                    assert not os.path.islink(path_extra) and n.digest(n.read(path_extra)) == extra['sha256']
                    os.unlink(path_extra)
        finally:
            s.j = None
            setup()
    # Original DCA backups were independently copied by the desktop. Ownership
    # of any recognized legacy data-centric bytes transfers across this reboot.
    from unified_dca import originals, RECORD
    import telecom_dca as dca
    import telecom_native as radio
    unused_files, values = originals()
    modified = False
    for name, original in values.items():
        actual = n.read(dca.source_path(name))
        assert actual in (original, dca.payload(original, 'data_centric'), dca.payload(original, 'voice_centric'))
        modified = modified or actual != original
    usage = radio.ue_usage_policy()
    if modified or usage != 0:
        assert entry is not None and usage in (0, 1), 'unowned_dca_policy'
        n.atomic(RECORD, profiles.canonical({'owner': policy.OWNER, 'phase': 'legacy_adopted',
            'boot': migration['installed_boot'], 'desired': usage}))
    migration['completed'] = True
    migration['completed_boot'] = boot_token()
    n.atomic(path, profiles.canonical(migration))
