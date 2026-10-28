"""Install the reviewed payload and AutoRoot addon, or disable its boot entry."""
import json
import os
import shutil
import sys
import time
import native as n
import compatibility as compatibility
import profiles
import device_info

BASE = '/var/rootdata/q10_volte'
ADDON = '/var/addons/q10-unicom-volte'


def install(stage, update=False):
    assert stage.startswith('/var/rootdata/q10_volte_stage_') and os.path.realpath(stage) == stage
    manifest = json.loads(n.read(stage + '/payload-manifest.json').decode('ascii'))
    assert manifest['owner'] == 'q10-unicom-volte-v1'
    required = compatibility.FILES
    assert set(manifest['files']) == required
    for name, expected in manifest['files'].items():
        data = n.read(stage + '/' + name)
        assert n.digest(data) == expected, 'Payload hash mismatch: ' + name
        if name.endswith('.py'):
            compile(data, name, 'exec')
    assert manifest['files']['driver/devnp-volte_swcrypto_probe.so'] == n.HELPER_HASH
    request = profiles.load_request(stage + '/profile-request.json')
    n.verify_stock()
    # Authoritative fresh check on the phone, even if the desktop already checked.
    # No payload, addon, modem or carrier changes occur before this gate.
    compatibility.require('update' if update else 'install', request['profile'], request['allow_experimental'])
    if update:
        previous = json.loads(n.read(BASE+'/installation.json').decode('ascii'))
        assert previous['owner'] == manifest['owner']
        assert set(previous['files']) in (compatibility.LEGACY_FILES, compatibility.V02_FILES, required)
        for name, expected in previous['files'].items():
            assert n.digest(n.read(BASE+'/'+name)) == expected, 'Installed file changed outside the project: '+name
        assert n.digest(n.read(ADDON+'/init/start.sh')) == previous['files']['device/addon-start.sh']
        assert not os.path.exists(BASE+'/state/lock.json'), 'Stop the manager before updating'
        if os.path.isfile(BASE+'/state/journal.json'):
            assert json.loads(n.read(BASE+'/state/journal.json').decode('ascii'))['restore_completed']
    else:
        assert not os.path.exists(BASE) and not os.path.exists(ADDON), 'Existing installation: inspect before replacing'
    assert not n.ims_pids(), 'Stop the temporary IMS test before installing'
    assert n.voice_policy() == 0, 'Original voice policy00 required'
    assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
    assert not n.active_vpn_sessions()
    was_enabled = os.path.isfile(BASE + '/enabled')
    if update and was_enabled:
        # Keep the addon from starting mixed old/new files after a power loss.
        # A failed update remains disabled until explicitly inspected.
        os.unlink(BASE + '/enabled')
    for path, mode in ((BASE, 0o755), (BASE+'/device', 0o755), (BASE+'/driver', 0o755),
                       (BASE+'/state', 0o700), (BASE+'/runtime', 0o755), (BASE+'/runtime/carrier', 0o755)):
        if not update:
            os.mkdir(path, mode)
            os.chmod(path, mode)
    # An interrupted write is never silently treated as an installed release.
    # Preserve this receipt on error for explicit recovery; do not retry blindly.
    n.atomic(BASE + '/install-transaction.json', json.dumps({
        'owner': compatibility.OWNER, 'version': manifest['version'],
        'action': 'update' if update else 'install', 'phase': 'writing_payload',
        'previously_enabled': was_enabled
    }).encode('ascii'))
    for name in sorted(required):
        mode = 0o755 if name.endswith('.so') else 0o700 if name.endswith('.sh') else 0o600
        n.atomic(BASE + '/' + name, n.read(stage + '/' + name), mode)
        n.command(['/proc/boot/pathtrust', '!'+BASE+'/'+name])
    if not os.path.exists('/var/addons'):
        os.mkdir('/var/addons', 0o755)
    assert os.path.isdir('/var/addons') and not os.path.islink('/var/addons')
    for path in (ADDON, ADDON+'/data', ADDON+'/init'):
        if not update:
            os.mkdir(path, 0o755)
    n.atomic(ADDON + '/init/start.sh', n.read(BASE+'/device/addon-start.sh'), 0o700)
    n.command(['/proc/boot/pathtrust', '!'+ADDON+'/init/start.sh'])
    n.atomic(BASE + '/carrier-profile.json', profiles.canonical(request))
    manifest['carrier_profile_sha256'] = profiles.fingerprint(request)
    manifest['carrier_profile_id'] = request['profile']['id']
    n.atomic(BASE + '/installation.json', json.dumps(manifest, indent=2).encode('ascii'))
    if request['profile']['runtime']['autostart']:
        n.atomic(BASE + '/enabled', b'enabled by owner installation\n')
    os.unlink(BASE + '/install-transaction.json')
    print(json.dumps({'installed': True, 'base': BASE, 'addon': ADDON,
                      'updated': update, 'started': False, 'startup_validation_pending': True}))


def main():
    assert os.geteuid() == 0
    action = sys.argv[1]
    if action in ('install', 'update'):
        assert len(sys.argv) == 3
        install(sys.argv[2], action == 'update')
    elif action in ('enable', 'disable', 'uninstall'):
        if not device_info.provider_lifecycle_supported(device_info.identify(device_info.read_identity())):
            raise RuntimeError('Provider lifecycle needs validation; preserve state and see issue #1')
        manifest = json.loads(n.read(BASE+'/installation.json').decode('ascii'))
        assert manifest['owner'] == 'q10-unicom-volte-v1'
        if action == 'enable':
            request = profiles.installed_request(BASE)
            compatibility.require('enable', request['profile'], request['allow_experimental'])
            assert os.path.isfile(ADDON+'/init/start.sh'), 'Boot addon has been uninstalled'
            n.atomic(BASE+'/enabled', b'enabled by owner\n')
        else:
            if os.path.exists(BASE+'/enabled'):
                os.unlink(BASE+'/enabled')
            n.command(['/bin/sh', BASE+'/device/run.sh', 'stop'], 120)
            deadline = time.time()+120
            while os.path.exists(BASE+'/state/lock.json') and time.time()<deadline:
                time.sleep(1)
            assert not os.path.exists(BASE+'/state/lock.json'), 'Stop is still pending'
            if os.path.isfile(BASE+'/state/journal.json'):
                journal = json.loads(n.read(BASE+'/state/journal.json').decode('ascii'))
                assert journal['restore_completed'] and not n.ims_pids()
            if action == 'uninstall' and os.path.exists(ADDON):
                assert not os.path.islink(ADDON)
                assert set(os.listdir(ADDON)) == {'data', 'init'}
                assert not os.listdir(ADDON+'/data') and os.listdir(ADDON+'/init') == ['start.sh']
                assert n.digest(n.read(ADDON+'/init/start.sh')) == manifest['files']['device/addon-start.sh']
                os.unlink(ADDON+'/init/start.sh')
                os.rmdir(ADDON+'/init'); os.rmdir(ADDON+'/data'); os.rmdir(ADDON)
        print(json.dumps({'action': action, 'completed': True,
                          'private_backup_and_payload_retained': BASE}))
    else:
        raise SystemExit('Use install/update STAGE, enable, disable or uninstall')


if __name__ == '__main__':
    main()
