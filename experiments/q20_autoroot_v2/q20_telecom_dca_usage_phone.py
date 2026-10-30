"""Two-phase Q20 DCA UE-usage experiment; exact source backups and rollback.

Only UE usage is appended to four empty, verified source objects. The normal
DCA publisher and qct_rrm's verified decoder perform any native NV operation.
No arbitrary modem write ABI, APN override, IMS engine or provider is used.
"""
import hashlib
import json
import os
import re
import signal
import stat
import sys
import time
import q20_volte_phone as q
from q20_telecom_native_probe_phone import QCT_HASH, ue_usage_policy

OWNER = 'q20-dca-usage-trial-v1'
POINTER = q.BASE + '/state/dca-usage-plan.json'
HEADER = b'@cellular_protocol_configuration\n'
SOURCES = ('ims', 'ims_defaults', 'omadm', 'test')


def source_path(name):
    assert name in SOURCES
    return '/var/dca/sources/' + name + '/services/carrier_config/radio_common/cellular_protocol_configuration'


def payload(original, usage):
    assert original in (b'', HEADER), 'Preserve a nonempty/unrecognized DCA source'
    assert usage in ('data_centric', 'voice_centric')
    return (original or HEADER) + ('ue_usage_setting::' + usage + '\n').encode('ascii')


def write_existing(path, before, after, item):
    assert not os.path.islink(path) and q.n.read(path) == before, 'Concurrent DCA source edit'
    info = os.stat(path)
    assert (info.st_ino, info.st_mode & 0o7777, info.st_uid, info.st_gid) == tuple(item['identity'])
    fd = os.open(path, os.O_WRONLY)
    try:
        assert os.write(fd, after) == len(after)
        os.ftruncate(fd, len(after))
        os.fsync(fd)
    finally:
        os.close(fd)
    assert q.n.read(path) == after
    info = os.stat(path)
    assert (info.st_ino, info.st_mode & 0o7777, info.st_uid, info.st_gid) == tuple(item['identity'])


def publish(folder, label):
    try:
        blob = q.n.command(['/usr/sbin/dca', '-s', '-a', '/pps'], 30)
        q.n.atomic(folder + '/dca-' + label + '.log', blob)
        return {'output_bytes': len(blob), 'output_sha256': q.n.digest(blob)}
    except Exception as error:
        # Rollback still restores files and reads NV if the publisher fails.
        return {'error_type': type(error).__name__, 'error_message': str(error)}


def plan():
    pointer = q.s.load(POINTER)
    assert pointer['owner'] == OWNER
    folder = pointer['folder']
    assert re.match(r'^/var/q20_volte/state/dca-usage-[0-9]{8}T[0-9]{6}Z$', folder)
    value = q.s.load(folder + '/plan.json')
    assert value['owner'] == OWNER and value['original_usage'] == 0 and value['original_voice'] == 0
    return folder, value


