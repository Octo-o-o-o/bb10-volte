"""Isolated adapter for the existing, explicitly opted-in manual carrier route."""
import os
import sys
import entry as e


def require_start(profile):
    import compatibility
    import profiles
    e.require(profiles.installed_request(compatibility.BASE) == profiles.request(profile, True),
              'legacy_profile_changed')
    # A prior inspection is not permission to start later. Recheck the exact
    # trial identity, all six native images, SIM and restoration requirements.
    compatibility.require('start', profile, True)


def management_actions(report):
    installed = report.get('installation', {})
    owned = report.get('can_restore') is True and installed.get('payload_verified') is True
    state = installed.get('state')
    return {'can_stop': owned and state in ('busy', 'stopped', 'recovery_required'),
            'can_uninstall': owned and state in ('busy', 'stopped')}


def backup_plan(plan, request):
    import worker
    import telecom_attach
    import telecom_dca
    folder = plan['folder']
    e.require(folder.startswith('/var/rootdata/q10_volte/state/telecom-attach-') and
              os.path.realpath(folder) == folder, 'invalid_backup_plan')
    raw = e.regular(folder + '/plan.json', 131072)
    e.require(e.digest(raw) == plan['plan_sha256'], 'backup_plan_changed')
    value = e.json_bytes(raw)
    e.require(value['owner'] == telecom_attach.OWNER and set(value['files']) == set(telecom_dca.SOURCES),
              'backup_plan_changed')
    blobs, hashes = {'plan.json': raw}, {}
    for name, item in value['files'].items():
        member = name + '.original'
        data = e.regular(folder + '/' + member)
        e.require(e.digest(data) == item['original_sha256'], 'original_backup_changed')
        blobs[member], hashes[member] = data, item['original_sha256']
    location = request['backup_location']
    destination = worker.export_blobs(blobs, location, request['operation_id'])
    receipt = {'schema': 2, 'owner': telecom_attach.OWNER, 'source': 'mobile',
               'operation_id': request['operation_id'], 'plan_sha256': e.digest(raw),
               'all_original_hashes_verified': True, 'files': hashes,
               'readback': dict((name, e.digest(e.regular(destination + '/' + name))) for name in hashes),
               'destination': {'type': 'removable' if location == 'sdcard' else 'same_device', 'id': destination}}
    worker.save(folder + '/backup-receipt.json', receipt)
    telecom_attach.verified_backup_receipt(folder, value)
    return destination


