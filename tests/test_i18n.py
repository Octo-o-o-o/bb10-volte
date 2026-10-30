"""System language selection and bilingual desktop presentation, offline."""
import ast
from pathlib import Path
import re
import string
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import i18n
from translations_en import ENGLISH


class LanguageSelectionTests(unittest.TestCase):
    def test_language_tags_and_unavailable_values(self):
        for value in ('zh', 'zh-CN', 'zh-Hans', 'zh-Hant-TW', 'zh_HK', 'Chinese (Simplified)_China',
                      'yue-Hant-HK', 'cmn-Hans', None, '', '  ', 'C', 'C.UTF-8', 'POSIX', 'und', '???'):
            with self.subTest(value=value):
                self.assertEqual(i18n.language_from_tag(value), 'zh')
        for value in ('en-US', 'fr-FR', 'ja', 'ko_KR', 'de_DE.UTF-8', 'sr_RS@latin'):
            with self.subTest(value=value):
                self.assertEqual(i18n.language_from_tag(value), 'en')

    def test_windows_uses_ui_language_not_formatting_locale(self):
        for langid, expected in ((0x0804, 'zh'), (0x0404, 'zh'), (0x0409, 'en'), (0x0411, 'en'), (0, 'zh')):
            kernel = SimpleNamespace(GetUserDefaultUILanguage=lambda: langid)
            with self.subTest(langid=langid), patch.object(i18n.sys, 'platform', 'win32'), \
                    patch.object(i18n.ctypes, 'windll', SimpleNamespace(kernel32=kernel), create=True), \
                    patch.object(i18n.locale, 'getlocale', side_effect=AssertionError('format locale used')):
                self.assertEqual(i18n.system_language(), expected)

    def test_mac_uses_first_preferred_language_and_failures_fall_back(self):
        for preference, expected in (('zh-Hant-TW', 'zh'), ('en-CN', 'en'), ('fr-FR', 'en'), (None, 'zh')):
            with self.subTest(preference=preference), patch.object(i18n.sys, 'platform', 'darwin'), \
                    patch.object(i18n, '_mac_language', return_value=preference):
                self.assertEqual(i18n.system_language(), expected)
        with patch.object(i18n.sys, 'platform', 'darwin'), patch.object(i18n, '_mac_language', side_effect=OSError):
            self.assertEqual(i18n.system_language(), 'zh')

    def test_unix_language_precedence_and_missing_preference(self):
        with patch.object(i18n.sys, 'platform', 'linux'), \
                patch.dict(i18n.os.environ, {'LC_MESSAGES': 'ja_JP.UTF-8', 'LANG': 'zh_CN.UTF-8'}, clear=True):
            self.assertEqual(i18n.system_language(), 'en')
        with patch.object(i18n.sys, 'platform', 'linux'), patch.dict(i18n.os.environ, {}, clear=True), \
                patch.object(i18n.locale, 'getlocale', return_value=(None, None)):
            self.assertEqual(i18n.system_language(), 'zh')

    def test_english_guide_and_chinese_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'guide.md'
            translated = Path(tmp) / 'guide.en.md'
            path.write_text('中文', encoding='utf-8')
            translated.write_text('English', encoding='utf-8')
            with patch.object(i18n, 'LANGUAGE', 'en'):
                self.assertEqual(i18n.document_path(path), translated)
                translated.unlink()
                self.assertEqual(i18n.document_path(path), path)
            with patch.object(i18n, 'LANGUAGE', 'zh'):
                self.assertEqual(i18n.document_path(path), path)

    def test_every_presentation_string_has_english_and_matching_format_fields(self):
        formatter = string.Formatter()
        for path in (ROOT / 'tools').glob('*.py'):
            if path.name == 'translations_en.py':
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and
                        node.func.id == 'tr' and node.args and isinstance(node.args[0], ast.Constant) and
                        isinstance(node.args[0].value, str)):
                    continue
                source = node.args[0].value
                with self.subTest(path=path.name, line=node.lineno):
                    self.assertIn(source, ENGLISH)
                    self.assertFalse(re.search(r'[\u4e00-\u9fff]', ENGLISH[source]))
                    fields = lambda text: [(field, spec, conversion) for _, field, spec, conversion in
                                           formatter.parse(text) if field is not None]
                    self.assertEqual(fields(source), fields(ENGLISH[source]))

    def test_english_interface_and_profile_round_trip_in_fresh_process(self):
        # Import-time dictionaries must be initialized in the selected language.
        code = r'''
import sys, tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path.cwd() / 'tools'))
sys.path.insert(0, str(Path.cwd() / 'device'))
import i18n
i18n.LANGUAGE = 'en'
import diagnostic_details as d
import gui, profile_editor, connection_flow, fetch_materials
assert gui.NAMES['model'] == 'Phone model'
assert 'do not mean' in connection_flow.guidance(error='connection_setup_required').detail
assert 'does not mean' in connection_flow.guidance(error='root_not_ready').detail
for profile in profile_editor.presets():
    original = profile['label']
    assert profile_editor.stored_label(profile_editor.display_label(original), original) == original
    assert profile_editor.profiles.fingerprint(profile) == profile_editor.profiles.fingerprint(dict(profile, label=profile_editor.stored_label(profile_editor.display_label(original), original)))
assert 'SSH alias' in gui.ERRORS['invalid_host']
assert 'firmware' in fetch_materials.MaterialImportError('import_hash_mismatch').user_message
report = {'checks': [{'id': 'baseline', 'status': 'wait', 'code': 'baseline_not_clean'}],
          'baseline': {'voice_policy': 3, 'crypto_swcr_id': -1, 'crypto_support': 0,
                       'ims_count': 0, 'vpn_count': 0, 'native_read_error': False},
          'installation': {'state': 'absent'}}
rows = d.baseline_rows(report)
assert rows and not any(any('\u4e00' <= c <= '\u9fff' for c in row['detail']) for row in rows)
try:
    import tkinter as tk
    root = tk.Tk()
except Exception:
    print('NO_DISPLAY')
    raise SystemExit(0)
root.withdraw()
with tempfile.TemporaryDirectory() as folder, patch.object(gui, 'private_root', return_value=Path(folder)), patch.object(gui, 'saved_connection', return_value=None):
    app = gui.App(root)
    assert app.check_button.cget('text') == 'Connect phone'
    assert app.setup_button.cget('text') == 'Connection help'
    assert app.ack_check.cget('text').startswith('I have a backup')
    assert not any('\u4e00' <= c <= '\u9fff' for c in app.detail.cget('text'))
    app.close()
print('OK')
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, text=True,
                                capture_output=True, timeout=60, encoding='utf-8', errors='replace')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(result.stdout.strip(), ('OK', 'NO_DISPLAY'))


if __name__ == '__main__':
    unittest.main()
