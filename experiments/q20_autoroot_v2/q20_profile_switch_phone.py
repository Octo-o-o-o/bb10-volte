"""Close the current Q20 carrier epoch before a normal power-off/SIM swap."""
import json
import os
import sys
import time
import q20_volte_phone as q


def select_profile():
    assert not os.path.isfile(q.BASE + '/enabled') and q.s.phone_idle()
    if os.path.isfile(q.s.LOCK):
        lock = q.s.load(q.s.LOCK)
        assert not (lock.get('boot') == q.boot_token() and q.s.alive(lock['pid']))
    assert q.n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}, 'Use a clean normal reboot after the SIM change'
    assert q.n.voice_policy() == 0 and all(q.c.configuration_diagnostics().values())
    assert not q.n.active_vpn_sessions()
    network = q.c.read_network(q.s.ACTIVE_PROFILE)
    assert network.get('mcc') == '460' and network.get('sim_state') == 'READY'
    mnc = network.get('mnc')
    families = {'01': 'unicom', '09': 'unicom', '00': 'mobile', '02': 'mobile', '07': 'mobile',
                '03': 'telecom', '05': 'telecom', '11': 'telecom'}
    assert mnc in families, 'The current SIM requires a separately reviewed operator profile'
    family = families[mnc]
    profile = q.profiles.read_json(q.BASE + '/profiles/china-' + family + '.json')
    profile.update(id='q20-sqc100-2-' + family + '-460' + mnc,
                   label='Q20 SQC100-2 China ' + family.title() + ' 460-' + mnc)
    profile['carrier']['mncs'] = [mnc]
    observed_apn = network.get('observed_data_apn')
    if observed_apn in profile['carrier']['data_apns']:
        profile['carrier']['data_apns'] = [observed_apn]
    metadata, unused = q.profiles.carrier_template(profile, '460', mnc)
    profile['carrier']['stock_config'] = metadata['path'].rsplit('/', 1)[-1][:-4]
    profile['carrier']['stock_sha256'] = metadata['sha256']
    request = q.profiles.request(profile, True)
    token = q.boot_token()
    if os.path.isfile(q.s.JOURNAL):
        journal = q.s.load(q.s.JOURNAL)
        assert journal.get('configuration_restored') or journal.get('restore_completed')
        assert journal['native_pid'] is None and journal['boot'] != token
        archive = q.BASE + '/archive'
        if not os.path.isdir(archive):
            os.mkdir(archive, 0o700)
        epoch = archive + '/' + q.s.ACTIVE_PROFILE['id'] + '-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
        os.mkdir(epoch, 0o700)
        for name in ('profile-request.json', 'state/journal.json', 'state/status.json',
                     'state/manual-call-acceptance.json', 'state/own-number-display.json'):
            path = q.BASE + '/' + name
            if os.path.isfile(path):
                q.n.atomic(epoch + '/' + name.rsplit('/', 1)[-1], q.n.read(path))
        os.rename(q.s.JOURNAL, epoch + '/journal-original.json')
    blob = q.profiles.canonical(request)
    manifest = q.s.load(q.BASE + '/payload-manifest.json')
    manifest['files']['profile-request.json'] = q.n.digest(blob)
    transaction = {'owner': 'q20-profile-switch-v1', 'old_profile': q.s.ACTIVE_PROFILE['id'],
                   'new_profile': profile['id'], 'profile_sha256': q.profiles.fingerprint(request),
                   'phase': 'writing', 'boot': token}
    q.n.atomic(q.s.STATE + '/profile-switch.json', json.dumps(transaction).encode('ascii'))
    q.n.atomic(q.BASE + '/profile-request.json', blob)
    q.n.atomic(q.BASE + '/payload-manifest.json', json.dumps(manifest, indent=2).encode('ascii'))
    transaction['phase'] = 'selected'
    q.n.atomic(q.s.STATE + '/profile-switch.json', json.dumps(transaction).encode('ascii'))
    return {'profile_selected': True, 'family': family, 'profile': profile,
            'profile_sha256': transaction['profile_sha256'], 'carrier_template': metadata,
            'network_configuration_written': False, 'autostart_enabled': False}


