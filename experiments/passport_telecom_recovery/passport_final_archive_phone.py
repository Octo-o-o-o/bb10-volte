"""Save accepted metadata and freeze private evidence without changing IMS."""
import json
import os
import stat
import sys
import time

BASE = '/var/rootdata/passport_volte_research'
sys.path.insert(0, BASE)
sys.path.insert(0, BASE + '/device')
import passport_volte_phone as q


def main():
    q.setup()
    q.verify_inputs()
    before = q.public_status()
    assert before['phase'] == 'running' and before['manager_alive'] and before['native_alive']
    assert before['current']['ims'] == 'connected' and before['current']['register_status'] == '200 OK'
    assert before['current']['radio'] == ['lte']
    request = q.s.load(BASE + '/final-acceptance-request.json')
    assert request['owner'] == 'passport-telecom-final-request-v2'
    assert request['boot'] == q.s.boot_token() and request['native_pid'] == before['native_pid']
    assert request['profile_sha256'] == q.profiles.fingerprint(q.s.ACTIVE_REQUEST)
    assert all(request[key] is True for key in ('owner_audio_confirmed', 'owner_lte_confirmed',
                                               'owner_name_confirmed', 'both_directions_verified'))
    receipt = q.acceptance_receipt()
    fingerprint = q.telecom_acceptance_sim(receipt)
    assert receipt['raw_log_sha256'] == request['manual_log_sha256']
    folder = request['post_reboot_folder']
    assert folder.startswith(q.EVIDENCE + '/acceptance-after-reboot-') and '..' not in folder
    assert not os.path.islink(folder)
    meta = q.s.load(folder + '/meta.json')
    assert meta['boot'] == request['boot'] and meta['native_pid'] == request['native_pid']
    assert q.n.digest(q.n.read(folder + '/owned-ims.log')) == request['post_reboot_log_sha256']
    assert not os.path.isfile(q.s.STATE + '/lease.json') and not os.path.isfile(q.s.STATE + '/watchdog.json')
    request.update(owner='passport-telecom-complete-v2', sim_fingerprint=fingerprint,
                   native_manifest_sha256=q.n.digest(q.n.read(BASE + '/research-manifest.json')),
                   accepted_unix=time.time(), network_configuration_writes=0, service_start_requests=0)
    q.n.atomic(q.s.STATE + '/telecom-boot-acceptance.json', json.dumps(request, indent=2).encode('ascii'))
    destination = '/var/passport_telecom_final_' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    os.mkdir(destination, 0o700)
    files, total = [], 0

    def copy(source, name):
        nonlocal total
        assert not os.path.islink(source)
        info = os.stat(source)
        assert stat.S_ISREG(info.st_mode) and info.st_size < 16777216
        blob = q.n.read(source)
        total += len(blob)
        assert len(files) < 2500 and total < 67108864
        target = destination + '/' + name
        parent = os.path.dirname(target)
        if not os.path.isdir(parent):
            os.makedirs(parent, 0o700)
        q.n.atomic(target, blob, 0o600)
        files.append({'file': name, 'bytes': len(blob), 'sha256': q.n.digest(blob)})

    for root, prefix in ((BASE, 'passport_volte_research'),
                         ('/var/rootdata/passport_operator_name', 'passport_operator_name')):
        for parent, dirs, names in os.walk(root, followlinks=False):
            assert not os.path.islink(parent)
            assert all(not os.path.islink(parent + '/' + name) for name in dirs)
            for name in sorted(names):
                path = parent + '/' + name
                copy(path, prefix + '/' + path[len(root) + 1:])
    copy(q.s.XML, 'private-identity/imsconfig_user.xml')
    for name in ('ims', 'ims_defaults', 'omadm', 'test'):
        copy('/var/dca/sources/' + name + '/services/carrier_config/radio_common/'
             'cellular_protocol_configuration', 'active-dca/' + name + '.pps')
    for addon in ('passport-volte', 'passport-operator-name'):
        copy('/var/addons/' + addon + '/init/start.sh', 'addons/' + addon + '/start.sh')
    after = q.public_status()
    q.verify_inputs()
    assert after['phase'] == 'running' and after['native_alive'] and after['current']['ims'] == 'connected'
    assert before['native_pid'] == after['native_pid'] and request['boot'] == q.s.boot_token()
    result = {'folder': destination, 'files': files, 'file_count': len(files), 'bytes': total,
              'before': before, 'after': after, 'boot': request['boot'],
              'network_configuration_writes': 0, 'service_interrupted': False,
              'consistency': 'per-file frozen snapshot; current native process checked before and after',
              'private_only': True}
    q.n.atomic(destination + '/manifest.json', json.dumps(result, indent=2).encode('ascii'))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
