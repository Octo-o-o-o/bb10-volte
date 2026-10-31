"""Test only the known DCA LTE voice field; restore exact original PPS/NV."""
import hashlib
import json
import os
import signal
import time
import q20_volte_phone as q

KEY = 'voice_domain_preference_EUTRAN'


def policy():
    try:
        return q.n.voice_policy()
    except Exception:
        return None


def restore(original):
    current = q.n.attrs(q.n.read(q.s.VOICE)).get(KEY)
    assert current in (original, 'n:3'), 'Concurrent DCA field change'
    if current != original:
        q.n.update_pps(q.s.VOICE, {KEY: original})
    result = {'pps_restored': q.n.attrs(q.n.read(q.s.VOICE)).get(KEY) == original,
              'voice_before': policy(), 'voice_restored': False}
    assert result['voice_before'] in (None, 0, 3), 'Concurrent voice policy change'
    if result['voice_before'] != 0:
        result['native_restore'] = q.s.set_voice_preference(4)
        assert result['native_restore']['rc'] == 0
    for unused in range(6):
        value = policy()
        if value == 0:
            result['voice_restored'] = True
            break
        assert value in (None, 3)
        time.sleep(3)
    result['after_voice_policy'] = value
    return result


def main():
    q.setup()
    q.verify()
    assert q.s.phone_idle() and not q.n.ims_pids() and not q.n.active_vpn_sessions()
    assert not os.path.exists(q.BASE + '/enabled')
    assert q.n.voice_policy() == 0 and q.n.crypto_policy()['swcr_id'] == -1
    assert all(q.c.configuration_diagnostics().values())
    assert q.s.ACTIVE_PROFILE['carrier']['mncs'] == ['11']
    imsi = q.s.current_usim()
    before = q.n.attrs(q.n.read(q.s.VOICE)).get(KEY)
    assert before is None
    run = q.s.STATE + '/dca-voice-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    os.mkdir(run, 0o700)
    boot = q.boot_token()
    result = {'variant': 'SQC100-2', 'boot': boot, 'original_pps_field': before,
              'applied_pps_field': 'n:3', 'original_voice_policy': 0,
              'sim_fingerprint': hashlib.sha256(imsi.encode('ascii')).hexdigest(),
              'apn_changes': 0, 'ims_configuration_changes': 0, 'crypto_operations': 0,
              'calls_placed': 0, 'observations': []}
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
            time.sleep(150)
            if not os.path.exists(run + '/done') and q.boot_token(False) == boot:
                q.verify()
                if q.s.phone_idle():
                    q.n.atomic(run + '/watchdog-restore.json', json.dumps(restore(before)).encode('ascii'))
        finally:
            os._exit(0)

    def interrupted(signum, frame):
        raise RuntimeError('Interrupted; restore DCA and original voice policy')

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    try:
        q.n.update_pps(q.s.VOICE, {KEY: 'n:3'})
        assert q.n.attrs(q.n.read(q.s.VOICE)).get(KEY) == 'n:3'
        for unused in range(10):
            assert q.s.phone_idle() and not q.n.ims_pids()
            network = q.c.read_network(q.s.ACTIVE_PROFILE)
            if network.get('sim_state') == 'READY':
                assert q.s.current_usim() == imsi, 'SIM changed during trial'
            result['observations'].append({'at': time.time(), 'network': network,
                'voice_policy': policy(), 'dca': q.c.incoming_diagnostics()})
            save()
            time.sleep(4)
    except Exception as error:
        result['error_type'], result['error_message'] = type(error).__name__, str(error)
    finally:
        result['restore'] = restore(before)
        result['restored'] = result['restore']['pps_restored'] and result['restore']['voice_restored']
        result['crypto_unchanged'] = q.n.crypto_policy()['swcr_id'] == -1
        save()
        if result['restored']:
            q.n.atomic(run + '/done', b'DCA field and original voice policy restored\n')
    result['private_report'] = path
    print(json.dumps(result))


if __name__ == '__main__':
    main()
