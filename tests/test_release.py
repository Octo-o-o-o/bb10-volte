"""Regression coverage for accidental private-file and credential publication."""
import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import check_release


class PublicReleaseTests(unittest.TestCase):
    def tracked(self):
        return [p.relative_to(check_release.ROOT).as_posix()
                for p in check_release.selected_files()]

    def run_with_index(self, names):
        index = ('\0'.join(names) + '\0').encode('utf-8')
        with patch.object(check_release.subprocess, 'check_output', return_value=index):
            return check_release.check(check_git=True)

    def test_exact_public_index_passes(self):
        result = self.run_with_index(self.tracked())
        self.assertTrue(result['git_allowlist_verified'])
        self.assertTrue(result['payload_hashes_verified'])

    def test_tracked_private_file_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'Git/public allowlist mismatch'):
            self.run_with_index(self.tracked() + ['private/owner-key'])

    def test_missing_public_file_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'Git/public allowlist mismatch'):
            self.run_with_index([p for p in self.tracked() if p != 'README.en.md'])

    def test_generated_token_shapes_are_detected(self):
        # Construct dummy strings so the test source contains no token-like literal.
        pattern = check_release.SENSITIVE['access token']
        for value in ('ghp_' + 'x' * 36, 'github_pat_' + 'x' * 50,
                      'AKIA' + '0' * 16):
            with self.subTest(prefix=value[:4]):
                self.assertIsNotNone(pattern.search(value))

    def test_changed_recording_media_is_rejected(self):
        original = Path.read_bytes
        def modified(path):
            data = original(path)
            return data + b'changed' if path.name == 'q10-xiaohongshu-final.mp4' else data
        with patch.object(Path, 'read_bytes', modified):
            with self.assertRaisesRegex(AssertionError, 'Changed recording input'):
                check_release.check()

    def test_recording_manifest_rejects_parent_traversal(self):
        manifest = {'schema': 1, 'files': {'docs/recordings/../../private/secret': 'a' * 64}}
        with patch.object(Path, 'read_text', return_value=json.dumps(manifest)):
            with self.assertRaises(AssertionError):
                check_release.recording_files()


if __name__ == '__main__':
    unittest.main()
