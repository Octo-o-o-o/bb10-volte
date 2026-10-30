"""Read-only, bounded call evidence for the owned Q10 Telecom IMS process."""
import json
import os
import re
import signal
import sys
import time
import ctypes
import native as n
import service as s
import profiles
import compatibility
import device_info

class Context(object):
    pass
q = Context()
q.n, q.s, q.profiles = n, s, profiles
q.live, q.boot_token = s.live, s.boot_token


def verify():
    assert os.geteuid() == 0 and os.uname()[0] == 'QNX' and ctypes.sizeof(ctypes.c_void_p) == 4
    identity = device_info.read_identity()
    assert identity['variant'] == 'SQN100-3' and identity['os_version'] == '10.3.3.3216'
    n.verify_stock()
    manifest = s.load(s.BASE + '/installation.json')
    assert manifest['owner'] == compatibility.OWNER and set(manifest['files']) == compatibility.FILES
    for name, expected in manifest['files'].items():
        assert not os.path.islink(s.BASE + '/' + name)
        assert n.digest(n.read(s.BASE + '/' + name)) == expected


def setup():
    verify()
    s.ACTIVE_REQUEST = profiles.installed_request(s.BASE)
    s.ACTIVE_PROFILE = s.ACTIVE_REQUEST['profile']
    assert s.ACTIVE_PROFILE['carrier']['mcc'] == '460' and s.ACTIVE_PROFILE['carrier']['mncs'] == ['11']


def status():
    result = s.read_status()
    result['registered'] = (result['phase'] == 'running' and result['manager_alive'] is True
        and result['native_alive'] is True and result['status_from_current_boot'] is True
        and result['current'].get('ims') == 'connected' and result['current'].get('register_status') == '200 OK'
        and result['current'].get('ran') in ('LTE', 'lte') and result['current'].get('radio') == ['lte'])
    return result

q.setup, q.status, q.verify = setup, status, verify



def record(label):
    assert label in ('manual', 'after-reboot')
    q.setup()
    status = q.status()
    assert status.get('registered') is True
    pid = status['native_pid']
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    folder = q.s.STATE + '/acceptance-' + label + '-' + stamp
    os.mkdir(folder, 0o700)
    meta = {'native_pid': pid, 'boot': q.boot_token(), 'label': label,
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
        q.n.atomic(q.s.STATE + '/acceptance-active.json', json.dumps(active).encode('ascii'))
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
    raw_calls = []
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
            snapshot = {'at': time.time(), 'live': q.live(), 'active_call_counts': {}}
            for namespace in ('public', 'private'):
                path = '/pps/services/phone/' + namespace + '/calls'
                names = os.listdir(path)
                snapshot['active_call_counts'][namespace] = len(names)
                for name in names[:16]:
                    if re.match(r'^[a-zA-Z0-9_.-]{1,80}$', name):
                        try:
                            raw_calls.append({'at': snapshot['at'], 'namespace': namespace,
                                              'object': q.n.read(path + '/' + name).decode('utf-8', 'replace')})
                        except OSError:
                            pass
            samples.append(snapshot)
            q.n.atomic(folder + '/samples.json', json.dumps(samples).encode('ascii'))
            if raw_calls:
                q.n.atomic(folder + '/private-call-objects.json', json.dumps(raw_calls).encode('ascii'))
            time.sleep(2)
    except Exception as error:
        q.n.atomic(folder + '/recorder-error.json', json.dumps({'type': type(error).__name__}).encode('ascii'))
    finally:
        q.n.atomic(folder + '/finished.json', json.dumps({'finished_unix': time.time(),
            'samples': len(samples), 'network_or_service_modified': False}).encode('ascii'))
    os._exit(0)


def finish():
    q.setup()
    q.verify()
    active = q.s.load(q.s.STATE + '/acceptance-active.json')
    assert active['boot'] == q.boot_token()
    folder = active['phone_folder']
    assert folder.startswith(q.s.STATE + '/acceptance-') and '..' not in folder
    q.n.atomic(folder + '/stop-recording', b'owner finished call tests\n')
    for unused in range(15):
        if os.path.isfile(folder + '/finished.json'):
            break
        time.sleep(1)
    result = dict(active)
    result.update(finished=os.path.isfile(folder + '/finished.json'), current=q.status())
    return result


if __name__ == '__main__':
    action = sys.argv[1]
    result = record(sys.argv[2]) if action == 'record' else finish() if action == 'finish' else None
    assert result is not None
    print(json.dumps(result))
