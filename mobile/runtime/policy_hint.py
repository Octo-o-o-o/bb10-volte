"""One durable restart suggestion for a verified, restored Passport policy.

This observes the existing engine. It never publishes, changes NV, starts IMS,
resumes a job or creates device state. Only the mobile hint record is written.
Python 3.2; keep the incident independent of app version and boot timestamps.
"""
import os
import re
import stat
import time
import binascii
import entry as e

OWNER = 'bb10-mobile-policy-restart-hint-v1'
MARKERS = ('install-pending.json', 'update-pending.json', 'rollback-pending.json',
           'uninstall-pending.json', 'uninstalled.json', 'state/stop-request')


def require(value):
    e.require(value, 'policy_hint_unavailable')


def token_valid(value):
    return (isinstance(value, list) and len(value) == 2 and
            value[0] == 'bb10-unified-carriers-v1' and isinstance(value[1], str) and
            re.match(r'\A[0-9a-f]{48}\Z', value[1]))


def directory(path, private=True):
    info = os.lstat(path)
    require(os.path.realpath(path) == path and stat.S_ISDIR(info.st_mode) and
            info.st_uid == os.geteuid() and info.st_mode & (0o077 if private else 0o022) == 0)


def existing_management_lock(manager):
    # The shared context can create missing bookkeeping. Hints must not do so.
    # Do not open/close this inode here: closing any FD can release a POSIX lock
    # already held by the same process during a reentrant inspection.
    directory(manager.MANAGEMENT)
    path = manager.MANAGEMENT + '/lock'
    info = os.lstat(path)
    require(os.path.realpath(path) == path and stat.S_ISREG(info.st_mode) and
            info.st_uid == os.geteuid() and info.st_nlink == 1 and info.st_mode & 0o077 == 0)


def read_file(path, private=True, maximum=4194304):
    require(os.path.realpath(path) == path)
    before = os.lstat(path)
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
            0 <= before.st_size <= maximum)
    if private:
        require(before.st_uid == os.geteuid() and before.st_mode & 0o077 == 0)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as source:
        opened = os.fstat(source.fileno())
        require((before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino))
        data = source.read(maximum + 1)
        after = os.fstat(source.fileno())
    current = os.lstat(path)
    identity = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_uid,
                             item.st_gid, item.st_nlink, item.st_size)
    require(identity(before) == identity(opened) == identity(after) == identity(current) and
            len(data) == before.st_size)
    return data, [before.st_ino, before.st_mode & 0o7777, before.st_uid, before.st_gid]


