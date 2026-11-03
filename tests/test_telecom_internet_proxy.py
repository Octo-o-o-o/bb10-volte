"""Check the carrier workaround across the supported device/SIM matrix."""
import json
import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'device'))
import carrier_policy as policy
import native as n
import profiles
import unified_install


BAD = profiles.TELECOM_446_BAD_PROXY
IMS_ALIAS = b'<ServiceConfigurationAlias><Name>ims</Name><Reference>internet</Reference></ServiceConfigurationAlias>'


def service(name, apn, proxy=b''):
    return (b'<ServiceConfiguration><Name>' + name + b'</Name><RadioAccessTechnology><APN>' + apn +
            b'</APN></RadioAccessTechnology>' + proxy + b'</ServiceConfiguration>')


def stock(internet, wap):
    return (b'<Carrier xmlns="urn:test">' + internet + wap +
            service(b'mms', b'ctwap', BAD) + IMS_ALIAS + b'</Carrier>')


class TelecomInternetProxyTests(unittest.TestCase):
    def test_released_r18_payload_is_admitted_for_a_bounded_upgrade(self):
        previous = json.loads((ROOT / 'materials/unified-payload-r18.json').read_text(encoding='ascii'))
        candidate = json.loads((ROOT / 'materials/unified-payload.json').read_text(encoding='ascii'))
        fingerprint = hashlib.sha256(profiles.canonical(previous['files'])).hexdigest()
        self.assertEqual(fingerprint, 'b975409427c96fee16f10f7a271c53ebf181d37522b64e1b858cd1aeda3db777')
        self.assertIn(fingerprint, unified_install.PREVIOUS_PAYLOADS)
        self.assertEqual(set(previous['files']), set(candidate['files']))
        changed = {name for name in previous['files'] if previous['files'][name] != candidate['files'][name]}
        self.assertEqual(changed, {'device/profiles.py', 'device/unified_install.py'})
        self.assertLessEqual(changed, set(unified_install.UPDATE_FILES))

    def test_supported_models_and_carriers_keep_their_own_data_and_mms(self):
        variants = [('SQN100-3', None), ('SQC100-2', 'CLASSICATT'),
                    ('SQW100-4', 'WINDERMERE4ROW')]
        mobile_wap = b'<HttpProxyV4>10.0.0.172:80</HttpProxyV4>'
        carriers = {
            '00': ('404', b'cmnet', b'cmwap', mobile_wap),
            '01': ('36', b'3gnet', b'3gwap', mobile_wap),
            '11': ('446', b'ctnet', b'ctwap', BAD),
        }
        for variant, board in variants:
            for mnc, (config, apn, wap_apn, wap_proxy) in carriers.items():
                with self.subTest(variant=variant, mnc=mnc):
                    internet = service(b'internet', apn, BAD if mnc == '11' else b'')
                    wap = service(b'internet', wap_apn, wap_proxy) if mnc != '11' else b''
                    original = stock(internet, wap)
                    selected = policy.select(
                        {'variant': variant, 'board_type': board, 'os_version': policy.OS_VERSION},
                        {'state': 'READY', 'kind': 2, 'mcc': '460', 'mnc': mnc,
                         'imsi': '460' + mnc + '0' * 10})
                    profile = selected['request']['profile']
                    home = {'mcc': 460, 'mnc': int(mnc),
                            'preloadedConfigFile': '/etc/carrier/config/' + config + '.xml'}
                    status = ('true_home_carrier:json:' + json.dumps(home) + '\n').encode('ascii')
                    digest = profiles.TELECOM_446_BAD_PROXY_SHA256 if mnc == '11' else '0' * 64
                    with patch.object(n, 'read', side_effect=lambda path: status if path.endswith('status_private') else original), \
                            patch.object(n, 'digest', return_value=digest), \
                            patch.object(profiles.os.path, 'islink', return_value=False):
                        template, changed = profiles.carrier_template(profile, '460', mnc)
                    self.assertEqual(template['path'], home['preloadedConfigFile'])
                    expected_internet = service(b'internet', apn)
                    expected = stock(expected_internet, wap).replace(IMS_ALIAS, profiles.ims_section(profile).lstrip())
                    self.assertEqual(changed, expected)
                    self.assertIn(service(b'mms', b'ctwap', BAD), changed)
                    self.assertIn(wap, changed)
                    self.assertEqual(original, stock(internet, wap))

    def test_unverified_operator_file_or_stock_hash_is_untouched(self):
        raw = stock(service(b'internet', b'ctnet', BAD), b'')
        good = ('/etc/carrier/config/446.xml', profiles.TELECOM_446_BAD_PROXY_SHA256, '460', '11')
        for args in [('/etc/carrier/config/445.xml', *good[1:]),
                     (good[0], 'f' * 64, *good[2:]),
                     (good[0], good[1], '460', '03'),
                     (good[0], good[1], '461', '11')]:
            with self.subTest(args=args):
                self.assertEqual(profiles.fix_known_telecom_internet_proxy(raw, *args), raw)

    def test_known_hash_with_ambiguous_internet_layout_fails_closed(self):
        item = service(b'internet', b'ctnet', BAD)
        for raw in (stock(item + item, b''), stock(service(b'internet', b'ctnet'), b''),
                    stock(service(b'internet', b'ctlte', BAD), b'')):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    profiles.fix_known_telecom_internet_proxy(
                        raw, '/etc/carrier/config/446.xml', profiles.TELECOM_446_BAD_PROXY_SHA256, '460', '11')


if __name__ == '__main__':
    unittest.main()
