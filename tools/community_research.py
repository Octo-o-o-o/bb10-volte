"""Offline community evidence, kept separate from device acceptance and policy."""
import copy
import json
from desktop_paths import resource_root


def catalog():
    with (resource_root() / 'materials/community-research.json').open(encoding='utf-8') as source:
        value = json.load(source)
    if value['schema'] != 1 or value['project_acceptance'] != 'not_established':
        raise ValueError('Invalid community evidence catalog')
    return value


def evidence_for(report):
    """Exact hardware/OS/network matches only; never changes any action gate."""
    try:
        value = catalog()
    except (OSError, ValueError, KeyError, TypeError):
        return {'status': 'unavailable', 'project_acceptance': 'not_established', 'records': []}
    device, facts = report.get('device', {}), report.get('facts', {})
    matches = []
    for entry in value['records']:
        selector = entry['selector']
        hardware = (not device.get('identity_conflict') and
                    (device.get('board_type') == selector['board_type'] if 'board_type' in selector
                     else device.get('variant') == selector['variant']))
        if (hardware and device.get('os_version') == selector['os_version'] and
                facts.get('mcc') == selector['mcc'] and facts.get('mnc') == selector['mnc']):
            matches.append(copy.deepcopy(entry))
    return {'status': 'matched' if matches else 'no_exact_match',
            'source': copy.deepcopy(value['source']), 'project_acceptance': 'not_established',
            'records': matches}
