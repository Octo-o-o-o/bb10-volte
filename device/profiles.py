"""Strict, portable operator configuration. Python 3.2; no side effects on import."""
import copy
import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET

import native as n

DEFAULT = {
    'schema': 1, 'id': 'unicom-46001-baseline', 'label': 'China Unicom 460-01 / Q10 baseline',
    'carrier': {'mcc': '460', 'mncs': ['01'], 'data_apns': ['3gnet'],
                'stock_config': 'auto', 'stock_sha256': ''},
    'ims': {'apn': 'ims', 'ip_family': 'IPv4v6', 'home_domain': 'auto', 'sms': True},
    'runtime': {'sim_wait_seconds': 300, 'ims_apn_wait_seconds': 45,
                'existing_ims_wait_seconds': 330, 'registration_wait_seconds': 180,
                'poll_seconds': 3, 'autostart': True},
}
RANGES = {'sim_wait_seconds': (30, 900), 'ims_apn_wait_seconds': (10, 180),
          'existing_ims_wait_seconds': (10, 600), 'registration_wait_seconds': (30, 900),
          'poll_seconds': (1, 10)}
APN_RE = r'[a-z0-9](?:[a-z0-9.-]{0,98}[a-z0-9])?'
CONFIG_RE = r'/etc/carrier/config/([0-9]{1,6})\.xml'
TRIAL_PREFIX = 'variant-trial-'
TRIAL_OPERATORS = {'mobile': ('00', ['cmnet']), 'unicom': ('01', ['3gnet']),
                   'telecom': ('11', ['ctnet', 'ctlte'])}
# Closed by the owner after exact-device field trials. This product exclusion
# does not assert that every possible location has incompatible radio coverage.
# Historical failed trials are evidence, not an activation veto.
UNSUPPORTED_OPERATORS = {}
OPTIONAL_IMS_KEYS = ('always_on', 'request_signalling_bearer_via_pco', 'disable_dad', 'ir92', 'ims_pps')
IR92_KEYS = ('UsePreconditions', 'SMS_Format', 'amr_modeset_list', 'amrwb_modeset_list')
IMS_PPS_KEYS = ('SilentRedial', 'SIP_Timer_CSFB', 'IPsec', 'SIP_transport', 'RegExpiration')
UE_USAGE_MODES = ('auto', 'voice_centric', 'data_centric')
MODESET_RE = r'(?:none|[0-8](?:,[0-8]){0,8})'
OPERATOR_MNCS = {
    'mobile': ('00', '02', '04', '07', '08', '13'),
    'unicom': ('01', '06', '09'),
    'telecom': ('03', '05', '11', '12'),
}


def _valid_label(value):
    return isinstance(value, str) and 1 <= len(value) <= 80 and all(ord(c) >= 32 and ord(c) != 127 for c in value)


