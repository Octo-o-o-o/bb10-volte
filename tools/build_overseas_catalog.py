"""Generate materials/overseas-carriers.json from pinned Apache-2.0 AOSP data.

This build-time tool consumes only pinned Apache-2.0 Android Open Source Project
inputs (apns-full-conf.xml and carrier_list.textpb), strictly excludes MCC 460
(Mainland China uses the verified three-carrier zero-config engine and blocks
460-15 Broadnet), validates every APN/PLMN against device/profiles.py rules, and
marks every entry as untested on BB10 until real hardware acceptance exists.
"""
import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'device'))
import profiles

AOSP_APNS_COMMIT = '73f904fbeb872f5675cb5f18cd9dfb15856425a6'
AOSP_APNS_SHA256 = '9e44015793ec01d0773123103dca19b181fbc5fdd43cfc1b1d5cfacbda622726'
AOSP_APNS_URL = 'https://android.googlesource.com/device/sample/+/' + AOSP_APNS_COMMIT + '/etc/apns-full-conf.xml'

AOSP_CID_COMMIT = 'bca387f553a4493c88e24455172225fd1049c91f'
AOSP_CID_SHA256 = 'a6a8cc44afb9ad091bda816da98e546c0d8eac86851ee28656ee6802e5ca0825'
AOSP_CID_URL = (
    'https://android.googlesource.com/platform/packages/providers/TelephonyProvider/+/'
    + AOSP_CID_COMMIT + '/assets/latest_carrier_id/carrier_list.textpb'
)

# Major global MNOs whose base entries in AOSP apns-full-conf.xml omit an
# explicit type="ims" row (or use MVNO matchers) so overseas users still get a
# clean PLMN-to-name + default APN starting point using standard 3GPP "ims".
EXTRA_BASE_PLMNS = (
    '204-08', '208-01', '208-10', '208-15', '208-20',
    '214-07', '222-01', '222-10', '228-01',
    '234-10', '234-20', '240-01',
    '302-220', '302-490', '302-610', '302-780',
    '310-260', '310-410', '311-480',
    '440-50', '440-51',
    '454-03', '454-06', '454-12', '466-01', '466-97',
    '505-02', '505-03', '525-03', '525-05', '530-01', '530-05',
)

PROTO_MAP = {
    'IP': 'IPv4',
    'IPV4': 'IPv4',
    'IPV6': 'IPv6',
    'IPV4V6': 'IPv4v6',
}

