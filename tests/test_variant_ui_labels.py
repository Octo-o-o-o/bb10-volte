"""Keep the phone's visible trial choices bound to the generated model catalog."""
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'device')]
import package_mobile


class ExactVariantMobileLabelsTests(unittest.TestCase):
    def test_visible_model_carrier_and_read_only_label_match_generated_choice(self):
        catalog = json.loads(package_mobile.trial_inputs()['materials/variant-trials.json'])
        cases = {case['profile_id']: case for case in catalog['cases']}
        page = (ROOT / 'mobile/native/assets/Experimental.qml').read_text(encoding='utf-8')
        options = re.findall(
            r'Option\s*\{\s*text:\s*(?P<label>[^;]+);\s*'
            r'value:\s*"(?P<value>variant-trial-[^"]+)";\s*'
            r'selected:\s*volteController\.legacyProfile\s*===\s*"(?P<selected>[^"]+)"\s*\}',
            page,
        )
        self.assertEqual(len(options), len(cases), 'every generated choice must have one visible option')
        self.assertEqual({value for _, value, _ in options}, set(cases))
        for label, value, selected in options:
            with self.subTest(profile=value):
                case = cases[value]
                rendered = re.fullmatch(
                    r'\s*"(?P<device>[^\"]+)"\s*\+\s*'
                    r'page\.t\(\s*"profile_(?P<operator>mobile|unicom|telecom)"\s*\)'
                    r'(?:\s*\+\s*"(?P<separator>[^\"]+)"\s*\+\s*'
                    r'page\.t\(\s*"trial_read_only"\s*\))?\s*',
                    label,
                )
                self.assertIsNotNone(rendered, 'visible option must name its model and carrier')
                device = re.fullmatch(r'\s*(SQ[NCW]100-[0-9]+)\s*/\s*', rendered.group('device'))
                self.assertIsNotNone(device)
                self.assertEqual(device.group(1), case['variant'])
                self.assertEqual(rendered.group('operator'), case['operator'])
                read_only = rendered.group('separator') is not None
                if read_only:
                    self.assertEqual(rendered.group('separator').strip(), '/')
                self.assertEqual(read_only, case['route'] == 'read_only_lifecycle_pending')
                self.assertEqual(selected, value, 'selected state must refer to the displayed option')


if __name__ == '__main__':
    unittest.main()