def barrier(path, expected):
    """QNX persistence needs a writable final FD, without truncate or recreate."""
    raw, unused = read_file(path)
    require(raw == expected)
    before = os.lstat(path)
    fd = os.open(path, os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        opened = os.fstat(fd)
        require((before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino))
        os.fsync(fd)
        current = os.lstat(path)
        require((current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino))
    finally:
        os.close(fd)
    require(read_file(path)[0] == expected)


def persist(path, value):
    raw = e.canonical(value)
    temporary = path + '.new-' + binascii.hexlify(os.urandom(16)).decode('ascii')
    try:
        e.write_new(temporary, raw)
        os.rename(temporary, path)
        barrier(path, raw)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def candidate(result):
    status = result.get('status') or {}
    return (result.get('installed') is True and result.get('installed_stage') == 'managed' and
            result.get('installed_management_schema') == 2 and result.get('family') == 'passport' and
            result.get('operator') == 'unicom' and result.get('sim_supported') is True and
            result.get('call_idle') is True and not result.get('installation_pending') and
            not result.get('update_pending') and not result.get('update_available') and
            status.get('phase') == 'error_restored' and status.get('enabled') is True and
            status.get('status_from_current_boot') is True and status.get('selected_this_boot') is True and
            status.get('current_sim_matches') is True and status.get('manager_alive') is False and
            status.get('native_alive') is False)


class Observation:
    def __init__(self, manager, root):
        import unified_service
        import unified_dca
        import carrier_policy
        import native
        import service
        import device_info
        self.m, self.root = manager, root
        self.u, self.d, self.p = unified_service, unified_dca, carrier_policy
        self.n, self.s, self.device = native, service, device_info

    def binding(self, variant):
        m, u, p = self.m, self.u, self.p
        for path in (self.root, m.MANAGEMENT, m.BASE + '/state', m.BASE + '/backup'):
            directory(path)
        directory(m.BASE, private=False)
        facts = self.device.read_identity()
        require(facts['variant'] == variant)
        selected = p.select(facts, u.card())
        require(selected['family'] == 'passport' and selected['operator'] == 'unicom')
        raw = {}
        for path in (m.MANAGEMENT + '/device.json', m.BASE + '/management.json',
                     m.BASE + '/backup/manifest.json', u.BOOT):
            raw[path] = read_file(path)[0]
        identity = m.management_identity({'variant': variant}, create=False)
        boot = u.boot_token(False)
        require(token_valid(boot))
        require(re.match(r'\A[0-9a-f]{64}\Z', selected['sim_sha256']))
        binding = {'device': identity['device'], 'installation_id': identity['installation_id'],
                   'backup_manifest_sha256': e.digest(raw[m.BASE + '/backup/manifest.json']),
                   'sim_sha256': selected['sim_sha256'], 'family': 'passport',
                   'operator': 'unicom', 'desired': 0}
        path = self.root + '/policy-restart-hint-' + e.digest(e.canonical(binding)) + '.json'
        return binding, path, boot, raw

    def proof(self, result):
        m, u, d, s, n, p = self.m, self.u, self.d, self.s, self.n, self.p
        binding, path, boot, raw = self.binding(result['variant'])
        for name in MARKERS:
            require(not os.path.lexists(m.BASE + '/' + name))
        raw[m.BASE + '/enabled'] = read_file(m.BASE + '/enabled')[0]
        records = {}
        for name in ('status', 'selection', 'native-attempt', 'dca', 'journal'):
            item = m.BASE + '/state/' + name + '.json'
            raw[item] = read_file(item)[0]
            records[name] = e.json_bytes(raw[item])
        status, selection, attempt, policy, journal = [records[name] for name in
            ('status', 'selection', 'native-attempt', 'dca', 'journal')]
        require(status.get('boot') == boot and status.get('phase') == 'error_restored' and
                status.get('error') == 'usage_restore_unconfirmed' and status.get('native_pid') is None)
        require(selection.get('boot') == boot and selection.get('sim_sha256') == binding['sim_sha256'] and
                selection.get('family') == 'passport' and selection.get('operator') == 'unicom')
        require(attempt.get('owner') == p.OWNER and attempt.get('boot') == boot)
        require(policy.get('owner') == p.OWNER and policy.get('boot') == boot and
                policy.get('policy_changed_boot') == boot and policy.get('phase') == 'applying' and
                type(policy.get('desired')) is int and policy['desired'] == 0 and
                type(policy.get('ue_usage_before')) is int and policy['ue_usage_before'] == 1 and
                policy.get('source_repair_only') is False and policy.get('operator') == 'unicom' and
                policy.get('sim_sha256') == binding['sim_sha256'] and
                isinstance(policy.get('publish'), dict) and 'error_type' not in policy['publish'])
        require(journal.get('owner') == 'q10-unicom-volte-v1' and journal.get('boot') == boot and
                journal.get('sim_sha256') == binding['sim_sha256'] and journal.get('operator') == 'unicom' and
                type(journal.get('original_voice_policy')) is int and journal['original_voice_policy'] == 0 and
                journal.get('native_pid') is None and journal.get('managed_files') == {} and
                journal.get('configuration_restored') is True and journal.get('restore_completed') is True and
                journal.get('provider_retained_until_reboot') is False)
        if os.path.lexists(s.LOCK):
            raw[s.LOCK] = read_file(s.LOCK)[0]
            lock = e.json_bytes(raw[s.LOCK])
            require(not (lock.get('boot') == boot and lock.get('pid') and s.alive(lock['pid'])))
        receipt = m.BASE + '/backup-receipt.json'
        if not os.path.lexists(receipt):
            receipt = m.BASE + '/desktop-backup-receipt.json'
        raw[receipt] = read_file(receipt)[0]
        manifest = e.json_bytes(raw[m.BASE + '/backup/manifest.json'])
        require(set(manifest['files']) == set(name + '.original' for name in d.dca.SOURCES))
        for name in d.dca.SOURCES:
            original_path = m.BASE + '/backup/' + name + '.original'
            raw[original_path] = read_file(original_path)[0]
            require(e.digest(raw[original_path]) == manifest['files'][name + '.original'])
        files, originals = d.originals()  # includes the existing backup receipt verifier
        sources = {}
        for name in d.dca.SOURCES:
            source = d.dca.source_path(name)
            data, identity = read_file(source, private=False)
            require(identity == list(files[name]['identity']) and
                    data == d.dca.payload(originals[name], 'voice_centric'))
            sources[source] = {'sha256': e.digest(data), 'identity': identity}
        published = n.read(s.VOICE)
        require(n.value(n.attrs(published), 'ue_usage_setting') == 'voice_centric')
        fingerprint = {'files': {key: e.digest(value) for key, value in raw.items()},
                       'sources': sources, 'published': e.digest(published), 'binding': binding}
        return {'binding': binding, 'path': path, 'boot': boot,
                'digest': e.digest(e.canonical(fingerprint))}

    def live_once(self):
        require(self.s.phone_idle() and not self.n.ims_pids() and not self.n.active_vpn_sessions())
        require(self.n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0})
        require(self.d.radio.ue_usage_policy() == 1 and self.n.voice_policy() == 0)