def restore(folder, value):
    assert q.s.phone_idle() and not q.n.ims_pids() and not q.n.active_vpn_sessions()
    result = {'sources_restored': False, 'ue_usage_restored': False, 'voice_restored': False}
    for name in SOURCES:
        item = value['files'][name]
        original = q.n.read(folder + '/' + name + '.original')
        assert q.n.digest(original) == item['original_sha256']
        current = q.n.read(source_path(name))
        assert current in (original, payload(original, 'data_centric'), payload(original, 'voice_centric'))
        if current != original:
            write_existing(source_path(name), current, original, item)
    result['publish'] = publish(folder, 'restore')
    for unused in range(3):
        try:
            if ue_usage_policy() == 0:
                result['ue_usage_restored'] = True
                break
        except Exception:
            pass
        time.sleep(3)
    if not result['ue_usage_restored']:
        # Force an explicit original usage through the same supported parser,
        # then put the original missing-key state back. No raw EFS setter.
        for name in SOURCES:
            item = value['files'][name]
            original = q.n.read(folder + '/' + name + '.original')
            write_existing(source_path(name), original, payload(original, 'voice_centric'), item)
        result['explicit_original_publish'] = publish(folder, 'restore-explicit')
        for unused in range(8):
            try:
                if ue_usage_policy() == 0:
                    result['ue_usage_restored'] = True
                    break
            except Exception:
                pass
            time.sleep(3)
        for name in SOURCES:
            item = value['files'][name]
            original = q.n.read(folder + '/' + name + '.original')
            write_existing(source_path(name), payload(original, 'voice_centric'), original, item)
        result['final_original_publish'] = publish(folder, 'restore-final')
    result['sources_restored'] = all(q.n.digest(q.n.read(source_path(name))) ==
                                    value['files'][name]['original_sha256'] for name in SOURCES)
    active = q.s.load(folder + '/report.json') if os.path.isfile(folder + '/report.json') else {}
    if active.get('voice_preference_change_attempted') is True:
        try:
            current_voice = q.n.voice_policy()
        except Exception:
            current_voice = None
        assert current_voice in (None, 0, 3), 'Concurrent native voice policy change'
        if current_voice != 0:
            result['voice_restore_setter'] = q.s.set_voice_preference(4)
            assert result['voice_restore_setter']['rc'] == 0
    for unused in range(8):
        try:
            result['after_ue_usage'], result['after_voice'] = ue_usage_policy(), q.n.voice_policy()
            result['ue_usage_restored'], result['voice_restored'] = result['after_ue_usage'] == 0, result['after_voice'] == 0
            if result['ue_usage_restored'] and result['voice_restored']:
                break
        except Exception as error:
            result['readback_error_type'] = type(error).__name__
        time.sleep(3)
    result['restored'] = all(result[key] for key in ('sources_restored', 'ue_usage_restored', 'voice_restored'))
    q.n.atomic(folder + '/restore.json', json.dumps(result, indent=2).encode('ascii'))
    if result['restored']:
        q.n.atomic(folder + '/done', b'original sources, UE usage00 and voice00 verified\n')
    return result


def prepare():
    assert q.s.phone_idle() and not q.n.ims_pids() and not q.n.active_vpn_sessions()
    assert ue_usage_policy() == 0 and q.n.voice_policy() == 0
    assert q.n.crypto_policy()['swcr_id'] == -1 and not os.path.exists(q.BASE + '/enabled')
    assert all(q.c.configuration_diagnostics().values())
    assert q.s.ACTIVE_PROFILE['carrier']['mncs'] == ['11']
    assert os.path.isfile('/usr/sbin/dca')
    if os.path.isfile(POINTER):
        prior_folder, prior_plan = plan()
        assert os.path.isfile(prior_folder + '/done'), 'Finish the earlier trial first'
    folder = q.s.STATE + '/dca-usage-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    os.mkdir(folder, 0o700)
    value = {'owner': OWNER, 'boot': q.boot_token(), 'original_usage': 0, 'original_voice': 0,
             'sim_fingerprint': hashlib.sha256(q.s.current_usim().encode('ascii')).hexdigest(),
             'dca_sha256': q.n.digest(q.n.read('/usr/sbin/dca')), 'files': {}}
    for name in SOURCES:
        path = source_path(name)
        assert not os.path.islink(path)
        info, original = os.lstat(path), q.n.read(path)
        assert stat.S_ISREG(info.st_mode)
        applied = payload(original, 'data_centric')
        value['files'][name] = {'path': path, 'original_sha256': q.n.digest(original),
            'applied_sha256': q.n.digest(applied),
            'identity': [info.st_ino, info.st_mode & 0o7777, info.st_uid, info.st_gid]}
        q.n.atomic(folder + '/' + name + '.original', original)
    q.n.atomic(folder + '/plan.json', json.dumps(value, indent=2).encode('ascii'))
    q.n.atomic(POINTER, json.dumps({'owner': OWNER, 'folder': folder}).encode('ascii'))
    return {'prepared': True, 'folder': folder, 'plan': value,
            'plan_sha256': q.n.digest(q.n.read(folder + '/plan.json')), 'configuration_writes': 0}


