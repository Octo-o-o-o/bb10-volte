"""Read-only bounded manifest of this task's Q20 files for private backup."""
import json
import os
import stat
import q20_volte_phone as q


def main():
    q.setup()
    q.verify()
    assert q.s.phone_idle() and not os.path.exists(q.BASE + '/enabled')
    assert not q.n.ims_pids() and not q.n.active_vpn_sessions()
    assert q.n.voice_policy() == 0 and q.n.crypto_policy()['swcr_id'] == -1
    assert all(q.c.configuration_diagnostics().values())
    files = []
    total = 0
    for parent, dirs, names in os.walk(q.BASE, followlinks=False):
        assert not os.path.islink(parent)
        assert all(not os.path.islink(parent + '/' + name) for name in dirs)
        for name in sorted(names):
            path = parent + '/' + name
            info = os.lstat(path)
            assert stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
            assert len(files) < 2000 and info.st_size < 16777216
            total += info.st_size
            assert total < 67108864
            blob = q.n.read(path)
            assert len(blob) == info.st_size
            files.append({'file': path[len(q.BASE) + 1:], 'bytes': len(blob),
                          'mode': info.st_mode & 0o7777, 'sha256': q.n.digest(blob)})
    print(json.dumps({'variant': 'SQC100-2', 'base': q.BASE, 'files': files,
        'bytes': total, 'file_count': len(files), 'voice_policy': 0,
        'crypto_provider': -1, 'carrier_configuration_clean': True,
        'autostart_enabled': False, 'private_data_must_stay_private': True}))


if __name__ == '__main__':
    main()