# Standard ITU-T E.212 MCC -> (ISO-3166 alpha-2 / ITU tag, searchable region label).
MCC_COUNTRY = {
    '202': ('GR', 'Greece'), '204': ('NL', 'Netherlands'), '206': ('BE', 'Belgium'),
    '208': ('FR', 'France'), '214': ('ES', 'Spain'), '216': ('HU', 'Hungary'),
    '219': ('HR', 'Croatia'), '222': ('IT', 'Italy'), '226': ('RO', 'Romania'),
    '228': ('CH', 'Switzerland'), '230': ('CZ', 'Czechia'), '231': ('SK', 'Slovakia'),
    '232': ('AT', 'Austria'), '234': ('GB', 'United Kingdom'), '238': ('DK', 'Denmark'),
    '240': ('SE', 'Sweden'), '242': ('NO', 'Norway'), '244': ('FI', 'Finland'),
    '246': ('LT', 'Lithuania'), '247': ('LV', 'Latvia'), '248': ('EE', 'Estonia'),
    '250': ('RU', 'Russia'), '259': ('MD', 'Moldova'), '260': ('PL', 'Poland'),
    '262': ('DE', 'Germany'), '268': ('PT', 'Portugal'), '270': ('LU', 'Luxembourg'),
    '272': ('IE', 'Ireland'), '284': ('BG', 'Bulgaria'), '286': ('TR', 'Turkey'),
    '290': ('GL', 'Greenland'), '302': ('CA', 'Canada'),
    '310': ('US', 'United States'), '311': ('US', 'United States'),
    '312': ('US', 'United States'), '313': ('US', 'United States'),
    '314': ('US', 'United States'), '334': ('MX', 'Mexico'), '340': ('GP', 'Guadeloupe'),
    '363': ('AW', 'Aruba'), '364': ('BS', 'Bahamas'),
    '404': ('IN', 'India'), '405': ('IN', 'India'), '417': ('SY', 'Syria'),
    '420': ('SA', 'Saudi Arabia'), '421': ('YE', 'Yemen'), '424': ('AE', 'UAE'),
    '432': ('IR', 'Iran'), '436': ('TJ', 'Tajikistan'), '440': ('JP', 'Japan'),
    '450': ('KR', 'South Korea'), '452': ('VN', 'Vietnam'), '454': ('HK', 'Hong Kong'),
    '455': ('MO', 'Macao'), '466': ('TW', 'Taiwan'), '502': ('MY', 'Malaysia'),
    '505': ('AU', 'Australia'), '520': ('TH', 'Thailand'), '525': ('SG', 'Singapore'),
    '530': ('NZ', 'New Zealand'), '606': ('LY', 'Libya'), '647': ('RE', 'Reunion'),
    '655': ('ZA', 'South Africa'), '716': ('PE', 'Peru'), '722': ('AR', 'Argentina'),
    '724': ('BR', 'Brazil'), '730': ('CL', 'Chile'), '732': ('CO', 'Colombia'),
    '740': ('EC', 'Ecuador'), '901': ('INTL', 'International'),
}


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def parse_carrier_names(text):
    names = {}
    for block in re.split(r'(?:^|\n)carrier_id\s*\{', text):
        if not block.strip():
            continue
        m_name = re.search(r'carrier_name:\s*"([^"]+)"', block)
        if not m_name:
            continue
        cname = clean_name(m_name.group(1))
        if not cname or len(cname) > 64:
            continue
        for attr in re.findall(r'carrier_attribute\s*\{([^}]+)\}', block):
            if any(k in attr for k in ('spn:', 'imsi_prefix_xpattern:', 'gid1:', 'gid2:', 'iccid_prefix:', 'plmn:', 'preferred_apn:')):
                continue
            for mm in re.findall(r'mccmnc_tuple:\s*"([0-9]{5,6})"', attr):
                mcc, mnc = mm[:3], mm[3:]
                if mcc != '460':
                    names.setdefault(mcc + '-' + mnc, cname)
    return names


def clean_apn(raw):
    val = (raw or '').strip().lower()
    if not val or not profiles.match(profiles.APN_RE, val):
        return None
    return val


def clean_name(raw):
    val = re.sub(r'\s+', ' ', (raw or '').strip())
    return val[:64] if val else ''


