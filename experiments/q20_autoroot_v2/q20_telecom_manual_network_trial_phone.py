"""Bounded 460-11 LTE registration request; always restore automatic selection."""
import hashlib
import json
import os
import signal
import time
import q20_volte_phone as q
from q20_nas_client_phone import NasClient

MANUAL = bytes.fromhex('01010002100500cc010b00081101000012010000')
AUTOMATIC = bytes.fromhex('0101000111010000')


def snapshot(client):
    return {'at': time.time(), 'selection': client.request(0x34),
            'serving': client.request(0x24), 'system': client.request(0x4d),
            'network': q.c.read_network(q.s.ACTIVE_PROFILE)}


def restore():
    result = {'restored': False, 'attempts': []}
    for unused in range(3):
        try:
            with NasClient() as client:
                before = client.request(0x34)['network_selection_preference']
                assert before in (0, 1), 'Unexpected concurrent selection preference'
                response = client.request(0x22, AUTOMATIC)
                for count in range(10):
                    after = client.request(0x34)['network_selection_preference']
                    if after == 0:
                        result['restored'] = True
                        break
                    time.sleep(1)
            result['attempts'].append({'before': before, 'response': response, 'after': after})
            if result['restored']:
                break
        except Exception as error:
            result['attempts'].append({'error_type': type(error).__name__})
        time.sleep(2)
    return result


def main():
    q.setup()
    q.verify()
    assert q.s.phone_idle() and not q.n.active_vpn_sessions()
    assert not os.path.exists(q.BASE + '/enabled')
    assert q.s.ACTIVE_PROFILE['carrier']['mncs'] == ['11']
    imsi = q.s.current_usim()
    assert q.n.voice_policy() == 0 and q.n.crypto_policy()['swcr_id'] == -1
    scans = sorted(name for name in os.listdir(q.s.STATE) if name.startswith('lte-scan-') and name.endswith('.json'))
    scan = q.s.load(q.s.STATE + '/' + scans[-1])
    assert 0 <= time.time() - scan['ended_unix'] <= 900
    assert any(row['mcc'] == 460 and row['mnc'] == 11 and row['available'] and row['home']
               and not row['forbidden'] for row in scan['scan']['networks'])
    with NasClient() as client:
        original = client.request(0x34)
    assert original['network_selection_preference'] == 0
    assert original['mode_preference_mask'] == 28 and original['usage_preference'] == 1
    run = q.s.STATE + '/manual-network-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    os.mkdir(run, 0o700)
    boot = q.boot_token()
    result = {'variant': 'SQC100-2', 'boot': boot, 'target_plmn': '460-11', 'target_rat': 'LTE',
              'duration': 'until_power_cycle', 'original': original,
              'sim_fingerprint': hashlib.sha256(imsi.encode('ascii')).hexdigest(),
              'apn_changes': 0, 'voice_nv_changes': 0, 'crypto_operations': 0,
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
                    q.n.atomic(run + '/watchdog-restore.json', json.dumps(restore()).encode('ascii'))
        finally:
            os._exit(0)

    def interrupted(signum, frame):
        raise RuntimeError('Interrupted; restore automatic selection')

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    try:
        with NasClient() as client:
            result['request'] = client.request(0x22, MANUAL)
            for unused in range(8):
                assert q.s.phone_idle() and q.s.current_usim() == imsi
                result['observations'].append(snapshot(client))
                save()
                time.sleep(5)
    except Exception as error:
        result['error_type'] = type(error).__name__
    finally:
        result['restore'] = restore()
        save()
        if result['restore']['restored']:
            q.n.atomic(run + '/done', b'automatic selection verified\n')
    with NasClient() as client:
        result['after'] = snapshot(client)
    result['after_voice_policy'] = q.n.voice_policy()
    result['private_report'] = path
    save()
    print(json.dumps(result))


if __name__ == '__main__':
    main()
