"""Private signed child entry; not exposed by the native application."""
import os
import sys
import entry as e


def main():
    e.require(os.geteuid() == 0 and os.uname()[0] == 'QNX' and sys.flags.optimize == 0, 'root_required')
    folder = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    e.require(os.path.dirname(folder) == e.ROOT + '/snapshots', 'private_snapshot_required')
    e.private_directory(folder)
    bundle = e.read_bundle(folder)
    e.require(os.path.basename(folder) == e.digest(bundle[1]), 'snapshot_changed')
    request = e.json_bytes(e.decode64(sys.argv[1]))
    e.require(set(request) == {'action', 'operation_id'} and request['action'] == 'engine-update', 'invalid_action')
    sys.path.insert(0, folder + '/payload/device')
    sys.path.insert(0, folder + '/runtime')
    import worker
    import unified_install as m
    stage = worker.stage_payload(folder, request['operation_id'])
    entered = False
    try:
        with m.management_lock():
            entered = True
            current = m.s.load(m.BASE + '/payload.json')
            candidate = m.s.load(stage + '/payload.json')
            if current == candidate and m.installed_management_schema() == 2 and not os.path.isfile(m.UPDATE_PENDING):
                m.u.verify()
                result = {'updated': True, 'runtime_only': True, 'reboot_required': False}
            else:
                result = m.manage('update', stage=stage, operation_id=request['operation_id'])
    except Exception as error:
        if not entered and str(error) == 'management_busy':
            return {'ok': False, 'error_code': 'management_busy',
                    'operation_id': request['operation_id'], 'not_dispatched': True}
        raise
    result['ok'] = True
    return result


if __name__ == '__main__':
    import json
    try:
        result = main()
    except Exception as error:
        import re
        code = str(error)
        result = {'ok': False, 'error_code': code if re.match(r'\A[a-z][a-z0-9_]{0,63}\Z', code) else 'update_recovery_check_failed'}
    print(json.dumps(result, ensure_ascii=True))
