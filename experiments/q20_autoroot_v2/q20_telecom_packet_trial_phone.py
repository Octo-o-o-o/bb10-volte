"""Q20 PS-only NAS test, motivated by observed CS-unavailable cause18."""
import hashlib
import json
import os
import signal
import sys
import time
import q20_volte_phone as q
from q20_nas_client_phone import NasClient


def snapshot(client):
    return {'at': time.time(), 'selection': client.request(0x34),
            'serving': client.request(0x24), 'system': client.request(0x4d),
            'network': q.c.read_network(q.s.ACTIVE_PROFILE)}


def restore(original):
    result = {}
    for field, allowed in (('usage_preference', (1, 2)), ('service_domain_preference', (1, 2)),
                           ('mode_preference_mask', (16, 28))):
        attempts = []
        for unused in range(3):
            try:
                with NasClient() as client:
                    before = client.request(0x34)[field]
                    assert before in allowed, 'Concurrent selection change'
                    response = client.set_preference(field, original[field]) if before != original[field] else None
                    after = client.request(0x34)[field]
                attempts.append({'before': before, 'response': response, 'after': after})
                if after == original[field]:
                    result[field] = {'restored': True, 'attempts': attempts}
                    break
            except Exception as error:
                attempts.append({'error_type': type(error).__name__})
            time.sleep(1)
        else:
            result[field] = {'restored': False, 'attempts': attempts}
    return result


def main():
    assert sys.argv[1:] in ([], ['data-centric'])
    combined = sys.argv[1:] == ['data-centric']
    q.setup()
    q.verify()
    assert q.s.phone_idle() and not q.n.ims_pids() and not q.n.active_vpn_sessions()
    assert not os.path.exists(q.BASE + '/enabled')
    assert q.n.voice_policy() == 0 and q.n.crypto_policy()['swcr_id'] == -1
    assert all(q.c.configuration_diagnostics().values())
    assert q.s.ACTIVE_PROFILE['carrier']['mncs'] == ['11']
    imsi = q.s.current_usim()
    with NasClient() as client:
        original = client.request(0x34)
    assert original['service_domain_preference'] == 2 and original['mode_preference_mask'] == 28
    assert original['usage_preference'] == 1 and original['network_selection_preference'] == 0
    run = q.s.STATE + '/packet-trial-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    os.mkdir(run, 0o700)
    boot = q.boot_token()
    result = {'variant': 'SQC100-2', 'boot': boot, 'original_selection': original,
              'sim_fingerprint': hashlib.sha256(imsi.encode('ascii')).hexdigest(),
              'motivation': 'qct_rrm CS-domain rejection domain1/cause18 observed',
              'duration': 'until_power_cycle', 'voice_nv_writes': 0, 'apn_changes': 0,
              'crypto_operations': 0, 'calls_placed': 0, 'phases': {}, 'restored': False,
              'combined_data_centric': combined}
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
            time.sleep(180)
            if not os.path.exists(run + '/done') and q.boot_token(False) == boot:
                q.verify()
                if q.s.phone_idle():
                    q.n.atomic(run + '/watchdog-restore.json', json.dumps(restore(original)).encode('ascii'))
        finally:
            os._exit(0)

    def interrupted(signum, frame):
        raise RuntimeError('Interrupted; restore original service domain and RAT')

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    try:
        with NasClient() as client:
            phases = [('packet_only', 'service_domain_preference', 1),
                      ('packet_lte_only', 'mode_preference_mask', 16)]
            if combined:
                result['initial_packet_set'] = client.set_preference('service_domain_preference', 1)
                result['initial_lte_set'] = client.set_preference('mode_preference_mask', 16)
                phases = [('packet_lte_data_centric', 'usage_preference', 2)]
            for phase, field, value in phases:
                result[phase + '_set'] = client.set_preference(field, value)
                result['phases'][phase] = []
                for unused in range(8):
                    assert q.s.phone_idle()
                    sample = snapshot(client)
                    if sample['network'].get('sim_state') == 'READY':
                        assert q.s.current_usim() == imsi, 'SIM changed during trial'
                    result['phases'][phase].append(sample)
                    save()
                    time.sleep(4)
    except Exception as error:
        result['error_type'], result['error_message'] = type(error).__name__, str(error)
    finally:
        result['restore'] = restore(original)
        result['restored'] = all(item['restored'] for item in result['restore'].values())
        result['after_voice_policy'] = q.n.voice_policy()
        save()
        if result['restored']:
            q.n.atomic(run + '/done', b'original service domain and RAT verified\n')
    with NasClient() as client:
        result['after'] = snapshot(client)
    result['private_report'] = path
    save()
    print(json.dumps(result))


if __name__ == '__main__':
    main()
