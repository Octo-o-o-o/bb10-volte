"""Q10-only native/source preflight and bounded private rollback snapshot."""
import ctypes
import json
import os
import stat
import sys
import time
import native as n
import compatibility as c
import device_info
import telecom_native
import telecom_dca

BASE = '/var/rootdata/q10_volte'
ADDON = '/var/addons/q10-unicom-volte'


def main():
    assert os.geteuid() == 0 and os.uname()[0] == 'QNX' and ctypes.sizeof(ctypes.c_void_p) == 4
    identity = device_info.read_identity()
    assert identity['variant'] == 'SQN100-3' and identity['os_version'] == '10.3.3.3216'
    n.verify_stock()
    assert c.installed_state()['payload_verified'] is True
    assert all(os.path.isdir(path) and not os.listdir(path) for path in
               ('/pps/services/phone/public/calls', '/pps/services/phone/private/calls'))
    assert n.digest(n.read('/radio/bin/qct_rrm')) == telecom_native.QCT_HASH
    assert n.digest(n.read('/usr/sbin/dca')) == telecom_native.DCA_HASH
    usage = telecom_native.ue_usage_policy()
    source_facts = {}
    for name in telecom_dca.SOURCES:
        path = telecom_dca.source_path(name)
        blob = n.read(path)
        info = os.lstat(path)
        assert stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
        source_facts[name] = {'sha256': n.digest(blob), 'bytes': len(blob),
                              'known_empty_baseline': blob in (b'', telecom_dca.HEADER)}
    before = {'voice_policy': n.voice_policy(), 'ue_usage_setting': usage,
              'crypto': n.crypto_policy(), 'ims_pids': n.ims_pids(),
              'enabled': os.path.isfile(BASE + '/enabled')}
    folder = '/var/q10_evidence_' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    os.mkdir(folder, 0o700)
    files, total = [], 0

    def copy(source, name):
        nonlocal total
        assert not os.path.islink(source)
        info = os.stat(source)
        assert stat.S_ISREG(info.st_mode) and info.st_size < 16777216
        blob = n.read(source)
        total += len(blob)
        assert len(files) < 2000 and total < 67108864
        target = folder + '/' + name
        parent = os.path.dirname(target)
        if not os.path.isdir(parent):
            os.makedirs(parent, 0o700)
        n.atomic(target, blob)
        files.append({'file': name, 'bytes': len(blob), 'sha256': n.digest(blob),
                      'source_mode': info.st_mode & 0o7777})

    for base, label in ((BASE, 'q10_volte'), (ADDON, 'addon')):
        for parent, dirs, names in os.walk(base, followlinks=False):
            assert not os.path.islink(parent) and all(not os.path.islink(parent + '/' + name) for name in dirs)
            for name in sorted(names):
                source = parent + '/' + name
                copy(source, label + '/' + source[len(base) + 1:])
    for name in telecom_dca.SOURCES:
        copy(telecom_dca.source_path(name), 'dca-originals/' + name + '.pps')
    if os.path.isfile('/var/ims/carrier/imsconfig_user.xml'):
        copy('/var/ims/carrier/imsconfig_user.xml', 'private-identity/imsconfig_user.xml')
    for label, source in (('cdsc', c.DATA_SETTINGS), ('radio', c.RADIO), ('data', c.DATA)):
        # PPS data is copied privately; only hashes and bounded facts are exported.
        blob = n.read(source)
        n.atomic(folder + '/' + label + '.pps', blob)
        files.append({'file': label + '.pps', 'bytes': len(blob), 'sha256': n.digest(blob)})
        total += len(blob)
    after = {'voice_policy': n.voice_policy(), 'ue_usage_setting': telecom_native.ue_usage_policy(),
             'crypto': n.crypto_policy(), 'ims_pids': n.ims_pids(),
             'enabled': os.path.isfile(BASE + '/enabled')}
    assert before == after, 'Service changed during snapshot; preserve evidence and inspect'
    record = {'schema': 1, 'variant': 'SQN100-3', 'os_version': '10.3.3.3216', 'folder': folder,
              'files': files, 'file_count': len(files), 'bytes': total, 'before': before, 'after': after,
              'source_facts': source_facts, 'qct_sha256': telecom_native.QCT_HASH, 'dca_sha256': telecom_native.DCA_HASH,
              'configuration_writes': 0, 'service_interrupted': False, 'private_data_must_stay_private': True}
    n.atomic(folder + '/manifest.json', json.dumps(record, indent=2).encode('ascii'))
    print(json.dumps(record))


if __name__ == '__main__':
    main()
