"""Bounded Q20 LTE/data-centric test, with independent rollback and watchdog."""
import hashlib
import json
import os
import signal
import time
import q20_volte_phone as q
from q20_nas_client_phone import NasClient


def snapshot(client):
    return {'at': time.time(), 'selection': client.request(0x34),
            'serving': client.request(0x24), 'system': client.request(0x4d),
            'network': q.c.read_network(q.s.ACTIVE_PROFILE)}


def restore(original):
    results = {}
    # A failed read or restore of one preference must not skip the other.
    for field, allowed in (('usage_preference', (1, 2)), ('mode_preference_mask', (16, 28))):
        attempts = []
        for unused in range(3):
            try:
                with NasClient() as client:
                    current = client.request(0x34)[field]
                    assert current in allowed, 'Concurrent NAS preference change'
                    response = client.set_preference(field, original[field]) if current != original[field] else None
                    after = client.request(0x34)[field]
                attempts.append({'before': current, 'response': response, 'after': after})
                if after == original[field]:
                    results[field] = {'restored': True, 'attempts': attempts}
                    break
            except Exception as error:
                attempts.append({'error_type': type(error).__name__})
            time.sleep(1)
        else:
            results[field] = {'restored': False, 'attempts': attempts}
    return results


def main():
    q.setup()
    q.verify()
    assert not os.path.exists(q.BASE + '/enabled') and q.s.phone_idle()
    assert not q.n.active_vpn_sessions() and q.n.voice_policy() == 0
    assert q.n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
    assert all(q.c.configuration_diagnostics().values())
    imsi = q.s.current_usim()
    with NasClient() as client:
        original = client.request(0x34)
    assert original['mode_preference_mask'] == 28 and original['usage_preference'] == 1
    assert original['network_selection_preference'] == 0
    run = q.s.STATE + '/selection-trial-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    os.mkdir(run, 0o700)
    boot = q.boot_token()
    card = q.n.attrs(q.n.read('/pps/services/cellular/uicc/card0/status_private'))
    report = {'variant': 'SQC100-2', 'boot': boot, 'original_selection': original,
              'sim_fingerprint': hashlib.sha256(imsi.encode('ascii')).hexdigest(),
              'mep_lock_state': q.n.value(card, 'mep_lock_state'),
              'mep_check_state': q.n.value(card, 'mep_check_state'),
              'apn_changes': 0, 'voice_nv_changes': 0, 'crypto_operations': 0,
              'calls_placed': 0, 'autostart_enabled': False, 'phases': {}, 'restored': False}
    path = run + '/report.json'

    def save():
        q.n.atomic(path, json.dumps(report, indent=2).encode('ascii'))

    save()
    watchdog = os.fork()
    if watchdog == 0:
        try:
            os.setsid()
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
            null = os.open('/dev/null', os.O_RDWR)
            for descriptor in (0, 1, 2):
                os.dup2(null, descriptor)
            if null > 2:
                os.close(null)
            time.sleep(180)
            if not os.path.isfile(run + '/done') and q.boot_token(False) == boot:
                q.verify()
                if q.s.phone_idle():
                    result = restore(original)
                    q.n.atomic(run + '/watchdog-restore.json', json.dumps(result).encode('ascii'))
        finally:
            os._exit(0)

    def interrupted(signum, frame):
        raise RuntimeError('Interrupted; restore temporary selection preferences')

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    try:
        with NasClient() as client:
            report['before'] = snapshot(client)
            for phase, field, value in (('lte_only', 'mode_preference_mask', 16),
                                         ('lte_data_centric', 'usage_preference', 2)):
                assert q.s.phone_idle() and q.s.current_usim() == imsi
                report[phase + '_set'] = client.set_preference(field, value)
                report['phases'][phase] = []
                for unused in range(8):
                    assert q.s.phone_idle() and q.s.current_usim() == imsi
                    report['phases'][phase].append(snapshot(client))
                    save()
                    time.sleep(4)
    except Exception as error:
        report['error_type'] = type(error).__name__
    finally:
        report['restore_results'] = restore(original)
        report['restored'] = all(item['restored'] for item in report['restore_results'].values())
        try:
            with NasClient() as client:
                report['after'] = snapshot(client)
            report['after_voice_policy'] = q.n.voice_policy()
            report['crypto_unchanged'] = q.n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
        except Exception as error:
            report['after_error_type'] = type(error).__name__
        save()
        if report['restored']:
            q.n.atomic(run + '/done', b'original mode and usage verified\n')
    report['private_report'] = run + '/report.json'
    print(json.dumps(report))


if __name__ == '__main__':
    main()
