"""Private Passport VoLTE lifecycle with provider retention until reboot.

Manual research runs use a bounded lease. Autostart is a separate owner-enabled
AutoRoot v4 addon, limited to profiles with a recorded manual call acceptance.
No public installer, btool change, provider rollback, or OS image writes.
Python 3.2 compatible. Device identities and SIP logs remain in mode-700 storage.
"""
import hashlib
import json
import os
import posixpath
import re
import signal
import subprocess
import sys
import time
import traceback

BASE = '/var/rootdata/passport_volte_research'
IR92 = '/pps/services/carrier_config/ims/ir92'
MOBILE_SETTINGS = '/var/ims/carrier/imsconfig_404.xml'
IMS_LOG_CONTROL = '/pps/services/ims/status_persistent'
NAS_DIR = '/var/rootdata/passport_diag'
NAS_PINS = {'nas_client_phone.py': 'f817c0d464838eae67c46c5ae4fd291adeb76bd666ec96b9f1c1a2bbc5a2d7e4',
            'nas_snapshot_phone.py': '47a056394591f1638d6303bfb75409d7a1977be33bb1e887dfa1ae33658f8652'}
MENU_TOOL = NAS_DIR + '/passport_mobile_radio_ui_phone.py'
MENU_TOOL_HASH = 'ee2a512bf492721c24e1ba65ec75cdeaba4e7fdf5ef7d70c55a33bf0dc8c6a33'
ENABLED = BASE + '/enabled'
ACCEPTANCE = BASE + '/acceptance'
EVIDENCE = BASE + '/evidence'
ADDONS = '/var/addons'
ADDON = ADDONS + '/passport-volte'
AUTOSTART_RECORD = BASE + '/autostart-install.json'
BOOT_RECORD = BASE + '/last-boot-launch.json'
# Base operator profiles only: their lifecycle has no lease-bound trial settings.
AUTOSTART_PROFILES = ('passport-unicom-manual-research', 'passport-mobile-manual-research',
                      'passport-telecom-manual-research')
# Manager exits that deliberately keep the journal for the next boot.
PRESERVED_EXITS = ('native_exited', 'suspended_for_shutdown')
# Q10-accepted UE1 + voice3 LTE bootstrap (telecom_attach r6), Passport-gated here.
TELECOM_PROFILES = ('passport-telecom-manual-research',)
# Marker that data-centric UE usage is persisted in EFS, awaiting a cold modem boot.
# Lives at BASE top level so it survives both a reboot and a STATE archive.
TELECOM_DATACENTRIC = BASE + '/telecom-datacentric.json'
sys.path.insert(0, BASE + '/device')
import native as n
import profiles
import compatibility
import device_info
import ims_image
import service as s

# Stock ims_rrm 0xb8eb0 seeds the MediaDialog.EarlySdp default (movs r1, #2).
# China Mobile's TAS cancels MT precondition calls when the reliable 180 repeats SDP.
EARLY_SDP_DEFAULT = 0xb8eb0
EARLY_SDP0_IMAGE = '647290caee0da86479ef7da7c42e68f98cd283fead8e9406f1c530a4a99c0494'
EARLY_SDP0_PROFILES = ('passport-mobile-manual-research', 'passport-mobile-earlysdp0-manual-research')


def setup():
    for name, value in {
            'BASE': BASE, 'STATE': BASE + '/state', 'RUNTIME': BASE + '/runtime',
            'JOURNAL': BASE + '/state/journal.json', 'STATUS': BASE + '/state/status.json',
            'LOCK': BASE + '/state/lock.json', 'STOP': BASE + '/state/stop-request',
            'BIN': BASE + '/runtime/ims_rrm',
            'MODULE': BASE + '/driver/devnp-volte_swcrypto_probe.so',
            'APN': BASE + '/runtime/carrier/36-ims.xml'}.items():
        setattr(s, name, value)
    s.ACTIVE_REQUEST = profiles.load_request(BASE + '/profile-request.json')
    s.ACTIVE_PROFILE = s.ACTIVE_REQUEST['profile']
    assert s.ACTIVE_PROFILE['runtime']['autostart'] is False
    assert s.ACTIVE_REQUEST['allow_experimental'] is True
    s.UPDATES = s.profile_updates(s.ACTIVE_PROFILE, s.ACTIVE_PROFILE['carrier']['mcc'],
                                 s.ACTIVE_PROFILE['carrier']['mncs'][0])
    # Passport's stock engine removes its PPS object when it exits. Absence
    # during a newly launched engine's initialization is an observed wait state.
    s.live = research_live
    if s.ACTIVE_PROFILE.get('lte_attach'):
        assert s.ACTIVE_PROFILE['id'] in TELECOM_PROFILES
        telecom()


def telecom():
    import telecom_attach

    def supported(identity):
        device = device_info.identify(identity)
        return (device['recognized'] and not device['identity_conflict'] and
                device['family'] == 'passport' and device['variant'] == 'SQW100-4' and
                identity.get('os_version') == device_info.OS_VERSION)
    telecom_attach.supported = supported
    return telecom_attach


def telecom_datacentric_persisted():
    """The persisted-data-centric marker, or None. Written by telecom-persist, cleared by restore/revert."""
    return s.load(TELECOM_DATACENTRIC) if os.path.isfile(TELECOM_DATACENTRIC) else None


def telecom_bind_dca():
    import telecom_dca
    context = type('Ctx', (), {})()
    context.s, context.n, context.BASE = s, n, BASE
    telecom_dca.q = context
    return telecom_dca


def telecom_persist():
    """Write data-centric to the four backed-up DCA sources and leave it for a cold modem boot.

    ue_usage_setting lives in modem NV that the Passport baseband only re-reads at a cold
    start, so the owned attach cannot bring it up in-session. This persists the EFS value and
    the desktop-verified backup; the owner then reboots once so the baseband reads data-centric.
    No voice-policy change, no IMS, no crypto provider, no reboot here.
    """
    verify_inputs()
    assert s.ACTIVE_PROFILE['id'] in TELECOM_PROFILES and not manager_active()
    assert not os.path.isfile(s.JOURNAL), 'Reconcile the previous run first'
    assert telecom_datacentric_persisted() is None, 'Data-centric already persisted; reboot or revert first'
    assert s.phone_idle() and only_stock_ims() and not n.active_vpn_sessions()
    assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0} and n.voice_policy() == 0
    attach = telecom()
    import telecom_native
    folder, value = attach.checked_plan(s)  # desktop backup receipt + originals + sources in (original, data_centric)
    assert telecom_native.ue_usage_policy() == 0
    fingerprint = hashlib.sha256(s.current_usim().encode('ascii')).hexdigest()
    assert fingerprint == value['sim_fingerprint'], 'Reprepare the Telecom backup after changing SIM'
    dca = telecom_bind_dca()
    for name in dca.SOURCES:
        item = value['files'][name]
        before = n.read(folder + '/' + name + '.original')
        if n.read(item['path']) == before:
            dca.write_existing(item['path'], before, dca.payload(before, 'data_centric'), item)
    published = dca.publish(folder, 'persist-cold-boot')
    assert 'error_type' not in published and telecom_native.ue_usage_policy() == 1
    # The existing telecom restore paths read this record by owner/plan_folder; keep its shape.
    record = {'owner': 'bb10-telecom-attach-v1', 'plan_folder': folder, 'profile_sha256': value['profile_sha256'],
              'sim_fingerprint': fingerprint, 'phase': 'persisted'}
    n.atomic(s.STATE + '/telecom-bootstrap.json', json.dumps(record).encode('ascii'))
    marker = {'owner': 'bb10-telecom-attach-v1', 'plan_folder': folder, 'profile_sha256': value['profile_sha256'],
              'sim_fingerprint': fingerprint, 'persisted_boot': s.boot_token(), 'ue_usage': 1,
              'voice_policy_at_persist': 0, 'at': time.time()}
    n.atomic(TELECOM_DATACENTRIC, json.dumps(marker, indent=2).encode('ascii'))
    return {'data_centric_persisted': True, 'ue_usage': 1, 'reboot_required': True,
            'persisted_boot': s.boot_token(), 'plan_folder': folder}


def telecom_revert():
    """Revert persisted data-centric without an owned run (e.g. before a SIM swap). Effective next reboot."""
    verify_inputs()
    assert not manager_active() and s.phone_idle() and only_stock_ims() and not n.active_vpn_sessions()
    marker = telecom_datacentric_persisted()
    assert marker is not None, 'No persisted data-centric to revert'
    assert not os.path.isfile(s.JOURNAL), 'An owned run exists; stop it to revert through the normal path'
    telecom().restore(s)  # reads STATE/telecom-bootstrap.json, writes the originals back, verifies
    os.unlink(TELECOM_DATACENTRIC)
    return {'telecom_datacentric_reverted': True, 'effective_after': 'next_reboot', 'marker_cleared': True}


