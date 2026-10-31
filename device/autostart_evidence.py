"""Read-only, per-SIM authorization for the accepted Q10 Telecom runtime.

The receipt is created only after maintainer-verified calls and a normal reboot.
It grants no native writes and never infers a phone number from an IMSI.
"""
import hashlib
import json
import os
import re

import native as n
import profiles
import device_info

OWNER = 'q10-telecom-autostart-accepted-v1'
CRITICAL_FILES = ('device/service.py', 'device/native.py', 'device/profiles.py',
                  'device/device_info.py', 'device/ims_image.py', 'device/radio_api.py',
                  'device/telecom_attach.py', 'device/telecom_dca.py', 'device/telecom_native.py',
                  'device/run.sh', 'device/addon-start.sh', 'driver/devnp-volte_swcrypto_probe.so')


def load(path):
    assert not os.path.islink(path)
    return json.loads(n.read(path).decode('ascii'))


def observe(base, profile):
    result = {'owned_configuration': False, 'autostart_authorized': False}
    try:
        facts = device_info.read_identity()
        assert facts['variant'] == 'SQN100-3' and facts['os_version'] == '10.3.3.3216'
        assert profile.get('lte_attach') == 'telecom_data_centric_v1'
        request = profiles.installed_request(base)
        assert request['profile'] == profiles.validate(profile)
        fingerprint = profiles.fingerprint(request)
        card = n.attrs(n.read('/pps/services/cellular/uicc/card0/status_private'))
        assert n.value(card, 'uicc_state', {}).get('state') == 'READY'
        home = n.value(card, 'hplmn', {})
        assert home.get('mcc') == '460' and home.get('mnc') == '11'
        kind = n.value(card, 'uicc_type')
        assert type(kind) is int and kind & 2 and not kind & 16
        identity = str(n.value(n.attrs(n.read('/pps/services/cellular/uicc/card0/status_restricted')), 'imsi'))
        assert profiles.identity_matches(identity, '460', '11')
        sim = hashlib.sha256(identity.encode('ascii')).hexdigest()
        pointer = load(base + '/state/telecom-plan.json')
        assert pointer['owner'] == 'bb10-telecom-attach-v1'
        folder = pointer['folder']
        assert re.match(r'^' + re.escape(base) + r'/state/telecom-attach-[a-f0-9]{16}$', folder)
        assert os.path.realpath(folder) == folder
        plan = load(folder + '/plan.json')
        assert plan['owner'] == pointer['owner'] and plan['profile_sha256'] == fingerprint
        assert plan['sim_fingerprint'] == sim and set(plan['files']) == {'ims', 'ims_defaults', 'omadm', 'test'}
        backup = load(folder + '/desktop-backup-receipt.json')
        assert backup['owner'] == pointer['owner'] and backup['all_original_hashes_verified'] is True
        assert backup['plan_sha256'] == n.digest(n.read(folder + '/plan.json'))
        applied = True
        for name, item in plan['files'].items():
            path = '/var/dca/sources/' + name + '/services/carrier_config/radio_common/cellular_protocol_configuration'
            assert item['path'] == path and not os.path.islink(path)
            original = n.read(folder + '/' + name + '.original')
            assert n.digest(original) == item['original_sha256']
            info = os.stat(path)
            assert [info.st_ino, info.st_mode & 0o7777, info.st_uid, info.st_gid] == item['identity']
            current = n.digest(n.read(path))
            assert current in (item['original_sha256'], item['applied_sha256'])
            applied = applied and current == item['applied_sha256']
        journal = load(base + '/state/journal.json')
        assert journal['owner'] == 'q10-unicom-volte-v1' and journal['original_voice_policy'] == 0
        assert journal['profile_sha256'] == fingerprint and journal['telecom_dca_plan'] == folder
        bootstrap = load(base + '/state/telecom-bootstrap.json')
        assert bootstrap['owner'] == pointer['owner'] and bootstrap['plan_folder'] == folder
        assert bootstrap['profile_sha256'] == fingerprint and bootstrap['sim_fingerprint'] == sim
        result['owned_configuration'] = applied and bootstrap['phase'] == 'ready'
        receipt = load(base + '/state/telecom-autostart-acceptance.json')
        assert receipt['owner'] == OWNER and receipt['variant'] == 'SQN100-3'
        assert receipt['profile_sha256'] == fingerprint and receipt['sim_fingerprint'] == sim
        assert all(receipt[key] is True for key in ('manual_calls', 'normal_reboot',
                   'post_reboot_calls_without_usb', 'audio_both_directions', 'lte',
                   'manual_sip_dialogs_verified', 'post_reboot_ims_call_events_verified'))
        assert type(receipt['desktop_starts_during_reboot']) is int and receipt['desktop_starts_during_reboot'] == 0
        manifest = load(base + '/installation.json')
        assert manifest['owner'] == 'q10-unicom-volte-v1'
        assert set(receipt['critical_files']) == set(CRITICAL_FILES)
        for name in CRITICAL_FILES:
            expected = receipt['critical_files'][name]
            assert manifest['files'][name] == expected
            assert not os.path.islink(base + '/' + name) and n.digest(n.read(base + '/' + name)) == expected
        result['autostart_authorized'] = True
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        pass
    return result
