"""Record a maintainer-verified Q10/SIM acceptance; never starts the service."""
import ctypes
import hashlib
import json
import os
import re
import sys
import time
import native as n
import service as s
import profiles
import compatibility as c
import device_info
import telecom_attach as t

CRITICAL = ('device/service.py', 'device/native.py', 'device/profiles.py',
    'device/device_info.py', 'device/ims_image.py', 'device/radio_api.py',
    'device/telecom_attach.py', 'device/telecom_dca.py', 'device/telecom_native.py',
    'device/run.sh', 'device/addon-start.sh', 'driver/devnp-volte_swcrypto_probe.so')
FLAGS = ('manual_calls', 'normal_reboot', 'post_reboot_calls_without_usb',
         'audio_both_directions', 'lte', 'manual_sip_dialogs_verified',
         'post_reboot_ims_call_events_verified')


def main():
    assert len(sys.argv) == 2 and sys.argv[1] == 'accept'
    assert os.geteuid() == 0 and os.uname()[0] == 'QNX' and ctypes.sizeof(ctypes.c_void_p) == 4
    identity = device_info.read_identity()
    assert identity['variant'] == 'SQN100-3' and identity['os_version'] == '10.3.3.3216'
    n.verify_stock()
    manifest = s.load(s.BASE + '/installation.json')
    assert manifest['owner'] == c.OWNER and set(manifest['files']) == c.FILES
    for name, digest in manifest['files'].items():
        assert not os.path.islink(s.BASE + '/' + name)
        assert n.digest(n.read(s.BASE + '/' + name)) == digest
    assert not os.path.exists(s.BASE + '/install-transaction.json')
    assert n.digest(n.read(c.ADDON + '/init/start.sh')) == manifest['files']['device/addon-start.sh']
    s.ACTIVE_REQUEST = profiles.installed_request(s.BASE)
    s.ACTIVE_PROFILE = s.ACTIVE_REQUEST['profile']
    assert t.selected(s.ACTIVE_PROFILE) and s.ACTIVE_PROFILE['runtime']['autostart'] is False
    folder, plan = t.checked_plan(s)
    sim = hashlib.sha256(s.current_usim().encode('ascii')).hexdigest()
    assert sim == plan['sim_fingerprint']
    manual = s.load(s.STATE + '/manual-call-acceptance.json')
    prior = s.load(s.STATE + '/automatic-start-authorization.json')
    request = s.load(s.STATE + '/telecom-autostart-request.json')
    fp = profiles.fingerprint(s.ACTIVE_REQUEST)
    assert request['owner'] == 'q10-telecom-autostart-request-v1'
    assert request['variant'] == 'SQN100-3' and request['profile_sha256'] == fp
    assert all(request[key] is True for key in FLAGS)
    assert type(request['desktop_starts_during_reboot']) is int and request['desktop_starts_during_reboot'] == 0
    assert request['boot'] == s.boot_token() and request['before_boot'] != s.boot_token()
    assert manual['owner'] == 'q10-telecom-call-acceptance-v1'
    assert manual['profile_sha256'] == fp and manual['sim_fingerprint'] == sim
    assert all(manual[key] is True for key in ('incoming', 'outgoing', 'audio_both_directions', 'lte', 'sip_dialogs_verified'))
    assert prior['owner'] == 'q10-telecom-controlled-autostart-v1'
    assert prior['profile_sha256'] == fp and prior['sim_fingerprint'] == sim
    assert request['before_boot'] == prior['before_boot'] == manual['boot']
    assert request['manual_raw_log_sha256'] == manual['raw_log_sha256']
    for key in ('manual_raw_log_sha256', 'post_reboot_raw_log_sha256', 'desktop_evidence_sha256'):
        assert re.match(r'^[a-f0-9]{64}$', request[key])
    assert set(request['critical_files']) == set(CRITICAL)
    assert request['critical_files'] == {name: manifest['files'][name] for name in CRITICAL}
    status = s.read_status()
    assert status['phase'] == 'running' and status['status_from_current_boot'] is True
    assert status['manager_alive'] is True and status['native_alive'] is True
    assert status['manager_pid'] == request['manager_pid'] and status['native_pid'] == request['native_pid']
    assert status['current']['ims'] == 'connected' and status['current']['register_status'] == '200 OK'
    assert status['current']['radio'] == ['lte'] and status['current']['ran'] in ('LTE', 'lte')
    assert s.phone_idle() and os.path.isfile(s.BASE + '/enabled')
    journal = s.load(s.JOURNAL)
    assert journal['owner'] == c.OWNER and journal['profile_sha256'] == fp
    assert journal['boot'] == s.boot_token() and journal['native_pid'] == request['native_pid']
    assert journal['telecom_dca_plan'] == folder and journal['original_voice_policy'] == 0
    assert journal['crypto_boot'] == s.boot_token() and n.crypto_policy()['swcr_id'] == journal['provider']
    assert n.voice_policy() == 3 and t.native.ue_usage_policy() == 1
    for name in t.dca.SOURCES:
        assert n.digest(n.read(t.dca.source_path(name))) == plan['files'][name]['applied_sha256']
    receipt = dict(request)
    receipt.update(owner='q10-telecom-autostart-accepted-v1', sim_fingerprint=sim,
                   accepted_at=time.time(), native_or_startup_configuration_changed=False)
    target = s.STATE + '/telecom-autostart-acceptance.json'
    assert not os.path.exists(target), 'Existing acceptance must be inspected rather than overwritten'
    n.atomic(target, json.dumps(receipt).encode('ascii'))
    assert s.load(target) == receipt
    print(json.dumps({'accepted': True, 'variant': 'SQN100-3', 'profile_sha256': fp,
        'boot': s.boot_token(), 'native_pid': status['native_pid'], 'network_or_service_writes': 0,
        'receipt_sha256': n.digest(n.read(target))}))


if __name__ == '__main__':
    main()
