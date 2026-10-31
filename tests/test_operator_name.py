"""Display fallback is scoped to the accepted SIM and never changes radio state."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'device'))
import operator_name as op
import profiles
from test_telecom_attach import telecom_profile


class OperatorNameTests(unittest.TestCase):
    def test_overlay_preserves_every_original_row_and_adds_only_missing_46011(self):
        original = b'PPCI&N|Abrev. Net. Name|MCC|MNC\nChina Telecom|China Telecom|460|3\n'
        with patch.object(op, 'STOCK_HASH', hashlib.sha256(original).hexdigest()):
            result = op.payload(original)
            self.assertTrue(result.startswith(original))
            self.assertEqual(result[len(original):].decode('utf-8'), op.NAME + '|' + op.NAME + '|460|11\n')
            with self.assertRaises(AssertionError): op.payload(original + b'foreign change')

    def test_existing_46011_mapping_is_preserved_instead_of_replaced(self):
        original = b'PPCI&N|Abrev. Net. Name|MCC|MNC\nOther|Other|460|11\n'
        with patch.object(op, 'STOCK_HASH', hashlib.sha256(original).hexdigest()):
            with self.assertRaises(AssertionError): op.payload(original)

    def facts(self):
        identity = '46011' + '0' * 10
        request = profiles.request(telecom_profile(), True)
        receipt = {'profile_sha256': profiles.fingerprint(request),
                   'sim_fingerprint': hashlib.sha256(identity.encode('ascii')).hexdigest()}
        blobs = {
            op.PRIVATE: ('@status\nuicc_state:json:{"state":"READY"}\nhplmn:json:{"mcc":"460","mnc":"11"}\n').encode(),
            '/pps/services/cellular/uicc/card0/status_restricted': ('@status\nimsi::' + identity + '\n').encode(),
            op.CELL: ('@status\nserving_network:json:{"mcc":"460","mnc":"11"}\nnetwork_technology::lte\n'
                      'network_service:n:2097152\nroaming:json:{"state":"NOT_ROAMING"}\n').encode()}
        return request, receipt, blobs

    def eligible(self, request, receipt, blobs, variant='SQN100-3', enabled=True):
        with patch.object(op.device_info, 'read_identity', return_value={'variant': variant, 'os_version': '10.3.3.3216'}), \
                patch.object(op.os.path, 'isfile', return_value=enabled), \
                patch.object(op.profiles, 'installed_request', return_value=request), \
                patch.object(op.n, 'read', side_effect=lambda path: blobs[path]):
            return op.eligible(receipt)

    def test_only_matching_home_SIM_on_normal_LTE_is_eligible(self):
        request, receipt, blobs = self.facts()
        self.assertTrue(self.eligible(request, receipt, blobs))
        for case in ('Passport', 'disabled', 'other_SIM', 'other_PLMN', 'emergency', 'roaming', 'searching'):
            copy = dict(blobs); current = dict(receipt)
            if case == 'other_SIM': current['sim_fingerprint'] = 'different'
            if case == 'other_PLMN': copy[op.CELL] = copy[op.CELL].replace(b'"mnc":"11"', b'"mnc":"01"')
            if case == 'emergency': copy[op.CELL] = copy[op.CELL].replace(b'2097152', b'33554432')
            if case == 'roaming': copy[op.CELL] = copy[op.CELL].replace(b'NOT_ROAMING', b'ROAMING')
            if case == 'searching': copy[op.PRIVATE] = copy[op.PRIVATE].replace(b'READY', b'WAITING')
            with self.subTest(case=case):
                self.assertFalse(self.eligible(request, current, copy,
                    variant='SQW100-4' if case == 'Passport' else 'SQN100-3', enabled=case != 'disabled'))

    def test_ineligible_state_does_not_change_a_name_or_path(self):
        with patch.object(op, 'eligible', return_value=False), patch.object(op, 'manager') as manager, \
                patch.object(op.n, 'update_pps') as update:
            self.assertFalse(op.apply_once({'checked': True})['applied'])
        manager.assert_not_called(); update.assert_not_called()

    def test_foreign_table_link_is_preserved(self):
        with patch.object(op, 'link_target', return_value='/foreign/table'), patch.object(op, 'manager') as manager:
            with self.assertRaises(RuntimeError): op.restore()
        manager.assert_not_called()

    def test_boot_waits_for_full_SIM_authorization_before_any_name_change(self):
        receipt = {'accepted': True}
        with patch.object(op, 'authorized_receipt', side_effect=[AssertionError('SIM not ready'), receipt]), \
                patch.object(op.os.path, 'isfile', side_effect=[True, True, True, False]), \
                patch.object(op, 'eligible', return_value=True), patch.object(op, 'apply_once') as apply, \
                patch.object(op, 'restore') as restore, patch.object(op.time, 'sleep') as sleep, \
                patch.object(op.signal, 'signal'), patch.object(op.signal, 'SIGHUP', 1, create=True):
            op.watch()
        apply.assert_called_once_with(receipt)
        self.assertEqual(sleep.call_args_list[0].args, (5,))
        restore.assert_called_once()


if __name__ == '__main__':
    unittest.main()
