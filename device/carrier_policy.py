"""Pure policy for the unified phone service. Compatible with Python 3.2.

Code/catalog integrity is independent of the selected SIM and generated profile.
Only the hardware, OS, PLMNs and stock images actually studied are admitted.
"""
import copy
import hashlib
import profiles

OWNER = 'bb10-unified-carriers-v1'
BASE = '/var/bb10_volte'
OS_VERSION = '10.3.3.3216'
MODELS = {'SQN100-3': ('q10', None), 'SQC100-2': ('classic', 'CLASSICATT'),
          'SQW100-4': ('passport', 'WINDERMERE4ROW')}
CARRIERS = {'00': ('mobile', 'China Mobile', ['cmnet']),
            '01': ('unicom', 'China Unicom', ['3gnet']),
            '11': ('telecom', 'China Telecom', ['ctnet', 'ctlte'])}


def model(facts):
    variant = facts.get('variant')
    if variant not in MODELS or facts.get('os_version') != OS_VERSION:
        raise ValueError('unsupported_model_or_os')
    family, board = MODELS[variant]
    if board is not None and facts.get('board_type') != board:
        raise ValueError('hardware_identity_conflict')
    return family


def select(facts, card):
    """Use the home PLMN, never a roaming/display/network name or cached SIM."""
    family = model(facts)
    if card.get('state') != 'READY':
        raise ValueError('sim_not_ready')
    kind = card.get('kind')
    if type(kind) is not int or not kind & 2 or kind & 16:
        raise ValueError('sim_route_unsupported')
    mcc, mnc, imsi = card.get('mcc'), card.get('mnc'), card.get('imsi')
    if mcc != '460' or mnc not in CARRIERS:
        raise ValueError('carrier_not_validated')
    if not profiles.identity_matches(imsi, mcc, mnc):
        raise ValueError('sim_identity_unavailable')
    operator, label, apns = CARRIERS[mnc]
    p = profiles.default()
    p.update(id='auto-' + operator + '-460' + mnc, label=label + ' / automatic SIM selection')
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
    if attempt and attempt.get('boot') == boot:
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
