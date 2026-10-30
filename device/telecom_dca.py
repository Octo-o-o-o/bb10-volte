"""Backed-up DCA UE usage support derived from the accepted Q20 implementation; exact source backups and rollback.

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
from telecom_native import QCT_HASH, ue_usage_policy
q = None  # Bound explicitly to the running service context, never on import.

OWNER = 'bb10-telecom-attach-v1'
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
    fd = os.open(path, os.O_RDWR | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    try:
        opened = os.fstat(fd)
        assert (opened.st_ino, opened.st_mode & 0o7777, opened.st_uid, opened.st_gid) == tuple(item['identity'])
        assert os.read(fd, 4096) == before, 'Concurrent DCA edit after open'
        os.lseek(fd, 0, os.SEEK_SET)
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
    pointer = q.s.load(q.s.STATE + '/telecom-plan.json')
    assert pointer['owner'] == OWNER
    folder = pointer['folder']
    assert re.match(r'^' + re.escape(q.s.STATE) + r'/telecom-attach-[a-f0-9]{16}$', folder)
    assert os.path.realpath(folder) == folder and not os.path.islink(folder)
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
