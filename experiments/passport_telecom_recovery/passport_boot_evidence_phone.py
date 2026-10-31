"""Read-only proof of an accepted Passport Telecom automatic boot."""
import hashlib
import json
import os
import sys

BASE = '/var/rootdata/passport_volte_research'
sys.path.insert(0, BASE)
sys.path.insert(0, BASE + '/device')
import passport_volte_phone as q


def main():
    q.setup()
    q.verify_inputs()
    assert q.s.ACTIVE_PROFILE['id'] == 'passport-telecom-manual-research'
    status = q.public_status()
    assert status['phase'] == 'running' and status['manager_alive'] and status['native_alive']
    assert status['status_from_current_boot'] and status['ims_observation_scope'] == 'owned_native'
    assert status['current']['ims'] == 'connected' and status['current']['register_status'] == '200 OK'
    assert status['current']['radio'] == ['lte']
    token = q.s.boot_token()
    launch = q.s.load(q.BOOT_RECORD)
    journal = q.s.load(q.s.JOURNAL)
    assert launch['boot'] == token and launch['source'] == 'autoroot-v4-addon'
    assert journal['boot'] == token and journal['crypto_boot'] == token
    assert journal['manual_only'] is False and journal['autostart']['source'] == 'autoroot-v4-addon'
    assert journal['native_pid'] == status['native_pid'] and q.n.ims_pids() == [journal['native_pid']]
    assert status['crypto']['swcr_id'] == journal['provider'] and status['crypto']['swcr_id'] >= 0
    assert status['voice_policy'] == 3
    receipt = q.acceptance_receipt()
    fingerprint = q.telecom_acceptance_sim(receipt)
    assert journal['configured_sim_fingerprint'] == fingerprint
    folder, plan = q.telecom().checked_plan(q.s)
    assert plan['sim_fingerprint'] == fingerprint and journal['telecom_dca_plan'] == folder
    import telecom_native
    assert telecom_native.ue_usage_policy() == 1
    dca = q.telecom_bind_dca()
    source_states = {}
    for name in dca.SOURCES:
        original = q.n.read(folder + '/' + name + '.original')
        current = q.n.read(dca.source_path(name))
        assert current in (original, dca.payload(original, 'data_centric'))
        source_states[name] = 'original' if current == original else 'data_centric'
    assert not any(os.path.exists(q.s.STATE + '/' + name) for name in ('lease.json', 'watchdog.json', 'stop-request'))
    addon = q.ADDON + '/init/start.sh'
    assert q.n.read(addon) == q.n.read(BASE + '/addon-start.sh')
    network = q.compatibility.read_network(q.s.ACTIVE_PROFILE)
    assert network['lte'] and not network['emergency_service'] and network['data_connected']
    assert network['observed_data_apn'] in ('ctnet', 'ctlte')
    timing = status['startup_timing']
    result = {'accepted': True, 'boot': token, 'profile_sha256': receipt['profile_sha256'],
              'manager_pid': launch['manager_pid'], 'native_pid': journal['native_pid'],
              'automatic_source': launch['source'], 'mode': launch['mode'],
              'status': status, 'same_sim_plan_receipt_and_journal': True,
              'current_boot_provider_verified': True, 'native_ue_usage': 1,
              'all_dca_sources_match_owned_plan': True, 'dca_source_states': source_states,
              'manual_lease_and_watchdog_absent': True,
              'core_manifest_sha256': q.n.digest(q.n.read(BASE + '/research-manifest.json')),
              'addon_entry_sha256': q.n.digest(q.n.read(addon)),
              'manager_to_registration_seconds': round(timing['running'] - timing['manager_started'], 3),
              'network': {key: network.get(key) for key in ('sim_state', 'mcc', 'mnc', 'lte', 'emergency_service',
                          'observed_data_apn', 'data_connected', 'lte_data_service')},
              'network_configuration_writes': 0, 'service_start_requests': 0,
              'subscriber_identity_exported': False}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
