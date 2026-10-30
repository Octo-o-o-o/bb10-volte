"""Freeze private evidence files without stopping or reconfiguring Q20 IMS."""
import json
import os
import stat
import time
import q20_volte_phone as q


def main():
    q.setup()
    q.verify()
    before = q.status()
    assert before['registered'] is True and before['enabled'] is True
    assert q.s.phone_idle()
    folder = '/var/q20_evidence_' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
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
            source = parent + '/' + name
            copy(source, 'q20_volte/' + source[len(q.BASE) + 1:])
    for name in ('ims', 'ims_defaults', 'omadm', 'test'):
        copy('/var/dca/sources/' + name + '/services/carrier_config/radio_common/'
             'cellular_protocol_configuration', 'active-dca/' + name + '.pps')
    copy(q.s.XML, 'private-identity/imsconfig_user.xml')
    copy('/apps/sys.android.gYABgKAOw1czN6neiAT72SGO.ns/native/system/xbin/btool', 'root-v2/btool')
    after = q.status()
    assert after['registered'] is True and after['enabled'] is True
    assert before['boot'] == after['boot'] and before['native_pid'] == after['native_pid']
    record = {'schema': 1, 'variant': 'SQC100-2', 'folder': folder, 'files': files,
              'file_count': len(files), 'bytes': total, 'before': before, 'after': after,
              'configuration_writes': 0, 'service_interrupted': False,
              'consistency': 'per-file frozen snapshot; live state sampled before and after',
              'private_data_must_stay_private': True}
    q.n.atomic(folder + '/manifest.json', json.dumps(record, indent=2).encode('ascii'))
    print(json.dumps(record))


if __name__ == '__main__':
    main()
