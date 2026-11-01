"""Public native client contracts; hardware rendering is a separate acceptance gate."""
from pathlib import Path
import ast
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "mobile" / "native"
NS = {"q": "http://www.qnx.com/schemas/application/1.0"}


class NativeDeliveryContracts(unittest.TestCase):
    def test_bar_keeps_upgrade_identity_and_minimum_permissions(self):
        root = ET.parse(NATIVE / "bar-descriptor.xml").getroot()
        self.assertEqual(root.findtext("q:id", namespaces=NS), "com.octolab.bb10volte")
        self.assertEqual(root.findtext("q:author", namespaces=NS), "OctoLab")
        self.assertEqual(root.findtext("q:authorId", namespaces=NS), "gYAOctoLabBB10VoLTE20261102")
        self.assertEqual({e.text for e in root.findall("q:permission", NS)},
                         {"run_native", "access_shared", "access_internet"})
        self.assertEqual(root.findtext("q:configuration/q:platformArchitecture", namespaces=NS), "armle-v7")
        entry = root.find("q:configuration/q:asset", NS)
        self.assertEqual(entry.get("type"), "Qnx/Elf")
        self.assertTrue((NATIVE / root.findtext("q:icon/q:image", namespaces=NS)).is_file())

    def test_every_ui_page_and_localized_reference_is_packaged(self):
        strings = (NATIVE / "src/ui_strings.h").read_text(encoding="utf-8")
        rows = re.findall(r'\{"([^"\n]+)",\s*"((?:\\.|[^"\\])*)",\s*"((?:\\.|[^"\\])*)"\}', strings)
        keys = {key for key, _, _ in rows}
        self.assertEqual(len(rows), len(keys), "Duplicate translation key")
        for key, chinese, english in rows:
            self.assertTrue(chinese and english, key)
            self.assertNotRegex(english, r"[\u4e00-\u9fff]", key)
        self.assertTrue((NATIVE / "assets/main.qml").is_file())
        for page in (NATIVE / "assets").glob("*.qml"):
            text = page.read_text(encoding="utf-8")
            for key in re.findall(r'\.t\("([^"\n]+)"\)', text):
                self.assertIn(key, keys, f"{page.name}: missing {key}")
            for filename in re.findall(r'source:\s*"([^"\n]+\.qml)"', text):
                self.assertTrue((page.parent / filename).is_file(), filename)
            self.assertIn("ScrollView", text, page.name)

    def test_client_never_exposes_shell_or_dialing_to_qml(self):
        header = (NATIVE / "src/mobilecontroller.h").read_text(encoding="utf-8")
        exposed = re.findall(r"Q_INVOKABLE[^;]+;", header)
        self.assertFalse(any(re.search(r"\b(?:shell|exec|command|runScript)\b", method) for method in exposed))
        source = (NATIVE / "src/mobilecontroller.cpp").read_text(encoding="utf-8")
        starts = re.findall(r"m_process\.start\(([^;]+);", source)
        self.assertEqual(len(starts), 1)
        self.assertTrue(starts[0].startswith('"/bin/__root", QStringList()'))
        for path in (NATIVE / "assets").glob("*.qml"):
            self.assertNotRegex(path.read_text(encoding="utf-8"), r"tel:|phone\.dial|invoke\(.*call")
        self.assertNotIn("QJsonDocument", source)

    def test_published_update_transport_has_no_tls_bypass(self):
        source = (NATIVE / "src/mobilecontroller.cpp").read_text(encoding="utf-8")
        code = re.sub(r"//[^\n]*", "", source)
        self.assertNotRegex(code, r"(?:ignoreSslErrors|VerifyNone)\s*\(")
        self.assertIn('url.scheme().toLower() == "https"', source)
        self.assertIn("!trustedUrl(target)", source)
        self.assertIn("m_downloadBytes > MAX_PACKAGE", source)
        self.assertIn("O_WRONLY | O_CREAT | O_EXCL", source)

    def test_human_call_confirmation_carries_a_fresh_context(self):
        source = (NATIVE / "src/mobilecontroller.cpp").read_text(encoding="utf-8")
        page = (NATIVE / "assets/CallCheck.qml").read_text(encoding="utf-8")
        self.assertIn('context != m_model.value("call_context").toString()', source)
        self.assertIn('extra.insert("call_context", context)', source)
        self.assertIn("onCallContextChanged", page)
        for check in ("outgoing", "incoming", "audio", "lte"):
            self.assertIn(check + ".checked = false", page)
            self.assertIn(f'extra.insert("{check}", true)', source)
        self.assertNotIn('extra.insert("call_checks"', source)

    def test_recoverable_failure_preserves_job_and_runtime_resume_action(self):
        source = (NATIVE / "src/mobilecontroller.cpp").read_text(encoding="utf-8")
        self.assertIn('m_runtimeError && action == "resume" && !m_jobId.isEmpty() && allowed(action)', source)
        self.assertIn('completed(job.value("state").toString()) && !recoverable', source)
        self.assertIn('response.value("actions").toList().contains(QVariant("resume"))', source)

    def test_bundled_service_upgrade_does_not_require_same_version_zip(self):
        source = (NATIVE / "src/mobilecontroller.cpp").read_text(encoding="utf-8")
        manage = (NATIVE / "assets/Manage.qml").read_text(encoding="utf-8")
        self.assertIn('if (primaryAction() == "update") applyBundledUpdate()', source)
        self.assertIn('!hasPackage() && !canApplyBundledUpdate()', source)
        start = source.index('void MobileController::applyBundledUpdate()')
        end = source.index('void MobileController::requestAction', start)
        self.assertIn('m_packagePath.clear()', source[start:end])
        self.assertIn('requestAction("update")', source[start:end])
        self.assertIn('visible: ui.canApplyBundledUpdate', manage)
        self.assertIn('onClicked: ui.applyBundledUpdate()', manage)

    def test_verified_entry_bytes_are_executed_from_a_private_copy(self):
        source = (NATIVE / "src/mobilecontroller.cpp").read_text(encoding="utf-8")
        self.assertIn('m_command.append(entryBytes)', source)
        self.assertIn('entryBytes.contains(boundary)', source)
        self.assertIn('"/var/bb10_mobile_entry_" + newOperationId()', source)
        self.assertIn('"mkdir -m 700 " + shellQuote(privateDir) + " || exit 73', source)
        self.assertIn('shellQuote("!" + privateEntry)', source)
        self.assertIn('shellQuote(privateEntry) + " " + shellQuote(action)', source)
        self.assertIn('shellQuote(bundlePath)', source)
        self.assertNotIn('QProcess::systemEnvironment()', source)
        self.assertNotIn('shellQuote("!" + entry)', source)

    def test_experimental_route_is_separate_and_keeps_explicit_opt_in(self):
        source = (NATIVE / "src/mobilecontroller.cpp").read_text(encoding="utf-8")
        home = (NATIVE / "assets/main.qml").read_text(encoding="utf-8")
        experimental = (NATIVE / "assets/Experimental.qml").read_text(encoding="utf-8")
        self.assertNotIn("legacy-install", home)
        self.assertIn('extra.insert("experimental", true)', source)
        self.assertIn('m_checkedLegacyProfile != m_legacyProfile', source)
        self.assertIn('value: "china-telecom-46011"', experimental)
        for action in ("legacy-inspect", "legacy-install", "legacy-start", "legacy-stop"):
            self.assertIn(action, experimental)

    def test_native_requests_match_runtime_whitelist_and_profiles(self):
        source = (NATIVE / "src/mobilecontroller.cpp").read_text(encoding="utf-8")
        entry = ast.parse((ROOT / "mobile/runtime/entry.py").read_text(encoding="utf-8"))
        accepted = None
        for item in ast.walk(entry):
            if (isinstance(item, ast.Compare) and isinstance(item.left, ast.Call)
                    and isinstance(item.left.func, ast.Name) and item.left.func.id == "set"
                    and item.left.args and isinstance(item.left.args[0], ast.Name)
                    and item.left.args[0].id == "request"
                    and isinstance(item.ops[0], ast.LtE) and isinstance(item.comparators[0], ast.Set)):
                accepted = ast.literal_eval(item.comparators[0])
        self.assertIsNotNone(accepted)
        submitted = set(re.findall(r'(?:request|extra)\.insert\("([a-z_]+)"', source))
        self.assertLessEqual(submitted, accepted)
        worker = ast.parse((ROOT / "mobile/runtime/worker.py").read_text(encoding="utf-8"))
        profiles = next(ast.literal_eval(item.value) for item in worker.body
                        if isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PROFILE_IDS" for t in item.targets))
        experimental = (NATIVE / "assets/Experimental.qml").read_text(encoding="utf-8")
        self.assertEqual(set(re.findall(r'value: "(china-[^"]+)"', experimental)), set(profiles))


if __name__ == "__main__":
    unittest.main()