def telecom_ensure_lte():
    """After the cold boot the baseband has read data-centric; just wait for LTE data, then IMS configures."""
    marker = telecom_datacentric_persisted()
    if marker is None:
        raise RuntimeError('Run telecom-persist and reboot before launching Telecom; '
                           'the Passport baseband applies data-centric only at a cold boot')
    assert marker['persisted_boot'] != s.boot_token(), 'Reboot before launching the persisted Telecom attach'
    attach = telecom()
    import telecom_native
    folder, value = attach.checked_plan(s)  # receipt + originals + sources already data_centric
    assert folder == marker['plan_folder']
    fingerprint = hashlib.sha256(s.current_usim().encode('ascii')).hexdigest()
    assert marker['owner'] == 'bb10-telecom-attach-v1'
    assert marker['profile_sha256'] == value['profile_sha256'] == profiles.fingerprint(s.ACTIVE_REQUEST)
    assert marker['sim_fingerprint'] == value['sim_fingerprint'] == fingerprint, 'Persisted Telecom SIM changed'
    assert telecom_native.ue_usage_policy() == 1, 'Cold boot did not apply data-centric'
    s.telecom_dca_plan = folder  # prepare_manual journals this after configure so restore can revert
    deadline = time.time() + 120
    while not s.ready():
        assert s.phone_idle() and not s.stopping(), 'Idle/stop guard before IMS'
        assert time.time() < deadline, 'Data-centric persisted but normal LTE data did not come up'
        s.status('telecom_waiting_for_lte_data')
        time.sleep(3)


def attach_pending(network, profile):
    """Before UE1 the Telecom SIM may only lack normal LTE data; every SIM check must pass."""
    waits = [c for c in compatibility.network_checks(network, profile) if c['status'] != 'pass']
    return bool(profile.get('lte_attach')) and all(c['id'] in ('lte', 'apn') and c['status'] == 'wait'
                                                   for c in waits)


def network_usable():
    return s.ready() or attach_pending(compatibility.read_network(s.ACTIVE_PROFILE), s.ACTIVE_PROFILE)


def manager_active():
    if not os.path.isfile(s.LOCK):
        return False
    lock = s.load(s.LOCK)
    return lock.get('boot') == s.boot_token() and s.alive(lock['pid'])


def previous_boot_unrestored():
    if not os.path.isfile(s.JOURNAL):
        return False
    saved = s.load(s.JOURNAL)
    return saved.get('boot') != s.boot_token() and not saved.get('configuration_restored')


def research_live():
    def optional(path):
        return n.attrs(n.read(path)) if os.path.exists(path) else {}
    public = optional('/pps/services/ims/status_public')
    engine = optional('/pps/services/ims/cellular/status_private')
    radio = optional(s.RADIO)
    return {'ims': n.value(public, 'status'), 'register_status': n.value(engine, 'register_status'),
            'ran': n.value(public, 'default_ran'), 'radio': n.value(radio, 'network_technology'),
            'power': n.value(radio, 'power_status')}


def nas_client_type():
    for name, expected in NAS_PINS.items():
        assert n.digest(n.read(NAS_DIR + '/' + name)) == expected
        n.command(['/proc/boot/pathtrust', '!' + NAS_DIR + '/' + name])
    if NAS_DIR not in sys.path:
        sys.path.insert(0, NAS_DIR)
    from nas_client_phone import NasClient
    return NasClient


def nas_trial_proof():
    if s.j is None:
        return None
    trial = s.j.get('nas_voice_trial')
    if trial is None:
        return None
    assert trial['owner'] == 'passport-mobile-nas-voice-only-v1'
    assert trial['boot'] == s.j['boot'] == s.boot_token()
    assert trial['before_epoch'] == trial['restore_target'] == s.j['original_voice_policy'] == 0
    assert trial['applied'] == 1 and trial['before_apply'] in (None, 3)
    assert s.ACTIVE_PROFILE['id'] == 'passport-mobile-psonly-manual-research'
    return trial


def nas_voice_guard():
    trial = nas_trial_proof()
    if trial is not None and trial['attempted']:
        with nas_client_type()() as client:
            current = client.request(0x34)
        assert current['voice_domain_preference'] in (0, 1, 3), 'Preserve independent NAS voice changes'


def restore_nas_voice():
    trial = nas_trial_proof()
    if trial is None or not trial['attempted']:
        return
    with nas_client_type()() as client:
        current = client.request(0x34)
        assert current['voice_domain_preference'] in (0, 1, 3), 'Preserve independent NAS voice changes'
        if current['voice_domain_preference'] != 0:
            trial['restore_ack'] = client.set_voice_domain(0)
        assert client.request(0x34)['voice_domain_preference'] == 0
    assert n.voice_policy() == 0
    trial['restored'] = True
    s.save_journal()


def ps_only_live():
    """Manager-only hook; one temporary NAS change after real IMS registration."""
    state = research_live()
    trial = nas_trial_proof()
    if trial is None or trial['attempted'] or state['ims'] != 'connected' or state['register_status'] != '200 OK':
        return state
    assert s.load(s.LOCK)['pid'] == os.getpid() and s.phone_idle()
    assert s.j['native_pid'] in n.ims_pids()
    with nas_client_type()() as client:
        before = client.request(0x34)
        assert before['voice_domain_preference'] == 3 and before['mode_preference_mask'] == 28
        assert before['service_domain_preference'] == 2 and before['usage_preference'] == 1
        trial.update(before_apply=3, attempted=True, before=before)
        s.save_journal()  # The watchdog owns recovery even if SET's reply is lost.
        trial['set_ack'] = client.set_voice_domain(1)
        after = client.request(0x34)
        assert after['voice_domain_preference'] == 1
        assert all(after[k] == before[k] for k in ('mode_preference_mask', 'service_domain_preference',
                                                  'usage_preference', 'lte_band_preference_mask'))
    trial.update(after=after, applied_unix=time.time(), nv_after=n.voice_policy())
    s.save_journal()
    return state


def verify_inputs():
    manifest = s.load(BASE + '/research-manifest.json')
    assert manifest['schema'] == 1
    assert manifest['lifecycle'] == 'retain-provider-until-reboot'
    for name, expected in manifest['files'].items():
        assert name in ('passport_volte_phone.py', 'profile-request.json', 'addon-start.sh',
                        'passport_call_recorder_phone.py') or name.startswith(('device/', 'driver/'))
        assert '..' not in name and not os.path.islink(BASE + '/' + name)
        assert n.digest(n.read(BASE + '/' + name)) == expected, 'Research input mismatch'
    n.verify_stock()
    identity = device_info.read_identity()
    device = device_info.identify(identity)
    assert device['recognized'] and not device['identity_conflict']
    assert device['family'] == 'passport' and device['variant'] == 'SQW100-4'
    assert device['board_type'] == 'WINDERMERE4ROW' and identity['os_version'] == '10.3.3.3216'
    assert n.digest(n.read(s.MODULE)) == n.HELPER_HASH
    return device


def precheck():
    device = verify_inputs()
    report = compatibility.probe(s.ACTIVE_PROFILE, True)
    remaining = [item for item in report['checks'] if item['status'] != 'pass']
    if s.ACTIVE_PROFILE.get('lte_attach'):
        # Emergency-only LTE is what the bootstrap repairs; IMS still waits for normal LTE data.
        remaining = [item for item in remaining if not (item['id'] in ('lte', 'apn') and item['status'] == 'wait')]
        if telecom_datacentric_persisted() is not None:
            # Data-centric is intentionally persisted, so the stock-baseline telecom_attach check no longer holds.
            remaining = [item for item in remaining if item['id'] != 'telecom_attach']
        assert not os.path.isfile(s.STATE + '/retained-provider.json'), 'Telecom needs a fresh boot'
    expected = [{'id': 'provider_lifecycle', 'status': 'adapt',
                 'code': 'passport_provider_lifecycle_unvalidated'}]
    retained = retained_provider_proof() if os.path.isfile(s.STATE + '/retained-provider.json') else None
    if retained is not None:
        assert retained_baseline_matches(report['baseline'], retained['provider'])
        expected.append({'id': 'baseline', 'status': 'wait', 'code': 'baseline_not_clean'})
    assert remaining == expected, 'Unexpected preflight condition'
    assert report['baseline']['clean_configuration'] is True
    assert s.phone_idle() and not n.active_vpn_sessions()
    assert not n.ims_pids(), 'An existing native IMS instance must be preserved'
    assert not os.path.isfile('/var/rootdata/q10_volte/enabled')
    assert not os.path.lexists('/var/addons/q10-unicom-volte')
    n.atomic(BASE + '/state/preflight.json', json.dumps(report, indent=2).encode('ascii'))
    return {'precheck_passed': True, 'device': device,
            'lifecycle': 'retain-provider-until-reboot', 'autostart': False,
            'provider_lifecycle_tested': False, 'reusing_owned_provider': retained is not None,
            'telecom_attach': report.get('telecom_attach'),
            'lte_bootstrap_pending': report.get('lte_bootstrap_pending')}