def run(folder, value, reload_voice=False):
    assert not os.path.exists(folder + '/done'), 'Prepare a new backed-up trial'
    assert value['boot'] == q.boot_token()
    assert hashlib.sha256(q.s.current_usim().encode('ascii')).hexdigest() == value['sim_fingerprint']
    assert ue_usage_policy() == 0 and q.n.voice_policy() == 0 and q.s.phone_idle()
    assert not q.n.ims_pids() and not q.n.active_vpn_sessions() and not os.path.exists(q.BASE + '/enabled')
    receipt = q.s.load(folder + '/desktop-backup-receipt.json')
    assert receipt['owner'] == OWNER and receipt['all_original_hashes_verified'] is True
    assert receipt['plan_sha256'] == q.n.digest(q.n.read(folder + '/plan.json'))
    assert q.n.digest(q.n.read('/usr/sbin/dca')) == value['dca_sha256']
    report = {'owner': OWNER, 'folder': folder, 'apn_changes': 0, 'ims_changes': 0,
              'crypto_operations': 0, 'calls_placed': 0, 'observations': [],
              'reload_voice_requested': reload_voice, 'voice_preference_change_attempted': False}
    path = folder + '/report.json'

    def save():
        q.n.atomic(path, json.dumps(report, indent=2).encode('ascii'))

    save()
    if os.fork() == 0:
        try:
            os.setsid()
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
            null = os.open('/dev/null', os.O_RDWR)
            for descriptor in (0, 1, 2):
                os.dup2(null, descriptor)
            if null > 2:
                os.close(null)
            deadline = time.time() + 240
            while time.time() < deadline and not os.path.exists(folder + '/done'):
                time.sleep(2)
            if not os.path.exists(folder + '/done'):
                q.verify()
                restore(folder, value)
        finally:
            os._exit(0)

    def interrupted(signum, frame):
        raise RuntimeError('Interrupted; restore exact DCA sources and original UE usage')

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    try:
        report['application_attempted'] = True
        save()
        for name in SOURCES:
            item = value['files'][name]
            original = q.n.read(folder + '/' + name + '.original')
            assert q.n.digest(original) == item['original_sha256']
            write_existing(source_path(name), original, payload(original, 'data_centric'), item)
        report['publish'] = publish(folder, 'apply')
        assert 'error_type' not in report['publish'], 'DCA publisher failed; restore original state'
        if reload_voice:
            assert ue_usage_policy() == 1 and q.s.phone_idle() and not q.n.ims_pids()
            assert hashlib.sha256(q.s.current_usim().encode('ascii')).hexdigest() == value['sim_fingerprint']
            report['voice_preference_change_attempted'] = True
            save()
            report['voice_setter'] = q.s.set_voice_preference(1)
            assert report['voice_setter']['rc'] == 0
        deadline = time.time() + 65
        for unused in range(12):
            assert q.s.phone_idle() and not q.n.ims_pids()
            network = q.c.read_network(q.s.ACTIVE_PROFILE)
            if network.get('sim_state') == 'READY':
                assert hashlib.sha256(q.s.current_usim().encode('ascii')).hexdigest() == value['sim_fingerprint']
            observation = {'at': time.time(), 'network': network}
            try:
                observation.update(ue_usage_setting=ue_usage_policy(), voice_policy=q.n.voice_policy())
            except Exception as error:
                observation['read_error_type'] = type(error).__name__
            report['observations'].append(observation)
            save()
            if time.time() >= deadline:
                break
            time.sleep(4)
    except Exception as error:
        report['error_type'], report['error_message'] = type(error).__name__, str(error)
    finally:
        report['restore'] = restore(folder, value)
        save()
    return report


def main():
    q.setup()
    q.verify()
    assert q.n.digest(q.n.read('/radio/bin/qct_rrm')) == QCT_HASH
    action = sys.argv[1]
    assert action in ('prepare', 'run', 'run-reload', 'restore')
    if action == 'prepare':
        result = prepare()
    else:
        folder, value = plan()
        result = run(folder, value, action == 'run-reload') if action in ('run', 'run-reload') else restore(folder, value)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
