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
STANDARD_BASE = '/var/rootdata/q10_volte'


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


def _load_legacy_json(path):
    assert not os.path.islink(path), 'legacy_payload_changed'
    try:
        value = s.load(path)
    except (IOError, OSError, ValueError, TypeError):
        assert False, 'legacy_payload_changed'
    assert isinstance(value, dict), 'legacy_payload_changed'
    return value


def inspect(facts):
    variant = facts['variant']
    if variant not in policy.MODELS:
        raise ValueError('unsupported_model_or_os')
    # Never borrow a suffix-specific Q20 or Passport research directory on another variant.
    if variant != 'SQC100-2' and os.path.lexists(BASES['SQC100-2']):
        assert False, 'unvalidated_legacy_installation'
    if variant != 'SQW100-4' and os.path.lexists(BASES['SQW100-4']):
        assert False, 'unvalidated_legacy_installation'
    present = [path for path in (STANDARD_BASE, BASES['SQC100-2'], BASES['SQW100-4'])
               if os.path.lexists(path)]
    if not present:
        return None
    if len(present) > 1:
        assert False, 'unvalidated_legacy_installation'
    base = present[0]
    assert not os.path.islink(base), 'legacy_directory_changed'
    if base == STANDARD_BASE:
        manifest_name = 'installation.json'
        if os.path.lexists(base + '/install-transaction.json'):
            assert False, 'legacy_install_interrupted'
        if not os.path.lexists(base + '/' + manifest_name):
            assert False, 'unvalidated_legacy_installation'
        assert not os.path.islink(base + '/' + manifest_name), 'legacy_payload_changed'
        assert os.path.isfile('/tmp/root.done'), 'root_scheme_not_supported'
        manifest = _load_legacy_json(base + '/' + manifest_name)
        assert manifest.get('owner') == 'q10-unicom-volte-v1', 'unknown_legacy_owner'
    elif base == BASES['SQC100-2']:
        manifest_name = 'payload-manifest.json'
        manifest = _load_legacy_json(base + '/' + manifest_name)
        assert manifest.get('owner') == 'q20-sqc100-2-volte-v1', 'unknown_legacy_owner'
    else:
        manifest_name = 'research-manifest.json'
        manifest = _load_legacy_json(base + '/' + manifest_name)
        assert manifest.get('schema') == 1 and manifest.get('lifecycle') == 'retain-provider-until-reboot', 'unknown_legacy_owner'
    # Verify every immutable file before requesting the running legacy manager
    # to stop. SIM-specific requests are checked against their existing manifest.
    assert isinstance(manifest.get('files'), dict) and manifest['files'], 'legacy_payload_changed'
    for name, expected in manifest['files'].items():
        assert isinstance(name, str) and not name.startswith('/') and '..' not in name.split('/') and '\\' not in name, 'legacy_payload_changed'
        path = base + '/' + name
        assert not os.path.islink(path), 'legacy_payload_changed'
        try:
            actual = n.digest(n.read(path))
        except (IOError, OSError):
            assert False, 'legacy_payload_changed'
        assert actual == expected, 'legacy_payload_changed'
    journal_path = base + '/state/journal.json'
    if os.path.lexists(journal_path):
        journal = _load_legacy_json(journal_path)
        assert journal.get('owner') == 'q10-unicom-volte-v1' and journal.get('original_voice_policy') == 0, 'legacy_payload_changed'
        assert not journal.get('nas_voice_trial'), 'unfinished_nas_trial'
    # Legacy service.py unloads software crypto on stop; never quiesce a live
    # legacy standalone manager on Passport in the same boot.
    if base == STANDARD_BASE and variant.startswith('SQW100-'):
        lock_path = base + '/state/lock.json'
        if os.path.isfile(lock_path):
            lock = _load_legacy_json(lock_path)
            if lock.get('boot') == legacy_boot(base) and s.alive(lock.get('pid')):
                assert False, 'unvalidated_legacy_installation'
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
