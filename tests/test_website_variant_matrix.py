"""The public compatibility table must match the actual desktop trial gates."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'device')]
import device_support
import variant_trials


class WebsiteVariantMatrixTests(unittest.TestCase):
    def test_public_routes_match_every_exact_variant_and_carrier(self):
        data = json.loads((ROOT / 'website/src/compatibility.json').read_text(encoding='utf-8'))
        variants = [item['variant'] for item in data['models']]
        self.assertEqual(len(variants), len(set(variants)))
        self.assertEqual(set(variants), set(device_support.catalog()))
        self.assertEqual(data['release'], 'v0.5.0-r42')
        for item in data['models']:
            self.assertEqual(item['family'], device_support.catalog()[item['variant']]['family'])
            self.assertEqual(set(item['routes']), {'mobile', 'unicom', 'telecom'})
            for operator, route in item['routes'].items():
                with self.subTest(variant=item['variant'], operator=operator):
                    self.assertEqual(route, variant_trials.plan(item['variant'], operator)['route'])
        sqw = next(item for item in data['models'] if item['variant'] == 'SQW100-1')
        self.assertIn('460-07', sqw['note']['zh'])
        self.assertIn('460-07', sqw['note']['en'])


if __name__ == '__main__':
    unittest.main()