def main():
    q.setup()
    q.verify()
    action = sys.argv[1]
    assert action in ('prepare-swap', 'swap-ready', 'select-profile', 'enable-current')
    assert q.s.phone_idle(), 'Hang up the current Q20 call before changing SIMs'
    if action == 'select-profile':
        result = select_profile()
    elif action == 'enable-current':
        assert q.status()['registered']
        receipt = q.s.load(q.s.STATE + '/manual-call-acceptance.json')
        assert receipt['owner'] == 'q20-call-acceptance-v1' and receipt['variant'] == 'SQC100-2'
        assert receipt['profile_sha256'] == q.profiles.fingerprint(q.s.ACTIVE_REQUEST)
        assert all(receipt[key] is True for key in ('incoming', 'outgoing', 'audio_both_directions', 'lte', 'sip_dialogs_verified'))
        boot = q.s.load(q.s.STATE + '/boot-install.json')
        path = '/apps/sys.android.gYABgKAOw1czN6neiAT72SGO.ns/native/system/xbin/btool'
        assert q.n.digest(q.n.read(path)) == boot['after_sha256']
        q.n.atomic(q.BASE + '/enabled', b'enabled after current carrier bidirectional call acceptance\n')
        result = {'enabled': True, 'profile_sha256': receipt['profile_sha256'], 'root_hook_reused_without_changes': True}
    elif action == 'prepare-swap':
        if os.path.isfile(q.BASE + '/enabled'):
            os.unlink(q.BASE + '/enabled')
        receipt = {'owner': 'q20-carrier-swap-v1', 'boot': q.boot_token(),
                   'profile_sha256': q.profiles.fingerprint(q.s.ACTIVE_REQUEST),
                   'autostart_disabled': True, 'requested_unix': time.time()}
        q.n.atomic(q.s.STATE + '/pending-sim-swap.json', json.dumps(receipt).encode('ascii'))
        if os.path.isfile(q.s.LOCK):
            lock = q.s.load(q.s.LOCK)
            assert lock['boot'] == q.boot_token() and q.s.alive(lock['pid'])
            q.n.atomic(q.s.STOP, b'owner-authorized Q20 SIM swap\n')
            result = {'autostart_disabled': True, 'stop_requested': True}
        else:
            result = {'autostart_disabled': True, 'manager_already_stopped': True}
    else:
        assert not os.path.isfile(q.BASE + '/enabled')
        if os.path.isfile(q.s.LOCK):
            lock = q.s.load(q.s.LOCK)
            assert not (lock.get('boot') == q.boot_token() and q.s.alive(lock['pid'])), 'VoLTE stop is still in progress'
        journal = q.s.load(q.s.JOURNAL)
        assert journal['boot'] == q.boot_token() and journal['native_pid'] is None
        assert journal.get('configuration_restored') is True or journal.get('restore_completed') is True
        assert q.n.voice_policy() == 0 and all(q.c.configuration_diagnostics().values())
        assert not q.n.active_vpn_sessions()
        crypto = q.n.crypto_policy()
        if crypto['swcr_id'] >= 0:
            assert journal['crypto_boot'] == q.boot_token() and crypto['swcr_id'] == journal['provider']
        import q20_own_number_auto as display
        display.restore(q.n, q.boot_token(), q.s.current_usim())
        result = {'ready_for_normal_poweroff_and_sim_swap': True, 'old_ims_identity_removed': True,
                  'original_carrier_configuration_restored': True, 'original_voice_policy': 0,
                  'autostart_disabled': True, 'owned_provider_retained_until_poweroff': crypto['swcr_id'] >= 0,
                  'unknown_ims_processes_signalled': 0}
        q.n.atomic(q.s.STATE + '/sim-swap-ready.json', json.dumps(result).encode('ascii'))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