def retained_baseline_matches(baseline, provider):
    return (type(provider) is int and 0 <= provider <= 127 and baseline == {
        'voice_policy': 0, 'crypto': {'swcr_id': provider, 'crypto_support': 0},
        'ims_count': 0, 'vpn_count': 0, 'native_read_error': False, 'clean_configuration': True})


def retained_provider_proof():
    proof = s.load(s.STATE + '/retained-provider.json')
    assert proof['owner'] == 'passport-retained-provider-epoch-v1'
    assert proof['boot'] == s.boot_token()
    assert proof['profile_sha256'] == profiles.fingerprint(s.ACTIVE_REQUEST)
    path = proof['origin']['path']
    assert path.startswith(BASE + '/archive/trial-') and path.endswith('/journal.json') and '..' not in path
    assert not os.path.islink(path)
    original = n.read(path)
    assert n.digest(original) == proof['origin']['sha256']
    owner = json.loads(original.decode('ascii'))
    assert owner['owner'] == 'q10-unicom-volte-v1' and owner['configuration_restored'] is True
    assert owner.get('lifecycle') == 'retain-provider-until-reboot'
    assert owner['boot'] == owner['crypto_boot'] == proof['boot']
    assert owner['provider'] == proof['provider'] and owner.get('provider_enable_attempted') is True
    assert n.crypto_policy() == {'swcr_id': proof['provider'], 'crypto_support': 0}
    return proof


def init_retained_journal():
    assert not os.path.exists(s.JOURNAL)
    proof = retained_provider_proof()
    assert s.phone_idle() and not n.ims_pids() and not n.active_vpn_sessions()
    assert n.voice_policy() == 0
    assert all(compatibility.configuration_diagnostics().values())
    before = {path: {key: n.attrs(n.read(path)).get(key) for key in updates}
              for path, updates in s.UPDATES.items()}
    s.j = {'owner': 'q10-unicom-volte-v1', 'created_unix': time.time(),
           'original_voice_policy': 0, 'pps_before': before, 'known_vpn_uids': [],
           'vpn_before_uids': [], 'native_pid': None, 'managed_files': {},
           'restore_completed': False, 'configuration_restored': False,
           'boot': s.boot_token(), 'crypto_boot': proof['boot'], 'provider': proof['provider'],
           'profile_sha256': proof['profile_sha256'], 'provider_reused': True,
           'provider_enable_attempted': False, 'provider_origin': proof['origin'],
           'lifecycle': 'retain-provider-until-reboot'}
    s.save_journal()


def restore_retaining_provider(previous_boot=False):
    """Restore only owned changes, deliberately never unregister software crypto."""
    assert s.j is not None and (s.j.get('boot') != s.boot_token()) == previous_boot
    assert s.phone_idle(), 'Call active; defer restoration until idle'
    nas_voice_guard()
    # Disable owned diagnostic capture while the engine can still consume it.
    if IMS_LOG_CONTROL in s.applied_updates():
        restore_pps_fields(IMS_LOG_CONTROL)
    s.stop_native()
    paths = ([IR92] if IR92 in s.applied_updates() else []) + [s.IMS, s.CDSC, s.VOICE]
    for path in paths:
        restore_pps_fields(path)
    s.remove_owned(s.XML)
    s.remove_platform()
    restore_extra_settings()
    policy = n.crypto_policy()  # Observation only. No rollback/disable/unload call.
    if n.voice_policy() != s.j['original_voice_policy']:
        assert n.voice_policy() == 3 or (n.voice_policy() == 1 and nas_trial_proof() is not None
                                        and nas_trial_proof()['attempted']), 'Unexpected voice policy; preserve state'
        assert s.set_voice_preference(4)['rc'] == 0
    for unused in range(2):
        time.sleep(1.2)
        assert n.voice_policy() == s.j['original_voice_policy'] == 0
    restore_nas_voice()
    if s.j.get('telecom_dca_plan'):
        telecom().restore(s)
        if os.path.isfile(TELECOM_DATACENTRIC):
            os.unlink(TELECOM_DATACENTRIC)
    s.j.update(configuration_restored=True, restore_completed=False,
               provider_retained_until_reboot=policy['swcr_id'] >= 0,
               observed_crypto_after_restore=policy, reboot_verification_required=True,
               lifecycle='retain-provider-until-reboot', native_pid=None)
    s.save_journal()
    s.status('configuration_restored_previous_boot' if previous_boot else
             'configuration_restored_reboot_required')


def restore_previous_boot():
    """Restore a manual run interrupted by a reboot; the reboot already cleared the provider."""
    verify_inputs()
    assert not os.path.isfile(ENABLED), 'Autostart continues this run; disable it first'
    assert not manager_active() and previous_boot_unrestored()
    s.j = s.load(s.JOURNAL)
    assert s.j['owner'] == 'q10-unicom-volte-v1' and s.j['original_voice_policy'] == 0
    assert s.j.get('profile_sha256') == profiles.fingerprint(s.ACTIVE_REQUEST), 'Select the run profile first'
    assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
    assert not n.ims_pids(), 'Hand off the idle stock IMS first'
    restore_retaining_provider(previous_boot=True)
    return {'previous_boot_restored': True, 'previous_boot': s.j['boot'],
            'next': 'reconcile-after-reboot'}


def restore_pps_fields(path):
    current = n.attrs(n.read(path))
    updates = {}
    for key, applied in s.applied_updates()[path].items():
        original = s.j['pps_before'][path][key]
        assert current.get(key) in (applied, original), 'Concurrent carrier change; preserve state'
        updates[key] = original
    n.update_pps(path, updates)
    assert all(n.attrs(n.read(path)).get(k) == v for k, v in updates.items())


def enable_native_capture():
    directory = '/var/ims/log'
    assert os.path.isdir(directory) and not os.path.islink(directory)
    meta = os.stat(directory)
    assert meta.st_uid == 453 and meta.st_gid == 31 and meta.st_mode & 0o777 == 0o700
    original = n.attrs(n.read(IMS_LOG_CONTROL)).get('logToPcap')
    assert original is None, 'Preserve existing diagnostic capture settings'
    s.j['pps_before'][IMS_LOG_CONTROL] = {'logToPcap': original}
    s.j['pps_applied'][IMS_LOG_CONTROL] = {'logToPcap': 'b:true'}
    s.j['compatibility_trial'] = {'diagnostics_only': True, 'native_logToPcap': True,
                                 'native_enum': 0x154, 'lease_seconds': 1200,
                                 'privacy': 'private directory; process umask unchanged'}
    s.save_journal()
    s.apply_fields(IMS_LOG_CONTROL)


def enable_mobile_hdvoice():
    assert s.ACTIVE_PROFILE['id'] == 'passport-mobile-hdvoice-manual-research'
    assert s.ACTIVE_PROFILE['carrier']['data_apns'] == ['cmnet']
    original = n.attrs(n.read(IR92)).get('HDvoice')
    assert original is None, 'Preserve an existing codec override'
    s.j['pps_before'][IR92] = {'HDvoice': original}
    s.j['pps_applied'][IR92] = {'HDvoice': 'b:true'}
    s.j['compatibility_trial'].update(diagnostics_only=False, HDvoice=True,
                                    scope='Mobile codec preference only; keep preconditions unchanged')
    s.save_journal()
    s.apply_fields(IR92)


def early_sdp0_binary(original, normal_voice=False):
    """Reviewed temporary image plus one immediate: the reliable 180 omits repeated SDP."""
    assert normal_voice is True
    changed, patches = ims_image.temporary_binary(original, normal_voice)
    off = EARLY_SDP_DEFAULT
    assert changed[off:off + 4] == b'\x02\x21\x78\x44'
    image = bytearray(changed)
    image[off] = 0
    image = bytes(image)
    assert len(image) == len(changed) and image[:off] == changed[:off] and image[off + 1:] == changed[off + 1:]
    assert hashlib.sha256(image).hexdigest() == EARLY_SDP0_IMAGE, 'Unexpected EarlySdp image'
    patches.append({'file_offset': off, 'bytes_before': '0221', 'bytes_after': '0021',
                    'before': 'movs r1, #2', 'after': 'movs r1, #0',
                    'config_key': 'MediaDialog.EarlySdp',
                    'purpose': 'Reliable 180 omits SDP after precondition offer/answer completed'})
    return image, patches