def build_catalog(apns_path, cid_path):
    apns_raw = Path(apns_path).read_bytes()
    cid_raw = Path(cid_path).read_bytes()
    if sha256_bytes(apns_raw) != AOSP_APNS_SHA256:
        raise ValueError('apns-full-conf.xml SHA-256 mismatch: ' + sha256_bytes(apns_raw))
    if sha256_bytes(cid_raw) != AOSP_CID_SHA256:
        raise ValueError('carrier_list.textpb SHA-256 mismatch: ' + sha256_bytes(cid_raw))

    cid_names = parse_carrier_names(cid_raw.decode('utf-8'))
    root = ET.fromstring(apns_raw)
    by_plmn = {}
    for el in root.findall('apn'):
        mcc = (el.get('mcc') or '').strip()
        mnc = (el.get('mnc') or '').strip()
        if mcc == '460' or not (re.fullmatch(r'[0-9]{3}', mcc) and re.fullmatch(r'[0-9]{2,3}', mnc)):
            continue
        if el.get('mvno_type') or el.get('mvno_match_data'):
            continue
        apn = clean_apn(el.get('apn'))
        if not apn:
            continue
        types = [t.strip().lower() for t in (el.get('type') or '').split(',') if t.strip()]
        proto = PROTO_MAP.get((el.get('protocol') or 'IPV4V6').strip().upper(), 'IPv4v6')
        plmn = mcc + '-' + mnc
        rec = by_plmn.setdefault(plmn, {'ims': [], 'data': [], 'names': []})
        if 'ims' in types:
            pair = (apn, proto)
            if pair not in rec['ims']:
                rec['ims'].append(pair)
        if 'default' in types or not types:
            if apn not in rec['data']:
                rec['data'].append(apn)
        cname = clean_name(el.get('carrier'))
        if cname and cname not in rec['names']:
            rec['names'].append(cname)

    target_plmns = sorted(
        {plmn for plmn, rec in by_plmn.items() if rec['ims']}
        | {plmn for plmn in EXTRA_BASE_PLMNS if plmn in by_plmn or plmn in cid_names}
    )

    entries = {}
    for plmn in target_plmns:
        mcc, mnc = plmn.split('-', 1)
        if mcc == '460':
            continue
        rec = by_plmn.get(plmn, {'ims': [], 'data': [], 'names': []})
        name = cid_names.get(plmn) or (rec['names'][0] if rec['names'] else ('PLMN ' + plmn))
        name = clean_name(name)
        if rec['ims']:
            ims_apn, ims_family = rec['ims'][0]
            source = 'aosp-apns'
        else:
            ims_apn, ims_family = 'ims', 'IPv4v6'
            source = 'aosp-carrier-list'
        data_apns = []
        seen_lower = set()
        for candidate in rec['data']:
            low = candidate.lower()
            if low not in seen_lower:
                seen_lower.add(low)
                data_apns.append(candidate)
            if len(data_apns) >= 3:
                break
        country_code, region_name = MCC_COUNTRY.get(mcc, ('', ''))
        entries[plmn] = {
            'mcc': mcc,
            'mnc': mnc,
            'country': country_code,
            'region': region_name,
            'name': name,
            'data_apns': data_apns,
            'ims_apn': ims_apn,
            'ims_ip_family': ims_family,
            'source': source,
            'bb10_status': 'untested',
        }

    return {
        'schema': 1,
        'license': 'Apache-2.0',
        'license_file': 'licenses/APACHE-2.0.txt',
        'copyright': 'Copyright (C) The Android Open Source Project',
        'attribution': 'Derived from Android Open Source Project (AOSP) device/sample apns-full-conf.xml and TelephonyProvider carrier_list.textpb',
        'modifications': 'Filtered non-460 carrier APN/IMS metadata into a compact offline lookup table with bb10_status marked untested and ITU-T E.212 country/region tags added.',
        'sources': {
            'aosp_apns_url': AOSP_APNS_URL,
            'aosp_apns_commit': AOSP_APNS_COMMIT,
            'aosp_apns_sha256': AOSP_APNS_SHA256,
            'aosp_carrier_list_url': AOSP_CID_URL,
            'aosp_carrier_list_commit': AOSP_CID_COMMIT,
            'aosp_carrier_list_sha256': AOSP_CID_SHA256,
        },
        'disclaimer': 'Public APN and carrier name suggestions only; not BB10 hardware or VoLTE certification. Excludes MCC 460.',
        'entry_count': len(entries),
        'carriers': entries,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apns', type=Path, required=True)
    parser.add_argument('--carrier-list', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'materials/overseas-carriers.json')
    args = parser.parse_args(argv)
    catalog = build_catalog(args.apns, args.carrier_list)
    encoded = json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    args.output.write_text(encoded, encoding='utf-8', newline='\n')
    print(json.dumps({'output': str(args.output), 'entries': catalog['entry_count'], 'bytes': len(encoded.encode('utf-8'))}))


if __name__ == '__main__':
    main()
