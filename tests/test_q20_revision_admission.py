"""Exercise desktop admission using the exact accepted historical manifest."""
import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import q20_managed
from workflow import WorkflowError


class Q20RevisionAdmissionTests(unittest.TestCase):
    def test_accepted_mobile_autostart_revision_can_be_inspected(self):
        raw = (ROOT / 'materials/q20-mobile-autostart-manifest.json').read_text(encoding='ascii')
        digest = hashlib.sha256(raw.encode('ascii')).hexdigest()
        self.assertEqual(digest, 'a517c79c1025068aa16fbaffc4122bc18cf415a7b6e368e8e101561bd2a05111')
        client = Mock(scp='scp', ssh='ssh', options=[], host='test-phone')
        client.remote.side_effect = [raw, '', '{"accepted": true}']
        self.assertEqual(q20_managed.Adapter(client).invoke('inspect'), {'accepted': True})
        client.process.assert_called_once()
        self.assertIn('inspect ' + digest, client.remote.call_args.args[0])

    def test_changed_historical_manifest_is_rejected_before_upload(self):
        raw = (ROOT / 'materials/q20-mobile-autostart-manifest.json').read_text(encoding='ascii')
        client = Mock(scp='scp', ssh='ssh', options=[], host='test-phone')
        client.remote.return_value = raw.replace('q20-sqc100-2-volte-v1', 'unrecognized-owner')
        with self.assertRaisesRegex(WorkflowError, 'package_mismatch'):
            q20_managed.Adapter(client).invoke('inspect')
        client.process.assert_not_called()
        self.assertEqual(client.remote.call_count, 1)
