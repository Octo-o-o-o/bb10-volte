"""Pure policy for the unified phone service. Compatible with Python 3.2.

Code/catalog integrity is independent of the selected SIM and generated profile.
Model admission is independent of historical hardware acceptance.
"""
import copy
import hashlib
import profiles

OWNER = 'bb10-unified-carriers-v1'
BASE = '/var/bb10_volte'
OS_VERSION = '10.3.3.3216'
MODELS = {
    'SQN100-1': ('q10', None),
    'SQN100-2': ('q10', None),
    'SQN100-3': ('q10', None),
    'SQN100-4': ('q10', None),
    'SQN100-5': ('q10', None),
    'SQC100-1': ('classic', 'CLASSICROW'),
    'SQC100-2': ('classic', 'CLASSICATT'),
    'SQC100-3': ('classic', 'CLASSICVZW'),
    'SQC100-4': ('classic', 'CLASSICNA'),
    'SQC100-5': ('classic', None),
    'SQW100-1': ('passport', 'WINDERMEREEMEA'),
    'SQW100-2': ('passport', None),
    'SQW100-3': ('passport', None),
    'SQW100-4': ('passport', 'WINDERMERE4ROW'),
    'SQK100-1': ('p9983', 'KHANE'),
    'SQK100-2': ('p9983', None),
}
CARRIERS = {
    '00': ('mobile', 'China Mobile', ['cmnet', 'cmwap']),
    '01': ('unicom', 'China Unicom', ['3gnet', 'wonet', 'uninet']),
    '02': ('mobile', 'China Mobile', ['cmnet', 'cmwap']),
    '03': ('telecom', 'China Telecom', ['ctnet', 'ctlte']),
    '04': ('mobile', 'China Mobile', ['cmnet', 'cmwap']),
    '05': ('telecom', 'China Telecom', ['ctnet', 'ctlte']),
    '06': ('unicom', 'China Unicom', ['3gnet', 'wonet', 'uninet']),
    '07': ('mobile', 'China Mobile', ['cmnet', 'cmwap']),
    '08': ('mobile', 'China Mobile', ['cmnet', 'cmwap']),
    '09': ('unicom', 'China Unicom', ['3gnet', 'wonet', 'uninet']),
    '11': ('telecom', 'China Telecom', ['ctnet', 'ctlte']),
    '12': ('telecom', 'China Telecom', ['ctnet', 'ctlte']),
}
# Open trial admission is not evidence of completed functional tests.
ADMITTED_MNCS = {variant: tuple(sorted(CARRIERS)) for variant in MODELS}
# Legacy API spelling retained for old tooling; never treat this as acceptance.
VALIDATED_MNCS = ADMITTED_MNCS
OWNER_TRIAL_MODELS = tuple(MODELS)


def model(facts):
    variant = facts.get('variant')
    if variant not in MODELS or facts.get('os_version') != OS_VERSION:
        raise ValueError('unsupported_model_or_os')
    family, board = MODELS[variant]
    if board is not None and facts.get('board_type') != board:
        raise ValueError('hardware_identity_conflict')
    import device_info
    if device_info.identify(facts).get('identity_conflict'):
        raise ValueError('hardware_identity_conflict')
    return family


def experimental_plmn(mcc, mnc):
    return (profiles.match(r'[0-9]{3}', mcc) and profiles.match(r'[0-9]{2,3}', mnc) and
            (mcc != '460' or mnc not in CARRIERS))


def select(facts, card):
    """Use the home PLMN, never a roaming/display/network name or cached SIM."""
    family = model(facts)
    if card.get('state') != 'READY':
        raise ValueError('sim_not_ready')
    kind = card.get('kind')
    mcc, mnc, imsi = card.get('mcc'), card.get('mnc'), card.get('imsi')
    if type(kind) is not int or not kind & 2:
        raise ValueError('sim_route_unsupported')
    exp = profiles.exp_trial_profile(mcc, mnc)
    allow_isim = bool(exp.get('experimental', {}).get('allow_isim')) if exp is not None else False
    if not allow_isim and kind & 16:
        raise ValueError('sim_route_unsupported')
    if profiles.carrier_adaptation_blocked(facts.get('variant'), mcc, (mnc,)):
        raise ValueError('operator_not_supported')
    if not profiles.identity_matches(imsi, mcc, mnc):
        raise ValueError('sim_identity_unavailable')
    if exp is not None:
        operator = 'other'
        p = exp
    else:
        carrier = CARRIERS.get(mnc) if mcc == '460' else None
        if (mcc, mnc) == ('460', '13'):
            carrier = ('mobile', 'China Mobile', ['cmnet', 'cmwap'])
        if carrier is None:
            operator = 'other'
            p = profiles.stock_trial_profile(mcc, mnc)
        else:
            operator, label, apns = carrier
            p = profiles.default()
            p.update(id='auto-' + operator + '-' + mcc + mnc, label=label + ' / automatic SIM selection')
            p['carrier'].update(mcc=mcc, mncs=[mnc], data_apns=list(apns))
    # The separate dispatcher owns boot policy. The legacy experimental profile
    # gate is deliberately not relaxed for standalone legacy service commands.
    p['runtime']['autostart'] = False
    return {'family': family, 'operator': operator, 'request': profiles.request(p, True),
            'sim_sha256': hashlib.sha256(imsi.encode('ascii')).hexdigest()}


def bind_template(selection, template):
    """Pin the actual read-only stock template after HPLMN/APN validation."""
    result = copy.deepcopy(selection)
    config_id = template['path'].rsplit('/', 1)[1].split('.')[0]
    if not config_id.isdigit():
        raise ValueError('invalid_stock_template')
    result['request']['profile']['carrier'].update(stock_config=config_id,
                                                  stock_sha256=template['sha256'])
    result['request'] = profiles.request(result['request']['profile'], True)
    return result


def transition(previous, selected, boot, provider_clear, attempt=None):
    """No native IMS restart after a SIM switch/provider activation in one boot."""
    if attempt and attempt.get('boot') == boot and attempt.get('stage') != 'pre_native':
        return 'reboot_required'
    if not provider_clear:
        return 'reboot_required'
    if previous and previous.get('boot') == boot and previous.get('sim_sha256') != selected['sim_sha256']:
        return 'reboot_required'
    return 'reconcile_then_start' if previous else 'start'


def restore_fields(actual, before, applied):
    """Never overwrite an independent carrier edit, including a changed SIM."""
    changes = {}
    for key, value in applied.items():
        original = before[key]
        if actual.get(key) not in (original, value):
            raise ValueError('carrier_configuration_changed')
        if actual.get(key) != original:
            changes[key] = original
    return changes
