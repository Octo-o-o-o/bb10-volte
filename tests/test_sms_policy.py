import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'device'))
import carrier_policy
import native
import profiles
import service

KEY = 'SMS_Over_IP_Network_Indication'


class SmsPolicyTests(unittest.TestCase):
    def test_all_nine_supported_combinations_publish_sms_policy(self):
        for variant, (family, board) in carrier_policy.MODELS.items():
            for mnc in carrier_policy.CARRIERS:
                facts = {'variant': variant, 'board_type': board, 'os_version': carrier_policy.OS_VERSION}
                card = {'state': 'READY', 'kind': 2, 'mcc': '460', 'mnc': mnc,
                        'imsi': '460' + mnc + '0' * 10}
                selected = carrier_policy.select(facts, card)
                profile = selected['request']['profile']
                changes = service.profile_updates(profile, '460', mnc)
                self.assertEqual(changes[service.IMS][KEY], 'b:true')
                self.assertEqual(changes[service.VOICE], {'voice_domain_preference_EUTRAN': 'n:3'})

    def test_sms_disabled_does_not_leave_ps_selection_enabled(self):
        profile = profiles.default()
        profile['ims']['sms'] = False
        changes = service.profile_updates(profile, '460', '01')
        self.assertEqual(changes[service.IMS][KEY], 'b:false')
        self.assertNotIn('"sms"', changes[service.IMS]['IMS_services'])

    def test_restored_legacy_journal_records_exact_original_before_apply(self):
        for original in (None, 'b:false', 'b:true'):
            journal = {'pps_before': {service.IMS: {}}, 'restore_completed': True}
            with patch.object(service, 'j', journal), patch.object(native, 'read', return_value=(
                    '@ims\n' + (KEY + ':' + original + '\n' if original else '')).encode()), \
                    patch.object(service, 'save_journal') as save:
                service.journal_sms_policy()
                self.assertEqual(journal['pps_before'][service.IMS][KEY], original)
                save.assert_called_once()
                service.journal_sms_policy()
                save.assert_called_once()

    def test_active_legacy_journal_must_be_restored_before_ownership_expands(self):
        journal = {'pps_before': {service.IMS: {}}, 'restore_completed': False}
        with patch.object(service, 'j', journal), patch.object(native, 'read') as read:
            with self.assertRaisesRegex(AssertionError, 'Restore legacy'):
                service.journal_sms_policy()
            read.assert_not_called()

    def test_invalid_original_policy_is_not_clobbered(self):
        journal = {'pps_before': {service.IMS: {}}, 'restore_completed': True}
        with patch.object(service, 'j', journal), patch.object(native, 'read', return_value=(
                '@ims\n' + KEY + ':n:1\n').encode()), patch.object(service, 'save_journal') as save:
            with self.assertRaisesRegex(AssertionError, 'Unexpected SMS'):
                service.journal_sms_policy()
            save.assert_not_called()

    def test_restore_keeps_original_value_and_preserves_concurrent_edits(self):
        for original in (None, 'b:true', 'b:false'):
            before, applied = {KEY: original}, {KEY: 'b:true'}
            actual = {KEY: 'b:true', 'unrelated': ':keep'}
            changes = carrier_policy.restore_fields(actual, before, applied)
            actual.update(changes)
            self.assertEqual(actual, {KEY: original, 'unrelated': ':keep'})
        with self.assertRaisesRegex(ValueError, 'carrier_configuration_changed'):
            carrier_policy.restore_fields({KEY: 'b:false'}, {KEY: None}, {KEY: 'b:true'})

    def test_pre_sms_restore_fallback_does_not_claim_new_field(self):
        with patch.object(service, 'j', {'pps_before': {}}):
            self.assertNotIn(KEY, service.applied_updates()[service.IMS])


if __name__ == '__main__':
    unittest.main()
