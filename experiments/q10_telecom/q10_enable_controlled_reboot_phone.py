"""Authorize one Q10 Telecom profile/SIM for a controlled normal-reboot test."""
import ctypes
import hashlib
import json
import os
import sys
import time
import native as n
import service as s
import profiles
import compatibility as c
import device_info
import telecom_attach as t


def main():
    assert len(sys.argv) == 2 and sys.argv[1] == 'enable'
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
    current_sim = hashlib.sha256(s.current_usim().encode('ascii')).hexdigest()
    assert current_sim == plan['sim_fingerprint']
    request_path = s.STATE + '/controlled-reboot-request.json'
    request = s.load(request_path)
    assert request['owner'] == 'q10-telecom-call-acceptance-v1' and request['variant'] == 'SQN100-3'
    assert request['profile_sha256'] == profiles.fingerprint(s.ACTIVE_REQUEST)
    assert request['boot'] == s.boot_token()
    assert all(request[key] is True for key in ('incoming', 'outgoing', 'audio_both_directions', 'lte', 'sip_dialogs_verified'))
    status = s.read_status()
    assert status['phase'] == 'running' and status['manager_alive'] is True and status['native_alive'] is True
    assert status['native_pid'] == request['native_pid'] and status['status_from_current_boot'] is True
    assert status['current']['ims'] == 'connected' and status['current']['register_status'] == '200 OK'
    assert status['current']['radio'] == ['lte'] and status['current']['ran'] in ('LTE', 'lte')
    assert s.phone_idle()
    journal = s.load(s.JOURNAL)
    assert journal['owner'] == c.OWNER and journal['profile_sha256'] == request['profile_sha256']
    assert journal['boot'] == s.boot_token() and journal['telecom_dca_plan'] == folder
    assert journal['native_pid'] == request['native_pid'] and journal['original_voice_policy'] == 0
    crypto = n.crypto_policy()
    assert journal['crypto_boot'] == s.boot_token() and crypto['swcr_id'] == journal['provider']
    assert n.voice_policy() == 3 and t.native.ue_usage_policy() == 1
    for name in t.dca.SOURCES:
        item = plan['files'][name]
        assert n.digest(n.read(t.dca.source_path(name))) == item['applied_sha256']
    request.update(sim_fingerprint=current_sim, accepted_at=time.time(), acceptance_scope='short_calls_only')
    n.atomic(s.STATE + '/manual-call-acceptance.json', json.dumps(request).encode('ascii'))
    authorization = {'owner': 'q10-telecom-controlled-autostart-v1', 'profile_sha256': request['profile_sha256'],
        'sim_fingerprint': current_sim, 'authorized_at': time.time(), 'before_boot': s.boot_token(),
        'before_native_pid': request['native_pid'], 'source': 'verified_short_calls_then_controlled_reboot',
        'normal_reboot_hardware_acceptance_pending': True}
    n.atomic(s.STATE + '/automatic-start-authorization.json', json.dumps(authorization).encode('ascii'))
    n.atomic(s.BASE + '/enabled', b'controlled Q10 Telecom reboot test after verified calls\n')
    print(json.dumps({'enabled': True, 'variant': 'SQN100-3', 'profile_sha256': request['profile_sha256'],
                      'before_boot': s.boot_token(), 'before_native_pid': request['native_pid'],
                      'normal_reboot_acceptance': 'pending', 'profile_parameters_unchanged': True}))


if __name__ == '__main__':
    main()
