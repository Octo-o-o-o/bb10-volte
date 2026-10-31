"""Read-only, bounded call evidence recording for the owned Passport IMS process."""
import json
import os
import signal
import sys
import time
import passport_volte_phone as q


def registered():
    status = q.s.read_status()
    current = status['current']
    assert status.get('phase') == 'running' and status.get('status_from_current_boot') is True
    assert status.get('manager_alive') is True and status.get('native_alive') is True
    assert current.get('ims') == 'connected' and current.get('register_status') == '200 OK'
    assert current.get('radio') == ['lte']
    return status


def record(label):
    assert label in ('manual', 'after-reboot', 'continued-boot')
    q.setup()
    q.verify_inputs()
    pid = registered()['native_pid']
    if not os.path.isdir(q.EVIDENCE):
        os.mkdir(q.EVIDENCE, 0o700)
    assert not os.path.islink(q.EVIDENCE)
    active_path = q.EVIDENCE + '/active.json'
    if os.path.isfile(active_path):
        previous = q.s.load(active_path)
        assert previous['boot'] != q.s.boot_token() or os.path.isfile(previous['phone_folder'] + '/finished.json'), \
            'A recorder is already active'
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    folder = q.EVIDENCE + '/acceptance-' + label + '-' + stamp
    os.mkdir(folder, 0o700)
    meta = {'native_pid': pid, 'boot': q.s.boot_token(), 'label': label,
            'profile_id': q.s.ACTIVE_PROFILE['id'],
            'profile_sha256': q.profiles.fingerprint(q.s.ACTIVE_REQUEST),
            'carrier': {'mcc': q.s.ACTIVE_PROFILE['carrier']['mcc'],
                        'mncs': q.s.ACTIVE_PROFILE['carrier']['mncs']},
            'started_unix': time.time(), 'network_configuration_writes': 0,
            'service_stopped_or_reconfigured': False, 'max_samples': 450}
    q.n.atomic(folder + '/meta.json', json.dumps(meta).encode('ascii'))
    child = os.fork()
    if child:
        active = {'recorder_pid': child, 'native_pid': pid, 'phone_folder': folder,
                  'label': label, 'boot': meta['boot'], 'profile_sha256': meta['profile_sha256']}
        q.n.atomic(active_path, json.dumps(active).encode('ascii'))
        return active
    os.setsid()
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    null = os.open('/dev/null', os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(null, fd)
    if null > 2:
        os.close(null)
    os.umask(0o077)
    seen = set()
    samples = []
    try:
        for index in range(meta['max_samples']):
            if os.path.isfile(folder + '/stop-recording') or pid not in q.n.ims_pids():
                break
            data = q.n.command(['/bin/slog2info', '-b', 'ims_rrm'], 10).decode('utf-8', 'replace')
            lines = [line for line in data.splitlines() if 'ims_rrm.' + str(pid) + ' ' in line]
            fresh = [line for line in lines if line not in seen]
            seen = set(lines)
            if fresh:
                with open(folder + '/owned-ims.log', 'ab') as output:
                    output.write(('\n'.join(fresh) + '\n').encode('utf-8'))
            snapshot = {'at': time.time(), 'live': q.research_live(), 'active_call_counts': {}}
            for namespace in ('public', 'private'):
                path = '/pps/services/phone/' + namespace + '/calls'
                snapshot['active_call_counts'][namespace] = len(os.listdir(path)) if os.path.isdir(path) else None
            samples.append(snapshot)
            q.n.atomic(folder + '/samples.json', json.dumps(samples).encode('ascii'))
            time.sleep(2)
    except Exception as error:
        q.n.atomic(folder + '/recorder-error.json', json.dumps({'type': type(error).__name__}).encode('ascii'))
    finally:
        q.n.atomic(folder + '/finished.json', json.dumps({'finished_unix': time.time(),
            'samples': len(samples), 'network_or_service_modified': False}).encode('ascii'))
    os._exit(0)


def finish():
    q.setup()
    q.verify_inputs()
    active = q.s.load(q.EVIDENCE + '/active.json')
    assert active['boot'] == q.s.boot_token()
    folder = active['phone_folder']
    assert folder.startswith(q.EVIDENCE + '/acceptance-') and '..' not in folder
    if not os.path.isfile(folder + '/finished.json'):
        q.n.atomic(folder + '/stop-recording', b'owner finished call tests\n')
    for unused in range(15):
        if os.path.isfile(folder + '/finished.json'):
            break
        time.sleep(1)
    result = dict(active)
    result.update(finished=os.path.isfile(folder + '/finished.json'))
    return result


if __name__ == '__main__':
    action = sys.argv[1]
    result = record(sys.argv[2]) if action == 'record' else finish() if action == 'finish' else None
    assert result is not None
    print(json.dumps(result))
