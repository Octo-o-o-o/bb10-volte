"""Offline packaged-runtime smoke test; never contacts or changes a phone."""
import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tkinter as tk
import tempfile
from tkinter import ttk

from desktop_paths import frozen, private_root, resource_root
from workflow import Client, verify_package, verify_diagnostics, CREATE_NO_WINDOW
from profile_editor import presets, ProfileEditor
from setup_wizard import SetupWizard
from recovery_gui import RecoveryDialog
from connection_dialog import ConnectionDialog
from i18n import tr


def run(output):
    def no_python_network(event, args):
        if event in ('socket.connect', 'socket.getaddrinfo', 'socket.bind'):
            raise RuntimeError('Packaging self-test must not use the network')
    sys.addaudithook(no_python_network)
    from gui import App
    import i18n
    assert i18n.language_from_tag('zh-Hant') == 'zh'
    assert i18n.language_from_tag('ja-JP') == 'en'
    assert i18n.language_from_tag(None) == 'zh'
    assert i18n.ENGLISH['连接手机'] == 'Connect phone'
    bundle = resource_root()
    manifest = verify_package()
    verify_diagnostics()
    import compatibility
    telecom = next(profile for profile in presets() if profile['id'] == 'china-telecom')
    assert set(telecom['carrier']['data_apns']) == {'ctnet', 'ctlte'}
    snapshot = {'apn_matches': True, 'data_connected': False, 'observed_data_apn': 'ctlte',
                'network_service': 2098186}
    assert compatibility.network_checks(snapshot, telecom)[-1]['code'] == 'data_apn_disconnected'
    assert compatibility.public_network_diagnostics(snapshot)['data_connected'] is False
    snapshot.update(data_connected=True, network_service=33555457)
    assert compatibility.network_checks(snapshot, telecom)[-1]['code'] == 'data_network_emergency_only'
    assert compatibility.public_network_diagnostics(snapshot)['emergency_service'] is True
    assert compatibility.public_network_diagnostics(snapshot)['lte_data_service'] is False
    assert set(compatibility.public_flags({}, compatibility.CONFIGURATION_FLAGS)) == set(compatibility.CONFIGURATION_FLAGS)
    from diagnostic_details import baseline_rows
    diagnostic_fixture = {'checks': [{'id': 'baseline', 'status': 'wait', 'code': 'baseline_not_clean'}],
                          'installation': {'state': 'absent'}, 'baseline': {'voice_policy': 3}}
    voice = next(row for row in baseline_rows(diagnostic_fixture) if row['id'] == 'voice_policy')
    assert voice['problem'] and voice['actual'] == '3' and voice['expected'] == '0'
    assert tr('未检测到本工具安装；请核对已有设置的来源，并提供排查摘要。') in voice['detail']
    root = tk.Tk()
    root.withdraw()
    app = App(root)
    assert ttk.Style(root).theme_use() == 'bb10'
    from auto_carrier import verify_package as verify_auto_package
    from auto_carrier_gui import AutoCarrierWindow
    auto_manifest = verify_auto_package()
    acceptance = json.loads((bundle / 'materials/unified-carrier-acceptance.json').read_text(encoding='utf-8'))
    assert acceptance['private_phone_identifiers_or_logs_included'] is False
    assert acceptance['functional_combinations_total'] == 9
    automatic = AutoCarrierWindow(root, 'bb10-root', '')
    automatic.window.attributes('-alpha', 0.0)
    automatic.window.update()
    assert str(automatic.buttons['install'].cget('state')) == 'disabled'
    automatic.report = {'installed': True, 'status': {'enabled': False}}
    automatic.refresh()
    assert str(automatic.buttons['enable'].cget('state')) == 'normal'
    assert str(automatic.buttons['disable'].cget('state')) == 'disabled'
    automatic.report = {'installed': True, 'update_available': True, 'can_update': True, 'update_pending': True}
    automatic.refresh()
    assert str(automatic.buttons['install'].cget('state')) == 'normal'
    assert automatic.buttons['install'].cget('text') == tr('更新自动适配')
    assert str(automatic.buttons['status'].cget('state')) == 'disabled'
    # Exercise the actual frozen UI without touching a phone or a connection.
    reboot = {'phase': 'carrier_reboot_required', 'enabled': True,
              'status_from_current_boot': True, 'selected_this_boot': True,
              'selected_operator': 'telecom', 'manager_alive': False, 'native_alive': False,
              'current': {'ims': None, 'register_status': '200 OK', 'ran': 'LTE', 'radio': ['lte']}}
    automatic.window.after_cancel(automatic.poll_job)
    automatic.events.put(('probe', {'variant': 'SQW100-4', 'installed': True, 'status': reboot}, None))
    automatic.poll()
    assert automatic.status.cget('text') == tr('还需一次正常重启，适配尚未完成')
    assert automatic.buttons['status'].cget('text') == tr('已重启，重新检查')
    assert '200 OK' not in automatic.details.get('1.0', 'end')
    automatic.window.update_idletasks()
    for widget in list(automatic.buttons.values()) + [automatic.status, automatic.details]:
        x = widget.winfo_rootx() - automatic.window.winfo_rootx()
        y = widget.winfo_rooty() - automatic.window.winfo_rooty()
        assert 0 <= x and x + widget.winfo_width() <= automatic.window.winfo_width()
        assert 0 <= y and y + widget.winfo_height() <= automatic.window.winfo_height()
    ready = dict(reboot, phase='running', manager_alive=True, native_alive=True,
                 current={'ims': 'connected', 'register_status': '200 OK', 'ran': 'LTE', 'radio': ['lte']})
    automatic.window.after_cancel(automatic.poll_job)
    automatic.events.put(('status', ready, None))
    automatic.poll()
    assert automatic.status.cget('text') == tr('本次开机注册成功，请验收通话')
    assert automatic.buttons['status'].cget('text') == tr('刷新状态')
    automatic.close()
    editor = ProfileEditor(root, app.profile, app.set_profile)
    editor.withdraw()
    assert editor.value() == app.profile
    manual_telecom = next(profile for profile in presets() if profile['id'] == 'china-telecom-46011-data-centric')
    editor.populate(manual_telecom)
    assert editor.value() == manual_telecom and editor.value()['runtime']['autostart'] is False
    editor.destroy()
    from q20_managed import bundle as q20_bundle
    q20_spec, q20_probe = q20_bundle()
    assert q20_probe.is_file() and q20_spec['variant'] == 'SQC100-2'
    wizard = SetupWizard(root, lambda *_: None, auto_check=False)
    wizard.withdraw()
    assert not wizard.busy and wizard.choice is None
    assert wizard.browser_download_button.cget('command')
    assert wizard.browse_firmware_button.cget('command')
    assert wizard.import_firmware_button.cget('command')
    assert wizard.backup_download_button.cget('command')
    assert wizard.copy_backup_download_button.cget('command')
    assert wizard.firmware_urls == []
    assert str(wizard.download_firmware_button.cget('state')) == 'disabled'
    wizard.variant.set('SQN100-3')
    assert len(wizard.firmware_urls) == 3
    assert str(wizard.domestic_download_button.cget('state')) == 'normal'
    assert str(wizard.backup_download_button.cget('state')) == 'normal'
    assert str(wizard.copy_backup_download_button.cget('state')) == 'normal'
    assert str(wizard.firmware_source.cget('state')) == 'readonly'
    wizard.firmware_source.current(1)
    assert wizard.firmware_source.get() == 'ia600407.us.archive.org'
    from root_setup import stock_firmware, selected_firmware_variant, SetupError
    for variant, family in [('SQC100-2', 'classic'), ('SQW100-4', 'passport')]:
        wizard.usb = {'usb_count': 1, 'device': {'ModelName': variant}}
        wizard.variant.set(variant)
        item = stock_firmware(variant)
        assert item['family'] == family
        assert item['file'] in wizard.firmware_label.cget('text')
        assert wizard.firmware_urls[0] == item['url']
        assert item['manual_download_url'] not in wizard.firmware_urls
        backup_url = item['backup_manual_download_url']
        assert str(wizard.backup_download_button.cget('state')) == 'normal'
        assert str(wizard.copy_backup_download_button.cget('state')) == 'normal'
        assert backup_url not in wizard.firmware_urls
        assert item['backup_manual_download_code'] in wizard.backup_download_hint.cget('text')
        assert str(wizard.domestic_download_button.cget('state')) == 'normal'
        assert str(wizard.download_firmware_button.cget('state')) == 'normal'
        assert str(wizard.prepare_button.cget('state')) == 'disabled'
        try:
            selected_firmware_variant('SQN100-3', wizard.usb)
        except SetupError as error:
            assert str(error) == 'firmware_model_mismatch'
        else:
            raise AssertionError('Wrong-model firmware selection was accepted')
    wizard.usb = {'usb_count': 2, 'device': {'ModelName': 'SQN100-3'}}
    wizard.variant.set('')
    assert wizard.firmware_urls == []
    assert str(wizard.download_firmware_button.cget('state')) == 'disabled'
    assert str(wizard.backup_download_button.cget('state')) == 'disabled'
    wizard.close()
    from fetch_materials import import_material, fetch_entries
    # Verify the bundled importer under the network-denying audit hook.
    with tempfile.TemporaryDirectory() as folder:
        scratch = Path(folder)
        source = scratch / 'browser-copy (1).7z'
        source.write_bytes(b'offline import packaging fixture')
        item = {'file': 'pinned-fixture.7z', 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
        imported = import_material(item, source, scratch / 'cache', lambda _: None)
        assert imported.read_bytes() == source.read_bytes()
        fetch_entries([item], scratch / 'cache', lambda _: None, verify_only=True)
    connection = ConnectionDialog(root, lambda *_: None, auto_check=False)
    connection.withdraw()
    assert not connection.busy and connection.choice is None
    assert str(connection.continue_button.cget('state')) == 'disabled'
    connection.close()
    recovery = RecoveryDialog(root, lambda *_: None)
    recovery.withdraw()
    assert not recovery.busy and not recovery.verified and len(recovery.tabs.tabs()) == 2
    recovery.close()
    assert (bundle / 'tools/phone_pairing.py').is_file()
    # Map an invisible minimum-sized window so Tk computes actual geometry.
    # Check that the complete action row and status stay inside the viewport.
    root.attributes('-alpha', 0.0)
    root.geometry('960x700')
    root.deiconify()
    root.update()
    visible_buttons = [button for button in app.buttons.values() if button.winfo_manager()]
    for widget in visible_buttons + [app.activity, app.setup_button]:
        x = widget.winfo_rootx() - root.winfo_rootx()
        y = widget.winfo_rooty() - root.winfo_rooty()
        assert widget.winfo_width() > 1 and widget.winfo_height() > 1
        assert x >= 0 and y >= 0 and x + widget.winfo_width() <= root.winfo_width()
        assert y + widget.winfo_height() <= root.winfo_height()
    assert all(button.winfo_width() >= 100 for button in visible_buttons)
    tcl, tk_version = root.tk.call('info', 'patchlevel'), root.tk.call('package', 'provide', 'Tk')
    app.close()
    client = Client()
    ssh = subprocess.run([client.ssh, '-V'], capture_output=True, text=True, timeout=15,
                         creationflags=CREATE_NO_WINDOW)
    scp = subprocess.run([client.scp], capture_output=True, text=True, timeout=15,
                         creationflags=CREATE_NO_WINDOW)
    assert ssh.returncode == 0 and 'OpenSSH' in ssh.stderr
    assert scp.returncode == 1 and 'usage:' in scp.stderr
    assert (bundle / 'docs/GUI.md').is_file()
    from community_research import catalog
    assert catalog()['project_acceptance'] == 'not_established'
    assert (bundle / 'docs/COMMUNITY-RESEARCH.md').is_file()
    assert (bundle / 'tools/stage_cleanup.py').is_file()
    transferred = []
    def local_transfer(args, timeout):
        source = resource_root() / args[-2]
        assert source.is_file()
        transferred.append(source)
        return ''
    # Exercise the frozen staging paths without invoking a transport operation.
    client.remote = lambda *args: ''
    client.process = local_transfer
    client.execute = lambda *args: {'stage_removed': True}
    with client.stage():
        pass
    assert bundle / 'tools/stage_cleanup.py' in transferred
    assert len(transferred) == 11
    with client.stage(diagnostic='root'):
        pass
    assert bundle / 'tools/root_probe.py' in transferred
    assert len(transferred) == 14
    if frozen():
        assert (bundle / 'licenses/THIRD-PARTY-NOTICES.txt').stat().st_size > 1000
        assert (bundle / 'assets/app.ico').is_file()
        assert not private_root().is_relative_to(bundle)
    result = {'passed': True, 'version': manifest['version'], 'frozen': frozen(),
              'desktop_revision': json.loads((bundle / 'project.json').read_text(encoding='utf-8')).get('desktop_revision'),
              'python': sys.version.split()[0], 'tcl': tcl, 'tk': tk_version,
              'python_on_path': bool(shutil.which('python')),
              'system_ssh_on_path': bool(shutil.which('ssh')),
              'bundled_ssh': client.ssh.startswith(str(bundle / 'vendor/openssh')),
              'ssh_version': ssh.stderr.strip(), 'scp_available': True,
              'payload_files_verified': len(manifest['files']),
              'automatic_carrier_payload_files_verified': len(auto_manifest['files']),
              'automatic_carrier_management_ui_verified': True,
              'automatic_carrier_extra_reboot_workflow_verified': True,
              'qnx_stage_cleanup_resource_present': True,
              'offline_staging_inputs_verified': len(transferred),
              'profiles_loaded': len(presets()), 'editor_roundtrip': True,
              'telecom_manual_profile_roundtrip': True, 'q20_managed_adapter_bundle_verified': True,
              'telecom_ctlte_and_diagnostic_gates_verified': True,
              'baseline_detail_explanations_verified': True,
              'first_run_wizard_without_probe_verified': True,
              'manual_firmware_import_ui_verified': True,
              'firmware_mirror_selection_ui_verified': True,
              'device_firmware_routing_verified': True,
              'firmware_without_q10_default_verified': True,
              'domestic_manual_download_ui_verified': True,
              'baidu_backup_download_ui_verified': True,
              'offline_material_import_verified': True,
              'existing_root_recovery_ui_verified': True,
              'connection_help_ui_verified': True,
              'phone_pairing_resource_present': True,
              'root_probe_resource_verified': True,
              'minimum_window_actions_visible': True,
              'shared_control_theme_loaded': True,
              'system_language_and_translations_verified': True,
              'persistent_state_outside_bundle': not private_root().is_relative_to(bundle),
              'python_network_disabled_during_selftest': True,
              'phone_contacted': False}
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return 0