def _valid_home_domain(domain):
    return (domain == 'auto' or (isinstance(domain, str) and len(domain) <= 253 and '.' in domain and
            re.search('[a-z]', domain) is not None and
            all(match(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in domain.split('.'))))


def _validate_modeset(value, max_mode):
    if value == 'none':
        return True
    if not isinstance(value, str) or not match(MODESET_RE, value):
        return False
    parts = [int(item) for item in value.split(',')]
    return len(set(parts)) == len(parts) and all(0 <= item <= max_mode for item in parts)


def _validate_optional_ims(ims, need):
    extra = set(ims) - set(DEFAULT['ims'])
    need(extra <= set(OPTIONAL_IMS_KEYS), 'ims keys')
    for flag in ('always_on', 'request_signalling_bearer_via_pco', 'disable_dad'):
        if flag in ims:
            need(type(ims[flag]) is bool, 'ims.' + flag)
    if 'ir92' in ims:
        ir92 = ims['ir92']
        need(isinstance(ir92, dict) and set(ir92) <= set(IR92_KEYS), 'ims.ir92')
        if 'UsePreconditions' in ir92:
            val = ir92['UsePreconditions']
            need(type(val) is bool or (type(val) is int and val in (0, 1)), 'ims.ir92.UsePreconditions')
            ir92['UsePreconditions'] = bool(val)
        if 'SMS_Format' in ir92:
            need(ir92['SMS_Format'] in ('3GPP', '3GPP2'), 'ims.ir92.SMS_Format')
        if 'amr_modeset_list' in ir92:
            need(_validate_modeset(ir92['amr_modeset_list'], 7), 'ims.ir92.amr_modeset_list')
        if 'amrwb_modeset_list' in ir92:
            need(_validate_modeset(ir92['amrwb_modeset_list'], 8), 'ims.ir92.amrwb_modeset_list')
    if 'ims_pps' in ims:
        pps = ims['ims_pps']
        need(isinstance(pps, dict) and set(pps) <= set(IMS_PPS_KEYS), 'ims.ims_pps')
        if 'SilentRedial' in pps:
            need(type(pps['SilentRedial']) is bool, 'ims.ims_pps.SilentRedial')
        if 'SIP_Timer_CSFB' in pps:
            need(type(pps['SIP_Timer_CSFB']) is int and 0 <= pps['SIP_Timer_CSFB'] <= 120, 'ims.ims_pps.SIP_Timer_CSFB')
        if 'IPsec' in pps:
            need(type(pps['IPsec']) is bool, 'ims.ims_pps.IPsec')
        if 'SIP_transport' in pps:
            need(pps['SIP_transport'] in ('UDP', 'TCP', 'TLS'), 'ims.ims_pps.SIP_transport')
        if 'RegExpiration' in pps:
            need(type(pps['RegExpiration']) is int and 60 <= pps['RegExpiration'] <= 86400, 'ims.ims_pps.RegExpiration')


def carrier_adaptation_blocked(variant, mcc, mncs):
    return mcc == '460' and any(
        operator in UNSUPPORTED_OPERATORS.get(variant, ()) and any(mnc in mncs for mnc in operator_mncs)
        for operator, operator_mncs in OPERATOR_MNCS.items())


def normalize_apn(value):
    """Normalize APN case/whitespace and strip any 3GPP TS 23.003 OI suffix."""
    text = value.strip().lower() if isinstance(value, str) else ''
    return re.sub(r'\.mnc[0-9]{2,3}\.mcc[0-9]{3}\.gprs\Z', '', text)


def usable_observed_apn(value):
    """Normalize an observed APN and reject placeholders such as other/unknown/auto."""
    norm = normalize_apn(value)
    if not norm or norm in ('other', 'unknown', 'auto') or not match(APN_RE, norm):
        return ''
    return norm


# This original BB10 carrier file assigns the legacy CTWAP proxy to the
# ordinary CTNET internet service. Keep this workaround bound to the exact
# stock file observed on the affected device, not to arbitrary carrier files.
TELECOM_446_BAD_PROXY_SHA256 = 'd94f9b7eaa664a9ac496475e706bb837c364635400dd1af9a79608337d57f407'
TELECOM_446_BAD_PROXY = b'<HttpProxyV4>10.0.0.200:80</HttpProxyV4>'
STOCK_DEFAULT_CONFIG_PATH = '/etc/carrier/config/0.xml'
STOCK_DEFAULT_CONFIG_SHA256 = '5d13a0b15b30554b8230e2080ea03d9f00f3f36f33d72fa4d6ef8989cd59dadb'
EXP_TRIAL_PATH = '/var/bb10_volte-exp-trial.json'
MOBILE_404_SHA256 = '01093873ac626da82ec30c45a2db18925af12f5f9dec1fdca63c7ef3c70f0598'
UNICOM_36_SHA256 = '929e5e6e92ecadd48c641ec77f93f34e4a8d494ce213ab71d6422d6f5bba3fe4'
TELECOM_MNCS = ('03', '05', '11', '12')
# Stock BB10 10.3.3.3216 carrierIds.xml predates newer China HPLMN allocations
# (such as 460-08, 460-09, 460-04, 460-05, 460-12) and maps them to empty 0.xml.
# Pin each admitted HPLMN to its exact verified read-only stock carrier file.
STOCK_FALLBACK_TEMPLATES = {
    ('460', '00'): ('/etc/carrier/config/404.xml', MOBILE_404_SHA256),
    ('460', '02'): ('/etc/carrier/config/404.xml', MOBILE_404_SHA256),
    ('460', '04'): ('/etc/carrier/config/404.xml', MOBILE_404_SHA256),
    ('460', '07'): ('/etc/carrier/config/404.xml', MOBILE_404_SHA256),
    ('460', '08'): ('/etc/carrier/config/404.xml', MOBILE_404_SHA256),
    ('460', '13'): ('/etc/carrier/config/404.xml', MOBILE_404_SHA256),
    ('460', '01'): ('/etc/carrier/config/36.xml', UNICOM_36_SHA256),
    ('460', '06'): ('/etc/carrier/config/36.xml', UNICOM_36_SHA256),
    ('460', '09'): ('/etc/carrier/config/36.xml', UNICOM_36_SHA256),
    ('460', '03'): ('/etc/carrier/config/446.xml', TELECOM_446_BAD_PROXY_SHA256),
    ('460', '05'): ('/etc/carrier/config/446.xml', TELECOM_446_BAD_PROXY_SHA256),
    ('460', '11'): ('/etc/carrier/config/446.xml', TELECOM_446_BAD_PROXY_SHA256),
    ('460', '12'): ('/etc/carrier/config/446.xml', TELECOM_446_BAD_PROXY_SHA256),
}


def trial_target(profile):
    """A reserved profile ID binds a manual trial to one exact model/carrier.

    This never overrides compatibility, native image or lifecycle checks.
    """
    value = profile.get('id', '')
    if not value.startswith(TRIAL_PREFIX):
        return None
    found = re.match(r'\Avariant-trial-(sq[ncwk]100-[1-5])-(mobile|unicom|telecom)\Z', value)
    if found is None:
        raise ValueError('Invalid trial profile identity')
    return {'variant': found.group(1).upper(), 'operator': found.group(2)}


def default():
    return copy.deepcopy(DEFAULT)


def match(pattern, value):
    return isinstance(value, str) and re.match(r'\A(?:' + pattern + r')\Z', value) is not None


def validate(value):
    def need(condition, field):
        if not condition:
            raise ValueError('Invalid profile field: ' + field)
    need(isinstance(value, dict) and set(value) in (
        set(DEFAULT), set(DEFAULT) | {'lte_attach'}, set(DEFAULT) | {'experimental'}), 'root keys')
    p = copy.deepcopy(value)
    need(type(p['schema']) is int and p['schema'] == 1, 'schema')
    need(match(r'[a-z0-9][a-z0-9_-]{0,63}', p['id']), 'id')
    need(_valid_label(p['label']), 'label')
    for section in ('carrier', 'runtime'):
        need(isinstance(p[section], dict) and set(p[section]) == set(DEFAULT[section]), section + ' keys')
    need(isinstance(p['ims'], dict) and set(DEFAULT['ims']) <= set(p['ims']), 'ims keys')
    c, ims, runtime = p['carrier'], p['ims'], p['runtime']
    if 'experimental' in p:
        exp = p['experimental']
        need(isinstance(exp, dict) and {'allow_isim', 'allow_stock_default_xml'} <= set(exp) <= {
            'allow_isim', 'allow_stock_default_xml', 'ue_usage'} and
             type(exp['allow_isim']) is bool and type(exp['allow_stock_default_xml']) is bool and
             exp.get('ue_usage', 'auto') in UE_USAGE_MODES and
             p['id'].startswith('exp-trial-') and runtime['autostart'] is False, 'experimental options')
        _validate_optional_ims(ims, need)
    else:
        need(set(ims) == set(DEFAULT['ims']), 'ims keys')
    if 'lte_attach' in p:
        need(p['lte_attach'] == 'telecom_data_centric_v1', 'lte_attach')
        need(c['mcc'] == '460' and c['mncs'] == ['11'] and
             set(c['data_apns']).issubset({'ctnet', 'ctlte'}) and
             runtime['autostart'] is False, 'lte_attach carrier/manual policy')
    need(match(r'[0-9]{3}', c['mcc']), 'carrier.mcc')
    for key, pattern in (('mncs', r'[0-9]{2,3}'), ('data_apns', APN_RE)):
        values = c[key]
        need(isinstance(values, list) and 1 <= len(values) <= 16, 'carrier.' + key)
        if key == 'data_apns' and 'experimental' in p:
            need(all(item == 'auto' or match(pattern, item) for item in values), 'carrier.' + key)
            need(len(set(values)) == len(values), 'carrier.' + key + ' duplicates')
            c[key] = (['auto'] if 'auto' in values else []) + [item for item in values if item != 'auto']
        else:
            need(all(match(pattern, item) for item in values), 'carrier.' + key)
            need(len(set(values)) == len(values), 'carrier.' + key + ' duplicates')
            c[key] = sorted(values)
    need(c['stock_config'] == 'auto' or match(r'[0-9]{1,6}', c['stock_config']), 'carrier.stock_config')
    need(c['stock_sha256'] == '' or match(r'[a-f0-9]{64}', c['stock_sha256']), 'carrier.stock_sha256')
    need(match(APN_RE, ims['apn']), 'ims.apn')
    need(ims['ip_family'] in ('IPv4', 'IPv6', 'IPv4v6'), 'ims.ip_family')
    need(_valid_home_domain(ims['home_domain']), 'ims.home_domain')
    need(type(ims['sms']) is bool and type(runtime['autostart']) is bool, 'boolean options')
    for key, limits in RANGES.items():
        need(type(runtime[key]) is int and limits[0] <= runtime[key] <= limits[1], 'runtime.' + key)
    trial = trial_target(p)
    if trial is not None:
        mnc, apns = TRIAL_OPERATORS[trial['operator']]
        need(c == {'mcc': '460', 'mncs': [mnc], 'data_apns': sorted(apns),
                   'stock_config': 'auto', 'stock_sha256': ''}, 'trial carrier binding')
        need(ims == DEFAULT['ims'] and not runtime['autostart'] and 'lte_attach' not in p,
             'trial manual policy')
    return p


def canonical(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def request(profile=None, allow_experimental=False):
    if type(allow_experimental) is not bool:
        raise ValueError('Experimental consent must be boolean')
    return {'schema': 1, 'profile': validate(default() if profile is None else profile),
            'allow_experimental': allow_experimental}


def read_json(path):
    with open(path, 'rb') as source:
        raw = source.read(32769)
    if len(raw) > 32768:
        raise ValueError('Profile exceeds size limit')
    return json.loads(raw.decode('utf-8'))


def load_request(path):
    value = read_json(path)
    if (not isinstance(value, dict) or set(value) != {'schema', 'profile', 'allow_experimental'} or
            type(value['schema']) is not int or value['schema'] != 1):
        raise ValueError('Invalid profile request')
    return request(value['profile'], value['allow_experimental'])


def installed_request(base):
    manifest = read_json(base + '/installation.json')
    value = load_request(base + '/carrier-profile.json')
    if fingerprint(value) != manifest.get('carrier_profile_sha256'):
        raise ValueError('Installed profile changed; restore before updating configuration')
    return value


def baseline_parameters(profile):
    p = validate(profile)
    return p['carrier'] == DEFAULT['carrier'] and p['ims'] == DEFAULT['ims']


def home_domain(profile, mcc, mnc):
    p = validate(profile)
    if not match(r'[0-9]{3}', mcc) or not match(r'[0-9]{2,3}', mnc):
        raise ValueError('SIM MCC/MNC unavailable')
    return (p['ims']['home_domain'] if p['ims']['home_domain'] != 'auto' else
            'ims.mnc' + mnc.zfill(3) + '.mcc' + mcc + '.3gppnetwork.org')


def identity_matches(imsi, mcc, mnc):
    return (match(r'[0-9]{3}', mcc) and match(r'[0-9]{2,3}', mnc) and
            match(r'[0-9]{15}', imsi) and imsi.startswith(mcc + mnc))


def ims_section(profile):
    p = validate(profile)
    # Only schema-validated APN/type text is interpolated, never identity or XML.
    always_on = 'true' if p['ims'].get('always_on', True) else 'false'
    disable_dad = '<DisableDAD>true</DisableDAD>' if p['ims'].get('disable_dad') else ''
    sig_pco = ('<RequestSignallingBearerViaPCO>true</RequestSignallingBearerViaPCO>'
               if p['ims'].get('request_signalling_bearer_via_pco') else '')
    return ('''    <ServiceConfiguration>
      <Name>ims</Name>
      <Description>BB10 IMS</Description>
      <AlwaysOn>{always_on}</AlwaysOn>
      <AppModifiable>false</AppModifiable>
      <LTEAttachService>false</LTEAttachService>
      <NetworkInterfaceConfiguration><IPConfiguration>
        <Type>{family}</Type><ProtectRouting>true</ProtectRouting>{disable_dad}
      </IPConfiguration></NetworkInterfaceConfiguration>
      <BearerManagementTimer/>
      <RadioAccessTechnology><NetworkServiceFilter>LTE</NetworkServiceFilter><APN>{apn}</APN></RadioAccessTechnology>
      <IMSConfiguration><RequestPCSCFViaPCO>true</RequestPCSCFViaPCO>{sig_pco}</IMSConfiguration>
      <EPDGConfiguration/>
    </ServiceConfiguration>'''.format(
        always_on=always_on, family=p['ims']['ip_family'], disable_dad=disable_dad,
        apn=p['ims']['apn'], sig_pco=sig_pco)).encode('ascii')


def parse_xml(data):
    root = ET.fromstring(data)
    # Stock BB10 XML uses a default namespace. Normalize the read-only tree;
    # serialization still uses original bytes, retaining namespaces and layout.
    for node in root.iter():
        node.tag = node.tag.rsplit('}', 1)[-1]
    return root


def patch_carrier(stock, profile):
    """Replace or insert the IMS service, preserving every other original byte."""
    parse_xml(stock)
    spans = []
    pattern = br'<(ServiceConfiguration|ServiceConfigurationAlias)(?:\s[^>]*)?>.*?</\1>'
    for found in re.finditer(pattern, stock, re.S):
        node = ET.fromstring(found.group(0))
        if node.findtext('Name') == 'ims':
            spans.append(found.span())
    if len(spans) > 1:
        raise ValueError('Carrier XML needs exactly one IMS service or alias')
    if len(spans) == 1:
        start, end = spans[0]
        result = stock[:start] + ims_section(profile).lstrip() + stock[end:]
    else:
        closing = b'</CarrierDataConfiguration>'
        if stock.count(closing) != 1:
            raise ValueError('Carrier XML needs exactly one IMS service or alias')
        pos = stock.index(closing)
        result = stock[:pos] + b'\n' + ims_section(profile) + b'\n  ' + stock[pos:]
    ET.fromstring(result)
    return result


def fix_known_telecom_internet_proxy(data, path, stock_sha256, mcc, mnc):
    """Remove the known CTNET proxy from the generated copy, never stock/MMS."""
    if not (mcc == '460' and mnc in TELECOM_MNCS and
            (path, stock_sha256) == ('/etc/carrier/config/446.xml', TELECOM_446_BAD_PROXY_SHA256)):
        return data
    spans = []
    for found in re.finditer(br'<ServiceConfiguration>.*?</ServiceConfiguration>', data, re.S):
        block = found.group(0)
        node = ET.fromstring(block)
        apns = [entry.text for entry in node.iter('APN')]
        proxy = node.findall('HttpProxyV4')
        if (node.findtext('Name') == 'internet' and apns == ['ctnet'] and
                len(proxy) == 1 and proxy[0].text == '10.0.0.200:80'):
            spans.append((found.start(), found.end(), block))
    if len(spans) != 1:
        raise ValueError('Known Telecom internet proxy layout changed')
    start, end, block = spans[0]
    if block.count(TELECOM_446_BAD_PROXY) != 1:
        raise ValueError('Known Telecom internet proxy bytes changed')
    result = data[:start] + block.replace(TELECOM_446_BAD_PROXY, b'', 1) + data[end:]
    ET.fromstring(result)
    return result


def preloaded_carrier_config(mcc, mnc):
    attrs = n.attrs(n.read('/pps/services/carriermanager/status_private'))
    home = n.value(attrs, 'true_home_carrier', {})
    if (not match(r'[0-9]{3}', mcc) or not match(r'[0-9]{2,3}', mnc) or
            home.get('mcc') != int(mcc) or home.get('mnc') != int(mnc)):
        raise ValueError('Current stock carrier selection cannot be verified')
    if home.get('downloadedConfigFile'):
        raise ValueError('downloaded_carrier_config_present')
    return home.get('preloadedConfigFile')


def internet_apns(root):
    entries = [node for node in root.iter('ServiceConfiguration') if node.findtext('Name') == 'internet']
    return {(node.text or '').strip().lower() for entry in entries for node in entry.iter('APN')
            if (node.text or '').strip()}


def stock_trial_profile(mcc, mnc):
    """Derive an untested carrier profile from this SIM's own original XML."""
    try:
        path = preloaded_carrier_config(mcc, mnc)
    except (IOError, OSError, ValueError) as error:
        if str(error) == 'downloaded_carrier_config_present':
            raise
        raise ValueError('experimental_stock_template_unavailable')
    if not match(CONFIG_RE, path) or path == STOCK_DEFAULT_CONFIG_PATH or os.path.islink(path):
        raise ValueError('experimental_stock_template_unavailable')
    try:
        stock = n.read(path)
        root = parse_xml(stock)
        apns = sorted(apn for apn in internet_apns(root) if match(APN_RE, apn))
        if not 1 <= len(apns) <= 16:
            raise ValueError('internet APN unavailable')
        profile = default()
        profile.update(id='auto-stock-' + mcc + mnc, label='Experimental stock carrier ' + mcc + '-' + mnc)
        profile['carrier'].update(mcc=mcc, mncs=[mnc], data_apns=apns,
                                  stock_config=path.rsplit('/', 1)[1][:-4], stock_sha256=n.digest(stock))
        ims = [node for node in root.iter('ServiceConfiguration') if node.findtext('Name') == 'ims']
        if ims:
            if len(ims) != 1:
                raise ValueError('ambiguous IMS service')
            rats = ims[0].findall('RadioAccessTechnology')
            lte_rats = [rat for rat in rats if 'LTE' in (rat.findtext('NetworkServiceFilter') or '').upper()]
            apn_nodes = lte_rats if lte_rats else [ims[0]]
            ims_apns = {(node.text or '').strip().lower()
                        for parent in apn_nodes for node in parent.iter('APN')
                        if (node.text or '').strip()}
            families = {node.findtext('Type') for node in ims[0].iter('IPConfiguration') if node.findtext('Type')}
            if len(ims_apns) > 1 or len(families) > 1:
                raise ValueError('ambiguous IMS service')
            if ims_apns:
                profile['ims']['apn'] = ims_apns.pop()
            if families:
                profile['ims']['ip_family'] = families.pop()
        profile['runtime']['autostart'] = False
        patch_carrier(stock, profile)
        return profile
    except (IOError, OSError, ValueError, ET.ParseError):
        raise ValueError('experimental_stock_template_unavailable')


def _validate_exp_entry(raw, schema_version, need, prefix=''):
    required = {'mcc', 'mncs', 'allow_isim', 'allow_stock_default_xml', 'data_apns', 'ims'}
    optional = {'label', 'stock_config', 'ue_usage'} if schema_version == 2 else set()
    need(isinstance(raw, dict) and required <= set(raw) <= (required | optional), prefix + 'keys')
    entry = copy.deepcopy(raw)
    need(type(entry['allow_isim']) is bool, prefix + 'allow_isim')
    need(type(entry['allow_stock_default_xml']) is bool, prefix + 'allow_stock_default_xml')
    need(match(r'[0-9]{3}', entry['mcc']), prefix + 'mcc')
    if 'label' in entry:
        need(_valid_label(entry['label']), prefix + 'label')
    if 'stock_config' in entry:
        need(entry['stock_config'] in ('auto', '0') or match(r'[0-9]{1,6}', entry['stock_config']),
             prefix + 'stock_config')
    if 'ue_usage' in entry:
        need(entry['ue_usage'] in UE_USAGE_MODES, prefix + 'ue_usage')
    mncs = entry['mncs']
    need(isinstance(mncs, list) and 1 <= len(mncs) <= 16, prefix + 'mncs')
    need(all(match(r'[0-9]{2,3}', item) for item in mncs), prefix + 'mncs')
    need(len(set(mncs)) == len(mncs), prefix + 'mncs duplicates')
    need(not (entry['mcc'] == '460' and '15' in mncs), prefix + 'mncs')
    entry['mncs'] = mncs
    raw_apns = entry['data_apns']
    need(isinstance(raw_apns, list) and 1 <= len(raw_apns) <= 16, prefix + 'data_apns')
    apns = []
    for item in raw_apns:
        if schema_version == 2 and isinstance(item, str) and item.strip().lower() == 'auto':
            apns.append('auto')
        else:
            norm = normalize_apn(item)
            need(match(APN_RE, norm), prefix + 'data_apns')
            apns.append(norm)
    need(len(set(apns)) == len(apns), prefix + 'data_apns duplicates')
    entry['data_apns'] = apns
    ims = entry['ims']
    need(isinstance(ims, dict) and set(DEFAULT['ims']) <= set(ims), prefix + 'ims keys')
    if schema_version == 1:
        need(set(ims) == set(DEFAULT['ims']), prefix + 'ims keys')
    else:
        _validate_optional_ims(ims, lambda cond, fld: need(cond, prefix + fld))
    ims['apn'] = normalize_apn(ims['apn'])
    need(match(APN_RE, ims['apn']), prefix + 'ims.apn')
    need(ims['ip_family'] in ('IPv4', 'IPv6', 'IPv4v6'), prefix + 'ims.ip_family')
    need(_valid_home_domain(ims['home_domain']), prefix + 'ims.home_domain')
    need(type(ims['sms']) is bool, prefix + 'ims.sms')
    return entry


def validate_exp_trial(value):
    """Validate an explicit opt-in experimental carrier trial JSON (schema 1 or 2)."""
    def need(condition, field):
        if not condition:
            raise ValueError('Invalid experimental trial field: ' + field)
    need(isinstance(value, dict), 'root')
    schema_version = value.get('schema')
    need(type(schema_version) is int and schema_version in (1, 2), 'schema')
    need(type(value.get('enabled')) is bool, 'enabled')
    if schema_version == 1:
        need(set(value) == {
            'schema', 'enabled', 'mcc', 'mncs', 'allow_isim', 'allow_stock_default_xml', 'data_apns', 'ims'}, 'keys')
        entry = _validate_exp_entry({k: value[k] for k in value if k not in ('schema', 'enabled')}, 1, need)
        result = {'schema': 1, 'enabled': value['enabled']}
        result.update(entry)
        return result
    if 'carriers' in value:
        need(set(value) == {'schema', 'enabled', 'carriers'}, 'keys')
        raw_list = value['carriers']
        need(isinstance(raw_list, list) and 1 <= len(raw_list) <= 16, 'carriers')
        entries = []
        seen_plmns = set()
        for idx, item in enumerate(raw_list):
            entry = _validate_exp_entry(item, 2, need, 'carriers[%d].' % idx)
            for mnc in entry['mncs']:
                pair = (entry['mcc'], mnc)
                need(pair not in seen_plmns, 'duplicate plmn ' + pair[0] + '-' + pair[1])
                seen_plmns.add(pair)
            entries.append(entry)
        return {'schema': 2, 'enabled': value['enabled'], 'carriers': entries}
    entry = _validate_exp_entry({k: value[k] for k in value if k not in ('schema', 'enabled')}, 2, need)
    result = {'schema': 2, 'enabled': value['enabled']}
    result.update(entry)
    return result


def exp_trial_entries(trial):
    """Return normalized list of carrier entries from a validated trial dict."""
    if not isinstance(trial, dict):
        return []
    if 'carriers' in trial and isinstance(trial['carriers'], list):
        return list(trial['carriers'])
    return [{k: v for k, v in trial.items() if k not in ('schema', 'enabled')}]


def exp_trial_summary(trial):
    """Return a non-identifying public summary of an active trial config."""
    if not isinstance(trial, dict):
        return None
    entries = exp_trial_entries(trial)
    items = []
    for entry in entries:
        ims = entry.get('ims', {})
        item = {
            'mcc': entry.get('mcc'),
            'mncs': list(entry.get('mncs', ())),
            'allow_isim': bool(entry.get('allow_isim')),
            'allow_stock_default_xml': bool(entry.get('allow_stock_default_xml')),
            'data_apns': list(entry.get('data_apns', ())),
            'ims_apn': ims.get('apn'),
            'ims_ip_family': ims.get('ip_family'),
            'ims_home_domain': ims.get('home_domain'),
            'ims_sms': bool(ims.get('sms')),
        }
        if entry.get('label'):
            item['label'] = entry['label']
        if entry.get('ue_usage') and entry['ue_usage'] != 'auto':
            item['ue_usage'] = entry['ue_usage']
        if ims.get('always_on') is False:
            item['ims_always_on'] = False
        if ims.get('request_signalling_bearer_via_pco'):
            item['request_signalling_bearer_via_pco'] = True
        if ims.get('disable_dad'):
            item['disable_dad'] = True
        if ims.get('ir92'):
            item['ir92'] = dict(ims['ir92'])
        if ims.get('ims_pps'):
            item['ims_pps'] = dict(ims['ims_pps'])
        items.append(item)
    plmns = [entry['mcc'] + '-' + mnc for entry in entries for mnc in entry.get('mncs', ())]
    return {'schema': trial.get('schema', 1), 'enabled': bool(trial.get('enabled')), 'plmns': plmns, 'carriers': items}


def load_exp_trial(path=None):
    """Load root-owned opt-in experimental trial config; absent/invalid returns None."""
    if path is None:
        path = EXP_TRIAL_PATH
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            return None
        st = os.lstat(path)
        if st.st_size > 16384:
            return None
        if hasattr(os, 'uname') and os.uname()[0] == 'QNX':
            if st.st_uid != 0 or (st.st_mode & 0o077) != 0:
                return None
        with open(path, 'rb') as source:
            raw = source.read(16385)
        if len(raw) > 16384:
            return None
        trial = validate_exp_trial(json.loads(raw.decode('utf-8')))
        return trial if trial['enabled'] is True else None
    except (IOError, OSError, ValueError, TypeError):
        return None


def exp_trial_profile(mcc, mnc, trial=None):
    """Build a strictly validated manual trial profile when opted in for this HPLMN."""
    if not match(r'[0-9]{3}', mcc) or not match(r'[0-9]{2,3}', mnc):
        return None
    if mcc == '460' and mnc == '15':
        return None
    if trial is None:
        trial = load_exp_trial()
    if trial is None or trial.get('enabled') is not True:
        return None
    matched = None
    for entry in exp_trial_entries(trial):
        if entry['mcc'] == mcc and mnc in entry['mncs']:
            matched = entry
            break
    if matched is None:
        return None
    profile = default()
    label = matched.get('label') or ('Experimental trial ' + mcc + '-' + mnc)
    profile.update(id='exp-trial-' + mcc + mnc, label=label)
    profile['carrier'].update(mcc=mcc, mncs=[mnc], data_apns=list(matched['data_apns']),
                              stock_config=matched.get('stock_config', 'auto'), stock_sha256='')
    profile['ims'] = copy.deepcopy(matched['ims'])
    profile['runtime']['autostart'] = False
    exp_opts = {
        'allow_isim': bool(matched['allow_isim']),
        'allow_stock_default_xml': bool(matched['allow_stock_default_xml']),
    }
    if matched.get('ue_usage') and matched['ue_usage'] != 'auto':
        exp_opts['ue_usage'] = matched['ue_usage']
    profile['experimental'] = exp_opts
    return validate(profile)


def live_data_apn():
    """Read normalized live internet APN from cnice status; None if absent/invalid."""
    try:
        attrs = n.attrs(n.read('/pps/services/cds/cnice/status'))
        internet = n.value(attrs, 'internet', {})
        apn = usable_observed_apn(internet.get('apn') if isinstance(internet, dict) else '')
        return apn or None
    except (IOError, OSError, ValueError, TypeError, AttributeError, KeyError):
        return None


def _resolve_default_data_apn(profile_apns):
    """Choose concrete APN for filling 0.xml from profile data_apns (handling 'auto')."""
    explicit = [item for item in profile_apns if item != 'auto']
    if 'auto' in profile_apns:
        live = live_data_apn()
        if live:
            return live
    if explicit:
        return explicit[0]
    raise ValueError('No concrete data APN available for 0.xml bootstrap')


def patch_default_internet_apn(stock, data_apn):
    """Fill the empty internet APN inside a verified stock 0.xml runtime copy."""
    if not match(APN_RE, data_apn):
        raise ValueError('Invalid experimental data APN')
    parse_xml(stock)
    spans = []
    for found in re.finditer(br'<ServiceConfiguration>.*?</ServiceConfiguration>', stock, re.S):
        block = found.group(0)
        node = ET.fromstring(block)
        if node.findtext('Name') == 'internet':
            spans.append((found.start(), found.end(), block))
    if len(spans) != 1:
        raise ValueError('Default stock carrier XML internet section changed')
    start, end, block = spans[0]
    replaced, count = re.subn(br'<APN>\s*</APN>|<APN\s*/>',
                              ('<APN>' + data_apn + '</APN>').encode('ascii'), block, count=1)
    if count != 1:
        raise ValueError('Default stock carrier XML empty APN tag changed')
    result = stock[:start] + replaced + stock[end:]
    ET.fromstring(result)
    return result


def carrier_template(profile, mcc, mnc):
    """Read only the SIM's stock carrier file, never a downloaded override."""
    p = validate(profile)
    preloaded = preloaded_carrier_config(mcc, mnc)
    fallback_used = False
    fallback_sha = ''
    exp_default_xml = bool(p.get('experimental', {}).get('allow_stock_default_xml'))
    stock_default_xml_used = False
    if p['carrier']['stock_config'] != 'auto':
        path = '/etc/carrier/config/' + p['carrier']['stock_config'] + '.xml'
        if p['id'].startswith('auto-stock-') and path != preloaded:
            raise ValueError('experimental_stock_template_unavailable')
        if (preloaded in (None, '', STOCK_DEFAULT_CONFIG_PATH) and (mcc, mnc) in STOCK_FALLBACK_TEMPLATES and
                STOCK_FALLBACK_TEMPLATES[(mcc, mnc)][0] == path):
            if preloaded == STOCK_DEFAULT_CONFIG_PATH:
                if os.path.islink(preloaded) or n.digest(n.read(preloaded)) != STOCK_DEFAULT_CONFIG_SHA256:
                    raise ValueError('Default stock carrier file changed')
            fallback_used = True
        elif exp_default_xml and path == STOCK_DEFAULT_CONFIG_PATH:
            fallback_sha = STOCK_DEFAULT_CONFIG_SHA256
            stock_default_xml_used = True
    elif preloaded in (None, '', STOCK_DEFAULT_CONFIG_PATH) and (mcc, mnc) in STOCK_FALLBACK_TEMPLATES:
        if preloaded == STOCK_DEFAULT_CONFIG_PATH:
            if os.path.islink(preloaded) or n.digest(n.read(preloaded)) != STOCK_DEFAULT_CONFIG_SHA256:
                raise ValueError('Default stock carrier file changed')
        path, fallback_sha = STOCK_FALLBACK_TEMPLATES[(mcc, mnc)]
        fallback_used = True
    elif exp_default_xml and preloaded in (None, '', STOCK_DEFAULT_CONFIG_PATH):
        path = STOCK_DEFAULT_CONFIG_PATH
        fallback_sha = STOCK_DEFAULT_CONFIG_SHA256
        stock_default_xml_used = True
    else:
        path = preloaded
    if not match(CONFIG_RE, path) or os.path.islink(path):
        raise ValueError('Only a regular stock carrier file is allowed')
    stock = n.read(path)
    digest = n.digest(stock)
    expected = p['carrier']['stock_sha256'] or fallback_sha
    if expected and digest != expected:
        raise ValueError('Selected carrier file hash differs from profile')
    if stock_default_xml_used:
        if digest != STOCK_DEFAULT_CONFIG_SHA256:
            raise ValueError('Default stock carrier file changed')
        working = patch_default_internet_apn(stock, _resolve_default_data_apn(p['carrier']['data_apns']))
        changed = patch_carrier(working, p)
    else:
        root = parse_xml(stock)
        apns = internet_apns(root)
        profile_apns = set(item.lower() for item in p['carrier']['data_apns'])
        explicit_apns = set(item for item in profile_apns if item != 'auto')
        allow_auto = 'auto' in profile_apns and 'experimental' in p
        live_apn = live_data_apn() if allow_auto else None
        auto_targets = (set([live_apn]) if live_apn else set()) | explicit_apns
        if allow_auto and apns and (not auto_targets or apns.intersection(auto_targets)):
            changed = patch_carrier(stock, p)
            changed = fix_known_telecom_internet_proxy(changed, path, digest, mcc, mnc)
        elif apns.intersection(explicit_apns):
            changed = patch_carrier(stock, p)
            changed = fix_known_telecom_internet_proxy(changed, path, digest, mcc, mnc)
        elif exp_default_xml and p['carrier']['stock_config'] == 'auto':
            # Overseas opt-in fallback when a 2015 stock carrier XML carries a stale APN.
            if os.path.islink(STOCK_DEFAULT_CONFIG_PATH):
                raise ValueError('Only a regular stock carrier file is allowed')
            path = STOCK_DEFAULT_CONFIG_PATH
            stock = n.read(path)
            digest = n.digest(stock)
            if digest != STOCK_DEFAULT_CONFIG_SHA256:
                raise ValueError('Default stock carrier file changed')
            stock_default_xml_used = True
            working = patch_default_internet_apn(stock, _resolve_default_data_apn(p['carrier']['data_apns']))
            changed = patch_carrier(working, p)
        else:
            # Preserve the existing data APN. Never silently transplant Unicom's data
            # configuration to another carrier just because its IMS APN is also "ims".
            raise ValueError('Stock data APN does not match selected profile')
    info = {'path': path, 'sha256': digest}
    if fallback_used:
        info.update(fallback_used=True, original_preloaded_config=preloaded or '')
    if stock_default_xml_used:
        info.update(stock_default_xml_used=True, original_preloaded_config=preloaded or '')
    return info, changed