def main():
    import io
    import json
    e.require(os.geteuid() == 0 and os.uname()[0] == 'QNX' and sys.flags.optimize == 0, 'root_required')
    folder = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    e.require(os.path.dirname(folder) == e.ROOT + '/snapshots', 'private_snapshot_required')
    e.private_directory(folder)
    bundle = e.read_bundle(folder)
    e.require(os.path.basename(folder) == e.digest(bundle[1]), 'snapshot_changed')
    request = e.json_bytes(e.decode64(sys.argv[1]))
    e.require(set(request) == {'action', 'profile_id', 'stage', 'backup_location', 'operation_id'}, 'invalid_request')
    action = request['action']
    e.require(action in ('legacy-inspect', 'legacy-install', 'legacy-start', 'legacy-stop',
                        'legacy-update', 'legacy-uninstall'), 'invalid_action')
    sys.path.insert(0, folder + '/payload/device')
    sys.path.insert(0, folder + '/runtime')
    import worker
    import compatibility
    import profiles
    import device_info
    import native as n
    profile = worker.profile_for(dict(request, experimental=True), folder)
    worker.validate_legacy_target(profile, device_info.read_identity(), action, folder)
    e.require(not os.path.lexists('/var/bb10_volte/payload.json'), 'unified_installation_present')
    if action == 'legacy-inspect':
        report = compatibility.probe(profile, True)
        # compatibility's public report is already allowlisted. Do not include
        # native internal plan data or private install/service JSON.
        fields = ('outcome', 'checks', 'device', 'can_install', 'can_start', 'can_restore', 'can_update',
                  'network_diagnostics', 'native_sha256', 'hardware_validation', 'baseline_diagnostics', 'variant_trial')
        result = dict((key, report.get(key)) for key in fields)
        result.update(management_actions(report))
        result['ok'] = True
        result['can_update'] = report.get('can_update') is True and not os.path.lexists(compatibility.BASE + '/enabled')
        return result
    previous = sys.stdout
    captured = io.StringIO()
    try:
        sys.stdout = captured
        if action in ('legacy-install', 'legacy-update'):
            if action == 'legacy-update':
                e.require(not os.path.lexists(compatibility.BASE + '/enabled'), 'legacy_disable_before_update')
                e.require(not os.path.lexists(compatibility.BASE + '/install-transaction.json'),
                          'legacy_install_recovery_required')
                import install
                install.install(request['stage'], update=True)
            elif os.path.isfile(compatibility.BASE + '/installation.json'):
                # Installation may have committed before removable backup
                # storage failed. Revalidate exact payload/profile and resume
                # only the missing backup, never blindly reinstall over it.
                e.require(not os.path.isfile(compatibility.BASE + '/install-transaction.json'), 'legacy_install_recovery_required')
                expected = e.json_bytes(e.regular(request['stage'] + '/payload-manifest.json'))
                installed = e.json_bytes(e.regular(compatibility.BASE + '/installation.json'))
                saved = profiles.installed_request(compatibility.BASE)
                e.require(installed['files'] == expected['files'] and saved == profiles.request(profile, True), 'legacy_installation_changed')
                for name, digest in expected['files'].items():
                    e.require(e.digest(e.regular(compatibility.BASE + '/' + name)) == digest, 'legacy_payload_changed')
                result = {'installed': True}
                if profile.get('lte_attach'):
                    pointer = e.json_bytes(e.regular(compatibility.BASE + '/state/telecom-plan.json'))
                    plan_folder = pointer['folder']
                    e.require(pointer['owner'] == 'bb10-telecom-attach-v1', 'backup_plan_changed')
                    result['telecom_plan'] = {'folder': plan_folder, 'plan_sha256': e.digest(e.regular(plan_folder + '/plan.json'))}
                print(json.dumps(result))
            else:
                import install
                install.install(request['stage'])
        else:
            # Installed integrity is checked before service's lifecycle gates.
            installed = compatibility.installed_state()
            e.require(installed.get('payload_verified') is True, 'legacy_payload_changed')
            if action == 'legacy-start':
                require_start(profile)
            if action == 'legacy-start':
                sys.path.insert(0, compatibility.BASE + '/device')
                import service
                sys.argv = [service.__file__, 'start']
                service.main()
            else:
                import install
                sys.argv = [install.__file__, 'uninstall' if action == 'legacy-uninstall' else 'disable']
                install.main()
    finally:
        sys.stdout = previous
    result = json.loads(captured.getvalue())
    if action in ('legacy-install', 'legacy-update') and result.get('telecom_plan'):
        path = backup_plan(result['telecom_plan'], request)
    else:
        path = None
    # Starting is explicit; successful installation is never reported as VoLTE.
    return {'ok': True, 'installed': result.get('installed') is True,
            'updated': result.get('updated') is True,
            'uninstalled': action == 'legacy-uninstall' and result.get('completed') is True,
            'private_backup_and_payload_retained': action == 'legacy-uninstall',
            'started': bool(result.get('started_manager_pid') or result.get('already_running')),
            'stop_requested': result.get('stop_requested') is True or action == 'legacy-stop' and result.get('completed') is True,
            'path': path, 'experimental': True, 'hardware_acceptance': 'not_established'}


if __name__ == '__main__':
    import json
    import re
    try:
        result = main()
    except Exception as error:
        code = str(error)
        result = {'ok': False, 'error_code': code if re.match(r'\A[a-z][a-z0-9_]{0,63}\Z', code) else 'legacy_preflight_failed'}
    print(json.dumps(result, ensure_ascii=True))
