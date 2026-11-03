"""Exercise completed-job observation against actual independent POSIX locks.

Run inside the disposable Qt test container as root; all journals are in /tmp.
No phone, network, or host state is used.
"""
import contextlib
import os
import select
import sys
import tempfile
import types
from unittest import mock

sys.path[:0] = ['/work/mobile/runtime', '/work/device']
import entry as e
import worker as w
import unified_install as manager

real_inspect = w.inspect

root = tempfile.mkdtemp(prefix='bb10-job-race-')
w.ROOT, w.JOBS = root + '/mobile', root + '/mobile/jobs'
e.ROOT = w.ROOT
os.mkdir(w.ROOT, 0o700)
os.mkdir(w.JOBS, 0o700)
manager.MANAGEMENT, manager.BASE = root + '/management', root + '/no-install'
w.require_current_selection = lambda folder: None
w.boot = lambda: ['owner', '2' * 48]
w.engine = lambda: types.SimpleNamespace(manage=lambda action: {'enabled': True, 'manager_alive': True},
                                         management_lock=manager.management_lock)
A, B = 'a' * 32, 'b' * 32


def make_job(state):
    return {'id': A, 'action': 'enable', 'state': state, 'phase': 'awaiting_reboot',
            'boot': ['owner', '1' * 48], 'result': {'enabled': True},
            'worker_safety': w.SAFE_JOB_GUARD, 'commit_outcome_unknown': False}


def write_active(job):
    w.save(w.job_path(job['id']), job)
    w.save(w.JOBS + '/active.json', {'id': job['id']})


def hold_observation(state):
    job = make_job(state)
    write_active(job)
    ready_r, ready_w = os.pipe()
    release_r, release_w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(ready_r); os.close(release_w)
        def inspect(*args):
            os.write(ready_w, b'1')
            os.read(release_r, 1)
            return {'schema': 2, 'ok': True, 'state': 'waiting'}
        w.inspect = inspect
        try:
            result = w.observed_job_response(dict(job), {}, '/verified')
            assert result['job_id'] == A and result['job']['state'] == 'completed'
            assert result.get('live_status') is True
        except Exception as error:
            print('child:', repr(error), file=sys.stderr, flush=True)
            os._exit(2)
        os._exit(0)
    os.close(ready_w); os.close(release_r)
    try:
        ready, _, _ = select.select([ready_r], [], [], 10)
        assert ready and os.read(ready_r, 1) == b'1', 'observation did not reach barrier'
        try:
            w.submit('enable', {'operation_id': B}, '/verified')
        except e.MobileError as error:
            assert str(error) == 'operation_in_progress', repr(error)
        else:
            raise AssertionError('new write entered while prior observation held the lock')
        assert not os.path.exists(w.job_path(B))
        assert w.active_job()['id'] == A
    finally:
        os.write(release_w, b'1')
        _, status = os.waitpid(pid, 0)
        os.close(ready_r); os.close(release_w)
    assert status == 0, status


hold_observation('completed')
hold_observation('waiting_reboot')
print('PASS: completed and reboot-transition observations exclude a concurrent submit')

prior = make_job('completed')
write_active(prior)
other = dict(make_job('running'), id=B)
write_active(other)
w.inspect = lambda *args: (_ for _ in ()).throw(AssertionError('unexpected live observation'))
result = w.observed_job_response(dict(prior), {}, '/verified')
assert result['job_id'] == A and result['job']['state'] == 'completed' and not result.get('live_status')
assert w.active_job()['id'] == B

ready_r, ready_w = os.pipe(); release_r, release_w = os.pipe()
pid = os.fork()
if pid == 0:
    os.close(ready_r); os.close(release_w)
    with w.job_lock():
        os.write(ready_w, b'1'); os.read(release_r, 1)
    os._exit(0)
os.close(ready_w); os.close(release_r)
try:
    ready, _, _ = select.select([ready_r], [], [], 10)
    assert ready and os.read(ready_r, 1) == b'1'
    result = w.observed_job_response(dict(prior), {}, '/verified')
    assert result['job_id'] == A and result['job']['state'] == 'completed' and not result.get('live_status')
    assert w.active_job()['id'] == B