def restore_extra_settings():
    extra = s.j.get('extra_carrier_settings')
    if extra is None:
        return
    assert extra['path'] == MOBILE_SETTINGS and extra['before_absent'] is True
    if os.path.lexists(MOBILE_SETTINGS):
        assert not os.path.islink(MOBILE_SETTINGS)
        assert n.digest(n.read(MOBILE_SETTINGS)) == extra['sha256'], 'Carrier user settings changed; preserve for review'
        os.unlink(MOBILE_SETTINGS)


def lease_stopping():
    lease = s.load(BASE + '/state/lease.json')
    if time.time() >= lease['deadline_unix'] and not os.path.exists(s.STOP):
        n.atomic(s.STOP, b'bounded manual research lease expired\n')
    return s.shutdown or os.path.exists(s.STOP)


def prepare_manual():
    verify_inputs()
    assert s.phone_idle() and not n.active_vpn_sessions()
    if s.ACTIVE_PROFILE.get('lte_attach'):
        assert not os.path.isfile(s.STATE + '/retained-provider.json'), 'Telecom needs a fresh boot'
        assert not n.ims_pids()
        telecom_ensure_lte()
    assert s.ready() and not n.ims_pids()
    # Initialize QMI only in the manager, after both Python-only forks. The
    # launcher/watchdog must not inherit QCCI worker threads or their locks.
    if s.ACTIVE_PROFILE['id'] == 'passport-mobile-psonly-manual-research':
        with nas_client_type()() as client:
            before = client.request(0x34)
        assert before['voice_domain_preference'] == 0 and before['mode_preference_mask'] == 28
    if os.path.isfile(s.STATE + '/retained-provider.json'):
        s.init_journal = init_retained_journal
    signal_trial = s.ACTIVE_PROFILE['id'] == 'passport-mobile-provision1-signal1-manual-research'
    if signal_trial:
        original_template = profiles.carrier_template
        def with_signalling_bearer(profile, mcc, mnc):
            template, content = original_template(profile, mcc, mnc)
            assert template['path'] == '/etc/carrier/config/404.xml'
            return template, signalling_bearer_xml(content)
        profiles.carrier_template = with_signalling_bearer
    early_sdp0 = s.ACTIVE_PROFILE['id'] in EARLY_SDP0_PROFILES
    if early_sdp0:
        assert s.ACTIVE_PROFILE['carrier']['data_apns'] == ['cmnet']
        assert n.attrs(n.read(IR92)).get('UsePreconditions') is None
        assert n.attrs(n.read(IR92)).get('HDvoice') is None
        s.temporary_binary = early_sdp0_binary
    s.status('configuring_manual_passport')
    s.configure()
    if s.ACTIVE_PROFILE.get('lte_attach'):
        # Record the DCA plan so stop/restore reverts the persisted data-centric sources.
        s.j['telecom_dca_plan'] = s.telecom_dca_plan
        s.j['configured_sim_fingerprint'] = hashlib.sha256(s.current_usim().encode('ascii')).hexdigest()
        assert s.j['configured_sim_fingerprint'] == telecom_datacentric_persisted()['sim_fingerprint']
        s.save_journal()
    if early_sdp0:
        assert s.j['binary_patches'][-1]['config_key'] == 'MediaDialog.EarlySdp'
        s.j['early_sdp0'] = {'MediaDialog.EarlySdp': 0, 'image_sha256': EARLY_SDP0_IMAGE,
                             'verified_mt_call': '2026-10-31T01:59 local, answered with audio'}
        s.save_journal()
    if s.ACTIVE_PROFILE['id'] in ('passport-mobile-pcaptrace-manual-research',
                                  'passport-mobile-hdvoice-manual-research'):
        enable_native_capture()
    if s.ACTIVE_PROFILE['id'] == 'passport-mobile-hdvoice-manual-research':
        enable_mobile_hdvoice()
    if s.ACTIVE_PROFILE['id'] == 'passport-mobile-psonly-manual-research':
        s.j['nas_voice_trial'] = {'owner': 'passport-mobile-nas-voice-only-v1', 'boot': s.boot_token(),
                                'before_epoch': 0, 'before_apply': None, 'applied': 1,
                                'restore_target': 0, 'attempted': False,
                                'temporary_until_power_cycle': True, 'restored': False}
        s.j['compatibility_trial'] = {'NAS_voice_domain': 1, 'scope': 'Mobile voice-only single variable'}
        s.save_journal()
    if s.ACTIVE_PROFILE['id'] == 'passport-mobile-preconditions0-manual-research':
        assert s.ACTIVE_PROFILE['carrier']['data_apns'] == ['cmnet']
        original = n.attrs(n.read(IR92)).get('UsePreconditions')
        assert original is None, 'An existing preconditions override needs independent review'
        s.j['pps_before'][IR92] = {'UsePreconditions': original}
        s.j['pps_applied'][IR92] = {'UsePreconditions': 'n:0'}
        s.j['compatibility_trial'] = {'UsePreconditions': 0, 'scope': 'mobile-incoming-single-variable'}
        s.save_journal()  # Persist ownership before changing the PPS field.
        s.apply_fields(IR92)
    if s.ACTIVE_PROFILE['id'] in ('passport-mobile-provision1-manual-research',
                                  'passport-mobile-provision1-signal1-manual-research'):
        assert s.j['carrier_template']['path'] == '/etc/carrier/config/404.xml'
        assert not os.path.lexists(MOBILE_SETTINGS), 'Existing carrier user settings must be preserved'
        assert n.attrs(n.read(IR92)).get('UsePreconditions') is None
        # The exact stock image contains /ims/UserSettings/User as its settings
        # XPath. The carrier-specific filename is also pinned in that image.
        content = (b'<?xml version="1.0" encoding="UTF-8"?>\n<ims><UserSettings><User>'
                   b'<AllowVoLteProvisioning>enabled</AllowVoLteProvisioning>'
                   b'</User></UserSettings></ims>\n')
        s.j['extra_carrier_settings'] = {'path': MOBILE_SETTINGS, 'before_absent': True,
                                        'sha256': n.digest(content)}
        s.j['compatibility_trial'] = {'AllowVoLteProvisioning': 1,
                                     'scope': 'mobile-incoming-single-variable'}
        if signal_trial:
            s.j['compatibility_trial']['RequestSignallingBearerViaPCO'] = True
            s.j['compatibility_trial']['scope'] = 'one-added-PCO-option-from-provision1-baseline'
        s.save_journal()
        fd = os.open(MOBILE_SETTINGS, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chown(MOBILE_SETTINGS, 453, 31)
        assert n.digest(n.read(MOBILE_SETTINGS)) == s.j['extra_carrier_settings']['sha256']
    s.j['lifecycle'] = 'retain-provider-until-reboot'
    s.j['manual_only'] = True
    s.save_journal()
    assert not n.ims_pids(), 'Native IMS appeared during configuration'
    return True


def signalling_bearer_xml(content):
    original = b'<RequestPCSCFViaPCO>true</RequestPCSCFViaPCO>'
    added = b'<RequestSignallingBearerViaPCO>true</RequestSignallingBearerViaPCO>'
    assert content.count(original) == 1 and b'RequestSignallingBearerViaPCO' not in content
    result = content.replace(original, original + added)
    assert result.replace(original + added, original) == content
    return result


def redirect():
    os.setsid()
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    null = os.open('/dev/null', os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(null, fd)
    if null > 2:
        os.close(null)


def watchdog(manager_pid, boot, expires):
    """Independent death/lease monitor; waits for idle before owned restoration."""
    try:
        while s.boot_token() == boot:
            time.sleep(4)
            if os.path.isfile(s.JOURNAL):
                saved = s.load(s.JOURNAL)
                if saved.get('configuration_restored'):
                    return
            if s.alive(manager_pid) and time.time() < expires:
                continue
            if not s.phone_idle():
                continue
            # Let a live manager process its own stop before trying recovery.
            if s.alive(manager_pid):
                if not os.path.exists(s.STOP):
                    n.atomic(s.STOP, b'watchdog lease stop\n')
                continue
            # QNX stops native IMS early in shutdown; a radio-policy reload then is unsafe.
            if os.path.isfile(s.STATUS) and s.load(s.STATUS).get('phase') in PRESERVED_EXITS:
                return
            if not os.path.isfile(s.JOURNAL):
                return
            s.j = s.load(s.JOURNAL)
            if s.j.get('boot') != boot:
                return
            restore_retaining_provider()
            return
    except Exception:
        n.atomic(BASE + '/state/watchdog-error.txt', traceback.format_exc().encode('utf-8'))


def launch():
    precheck()
    assert not os.path.exists(s.JOURNAL), 'A previous trial requires reconciliation first'
    if os.path.exists(s.LOCK):
        old = s.load(s.LOCK)
        assert old.get('boot') != s.boot_token() or not s.alive(old['pid'])
    assert not os.path.exists(BASE + '/state/launch.json'), 'Do not retry an uncertain launch'
    boot = s.boot_token()
    lease_seconds = 1200 if s.ACTIVE_PROFILE['id'] in (
        'passport-mobile-pcaptrace-manual-research', 'passport-mobile-hdvoice-manual-research') else 1800
    expires = time.time() + lease_seconds
    n.atomic(BASE + '/state/lease.json', json.dumps({'boot': boot, 'deadline_unix': expires}).encode('ascii'))
    n.atomic(BASE + '/state/launch.json', json.dumps({'boot': boot, 'started_unix': time.time(),
             'deadline_unix': expires, 'lifecycle': 'retain-provider-until-reboot'}).encode('ascii'))
    pid = os.fork()
    if pid == 0:
        redirect()
        # The watchdog exists before any voice/PPS/provider mutation.
        manager_pid = os.getpid()
        watcher = os.fork()
        if watcher == 0:
            try:
                watchdog(manager_pid, boot, expires)
            finally:
                os._exit(0)
        n.atomic(BASE + '/state/watchdog.json', json.dumps({'pid': watcher, 'manager_pid': os.getpid(),
                 'boot': boot, 'deadline_unix': expires}).encode('ascii'))
        s.restore = restore_retaining_provider
        s.stopping = lease_stopping
        s.prepare_connection = prepare_manual
        if s.ACTIVE_PROFILE['id'] == 'passport-mobile-psonly-manual-research':
            s.live = ps_only_live
        try:
            s.serve()
        finally:
            os._exit(0)
    return {'started_manager_pid': pid, 'lease_seconds': lease_seconds,
            'autostart': False, 'lifecycle': 'retain-provider-until-reboot'}


def public_status():
    raw = s.read_status()
    result = {key: raw.get(key) for key in ('phase', 'manager_alive', 'native_alive',
              'status_from_current_boot', 'ims_observation_scope', 'current', 'native_pid')}
    result.update(crypto=n.crypto_policy(), voice_policy=n.voice_policy(),
                  native_count=len(n.ims_pids()), autostart=autostart_summary(),
                  lifecycle='retain-provider-until-reboot', phone_idle=s.phone_idle())
    for key in ('stock_handoff', 'startup_timing', 'error'):
        if raw.get('status_from_current_boot') and raw.get(key):
            result[key] = raw[key]
    if os.path.isfile(s.JOURNAL):
        saved = s.load(s.JOURNAL)
        result['configuration_restored'] = saved.get('configuration_restored', False)
        result['full_restore_verified'] = saved.get('restore_completed', False)
        result['reboot_verification_required'] = saved.get('reboot_verification_required', True)
    if os.path.isfile(s.STATUS):
        status = s.load(s.STATUS)
        result['error_present'] = status.get('error') is not None
        if isinstance(status.get('startup_wait'), dict):
            result['startup_wait'] = status['startup_wait']
    return result


def stop():
    verify_inputs()
    if os.path.isfile(s.LOCK):
        lock = s.load(s.LOCK)
        if lock.get('boot') == s.boot_token() and s.alive(lock['pid']):
            n.atomic(s.STOP, b'explicit manual research stop\n')
            return {'stop_requested': True, 'provider_will_be_retained_until_reboot': True}
    s.j = s.load(s.JOURNAL)
    restore_retaining_provider()
    return public_status()


def reconcile_after_reboot():
    verify_inputs()
    s.j = s.load(s.JOURNAL)
    assert s.j.get('configuration_restored') is True
    # Only a run that never enabled the provider has nothing left for a reboot to clear.
    same_boot = s.j.get('boot') == s.boot_token()
    assert not same_boot or (not s.j.get('provider_enable_attempted') and not manager_active()), \
        'A new boot is required'
    assert s.phone_idle() and not n.active_vpn_sessions()
    assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
    assert n.voice_policy() == 0
    assert not os.path.lexists(s.XML) and not os.path.lexists(s.CFG_DIR)
    assert not os.listdir('/var/radio/cdsc')
    for path, values in s.j['pps_before'].items():
        actual = n.attrs(n.read(path))
        assert all(actual.get(key) == expected for key, expected in values.items()), 'Reboot configuration conflict'
    if s.j.get('telecom_dca_plan'):
        import telecom_native
        assert s.load(s.STATE + '/telecom-bootstrap.json')['phase'] == 'restored'
        assert os.path.isfile(s.j['telecom_dca_plan'] + '/done')
        assert telecom_native.ue_usage_policy() == 0
    # Only known inert runtime copies can be removed; archive all receipts/logs.
    for path, expected in s.j['managed_files'].items():
        if path.startswith(s.RUNTIME + '/') and os.path.exists(path):
            assert not os.path.islink(path) and n.digest(n.read(path)) == expected
    report = {'provider_cleared_by_normal_reboot': not same_boot, 'same_boot_without_provider': same_boot,
              'crypto': n.crypto_policy(),
              'voice_policy': n.voice_policy(), 'configuration_restored': True,
              'previous_boot': s.j['boot'], 'current_boot': s.boot_token(),
              'native_ims_count': len(n.ims_pids()), 'autostart': False,
              'reconciled_unix': time.time()}
    s.j.update(restore_completed=True, reboot_verification_required=False,
               provider_retained_until_reboot=False, reboot_verification=report)
    s.save_journal()
    for path, expected in s.j['managed_files'].items():
        if path.startswith(s.RUNTIME + '/') and os.path.exists(path):
            os.unlink(path)
    archive = BASE + '/archive'
    if not os.path.exists(archive):
        os.mkdir(archive, 0o700)
    assert not os.path.islink(archive)
    target = archive + '/trial-' + str(int(s.j['created_unix']))
    assert not os.path.exists(target)
    os.rename(s.STATE, target)
    os.mkdir(s.STATE, 0o700)
    n.atomic(BASE + '/last-reboot-verification.json', json.dumps(report, indent=2).encode('ascii'))
    return report


def idle_stock_proof(pid):
    assert n.ims_pids() == [pid] and s.phone_idle() and not n.active_vpn_sessions()
    assert network_usable() and n.value(n.attrs(n.read('/pps/services/ims/status_public')), 'status') == 'disconnected'
    config = n.attrs(n.read(s.IMS))
    assert all(n.value(config, key) in (None, []) for key in ('IMS_profiles', 'IMS_profilesV2'))
    rows = [line.strip().split() for line in n.command(
        ['/bin/pidin', '-p', str(pid), '-f', 'A']).decode('ascii').splitlines() if line.strip()]
    assert rows == [['Arguments'], ['/radio/bin/ims_rrm', '-U', '453:31,80,387,427,521,1001']]
    names = [line.strip() for line in n.command(
        ['/bin/pidin', '-p', str(pid), '-F', '%80N']).decode('ascii').splitlines() if line.strip()]
    assert len(names) == 2 and names[0] == 'name'
    assert posixpath.normpath('/' + names[1].lstrip('/')) == '/radio/bin/ims_rrm'
    logs = n.command(['/bin/slog2info', '-b', 'ims_rrm'], 8).decode('utf-8', 'replace')
    own = '\n'.join(line for line in logs.splitlines() if 'ims_rrm.' + str(pid) + ' ' in line)
    assert 'No IMS profiles provisioned .. waiting' in own and 'exit req but wait acl' not in own
    pointers = re.findall(r'bb\.cfgmgr:\d+ imsProfiles= 0x([0-9a-fA-F]+)', own)
    assert pointers and int(pointers[-1], 16) == 0
    assert not re.search(r'CSeq:\s*\d+\s+(?:REGISTER|INVITE)\b', own)


def handoff_idle_stock():
    """One exact-PID SIGTERM per boot, only for proven idle no-profile stock."""
    verify_inputs()
    assert not manager_active(), 'Manual manager already active'
    assert network_usable() and s.current_usim()
    # An interrupted run leaves the owned voice policy until restore-previous-boot.
    voice = (0, 3) if previous_boot_unrestored() else (0,)
    assert n.voice_policy() in voice and n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
    pids = n.ims_pids()
    if not pids:
        return {'stock_already_exited': True, 'signal_sent': False}
    assert len(pids) == 1
    pid = pids[0]
    token = s.boot_token()
    receipt = BASE + '/stock-handoff-' + str(token[0]) + '.json'
    assert not os.path.exists(receipt), 'A handoff was already attempted this boot'
    idle_stock_proof(pid)
    time.sleep(3)
    idle_stock_proof(pid)
    assert s.boot_token() == token
    record = {'boot': token, 'pid': pid, 'at': time.time(),
              'reason': 'exact_stock_idle_no_profiles', 'signal': 'SIGTERM',
              'calls_empty': True, 'active_vpn_count': 0}
    n.atomic(receipt, json.dumps(record, indent=2).encode('ascii'))
    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 25
    while n.ims_pids() and time.time() < deadline:
        time.sleep(0.5)
    record['stock_exited'] = not n.ims_pids()
    if record['stock_exited']:
        time.sleep(3)
        record['quiet_after_exit'] = not n.ims_pids()
    n.atomic(receipt, json.dumps(record, indent=2).encode('ascii'))
    return record


def telecom_prepare():
    """Save the four DCA originals; launch requires the desktop's independent backup receipt."""
    verify_inputs()
    assert s.ACTIVE_PROFILE['id'] in TELECOM_PROFILES and not manager_active()
    assert not os.path.isfile(s.JOURNAL), 'Reconcile the previous run first'
    assert telecom_datacentric_persisted() is None, 'Revert the persisted data-centric before re-preparing'
    return telecom().prepare(s)


def only_stock_ims():
    for pid in n.ims_pids():
        rows = [line.strip().split() for line in n.command(
            ['/bin/pidin', '-p', str(pid), '-f', 'A']).decode('ascii').splitlines() if line.strip()]
        if rows != [['Arguments'], ['/radio/bin/ims_rrm', '-U', '453:31,80,387,427,521,1001']]:
            return False
    return True


def select_candidate_profile():
    """Start a new operator epoch only after proven owned recovery, no radio writes."""
    verify_inputs()
    assert telecom_datacentric_persisted() is None, 'Revert the persisted data-centric before switching profiles'
    # The stock engine may keep running: the handoff needs the profile that matches the new card.
    assert not os.path.isfile(s.LOCK) and s.phone_idle() and only_stock_ims()
    assert not n.active_vpn_sessions() and n.voice_policy() == 0
    assert all(compatibility.configuration_diagnostics().values())
    candidate = profiles.load_request(BASE + '/profile-candidate.json')
    profile = candidate['profile']
    assert candidate['allow_experimental'] is True and profile['runtime']['autostart'] is False
    allowed = {'01': ['3gnet'], '00': ['cmnet'], '02': ['cmnet'], '07': ['cmnet'],
               '03': ['ctnet', 'ctlte'], '11': ['ctnet', 'ctlte']}
    assert profile['carrier']['mcc'] == '460' and profile['carrier']['stock_config'] == 'auto'
    assert all(mnc in allowed and sorted(allowed[mnc]) == profile['carrier']['data_apns']
               for mnc in profile['carrier']['mncs'])
    network = compatibility.read_network(profile)
    if profile.get('lte_attach'):
        assert profile['id'] in TELECOM_PROFILES and not os.path.isfile(s.JOURNAL), 'Telecom needs a fresh boot'
    assert compatibility.network_state(network, profile) == 'ready' or attach_pending(network, profile)
    template, unused = profiles.carrier_template(profile, network['mcc'], network['mnc'])
    crypto = n.crypto_policy()
    proof = None
    if os.path.isfile(s.JOURNAL):
        old = s.load(s.JOURNAL)
        assert old['owner'] == 'q10-unicom-volte-v1' and old.get('configuration_restored') is True
        if old.get('extra_carrier_settings'):
            assert old['extra_carrier_settings']['path'] == MOBILE_SETTINGS
            assert not os.path.lexists(MOBILE_SETTINGS), 'Previous carrier settings still exist'
        assert old.get('boot') == s.boot_token(), 'Reconcile a new boot before changing profile'
        assert old.get('crypto_boot') == s.boot_token() and old.get('provider') == crypto['swcr_id']
        assert 0 <= crypto['swcr_id'] <= 127 and crypto['crypto_support'] == 0
        if os.path.isfile(s.STATE + '/watchdog.json'):
            watcher = s.load(s.STATE + '/watchdog.json')
            deadline = time.time() + 8
            while watcher.get('boot') == s.boot_token() and s.alive(watcher['pid']) and time.time() < deadline:
                time.sleep(0.5)
            assert watcher.get('boot') != s.boot_token() or not s.alive(watcher['pid']), 'Previous watchdog still active'
        paths = []
        for path, expected in old['managed_files'].items():
            assert path == s.XML or path.startswith(s.RUNTIME + '/')
            if os.path.exists(path):
                assert path.startswith(s.RUNTIME + '/') and not os.path.islink(path)
                assert n.digest(n.read(path)) == expected
                paths.append(path)
        archive = BASE + '/archive'
        if not os.path.exists(archive):
            os.mkdir(archive, 0o700)
        assert not os.path.islink(archive)
        destination = archive + '/trial-' + str(int(old['created_unix']))
        assert not os.path.exists(destination)
        # Verify all ownership/inputs first. Only inert, hash-matched copies are removed.
        for path in paths:
            os.unlink(path)
        os.rename(s.STATE, destination)
        os.mkdir(s.STATE, 0o700)
        origin = old.get('provider_origin')
        if origin is None:
            assert old.get('provider_enable_attempted') is True
            origin = {'path': destination + '/journal.json',
                      'sha256': n.digest(n.read(destination + '/journal.json'))}
        proof = {'owner': 'passport-retained-provider-epoch-v1', 'boot': s.boot_token(),
                 'provider': crypto['swcr_id'], 'origin': origin,
                 'profile_sha256': profiles.fingerprint(candidate), 'prepared_unix': time.time()}
    else:
        assert crypto == {'swcr_id': -1, 'crypto_support': 0}
    n.atomic(BASE + '/profile-request.json', profiles.canonical(candidate))
    manifest = s.load(BASE + '/research-manifest.json')
    manifest['files']['profile-request.json'] = n.digest(n.read(BASE + '/profile-request.json'))
    n.atomic(BASE + '/research-manifest.json', json.dumps(manifest, indent=2).encode('ascii'))
    if proof is not None:
        n.atomic(s.STATE + '/retained-provider.json', json.dumps(proof, indent=2).encode('ascii'))
    return {'profile_selected': profile['id'], 'profile_sha256': profiles.fingerprint(candidate),
            'carrier_template': template, 'reusing_owned_provider': proof is not None,
            'radio_configuration_writes': 0, 'autostart': False}


def acceptance_valid(receipt, sha):
    valid = (receipt.get('owner') == 'passport-call-acceptance-v1' and receipt.get('variant') == 'SQW100-4'
            and receipt.get('profile_sha256') == sha and receipt.get('profile_id') == s.ACTIVE_PROFILE['id']
            and s.ACTIVE_PROFILE['id'] in AUTOSTART_PROFILES
            and all(receipt.get(key) is True for key in
                    ('incoming', 'outgoing', 'audio_both_directions', 'lte', 'sip_dialogs_verified')))
    if s.ACTIVE_PROFILE['id'] in TELECOM_PROFILES:
        fingerprint = receipt.get('sim_fingerprint')
        return valid and isinstance(fingerprint, str) and re.match(r'^[a-f0-9]{64}$', fingerprint) is not None
    return valid


def telecom_acceptance_sim(receipt):
    """Authorize this exact accepted Telecom SIM before any automatic configuration."""
    assert s.ACTIVE_PROFILE['id'] in TELECOM_PROFILES
    fingerprint = hashlib.sha256(s.current_usim().encode('ascii')).hexdigest()
    marker = telecom_datacentric_persisted()
    assert marker is not None and marker['owner'] == 'bb10-telecom-attach-v1'
    assert marker['profile_sha256'] == receipt['profile_sha256'] == profiles.fingerprint(s.ACTIVE_REQUEST)
    assert marker['sim_fingerprint'] == receipt['sim_fingerprint'] == fingerprint, 'Accepted Telecom SIM changed'
    return fingerprint


def acceptance_receipt():
    sha = profiles.fingerprint(s.ACTIVE_REQUEST)
    path = ACCEPTANCE + '/' + sha + '.json'
    assert not os.path.islink(path)
    receipt = s.load(path)
    assert acceptance_valid(receipt, sha), 'Manual call acceptance is required for this profile'
    return receipt


def accept_calls():
    """Bind a desktop SIP summary to this boot's owned evidence and profile."""
    verify_inputs()
    path = BASE + '/acceptance-candidate.json'
    candidate = s.load(path)
    sha = profiles.fingerprint(s.ACTIVE_REQUEST)
    assert acceptance_valid(candidate, sha), 'Incomplete call acceptance'
    assert candidate['boot'] == s.boot_token()
    journal = s.load(s.JOURNAL)
    assert journal['boot'] == s.boot_token() and journal['profile_sha256'] == sha
    if s.ACTIVE_PROFILE['id'] in TELECOM_PROFILES:
        assert journal['configured_sim_fingerprint'] == telecom_acceptance_sim(candidate)
    folder = candidate['phone_folder']
    assert folder.startswith(EVIDENCE + '/acceptance-') and '..' not in folder and not os.path.islink(folder)
    meta = s.load(folder + '/meta.json')
    assert meta['boot'] == candidate['boot'] and meta['native_pid'] == candidate['native_pid']
    assert meta['profile_sha256'] == sha
    assert n.digest(n.read(folder + '/owned-ims.log')) == candidate['raw_log_sha256']
    if not os.path.isdir(ACCEPTANCE):
        os.mkdir(ACCEPTANCE, 0o700)
    assert not os.path.islink(ACCEPTANCE)
    target = ACCEPTANCE + '/' + sha + '.json'
    n.atomic(target, json.dumps(candidate, indent=2).encode('ascii'))
    os.unlink(path)
    return {'accepted_profile': s.ACTIVE_PROFILE['id'], 'profile_sha256': sha, 'receipt': target}


def autostart_summary():
    result = {'enabled': os.path.isfile(ENABLED), 'addon_installed': os.path.isfile(ADDON + '/init/start.sh'),
              'profile_id': s.ACTIVE_PROFILE['id']}
    try:
        acceptance_receipt()
        result['profile_accepted'] = True
    except Exception:
        result['profile_accepted'] = False
    if os.path.isfile(BOOT_RECORD):
        launch = s.load(BOOT_RECORD)
        result['last_boot_launch'] = launch
        result['last_boot_launch_is_current'] = launch.get('boot') == s.boot_token()
    return result


def enable_autostart():
    verify_inputs()
    receipt = acceptance_receipt()
    if s.ACTIVE_PROFILE['id'] in TELECOM_PROFILES:
        telecom_acceptance_sim(receipt)
    assert not os.path.isfile('/var/rootdata/q10_volte/enabled')
    assert not os.path.lexists(ADDONS + '/q10-unicom-volte')
    script = n.read(BASE + '/addon-start.sh')
    digest = n.digest(script)
    start = ADDON + '/init/start.sh'
    if os.path.isfile(AUTOSTART_RECORD):
        record = s.load(AUTOSTART_RECORD)
        assert record['owner'] == 'passport-volte-autostart-v1' and record['addon'] == ADDON
        if record['start_sha256'] is not None:
            assert not os.path.islink(start) and n.digest(n.read(start)) == record['start_sha256'], \
                'Addon changed outside the project'
    else:
        assert not os.path.lexists(ADDON), 'Preserve an unowned addon'
        # Journal ownership before the first directory exists.
        record = {'owner': 'passport-volte-autostart-v1', 'addon': ADDON, 'created_unix': time.time(),
                  'created_addons_root': not os.path.lexists(ADDONS), 'start_sha256': None}
        n.atomic(AUTOSTART_RECORD, json.dumps(record, indent=2).encode('ascii'))
    if record['created_addons_root'] and not os.path.isdir(ADDONS):
        os.mkdir(ADDONS, 0o755)
    assert os.path.isdir(ADDONS) and not os.path.islink(ADDONS)
    for path in (ADDON, ADDON + '/data', ADDON + '/init'):
        if not os.path.isdir(path):
            os.mkdir(path, 0o755)
        assert not os.path.islink(path)
    assert set(os.listdir(ADDON)) == {'data', 'init'} and not os.listdir(ADDON + '/data')
    assert set(os.listdir(ADDON + '/init')) <= {'start.sh', 'start.sh.new'}
    if record['start_sha256'] != digest:
        n.atomic(start, script, 0o700)
        record.update(start_sha256=digest, updated_unix=time.time())
        n.atomic(AUTOSTART_RECORD, json.dumps(record, indent=2).encode('ascii'))
    n.command(['/proc/boot/pathtrust', '!' + start])
    assert n.digest(n.read(start)) == digest
    n.atomic(ENABLED, b'enabled by owner after manual call acceptance\n')
    return autostart_summary()


def disable_autostart():
    """Remove the boot entry only; a running manager is stopped separately."""
    verify_inputs()
    if os.path.exists(ENABLED):
        os.unlink(ENABLED)
    removed = False
    if os.path.isfile(AUTOSTART_RECORD):
        record = s.load(AUTOSTART_RECORD)
        assert record['owner'] == 'passport-volte-autostart-v1' and record['addon'] == ADDON
        start = ADDON + '/init/start.sh'
        if os.path.lexists(start):
            assert not os.path.islink(start) and n.digest(n.read(start)) == record['start_sha256'], \
                'Addon changed outside the project'
            os.unlink(start)
        for path in (ADDON + '/init', ADDON + '/data', ADDON):
            if os.path.isdir(path):
                assert not os.listdir(path), 'Preserve unowned addon content'
                os.rmdir(path)
        if record['created_addons_root'] and os.path.isdir(ADDONS) and not os.listdir(ADDONS):
            os.rmdir(ADDONS)
        os.rename(AUTOSTART_RECORD, AUTOSTART_RECORD + '.removed-' + str(int(time.time())))
        removed = True
    result = autostart_summary()
    result.update(addon_removed=removed, running_manager_unchanged=True)
    return result


def apply_mobile_menu():
    """Re-apply the reviewed runtime Settings template for 460-00; it is cleared at boot."""
    try:
        card = n.attrs(n.read('/pps/services/cellular/uicc/card0/status_private'))
        if n.value(card, 'hplmn') != {'mcc': '460', 'mnc': '00'}:
            return {'applied': False, 'reason': 'not_460_00'}
        assert n.digest(n.read(MENU_TOOL)) == MENU_TOOL_HASH
        n.command(['/proc/boot/pathtrust', '!' + MENU_TOOL])
        if NAS_DIR not in sys.path:
            sys.path.insert(0, NAS_DIR)
        import passport_mobile_radio_ui_phone as ui
        ui.identity()
        current = n.attrs(n.read(ui.PATH))
        applied = ui.replacement()
        token = ui.boot()
        if os.path.lexists(ui.RECEIPT):
            assert not os.path.islink(ui.RECEIPT)
            previous = s.load(ui.RECEIPT)
            assert previous['owner'] == 'passport-mobile-radio-ui-v1' and previous['path'] == ui.PATH
            assert previous['applied'] == applied
            if previous['boot'] == token:
                return {'applied': current.get('network_technologies') == applied, 'reason': 'handled_this_boot'}
            assert current.get('network_technologies') == previous['before'], 'Carrier menu changed independently'
            archive = ui.RECEIPT + '.boot-' + str(previous['boot'][0])
            if os.path.lexists(archive):
                archive += '-' + str(int(time.time()))
            os.rename(ui.RECEIPT, archive)
        value = n.value(current, 'network_technologies')
        assert len(value) == 1 and value[0]['nw_tech_name'] == 'NETWORK_TECH_GSM_HSPA_UMTS'
        assert value[0]['default_nw_mode'] == 'UMTS_GSM'
        assert value[0]['nw_modes'] == [['UMTS_GSM', 'NETWORK_MODE_3G_2G'],
                                      ['UMTS', 'NETWORK_MODE_3G'], ['GSM', 'NETWORK_MODE_2G']]
        assert current.get('network_technology_lte_disabled') is None
        receipt = {'owner': 'passport-mobile-radio-ui-v1', 'created_unix': time.time(), 'boot': token,
                   'path': ui.PATH, 'before': current['network_technologies'], 'applied': applied,
                   'stock_asset_sha256': ui.ASSET_HASH, 'restored': False,
                   'scope': 'SQW100-4 / Mobile 460-00; runtime PPS only', 'source': 'passport-volte-boot'}
        n.atomic(ui.RECEIPT, json.dumps(receipt, indent=2).encode('ascii'))
        n.update_pps(ui.PATH, {'network_technologies': applied})
        assert n.attrs(n.read(ui.PATH))['network_technologies'] == applied
        return {'applied': True}
    except Exception as error:
        # A Settings-menu convenience must never block voice configuration.
        return {'applied': False, 'error_type': type(error).__name__}


def boot_stock_handoff():
    """Autostart form of handoff-idle-stock; any doubt selects the passive wait."""
    s.startup_handoff = {'attempted': False}
    signalled = False
    try:
        token = s.boot_token()
        receipt = BASE + '/stock-handoff-' + str(token[0]) + '.json'
        if os.path.exists(receipt):
            s.startup_handoff['reason'] = 'already_attempted_this_boot'
            return False
        continuing = os.path.isfile(s.JOURNAL)
        if continuing:
            saved = s.load(s.JOURNAL)
            assert saved.get('boot') != token and not saved.get('configuration_restored')
        # Root setup can finish before the stock engine logs its idle wait.
        proofs = 0
        pid = None
        for unused in range(40):
            if s.stopping():
                break
            pids = n.ims_pids()
            if not pids:
                s.startup_handoff['reason'] = 'no_stock_process'
                return False
            try:
                assert len(pids) == 1 and pid in (None, pids[0])
                pid = pids[0]
                assert n.voice_policy() in ((0, 3) if continuing else (0,))
                assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
                idle_stock_proof(pid)
                proofs += 1
            except AssertionError:
                proofs = 0
            if proofs >= 2:
                break
            time.sleep(3)
        if proofs < 2 or s.stopping() or s.boot_token() != token:
            s.startup_handoff['reason'] = 'no_current_idle_stock_evidence'
            return False
        record = {'boot': token, 'pid': pid, 'at': time.time(), 'reason': 'exact_stock_idle_no_profiles',
                  'signal': 'SIGTERM', 'calls_empty': True, 'active_vpn_count': 0, 'source': 'autostart'}
        n.atomic(receipt, json.dumps(record, indent=2).encode('ascii'))
        s.startup_handoff = {'attempted': True, 'reason': 'sigterm_requested', 'pid': pid,
                             'boot': token, 'requested_at': time.time()}
        os.kill(pid, signal.SIGTERM)
        signalled = True
        s.startup_timing['stock_exit_requested'] = time.time()
        s.startup_handoff['signal_delivered'] = True
        return True
    except Exception as error:
        s.startup_handoff.update(reason='passive_wait_after_unavailable_evidence',
                                 error_type=type(error).__name__)
        return signalled


def autostart_configure(original):
    def configure():
        verify_inputs()
        assert s.phone_idle() and not n.ims_pids() and not n.active_vpn_sessions()
        telecom_sim = None
        if s.ACTIVE_PROFILE['id'] in TELECOM_PROFILES:
            telecom_sim = telecom_acceptance_sim(acceptance_receipt())
            telecom_ensure_lte()
        early_sdp0 = s.ACTIVE_PROFILE['id'] in EARLY_SDP0_PROFILES
        if early_sdp0:
            assert s.ACTIVE_PROFILE['carrier']['data_apns'] == ['cmnet']
            assert n.attrs(n.read(IR92)).get('UsePreconditions') is None
            assert n.attrs(n.read(IR92)).get('HDvoice') is None
            s.temporary_binary = early_sdp0_binary
        menu = apply_mobile_menu() if s.ACTIVE_PROFILE['carrier']['data_apns'] == ['cmnet'] else None
        original()
        if telecom_sim is not None:
            assert hashlib.sha256(s.current_usim().encode('ascii')).hexdigest() == telecom_sim
            s.j.update(telecom_dca_plan=s.telecom_dca_plan, configured_sim_fingerprint=telecom_sim)
        if early_sdp0:
            assert s.j['binary_patches'][-1]['config_key'] == 'MediaDialog.EarlySdp'
            s.j['early_sdp0'] = {'MediaDialog.EarlySdp': 0, 'image_sha256': EARLY_SDP0_IMAGE}
        s.j.update(lifecycle='retain-provider-until-reboot', manual_only=False,
                   autostart={'source': 'autoroot-v4-addon', 'boot': s.boot_token(), 'mobile_menu': menu})
        s.save_journal()
        assert not n.ims_pids(), 'Native IMS appeared during configuration'
    return configure


def archive_previous_boot_files(token):
    names = [name for name in ('launch.json', 'lease.json', 'watchdog.json', 'retained-provider.json')
             if os.path.lexists(s.STATE + '/' + name)]
    for name in names:
        assert s.load(s.STATE + '/' + name).get('boot') != token
    if names:
        archive = BASE + '/archive'
        if not os.path.exists(archive):
            os.mkdir(archive, 0o700)
        assert not os.path.islink(archive)
        folder = archive + '/previous-boot-' + str(int(time.time()))
        os.mkdir(folder, 0o700)
        for name in names:
            os.rename(s.STATE + '/' + name, folder + '/' + name)
    return names


def profile_sim_state(seconds=120):
    """A swapped card must leave the stock IMS and any previous run untouched."""
    deadline = time.time() + seconds
    while True:
        try:
            s.current_usim()
            return 'matches'
        except AssertionError as error:
            if str(error) != 'SIM not ready':
                return 'does_not_match_profile'
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            pass
        if time.time() >= deadline:
            return 'not_ready'
        time.sleep(2)


def boot():
    """AutoRoot v4 addon entry: at most one owned start per boot, for an accepted profile."""
    token = s.boot_token()
    record = {'boot': token, 'at': time.time(), 'source': 'autoroot-v4-addon',
              'profile_id': s.ACTIVE_PROFILE['id']}

    def finish(mode, **extra):
        record.update(extra)
        record['mode'] = mode
        n.atomic(BOOT_RECORD, json.dumps(record, indent=2).encode('ascii'))
        return record
    if not os.path.isfile(ENABLED):
        return {'mode': 'skipped', 'reason': 'not_enabled'}
    if os.path.isfile(BOOT_RECORD) and s.load(BOOT_RECORD).get('boot') == token:
        return {'mode': 'skipped', 'reason': 'already_attempted_this_boot'}
    finish('starting')
    verify_inputs()
    record['profile_sha256'] = acceptance_receipt()['profile_sha256']
    if os.path.isfile(s.LOCK):
        lock = s.load(s.LOCK)
        if lock.get('boot') == token and s.alive(lock['pid']):
            return finish('skipped', reason='manager_already_running')
    sim = profile_sim_state()
    if sim != 'matches':
        return finish('skipped', reason='sim_' + sim)
    if s.ACTIVE_PROFILE['id'] in TELECOM_PROFILES:
        telecom_acceptance_sim(acceptance_receipt())
    mode = 'fresh'
    if os.path.isfile(s.JOURNAL):
        saved = s.load(s.JOURNAL)
        assert saved['owner'] == 'q10-unicom-volte-v1' and saved['original_voice_policy'] == 0
        if saved.get('boot') == token:
            return finish('skipped', reason='journal_from_this_boot')
        if saved.get('configuration_restored'):
            deadline = time.time() + 120
            while not s.phone_idle() and time.time() < deadline:
                time.sleep(2)
            report = reconcile_after_reboot()
            s.j = None
            record['reconciled_previous_boot'] = report['previous_boot']
        else:
            if os.path.exists(s.STOP):
                return finish('skipped', reason='stop_requested_before_reboot')
            assert saved.get('profile_sha256') == record['profile_sha256'], 'Restore the previous profile first'
            assert saved.get('lifecycle') == 'retain-provider-until-reboot'
            record['previous_boot_files'] = archive_previous_boot_files(token)
            mode = 'continue_previous_boot'
    elif os.path.isfile(s.STATE + '/retained-provider.json'):
        record['previous_boot_files'] = archive_previous_boot_files(token)
    pid = os.fork()
    if pid == 0:
        redirect()
        s.restore = restore_retaining_provider
        s.request_idle_stock_exit = boot_stock_handoff
        s.configure = autostart_configure(s.configure)
        if s.ACTIVE_PROFILE['id'] in TELECOM_PROFILES:
            # The shared prepare_connection calls telecom_attach.ensure_lte
            # before the configure hook. Route that first call through the
            # already persisted Passport cold-boot path, before stock handoff.
            def persisted_attach(service):
                assert service is s
                return telecom_ensure_lte()
            telecom().ensure_lte = persisted_attach
        try:
            s.serve()
        finally:
            os._exit(0)
    return finish(mode, manager_pid=pid)


def main():
    setup()
    assert len(sys.argv) == 2 and os.geteuid() == 0
    action = sys.argv[1]
    if action == 'precheck':
        result = precheck()
    elif action == 'launch':
        result = launch()
    elif action == 'status':
        result = public_status()
    elif action == 'stop':
        result = stop()
    elif action == 'reconcile-after-reboot':
        result = reconcile_after_reboot()
    elif action == 'handoff-idle-stock':
        result = handoff_idle_stock()
    elif action == 'select-profile':
        result = select_candidate_profile()
    elif action == 'boot':
        result = boot()
    elif action == 'accept':
        result = accept_calls()
    elif action == 'enable-autostart':
        result = enable_autostart()
    elif action == 'disable-autostart':
        result = disable_autostart()
    elif action == 'telecom-prepare':
        result = telecom_prepare()
    elif action == 'telecom-persist':
        result = telecom_persist()
    elif action == 'telecom-revert':
        result = telecom_revert()
    elif action == 'restore-previous-boot':
        result = restore_previous_boot()
    else:
        raise ValueError('Supported actions: precheck, launch, status, stop, reconcile-after-reboot, '
                         'handoff-idle-stock, select-profile, boot, accept, enable-autostart, disable-autostart, '
                         'telecom-prepare, telecom-persist, telecom-revert, restore-previous-boot')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
