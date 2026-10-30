"""Read-only import/preparation checks for the retained Q10 install stage."""
import json
import os
import sys
import traceback


def main():
    result = {'configuration_writes': 0, 'imports': {}, 'checks': {}}
    for name in ('service', 'telecom_attach', 'telecom_dca', 'telecom_native'):
        try:
            module = __import__(name)
            result['imports'][name] = {'ok': True, 'path': module.__file__}
        except Exception as error:
            result['imports'][name] = {'ok': False, 'type': type(error).__name__, 'error': str(error),
                                        'traceback': traceback.format_exc()}
    if all(value['ok'] for value in result['imports'].values()):
        import service as s
        import telecom_attach as t
        s.ACTIVE_REQUEST = s.profiles.installed_request(s.BASE)
        s.ACTIVE_PROFILE = s.ACTIVE_REQUEST['profile']
        for name, check in (('selected', lambda: t.selected(s.ACTIVE_PROFILE)),
                            ('supported', lambda: t.supported(t.device_info.read_identity())),
                            ('native_verify', t.native.verify),
                            ('idle', s.phone_idle), ('ims_count', lambda: len(s.n.ims_pids())),
                            ('vpn_count', lambda: len(s.n.active_vpn_sessions())),
                            ('voice', s.n.voice_policy), ('usage', t.native.ue_usage_policy),
                            ('crypto', s.n.crypto_policy), ('sources', t.source_baseline),
                            ('sim_ready_profile_matches', lambda: bool(s.current_usim()))):
            try:
                result['checks'][name] = {'ok': True, 'result': check()}
            except Exception as error:
                result['checks'][name] = {'ok': False, 'type': type(error).__name__, 'error': str(error)}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