finally:
    os.write(release_w, b'1'); _, status = os.waitpid(pid, 0)
    os.close(ready_r); os.close(release_w)
assert status == 0
print('PASS: a different active task and a held lock retain the original terminal identity')

# A separate client holding the management lock makes the live check
# unavailable without changing the already completed journal's identity.
write_active(prior)
w.inspect = real_inspect
w.inspection_details = lambda folder: {}
def probe(action):
    with manager.management_lock():
        return {'installed': False}
w.engine = lambda: types.SimpleNamespace(manage=probe, management_lock=manager.management_lock)
ready_r, ready_w = os.pipe(); release_r, release_w = os.pipe()
pid = os.fork()
if pid == 0:
    os.close(ready_r); os.close(release_w)
    with manager.management_lock():
        os.write(ready_w, b'1'); os.read(release_r, 1)
    os._exit(0)
os.close(ready_w); os.close(release_r)
try:
    ready, _, _ = select.select([ready_r], [], [], 10)
    assert ready and os.read(ready_r, 1) == b'1'
    result = w.observed_job_response(dict(prior), {}, '/verified')
    assert result['job_id'] == A and result['job']['state'] == 'completed'
    assert result['state'] == 'error' and result['error']['code'] == 'management_busy'
    assert result['live_status'] is True and result['ok'] is False
    pending = make_job('waiting_reboot')
    write_active(pending)
    result = w.observed_job_response(dict(pending), {}, '/verified')
    assert result['job_id'] == A and result['job']['state'] == 'waiting_reboot'
    assert result['state'] == 'task_service_busy' and result['primary_action'] == 'poll'
    assert w.active_job()['state'] == 'waiting_reboot'
finally:
    os.write(release_w, b'1'); _, status = os.waitpid(pid, 0)
    os.close(ready_r); os.close(release_w)
assert status == 0
print('PASS: a busy management lock preserves completed and waiting-reboot task identities')

# A desktop operation can own the manager lock while a mobile worker starts.
# None of these blocked writes may be misclassified as an unknown commit.
snapshot = root + '/snapshot'
os.mkdir(snapshot, 0o700)
def forbidden_manage(*args, **kwargs):
    raise AssertionError('write reached the manager while its lock was held')
w.engine = lambda: types.SimpleNamespace(manage=forbidden_manage, management_lock=manager.management_lock,
                                         BASE=manager.BASE, s=types.SimpleNamespace(phone_idle=lambda: True))
w.mobile_radio_state = lambda: 'ON'
ready_r, ready_w = os.pipe(); release_r, release_w = os.pipe()
pid = os.fork()
if pid == 0:
    os.close(ready_r); os.close(release_w)
    with manager.management_lock():
        os.write(ready_w, b'1'); os.read(release_r, 1)
    os._exit(0)
os.close(ready_w); os.close(release_r)
try:
    ready, _, _ = select.select([ready_r], [], [], 10)
    assert ready and os.read(ready_r, 1) == b'1'
    for action in ('enable', 'disable', 'uninstall', 'rollback'):
        job = {'id': A, 'attempt': 'c' * 32, 'action': action, 'request': {}, 'bundle': snapshot,
               'state': 'queued', 'phase': 'checking', 'worker_safety': w.SAFE_JOB_GUARD,
               'commit_outcome_unknown': False}
        write_active(job)
        with mock.patch.object(e, 'read_bundle', return_value=({}, b'', b'', {})):
            w.run_job(A, job['attempt'])
        result = w.load(w.job_path(A))
        assert result['state'] == 'failed' and result['error_code'] == 'management_busy', (action, result)
        assert result['commit_outcome_unknown'] is False and w.resumable_job(result), (action, result)
finally:
    os.write(release_w, b'1'); _, status = os.waitpid(pid, 0)
    os.close(ready_r); os.close(release_w)
assert status == 0
print('PASS: manager lock contention preserves a resumable job without an unknown write')
