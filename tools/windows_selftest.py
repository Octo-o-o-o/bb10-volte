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


def verify_tls_context(context):
    """Check strict TLS even when Windows uses a native trust adapter."""
    import ssl
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    try:
        assert context.cert_store_stats()['x509_ca'] > 0
    except NotImplementedError:
        # Some Windows native-store adapters cannot expose OpenSSL statistics.
        # Check the OS root store instead; do not disable hostname verification
        # or accept an empty/non-server-auth certificate store.
        if sys.platform != 'win32' or not hasattr(ssl, 'enum_certificates'):
            raise
        server_auth = '1.3.6.1.5.5.7.3.1'
        assert any(encoded and kind == 'x509_asn' and
                   (trust is True or isinstance(trust, (set, frozenset)) and server_auth in trust)
                   for encoded, kind, trust in ssl.enum_certificates('ROOT'))


def run(output):
    def no_python_network(event, args):
        if event in ('socket.connect', 'socket.getaddrinfo', 'socket.bind'):
            raise RuntimeError('Packaging self-test must not use the network')
    sys.addaudithook(no_python_network)
    from gui import App
    import ssl
    from fetch_materials import download_ssl_context
    tls = download_ssl_context()
    verify_tls_context(tls)
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
    from mobile_app_gui import MobileAppInstallWindow
    from mobile_app_install import release as mobile_app_release
    app_pin = mobile_app_release()
    assert app_pin['version'] == json.loads((bundle / 'project.json').read_text(encoding='utf-8'))['mobile_version']
    class NoPhoneInstaller:
        def inspect(self):
            raise AssertionError('No phone action allowed in packaging self-test')
        install = inspect
    phone_app = MobileAppInstallWindow(root, 'offline-selftest', '')
    phone_app.window.attributes('-alpha', 0.0)
    phone_app.installer = NoPhoneInstaller()
    assert str(phone_app.install_button.cget('state')) == 'disabled'
    phone_app.events.put(('result', ('install', {'schema': 1, 'state': 'pending', 'can_install': False})))
    phone_app.window.after_cancel(phone_app.poll_job)
    phone_app.poll()
    assert phone_app.title.cget('text') == tr('正在核对同一安装任务')
    assert str(phone_app.install_button.cget('state')) == 'disabled'
    assert phone_app.recheck_job is not None
    phone_app.close()
    assert not phone_app.window.winfo_exists()
    import variant_trials
    from variant_trial_gui import VariantTrialDialog
    assert variant_trials.plan('SQC100-5', 'unicom')['route'] == 'automatic_supported'
    assert variant_trials.plan('SQC100-3', 'unicom')['route'] == 'automatic_supported'
    assert variant_trials.plan('SQC100-4', 'mobile')['route'] == 'automatic_supported'
    trial = VariantTrialDialog(root, lambda _: (_ for _ in ()).throw(AssertionError('No phone action allowed')))
    trial.attributes('-alpha', 0.0)
    trial.variant.set('SQW100-1')
    trial.operator.set(tr('中国联通'))
    assert trial.decision()['route'] == 'automatic_supported'
    trial.operator.set(tr('中国电信'))
    assert trial.decision()['route'] == 'automatic_supported'
    trial.destroy()
    from feedback import Journal, write_bundle
    from feedback_gui import FeedbackDialog
    import zipfile
    previous_journal = root._feedback_journal
    with tempfile.TemporaryDirectory() as feedback_folder:
        root._feedback_journal = Journal(feedback_folder)
        root._feedback_journal.record('trials', 'preflight', 'needs_attention', details={
            'variant_trial': {'variant': 'SQC100-3', 'operator': 'unicom', 'automatic_start': False,
                              'hardware_acceptance': 'not_established'},
            'checks': [{'id': 'trial_native', 'status': 'block', 'code': 'trial_six_native_hashes_required'}]})
        feedback = FeedbackDialog(root, 'trials')
        feedback.withdraw()
        feedback.note.insert('1.0', 'offline packaged feedback check')
        feedback.preview()
        feedback_path = Path(feedback_folder) / 'feedback.zip'
        write_bundle(feedback_path, feedback.payload)
        with zipfile.ZipFile(feedback_path) as archive:
            assert set(archive.namelist()) == {'feedback.json', 'timeline.txt', 'README.txt'}
            exported = json.loads(archive.read('feedback.json'))
            assert exported['limits']['automatic_upload'] is False
            assert exported['sessions'][-1]['events'][0]['details']['variant_trial']['variant'] == 'SQC100-3'
        feedback.close()
    root._feedback_journal = previous_journal
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
    assert str(automatic.completion_button.cget('state')) == 'disabled'
    assert automatic.completion_dialog is None
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
    assert str(automatic.completion_button.cget('state')) == 'normal'
    assert automatic.completion_dialog is None
    automatic.completion_button.invoke()
    assert automatic.completion_dialog.winfo_exists()
    automatic.completion_dialog.done_button.invoke()
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
    assert wizard.copy_domestic_download_button.cget('command')
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
        wizard.usb = {'usb_count': 1, 'device': {'ModelName': variant, 'PlatformVersion': '10.3.3.3216'}}
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
        assert str(wizard.prepare_button.cget('state')) == 'normal'
        assert str(wizard.copy_domestic_download_button.cget('state')) == 'normal'
        from root_images import recipe
        stock, expected = recipe(variant)
        assert stock['id'] == item['id'] == expected['firmware_id']
        assert stock['extracted_sha256'] == expected['stock_sha256']
        wizard.imported_variant = variant
        wizard.ack.set(True)
        assert str(wizard.flash_button.cget('state')) == 'disabled'
        assert variant in wizard.root_hint.cget('text')
        assert tr('自动准备 Root 镜像') in wizard.root_hint.cget('text')
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
    from firmware_gui import FirmwareDialog
    from firmware_upgrade import stock_images
    from firmware_policy import assess_version
    from root_setup import stock_firmware
    from pairing_instructions import phone_commands
    firmware = FirmwareDialog(root, lambda *_: None,
        usb={'usb_count': 1, 'device': {'ModelName': 'SQW100-4', 'PlatformVersion': '10.3.3.2205'}})
    firmware.withdraw()
    assert str(firmware.upgrade_button.cget('state')) == 'disabled'
    assert str(firmware.root_button.cget('state')) == 'disabled'
    firmware.close()
    assert assess_version('10.3.3.2205').state == 'upgrade'
    assert assess_version('10.3.3.9999').state == 'newer'
    for variant in ('SQN100-3', 'SQC100-2', 'SQW100-4'):
        assert set(stock_images(stock_firmware(variant))) == {'stock_os', 'stock_radio'}
    commands = phone_commands('bb10-pair-abcdef123456.py')
    assert 'ROOT_REQUIRED' in commands and 'PAIR_FILE_NOT_FOUND' in commands and ' &&\n' in commands
    assert (bundle / 'tools/phone_pairing.py').is_file()
    # Map an invisible minimum-sized window so Tk computes actual geometry.
    # Check that the complete action row and status stay inside the viewport.
    root.attributes('-alpha', 0.0)
    root.geometry('960x700')
    root.deiconify()
    from ui_responsiveness import measure
    ui_responsiveness = {}
    if sys.platform == 'win32':
        ui_responsiveness['main_resize'] = measure(root, action=lambda count:
            root.geometry('{}x700'.format(960 + count % 10 * 4)))
        root.geometry('960x700')
        # Constructors alone do not paint withdrawn windows. Exercise the
        # actual connection/Root pages and their progress animation offline.
        connection = ConnectionDialog(root, lambda *_: None, auto_check=False)
        connection.attributes('-alpha', 0.0)
        connection.progress.pack(fill='x')
        connection.progress.start()
        ui_responsiveness['connection_resize'] = measure(connection, action=lambda count:
            connection.geometry('{}x650'.format(790 + count % 10 * 4)))
        connection.progress.stop()
        connection.close()
        wizard = SetupWizard(root, lambda *_: None, auto_check=False)
        wizard.attributes('-alpha', 0.0)
        wizard.progress.start()
        ui_responsiveness['root_tabs'] = measure(wizard, action=lambda count:
            wizard.tabs.select((count // 5) % len(wizard.tabs.tabs())))
        wizard.progress.stop()
        wizard.close()
        for sample in ui_responsiveness.values():
            assert sample['samples'] >= 10 and sample['p95_gap_ms'] < 250, sample
            assert sample['max_gap_ms'] < 750, sample
    root.update()
    visible_buttons = [button for button in app.buttons.values() if button.winfo_manager()]
    for widget in visible_buttons + [app.activity, app.setup_button]:
        x = widget.winfo_rootx() - root.winfo_rootx()
        y = widget.winfo_rooty() - root.winfo_rooty()
        assert widget.winfo_width() > 1 and widget.winfo_height() > 1
        assert x >= 0 and y >= 0 and x + widget.winfo_width() <= root.winfo_width()
        assert y + widget.winfo_height() <= root.winfo_height()
    assert all(button.winfo_width() >= 100 for button in visible_buttons)
    # The optional receipt UI must load inside the frozen app without Pillow
    # or a network client. Exercise every installed amount/provider resource.
    from completion_dialog import CompletionDialog
    from support_config import AMOUNTS, PROVIDERS, QR_FILES, SUPPORT_ICON
    assert (bundle / SUPPORT_ICON).is_file()
    completion = CompletionDialog(root)
    assert not completion.payment.winfo_manager()
    completion.toggle_coffee()
    receipt_images_verified = []
    for provider in PROVIDERS:
        for amount in AMOUNTS:
            name = QR_FILES[provider][amount]
            assert (bundle / name).is_file()
            if (bundle / name).is_file():
                completion.provider.set(provider)
                completion.amount.set(amount)
                completion.update_receipt()
                assert completion.qr_image is not None
                assert 48 < completion.qr_image.width() <= 264
                assert 48 < completion.qr_image.height() <= 264
                receipt_images_verified.append(name)
    from unittest.mock import patch
    from support_config import OCTOLAB_URL, PROJECT_WEBSITE_URL
    copied = []
    with patch.object(completion, 'clipboard_clear'), patch.object(completion, 'clipboard_append', side_effect=copied.append), patch('completion_dialog.webbrowser.open') as browser:
        for language in ('zh', 'en'):
            with patch.object(i18n, 'LANGUAGE', language):
                completion.copy_share()
        assert len(copied) == 2 and copied[0] != copied[1]
        assert all(PROJECT_WEBSITE_URL in value for value in copied)
        browser.assert_not_called()
        completion.brand_button.invoke()
        browser.assert_called_once_with(OCTOLAB_URL)
    completion.done_button.invoke()
    assert not completion.winfo_exists()
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
              'mobile_app_provisioning_ui_and_pending_task_verified': True,
              'mobile_app_complete_bar_pin_and_helper_verified': True,
              'mobile_app_target_version': app_pin['version'],
              'candidate_trial_selection_verified': True, 'local_feedback_ui_and_zip_verified': True,
              'download_tls_verification_and_ca_store_verified': True,
              'firmware_upgrade_ui_and_stock_catalog_verified': True,
              'pairing_shell_guards_bundled': True,
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
              'domestic_copy_link_ui_verified': True,
              'q20_passport_root_preparation_enabled': True,
              'model_bound_root_recipes_verified': True,
              'import_requires_root_image_preparation_verified': True,
              'baidu_backup_download_ui_verified': True,
              'offline_material_import_verified': True,
              'existing_root_recovery_ui_verified': True,
              'connection_help_ui_verified': True,
              'phone_pairing_resource_present': True,
              'root_probe_resource_verified': True,
              'minimum_window_actions_visible': True,
              'shared_control_theme_loaded': True,
              'ui_responsiveness': ui_responsiveness,
              'system_language_and_translations_verified': True,
              'persistent_state_outside_bundle': not private_root().is_relative_to(bundle),
              'python_network_disabled_during_selftest': True,
              'completion_page_verified': True, 'support_brand_icon_present': True,
              'receipt_images_verified': receipt_images_verified,
              'localized_share_and_octolab_link_verified': True,
              'automatic_carrier_completion_gate_verified': True,
              'phone_contacted': False}
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return 0
