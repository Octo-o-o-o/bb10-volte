"""Device recognition is distinct from native patch compatibility. Python 3.2."""
import re
import native as n

ENGINE = 'qnx-arm32-os3216-native-v1'
OS_VERSION = '10.3.3.3216'
FAMILIES = {
    'q10': {'name': 'BlackBerry Q10', 'prefix': 'SQN100-', 'aliases': ('q10',)},
    'classic': {'name': 'BlackBerry Classic (Q20)', 'prefix': 'SQC100-', 'aliases': ('q20', 'classic')},
    'passport': {'name': 'BlackBerry Passport (Q30)', 'prefix': 'SQW100-', 'aliases': ('q30', 'passport')},
}


def read_identity():
    props = n.attrs(n.read('/pps/services/deviceproperties'))
    return {'model': n.value(props, 'modelname'), 'full_model': n.value(props, 'modelfullname'),
            'variant': n.value(props, 'modelnumber'),
            'os_version': n.read('/etc/os.version').decode('ascii').strip()}


def identify(facts):
    raw = (str(facts.get('model') or '') + ' ' + str(facts.get('full_model') or '')).lower()
    words = set(re.findall(r'[a-z0-9]+', raw))
    variant = str(facts.get('variant') or '')
    by_name = {key for key, entry in FAMILIES.items() if words.intersection(entry['aliases'])}
    by_variant = {key for key, entry in FAMILIES.items() if re.match(r'\A' + entry['prefix'] + r'[0-9]+\Z', variant)}
    candidates = by_name | by_variant
    conflict = len(candidates) > 1
    family = next(iter(candidates)) if len(candidates) == 1 else 'unknown'
    recognized = family != 'unknown' and by_variant == {family}
    baseline = recognized and family == 'q10' and variant == 'SQN100-3'
    return {'family': family, 'display_name': FAMILIES[family]['name'] if family in FAMILIES else 'Unrecognized BB10 device',
            'recognized': recognized, 'identity_conflict': conflict, 'hardware_tested': baseline,
            'variant': facts.get('variant'), 'os_version': facts.get('os_version'),
            'native_engine': ENGINE, 'experimental_device': recognized and not baseline}


def engine_matches(facts):
    device = identify(facts)
    hashes = facts.get('native_hashes', {})
    return (device['recognized'] and facts.get('os_version') == OS_VERSION and
            facts.get('arm32_qnx') is True and set(hashes) == set(n.STOCK_HASHES) and all(hashes.values()))