def record(path, binding):
    if not os.path.lexists(path):
        return None
    raw = read_file(path)[0]
    value = e.json_bytes(raw)
    require(isinstance(value, dict) and value.get('schema') == 1 and value.get('owner') == OWNER and
            value.get('binding') == binding and value.get('phase') in ('issued', 'exhausted', 'resolved') and
            token_valid(value.get('first_boot')) and isinstance(value.get('proof_sha256'), str) and
            re.match(r'\A[0-9a-f]{64}\Z', value['proof_sha256']) and
            type(value.get('verified_at')) is int)
    if value['phase'] == 'resolved':
        require(token_valid(value.get('resolved_boot')))
    return value


def suggestion(result, manager, root):
    if not candidate(result):
        return None
    try:
        existing_management_lock(manager)
        with manager.management_lock(blocking=False):
            observation = Observation(manager, root)
            proof = observation.proof(result)
            path, boot = proof['path'], proof['boot']
            old = record(path, proof['binding'])
            if old and old['phase'] in ('issued', 'exhausted'):
                if old['first_boot'] != boot or old['phase'] == 'exhausted':
                    if old['phase'] != 'exhausted':
                        old['phase'] = 'exhausted'
                        persist(path, old)
                    else:
                        barrier(path, e.canonical(old))
                    return 'policy_restart_unconfirmed'
                require(old['proof_sha256'] == proof['digest'])
                barrier(path, e.canonical(old))
                return 'policy_restart_once'
            if old and old.get('resolved_boot') == boot:
                return None
            observation.live_once()
            require(observation.proof(result) == proof)
            issued = {'schema': 1, 'owner': OWNER, 'binding': proof['binding'], 'phase': 'issued',
                      'first_boot': boot, 'proof_sha256': proof['digest'], 'verified_at': int(time.time())}
            persist(path, issued)
            return 'policy_restart_once'
    except Exception:
        # Retain malformed/spent records and use ordinary recovery on uncertainty.
        return None


def resolve(result, context, manager, root):
    """Called only after worker.registered; never infer registration from NV or a job."""
    try:
        if result.get('family') != 'passport' or result.get('operator') != 'unicom':
            return
        existing_management_lock(manager)
        with manager.management_lock(blocking=False):
            observation = Observation(manager, root)
            binding, path, boot, unused = observation.binding(result['variant'])
            require(context['binding']['boot'] == boot and context['binding']['sim'] == binding['sim_sha256'])
            current = e.json_bytes(read_file(manager.BASE + '/state/status.json')[0])
            selected = e.json_bytes(read_file(manager.BASE + '/state/selection.json')[0])
            require(current.get('boot') == boot and current.get('phase') == 'running' and
                    selected.get('boot') == boot and selected.get('sim_sha256') == binding['sim_sha256'])
            old = record(path, binding)
            if old and old['phase'] != 'resolved':
                old.update(phase='resolved', resolved_boot=boot)
                persist(path, old)
    except Exception:
        # Failure to save resolution must not hide real, current registration.
        pass
