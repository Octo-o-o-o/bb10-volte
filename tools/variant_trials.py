"""Prepare exact-model local trials using the existing manual device workflow."""
import argparse
import json
from pathlib import Path
import device_support
import profiles


def plan(variant, operator):
    scope = device_support.assess(variant, operator)
    if operator not in profiles.TRIAL_OPERATORS:
        route = 'operator_required'
    elif scope['code'] == 'supported':
        route = 'automatic_supported'
    elif scope['code'] != 'adaptation_pending':
        route = 'blocked'
    elif device_support.catalog()[variant]['family'] == 'passport':
        route = 'read_only_lifecycle_pending'
    else:
        route = 'manual_candidate'
    return {'schema': 1, 'variant': variant, 'operator': operator, 'route': route,
            'scope_code': scope['code'], 'hardware_acceptance': 'not_established_by_this_plan',
            'validated_home_plmns': scope['validated_home_plmns'],
            'autostart': False, 'changes_radio_attach_policy': False,
            'actual_device_checks_required': ['exact_variant', 'os_3216', 'root_v4_qnx_arm32',
                'six_native_hashes', 'current_usim_without_isim', 'home_plmn', 'lte_data',
                'stock_template', 'clean_baseline', 'known_installation', 'provider_restore']}


def profile(variant, operator):
    decision = plan(variant, operator)
    if decision['route'] not in ('manual_candidate', 'read_only_lifecycle_pending'):
        raise ValueError('This combination has no candidate trial route')
    p = profiles.default()
    p['id'] = 'variant-trial-' + variant.lower() + '-' + operator
    p['label'] = variant + ' / ' + operator + ' / local trial'
    mnc, apns = profiles.TRIAL_OPERATORS[operator]
    p['carrier'].update(mcc='460', mncs=[mnc], data_apns=list(apns))
    p['runtime']['autostart'] = False
    return profiles.validate(p)


def export(folder):
    """Produce public configuration, a coverage matrix and a blank result form."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    configs = folder / 'profiles'
    configs.mkdir()
    decisions = []
    for variant in device_support.catalog():
        for operator in profiles.TRIAL_OPERATORS:
            item = plan(variant, operator)
            if item['route'] in ('manual_candidate', 'read_only_lifecycle_pending'):
                p = profile(variant, operator)
                item['profile_file'] = 'profiles/' + p['id'] + '.json'
                (folder / item['profile_file']).write_text(json.dumps(p, indent=2) + '\n', encoding='utf-8')
            decisions.append(item)
    matrix = {'schema': 1, 'kind': 'local_trial_plans_not_hardware_acceptance', 'cases': decisions}
    (folder / 'test-matrix.json').write_text(json.dumps(matrix, indent=2) + '\n', encoding='utf-8')
    form = {'schema': 1, 'instruction': 'Record real observations; null means not tested. Never include phone numbers, IMSI, IMEI, ICCID, keys or SMS content.',
            'variant': '', 'operator': '', 'application_build': '', 'os_version': '',
            'native_preflight_report_filename': '', 'installation_completed': None,
            'manual_start_completed': None, 'incoming_call': None, 'outgoing_call': None,
            'audio_both_directions': None, 'lte_during_call': None, 'short_sms_received_once': None,
            'long_sms_received_once': None, 'two_identical_but_distinct_sms_received_twice': None,
            'sms_send': None, 'stop_and_original_state_restored': None,
            'normal_reboot_kept_autostart_off': None, 'sanitized_error_code': ''}
    (folder / 'results-template.json').write_text(json.dumps(form, indent=2) + '\n', encoding='utf-8')
    return matrix


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', type=Path, required=True, help='New destination folder; no device is contacted')
    args = parser.parse_args()
    result = export(args.export)
    print(json.dumps({'cases': len(result['cases']), 'phone_contacted': False, 'destination': str(args.export)}))
