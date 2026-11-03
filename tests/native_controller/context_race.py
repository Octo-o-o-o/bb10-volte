"""Isolated, two-process regression probe for the mobile call-context lock.

Run only inside a disposable Linux container with the checkout mounted at /work:
    docker run --rm --network none --cap-drop ALL \
      --security-opt no-new-privileges --read-only \
      --tmpfs /tmp:rw,exec,nosuid,nodev,size=64m \
      --mount type=bind,source=CHECKOUT,target=/work,readonly \
      --entrypoint python3 bb10-controller-qt-harness:local \
      /work/tests/native_controller/context_race.py --after

--before confirms the previously observed bug on uncorrected code. --after
proves that an in-progress create excludes a second create and confirmation,
then verifies a confirmed record remains readable after the first process exits.
No real device access; actual job_lock and management_lock use /tmp only.
"""
import argparse
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

parser = argparse.ArgumentParser()
parser.add_argument('--before', action='store_true')
parser.add_argument('--after', action='store_true')
args = parser.parse_args()
assert args.before != args.after, 'Select exactly one of --before / --after'

root = tempfile.mkdtemp(prefix='review-context-mp-')
w.ROOT, w.JOBS = root + '/mobile', root + '/mobile/jobs'
os.mkdir(w.ROOT, 0o700)
e.ROOT = w.ROOT
e.FOREGROUND_ACTIVE_POINTER = (False, b'')
manager.MANAGEMENT, manager.BASE = root + '/management', root + '/no-install'
base = root + '/payload'
os.mkdir(base)
with open(base + '/payload.json', 'wb') as destination:
    destination.write(b'{}')

u = types.ModuleType('unified_service')
u.card = lambda: {}
u.boot_token = lambda create=False: ['owner', 'a' * 48]
p = types.ModuleType('carrier_policy')
p.BASE = base
p.select = lambda facts, card: {'sim_sha256': 'b' * 64}
d = types.ModuleType('device_info')
d.read_identity = lambda: {}
status = {'enabled': True, 'status_from_current_boot': True, 'selected_this_boot': True,
          'current_sim_matches': True, 'phase': 'running', 'manager_alive': True,
          'native_alive': True, 'current': {'ims': 'connected', 'register_status': '200 OK',
                                            'ran': 'lte', 'radio': ['lte']}}
manager.manage = lambda action: {'installed': True, 'sim_supported': True, 'status': status,
                                 'operator': 'telecom', 'family': 'q10'}
w.inspection_details = lambda folder: {}
ready_r, ready_w = os.pipe()
release_r, release_w = os.pipe()

with mock.patch.dict(sys.modules, {'unified_service': u, 'carrier_policy': p, 'device_info': d}), \
        mock.patch.object(w, 'engine', return_value=manager):
    pid = os.fork()
    if pid == 0:
        os.close(ready_r)
        os.close(release_w)
        original = w.save
        def delayed_save(path, value):
            if path.endswith('/call-context.json'):
                os.write(ready_w, b'1')
                os.read(release_r, 1)
            return original(path, value)
        w.save = delayed_save
        try:
            w.call_context()
        except Exception as error:
            print('child inspection failed:', repr(error), file=sys.stderr, flush=True)
            os._exit(2)
        os._exit(0)

    os.close(ready_w)
    os.close(release_r)
    released = False
    try:
        ready, _, _ = select.select([ready_r], [], [], 10)
        assert ready and os.read(ready_r, 1) == b'1', 'child did not reach the save barrier'
        request = dict.fromkeys(('confirmed', 'incoming', 'outgoing', 'audio', 'lte'), True)
        request['language'] = 'en'
        if args.before:
            fresh = w.call_context()
            request['call_context'] = fresh['context']
            ack = w.dispatch('confirm-calls', request, '/verified')
            assert ack['state'] == 'verified' and ack['call_context'] == fresh['context']
            os.write(release_w, b'1')
            released = True
            _, child_status = os.waitpid(pid, 0)
            assert child_status == 0
            after = w.call_context(False)
            assert after['context'] != fresh['context'] and not after['calls_verified']
            print('REPRODUCED: an independent delayed inspect overwrote a verified context')
        else:
            # The delayed inspector holds the real management lock. Another
            # reader/creator and a confirmer must fail closed until it exits.
            for attempt in ('inspect', 'confirm'):
                try:
                    if attempt == 'inspect':
                        w.call_context()
                    else:
                        request['call_context'] = 'c' * 32
                        w.dispatch('confirm-calls', request, '/verified')
                except Exception as error:
                    assert str(error) == 'management_busy', (attempt, repr(error))
                else:
                    raise AssertionError(attempt + ' bypassed the held management lock')
            os.write(release_w, b'1')
            released = True
            _, child_status = os.waitpid(pid, 0)
            assert child_status == 0
            fresh = w.call_context()
            request['call_context'] = fresh['context']
            ack = w.dispatch('confirm-calls', request, '/verified')
            after = w.call_context(False)
            assert ack['state'] == 'verified'
            assert after['context'] == fresh['context'] and after['calls_verified'] is True
            print('PASS: real management lock excludes competing context create/confirm')
            print('PASS: successful confirmation persists under the current context')
    finally:
        if not released:
            os.write(release_w, b'1')
            os.waitpid(pid, 0)
        os.close(ready_r)
        os.close(release_w)
