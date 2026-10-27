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


def default():
    return copy.deepcopy(DEFAULT)


def match(pattern, value):
    return isinstance(value, str) and re.match(r'\A(?:' + pattern + r')\Z', value) is not None


def validate(value):
    def need(condition, field):
        if not condition:
            raise ValueError('Invalid profile field: ' + field)
    need(isinstance(value, dict) and set(value) == set(DEFAULT), 'root keys')
    p = copy.deepcopy(value)
    need(type(p['schema']) is int and p['schema'] == 1, 'schema')
    need(match(r'[a-z0-9][a-z0-9_-]{0,63}', p['id']), 'id')
    need(isinstance(p['label'], str) and 1 <= len(p['label']) <= 80 and
         all(ord(c) >= 32 and ord(c) != 127 for c in p['label']), 'label')
    for section in ('carrier', 'ims', 'runtime'):
        need(isinstance(p[section], dict) and set(p[section]) == set(DEFAULT[section]), section + ' keys')
    c, ims, runtime = p['carrier'], p['ims'], p['runtime']
    need(match(r'[0-9]{3}', c['mcc']), 'carrier.mcc')
    for key, pattern in (('mncs', r'[0-9]{2,3}'), ('data_apns', APN_RE)):
        values = c[key]
        need(isinstance(values, list) and 1 <= len(values) <= 16, 'carrier.' + key)
        need(all(match(pattern, item) for item in values), 'carrier.' + key)
        need(len(set(values)) == len(values), 'carrier.' + key + ' duplicates')
        c[key] = sorted(values)
    need(c['stock_config'] == 'auto' or match(r'[0-9]{1,6}', c['stock_config']), 'carrier.stock_config')
    need(c['stock_sha256'] == '' or match(r'[a-f0-9]{64}', c['stock_sha256']), 'carrier.stock_sha256')
    need(match(APN_RE, ims['apn']), 'ims.apn')
    need(ims['ip_family'] in ('IPv4', 'IPv6', 'IPv4v6'), 'ims.ip_family')
    domain = ims['home_domain']
    need(domain == 'auto' or (isinstance(domain, str) and len(domain) <= 253 and '.' in domain and
         re.search('[a-z]', domain) is not None and all(match(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',
         label) for label in domain.split('.'))), 'ims.home_domain')
    need(type(ims['sms']) is bool and type(runtime['autostart']) is bool, 'boolean options')
    for key, limits in RANGES.items():
        need(type(runtime[key]) is int and limits[0] <= runtime[key] <= limits[1], 'runtime.' + key)
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
    return ('''    <ServiceConfiguration>
      <Name>ims</Name>
      <Description>BB10 IMS</Description>
      <AlwaysOn>true</AlwaysOn>
      <AppModifiable>false</AppModifiable>
      <LTEAttachService>false</LTEAttachService>
      <NetworkInterfaceConfiguration><IPConfiguration>
        <Type>{family}</Type><ProtectRouting>true</ProtectRouting>
      </IPConfiguration></NetworkInterfaceConfiguration>
      <BearerManagementTimer/>
      <RadioAccessTechnology><NetworkServiceFilter>LTE</NetworkServiceFilter><APN>{apn}</APN></RadioAccessTechnology>
      <IMSConfiguration><RequestPCSCFViaPCO>true</RequestPCSCFViaPCO></IMSConfiguration>
      <EPDGConfiguration/>
    </ServiceConfiguration>'''.format(family=p['ims']['ip_family'], apn=p['ims']['apn'])).encode('ascii')


def parse_xml(data):
    root = ET.fromstring(data)
    # Stock BB10 XML uses a default namespace. Normalize the read-only tree;
    # serialization still uses original bytes, retaining namespaces and layout.
    for node in root.iter():
        node.tag = node.tag.rsplit('}', 1)[-1]
    return root


def patch_carrier(stock, profile):
    """Replace exactly the IMS service, preserving every other original byte."""
    parse_xml(stock)
    spans = []
    pattern = br'<(ServiceConfiguration|ServiceConfigurationAlias)>.*?</\1>'
    for found in re.finditer(pattern, stock, re.S):
        node = ET.fromstring(found.group(0))
        if node.findtext('Name') == 'ims':
            spans.append(found.span())
    if len(spans) != 1:
        raise ValueError('Carrier XML needs exactly one IMS service or alias')
    start, end = spans[0]
    result = stock[:start] + ims_section(profile).lstrip() + stock[end:]
    ET.fromstring(result)
    return result


def carrier_template(profile, mcc, mnc):
    """Read only the SIM's stock carrier file, never a downloaded override."""
    p = validate(profile)
    attrs = n.attrs(n.read('/pps/services/carriermanager/status_private'))
    home = n.value(attrs, 'true_home_carrier', {})
    if (not match(r'[0-9]{3}', mcc) or not match(r'[0-9]{2,3}', mnc) or
            home.get('mcc') != int(mcc) or home.get('mnc') != int(mnc) or home.get('downloadedConfigFile')):
        raise ValueError('Current stock carrier selection cannot be verified')
    path = home.get('preloadedConfigFile')
    if p['carrier']['stock_config'] != 'auto':
        path = '/etc/carrier/config/' + p['carrier']['stock_config'] + '.xml'
    if not match(CONFIG_RE, path) or os.path.islink(path):
        raise ValueError('Only a regular stock carrier file is allowed')
    stock = n.read(path)
    digest = n.digest(stock)
    expected = p['carrier']['stock_sha256']
    if expected and digest != expected:
        raise ValueError('Selected carrier file hash differs from profile')
    root = parse_xml(stock)
    internet = [node for node in root.iter('ServiceConfiguration') if node.findtext('Name') == 'internet']
    apns = {node.text for entry in internet for node in entry.iter('APN')}
    # Preserve the existing data APN. Never silently transplant Unicom's data
    # configuration to another carrier just because its IMS APN is also "ims".
    if not apns.intersection(p['carrier']['data_apns']):
        raise ValueError('Stock data APN does not match selected profile')
    changed = patch_carrier(stock, p)
    return {'path': path, 'sha256': digest}, changed
