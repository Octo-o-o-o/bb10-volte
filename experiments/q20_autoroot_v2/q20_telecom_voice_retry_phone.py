"""Q20 native IMS-preference trial with retrying readback and explicit rollback.

The old trial's final read could raise before its restoration setter. This
version records transient failures, and restoration is independent of sampling.
"""
import hashlib
import json
import os
import signal
import time
import q20_volte_phone as q


def read_policy():
    try:
        return {'value': q.n.voice_policy()}
    except Exception as error:
        return {'value': None, 'error_type': type(error).__name__}


def restore_voice():
    result = {'before': read_policy(), 'restored': False, 'observations': []}
    before = result['before']['value']
    assert before in (None, 0, 3), 'Foreign voice policy; preserve it for inspection'
    if before != 0:
        result['setter'] = q.s.set_voice_preference(4)
        assert result['setter']['rc'] == 0
    for unused in range(8):
        observation = read_policy()
        result['observations'].append(observation)
        if observation['value'] == 0:
            result['restored'] = True
            break
        assert observation['value'] in (None, 3), 'Foreign voice policy; inspect'
        time.sleep(3)
    return result


def main():
    q.setup()
    q.verify()
    assert q.s.phone_idle() and not q.n.active_vpn_sessions()
    assert not os.path.exists(q.BASE + '/enabled') and q.n.voice_policy() == 0
    assert q.n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
    assert all(q.c.configuration_diagnostics().values())
    assert q.s.ACTIVE_PROFILE['carrier']['mncs'] == ['11']
    imsi = q.s.current_usim()
    # Leave the original, unconfigured IMS alone. Reject an active/custom one.
    stock = q.n.ims_pids()
    assert len(stock) <= 1
    if stock:
        text = q.n.command(['/bin/pidin', '-p', str(stock[0]), '-f', 'A']).decode('ascii')
        assert '/radio/bin/ims_rrm -U 453:31,80,387,427,521,1001' in text
        assert not any(q.n.value(q.n.attrs(q.n.read(q.s.IMS)), key) for key in ('IMS_profiles', 'IMS_profilesV2'))
        assert q.live()['ims'] in (None, 'idle', 'disconnected')
    run = q.s.STATE + '/voice-retry-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    os.mkdir(run, 0o700)
    boot = q.boot_token()
    result = {'variant': 'SQC100-2', 'boot': boot, 'original_voice_policy': 0,
              'target_voice_policy': 3, 'native_api_value': 1, 'native_api_mask': 2,
              'sim_fingerprint': hashlib.sha256(imsi.encode('ascii')).hexdigest(),
              'original_ims_pids_untouched': stock, 'apn_changes': 0,
              'crypto_operations': 0, 'calls_placed': 0, 'observations': [],
              'change_attempted': False, 'restored': True}
    path = run + '/report.json'

    def save():
        q.n.atomic(path, json.dumps(result, indent=2).encode('ascii'))

    save()
    if os.fork() == 0:
        try:
            os.setsid()
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
            null = os.open('/dev/null', os.O_RDWR)
            for descriptor in (0, 1, 2):
                os.dup2(null, descriptor)
            if null > 2:
                os.close(null)
            time.sleep(210)
            if not os.path.exists(run + '/done') and q.boot_token(False) == boot:
                q.verify()
                if q.s.phone_idle():
                    q.n.atomic(run + '/watchdog-restore.json', json.dumps(restore_voice()).encode('ascii'))
        finally:
            os._exit(0)

    def interrupted(signum, frame):
        raise RuntimeError('Interrupted; restore native voice policy')

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    try:
        result.update(change_attempted=True, restored=False)
        save()
        result['setter'] = q.s.set_voice_preference(1)
        assert result['setter']['rc'] == 0
        deadline = time.time() + 75
        for unused in range(15):
            assert q.s.phone_idle()
            network = q.c.read_network(q.s.ACTIVE_PROFILE)
            # This native setting restarts the modem/SIM session on this Q20.
            # A ready SIM must still match; transient NOT_READY is observed.
            if network.get('sim_state') == 'READY':
                assert q.s.current_usim() == imsi, 'SIM changed during trial'
            result['observations'].append({'at': time.time(), 'voice': read_policy(),
                'network': network})
            save()
            if time.time() >= deadline:
                break
            time.sleep(5)
    except Exception as error:
        result['error_type'] = type(error).__name__
        result['error_message'] = str(error)
    finally:
        result['restore'] = restore_voice()
        result['restored'] = result['restore']['restored']
        result['after_network'] = q.c.read_network(q.s.ACTIVE_PROFILE)
        result['crypto_unchanged'] = q.n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
        save()
        if result['restored']:
            q.n.atomic(run + '/done', b'original voice policy verified\n')
    result['private_report'] = path
    print(json.dumps(result))


if __name__ == '__main__':
    main()
