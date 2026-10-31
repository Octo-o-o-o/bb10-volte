"""Freeze the Q20 carrier epoch before cleanup, including an inactive epoch."""
import json
import os
import stat
import time
import q20_volte_phone as q


def main():
    q.setup()
    q.verify()
    assert q.s.phone_idle()
    before = q.status()
    assert before.get('manager_alive') is False and not q.n.ims_pids()
    folder = '/var/q20_transition_' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    os.mkdir(folder, 0o700)
    files, total = [], 0

    def copy(source, name):
        nonlocal total
        assert not os.path.islink(source)
        info = os.stat(source)
        assert stat.S_ISREG(info.st_mode) and info.st_size < 16777216
        blob = q.n.read(source)
        total += len(blob)
        assert len(files) < 2000 and total < 67108864
        target = folder + '/' + name
        parent = os.path.dirname(target)
        if not os.path.isdir(parent):
            os.makedirs(parent, 0o700)
        q.n.atomic(target, blob, 0o600)
        files.append({'file': name, 'source': source, 'bytes': len(blob),
                      'sha256': q.n.digest(blob), 'source_mode': info.st_mode & 0o7777})

    for parent, dirs, names in os.walk(q.BASE, followlinks=False):
        assert not os.path.islink(parent)
        assert all(not os.path.islink(parent + '/' + name) for name in dirs)
        for name in sorted(names):
            copy(parent + '/' + name, 'q20_volte/' + (parent + '/' + name)[len(q.BASE) + 1:])
    for name in ('ims', 'ims_defaults', 'omadm', 'test'):
        copy('/var/dca/sources/' + name + '/services/carrier_config/radio_common/'
             'cellular_protocol_configuration', 'active-dca/' + name + '.pps')
    for name, source in [('identity', q.s.XML), ('ims', q.s.IMS), ('cdsc', q.s.CDSC),
                         ('voice', q.s.VOICE), ('radio', q.s.RADIO)]:
        if os.path.isfile(source):
            copy(source, 'active-private/' + name)
    copy('/apps/sys.android.gYABgKAOw1czN6neiAT72SGO.ns/native/system/xbin/btool', 'root-v2/btool')
    after = q.status()
    assert before['boot'] == after['boot'] and not q.n.ims_pids() and q.s.phone_idle()
    record = {'schema': 1, 'variant': 'SQC100-2', 'folder': folder, 'files': files,
              'file_count': len(files), 'bytes': total, 'before': before, 'after': after,
              'network': q.c.read_network(q.s.ACTIVE_PROFILE),
              'baseline': {'voice': q.n.voice_policy(), 'crypto': q.n.crypto_policy(),
                           'vpn_sessions': q.n.active_vpn_sessions()},
              'configuration_writes': 0, 'service_interrupted': False,
              'private_data_must_stay_private': True}
    q.n.atomic(folder + '/manifest.json', json.dumps(record, indent=2).encode('ascii'))
    print(json.dumps(record))


if __name__ == '__main__':
    main()
