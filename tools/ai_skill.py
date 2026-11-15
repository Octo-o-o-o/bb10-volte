"""Headless JSON CLI for AI coding agents to identify and operate BB10 devices.

Built on the audited desktop/device modules without bypassing model, OS, hash,
backup, host-key or destructive-operation confirmation gates. Device passwords,
private keys, SIM identifiers and phone numbers are never accepted on the
command line or emitted in output.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys

if not hasattr(Path, 'is_junction'):
    def _path_is_junction(self):
        if os.name != 'nt':
            return False
        try:
            st = os.lstat(self)
        except OSError:
            return False
        return bool(getattr(st, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)) and not stat.S_ISLNK(st.st_mode)

    Path.is_junction = _path_is_junction

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
for _entry in (str(TOOLS_DIR), str(REPO_ROOT / 'device')):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import i18n
from desktop_paths import private_root, resource_root
import carrier_policy
import device_info
import device_support
import connection
import connection_flow
import connection_materials
import connection_recovery
import firmware_policy
import firmware_upgrade
import pairing_instructions
import root_setup
from auto_carrier import AutoClient
from auto_carrier_view import registration_ready, status_view
from mobile_app_install import BUNDLED_BAR, MobileAppInstaller, bundled_bar, release as mobile_release
from workflow import WorkflowError, public_status

FAMILY_ALIASES = {
    'q10': 'q10',
    'sqn100': 'q10',
    'q20': 'classic',
    'classic': 'classic',
    'sqc100': 'classic',
    'q30': 'passport',
    'passport': 'passport',
    'sqw100': 'passport',
    'p9983': 'p9983',
    '9983': 'p9983',
    'sqk100': 'p9983',
}

SAFE_DISCOVERY_KEYS = (
    'OsType',
    'ModelName',
    'PlatformVersion',
    'DeveloperModeEnabled',
    'OobeCompleted',
)

SAFE_PROBE_KEYS = (
    'schema',
    'management_schema',
    'installed_management_schema',
    'variant',
    'family',
    'os_version',
    'board_type',
    'installed',
    'installed_stage',
    'installation_pending',
    'pending_phase',
    'update_available',
    'update_pending',
    'can_install',
    'can_update',
    'can_prepare_mobile_network',
    'call_idle',
    'sim_supported',
    'sim_reason',
    'sim_plmn',
    'operator',
    'stock_template_verified',
    'mobile_network_off',
    'reboot_required',
    'uninstalled',
    'root_kind',
    'legacy_detected',
    'scope_error',
    'normal_reboot_after_sim_change',
)

SAFE_MOBILE_APP_KEYS = (
    'schema',
    'state',
    'can_install',
    'installed_version',
    'target_version',
    'up_to_date',
    'installed_files_verified',
    'reason',
)


def configure_stdio():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            try:
                stream.reconfigure(encoding='utf-8', errors='replace')
            except (OSError, ValueError):
                pass


def set_language(lang):
    if lang in ('zh', 'en'):
        i18n.LANGUAGE = lang


def project_metadata():
    return json.loads((resource_root() / 'project.json').read_text(encoding='utf-8'))


def normalize_variant(raw):
    if not raw:
        return None, None
    cleaned = re.sub(r'\s+', '', str(raw).strip())
    upper = cleaned.upper()
    if upper in carrier_policy.MODELS:
        return upper, None
    compact = re.sub(r'[^A-Za-z0-9]', '', cleaned).lower()
    if compact in FAMILY_ALIASES:
        return None, FAMILY_ALIASES[compact]
    match = re.fullmatch(r'(sq[ncwk]100)([0-9]+)', compact)
    if match:
        candidate = match.group(1).upper() + '-' + match.group(2)
        if candidate in carrier_policy.MODELS:
            return candidate, None
    return upper, None


def variant_entry(variant):
    family, pinned_board = carrier_policy.MODELS[variant]
    support_row = device_support.catalog().get(variant, {})
    evidence_row = device_support.evidence_catalog().get(variant, {})
    assessment = device_support.assess(variant)
    auto_root_variants = set(root_setup.catalog().get('auto_root_variants', ()))
    stock = None
    if variant in auto_root_variants:
        try:
            fw = root_setup.stock_firmware(variant)
            stock = {
                'firmware_id': fw['id'],
                'archive_file': fw['file'],
                'archive_sha256': fw['sha256'],
                'extracted_file': fw['extracted_file'],
                'extracted_sha256': fw['extracted_sha256'],
            }
        except root_setup.SetupError:
            stock = None
    special_notes = []
    if family == 'passport':
        special_notes.append(
            'Passport switching between China Unicom (ue_usage=0) and China Mobile/Telecom (ue_usage=1) requires '
            'one extra normal power-menu reboot when phase is carrier_reboot_required; live io-pkt provider restart '
            'is intentionally disabled.'
        )
    if variant == 'SQK100-2':
        special_notes.append(
            'Open for unified 3-carrier VoLTE and mobile app when already rooted on 10.3.3.3216 with matching '
            'native files; no verified local first-flash Root recipe is bundled.'
        )
    if variant == 'SQW100-2':
        special_notes.append(
            'Production hardware identity for SQW100-2 remains unconfirmed in official certification listings; '
            'entry stays open if a real unit matches 10.3.3.3216 and native hashes.'
        )
    if variant == 'SQC100-4':
        special_notes.append(
            'Windows Root preparation automatically appends UseDNS=no to sshd_config to prevent mobile-data '
            'pre-auth SSH stalls observed on SQC100-4.'
        )
    return {
        'variant': variant,
        'family': family,
        'display_name': device_info.FAMILIES[family]['name'],
        'required_os': carrier_policy.OS_VERSION,
        'pinned_board_type': pinned_board,
        'identity_documented': bool(support_row.get('identity_documented')),
        'china_fdd_lte_bands': list(support_row.get('china_fdd_bands') or []),
        'radio_band_overlap_operators': list(support_row.get('radio_candidate_operators') or []),
        'volte_admitted_operators': assessment['candidate_operators'],
        'volte_admitted_plmns': assessment['admitted_home_plmns'],
        'historical_evidence_status': evidence_row.get('status', {}),
        'note': (evidence_row.get('note') or {}).get(i18n.LANGUAGE, ''),
        'auto_root_recipe_supported': variant in auto_root_variants,
        'stock_3216_firmware': stock,
        'special_notes': special_notes,
    }


def sanitize_probe(raw):
    if not isinstance(raw, dict):
        return {}
    out = {key: raw[key] for key in SAFE_PROBE_KEYS if key in raw}
    if isinstance(raw.get('stock_template'), dict):
        tpl = raw['stock_template']
        out['stock_template'] = {
            k: tpl[k]
            for k in ('path', 'sha256', 'fallback_used', 'original_preloaded_config')
            if k in tpl
        }
    if isinstance(raw.get('status'), dict):
        out['status'] = public_status(raw['status'])
        view = status_view(out['status'])
        out['registration_ready'] = registration_ready(out['status'])
        out['status_view'] = {
            'ready': view['ready'],
            'check_code': view['check_code'],
            'title': view['title'],
            'guidance': view['guidance'],
        }
    note = device_support.report_note(raw)
    if note:
        out['blocker_explanation'] = note
    return out


def sanitize_mobile_app(raw):
    if not isinstance(raw, dict):
        return {}
    out = {key: raw[key] for key in SAFE_MOBILE_APP_KEYS if key in raw}
    if isinstance(raw.get('installed'), dict):
        inst = raw['installed']
        out['installed'] = {
            k: inst[k]
            for k in ('state', 'version', 'can_install', 'up_to_date', 'files_verified')
            if k in inst
        }
    return out


def synthesize_next_step(usb, os_state, discovery, root_verified, ssh_error, probe, mobile_app):
    usb_count = usb.get('usb_count')
    if isinstance(usb_count, int) and usb_count > 1:
        return {
            'code': 'disconnect_extra_devices',
            'summary': i18n.tr('检测到多台黑莓 USB 设备，请先拔掉其他黑莓手机，仅保留当前操作的一台后再运行 detect。'),
            'destructive': False,
        }
    if root_verified and isinstance(probe, dict):
        if probe.get('scope_error'):
            return {
                'code': 'blocked_by_device_scope',
                'reason': probe['scope_error'],
                'summary': device_support.report_note(probe) or probe['scope_error'],
                'destructive': False,
            }
        status = probe.get('status') or {}
        view = probe.get('status_view') or {}
        if probe.get('registration_ready') is True:
            return {
                'code': 'ready_for_manual_call_sms_acceptance',
                'summary': (
                    'VoLTE is registered on LTE in the current boot (200 OK). Unplug USB and ask the human owner '
                    'to place outbound and inbound calls (>= 00:35 connected audio each), verify LTE retention, and test SMS.'
                ),
                'destructive': False,
            }
        if probe.get('reboot_required') or view.get('check_code') in (
            'unified_reboot_required',
            'unified_carrier_reboot_required',
            'unified_sim_changed',
        ):
            return {
                'code': view.get('check_code') or 'normal_reboot_required',
                'summary': view.get('guidance') or 'Use the phone power menu to restart normally, unlock, wait 3-5 minutes, then run `volte status`.',
                'destructive': False,
            }
        if probe.get('installed') and status.get('enabled') is True and status.get('status_from_current_boot') is not True:
            return {
                'code': 'normal_reboot_or_wait_boot_status',
                'summary': view.get('guidance') or 'Restart normally from the phone power menu, unlock, wait 3-5 minutes, then run `volte status`.',
                'destructive': False,
            }
        if probe.get('update_available'):
            if probe.get('can_update'):
                return {
                    'code': 'install_in_place_update',
                    'summary': 'A verified unified-service update is ready. Run `volte install` (and optionally `mobile-app install`), then restart normally.',
                    'destructive': False,
                }
            return {
                'code': 'stop_and_reboot_before_update',
                'summary': 'An older payload is currently active. Run `volte disable`, ask the owner to restart normally from the power menu, then run `volte install`.',
                'destructive': False,
            }
        if not probe.get('installed'):
            if probe.get('sim_supported') is False:
                return {
                    'code': 'install_mobile_app_or_prepare_sim',
                    'reason': probe.get('sim_reason'),
                    'summary': (
                        'Root and OS 10.3.3.3216 are verified, so you can already run `mobile-app install` ('
                        + str(project_metadata().get('mobile_version', ''))
                        + ') for standalone on-phone management. Direct desktop `volte install` requires a ready '
                        'China Mobile/Unicom/Telecom USIM (reason: '
                        + str(probe.get('sim_reason')) + ').'
                    ),
                    'destructive': False,
                }
            if probe.get('can_install') or probe.get('can_prepare_mobile_network'):
                return {
                    'code': 'ready_to_install_volte_and_mobile_app',
                    'summary': (
                        'Device passed Root UID 0, OS 10.3.3.3216, native ABI hashes and SIM checks. '
                        'Run `mobile-app install` to install/update the on-phone app and/or `volte install` to back up original configs and activate 3-carrier VoLTE.'
                    ),
                    'destructive': False,
                }
        installed_app = (mobile_app or {}).get('installed') or {}
        if installed_app.get('up_to_date') is False and (mobile_app or {}).get('can_install') is not False:
            return {
                'code': 'optional_mobile_app_update',
                'summary': 'Unified VoLTE is already installed; you may optionally update the on-phone BB10 VoLTE app via `mobile-app install` or check registration via `volte status`.',
                'destructive': False,
            }
        return {
            'code': 'inspect_volte_status',
            'summary': view.get('guidance') or 'Run `volte status` to monitor current-boot IMS registration.',
            'destructive': False,
        }

    if os_state.state == 'upgrade':
        return {
            'code': 'upgrade_os_to_3216',
            'summary': (
                f'Phone OS is {os_state.current}, below required baseline {os_state.target}. '
                'Ask the owner for explicit data-wipe confirmation, run `firmware prepare-upgrade --variant <VARIANT>`, '
                'flash stock 10.3.3.3216, verify boot (`firmware verify-upgrade-boot`), complete OOBE, then flash Root.'
            ),
            'destructive': True,
        }
    if os_state.state == 'newer':
        return {
            'code': 'unsupported_newer_os',
            'summary': f'Phone OS is {os_state.current} (newer than baseline {os_state.target}). Do not auto-downgrade; stop and inspect firmware baseline.',
            'destructive': False,
        }
    if discovery.get('OobeCompleted') == '0':
        return {
            'code': 'complete_initial_oobe_setup',
            'summary': (
                'Phone reports OobeCompleted=0 (initial BB10 setup not finished). Ask the owner to finish initial setup on the phone '
                'and enable Development Mode before pairing or installing. Do not infer that the phone is unrooted.'
            ),
            'destructive': False,
        }
    if discovery.get('DeveloperModeEnabled') == '0':
        return {
            'code': 'enable_developer_mode',
            'summary': 'Enable Settings -> Security and Privacy -> Development Mode on the phone while keeping USB connected, then re-run `detect`.',
            'destructive': False,
        }
    if not discovery and usb.get('usb_present') is False:
        return {
            'code': 'connect_usb_or_check_cable',
            'summary': (
                'No BlackBerry 10 USB device (VID 0x0FCA) detected. Connect one unlocked BB10 phone with a data-capable USB cable. '
                'Note: if this is a BlackBerry Passport flashed to Android 11 (LineageOS 18.1), use https://github.com/Octo-o-o-o/qcom32-volte instead.'
            ),
            'destructive': False,
        }
    if not discovery and usb.get('usb_network') is False:
        return {
            'code': 'prepare_and_install_usb_driver',
            'summary': 'BlackBerry USB hardware is present, but the USB network link is inactive. Unlock the phone; on Windows run `firmware prepare-driver` and `firmware install-driver` if drivers are missing.',
            'destructive': False,
        }
    return {
        'code': 'connect_existing_root_or_prepare_first_root',
        'ssh_error': ssh_error,
        'summary': (
            'SSH Root session is not yet established (SSH failure NEVER proves the phone is unrooted). '
            'Ask the owner whether the phone is already rooted: '
            '(1) If ALREADY ROOTED: if AutoRoot SSH is asleep (`connection_refused`), open BlackBerry World once on the phone and wait 30s; '
            'if this computer is not authorized yet, use `pair prepare` or `pair import-ssh`. '
            '(2) If NEVER ROOTED: warn that initial Root flashing wipes phone data, get explicit owner confirmation, '
            'then run `firmware prepare-root --variant <VARIANT>` followed by `firmware flash-root`.'
        ),
        'destructive': False,
    }


def cmd_models(args):
    proj = project_metadata()
    pin = mobile_release()
    variant, family_hint = normalize_variant(args.variant)
    if family_hint:
        matching = [v for v, (fam, _) in carrier_policy.MODELS.items() if fam == family_hint]
        return 0, {
            'ok': True,
            'action': 'models',
            'family_matched': family_hint,
            'exact_suffix_required': True,
            'how_to_find_exact_suffix': (
                'Connect the phone over USB and run `python tools/ai_skill.py detect`, '
                'or check Settings -> About -> General -> Model Number on the phone (e.g. ' + ', '.join(matching) + ').'
            ),
            'variants': [variant_entry(v) for v in matching],
        }
    if variant:
        if variant not in carrier_policy.MODELS:
            return 2, {
                'ok': False,
                'action': 'models',
                'error': 'model_unconfirmed',
                'requested_variant': args.variant,
                'supported_variants': list(carrier_policy.MODELS),
                'hint': (
                    'bb10-volte supports the 16 BB10 QNX hardware variants listed in supported_variants. '
                    'If the device runs Android 11 (LineageOS 18.1), use https://github.com/Octo-o-o-o/qcom32-volte.'
                ),
            }
        entry = variant_entry(variant)
        if args.operator:
            entry['operator_assessment'] = device_support.assess(variant, args.operator)
        return 0, {
            'ok': True,
            'action': 'models',
            'project': {
                'name': proj['name'],
                'version': proj['version'],
                'desktop_revision': proj['desktop_revision'],
                'mobile_version': pin['version'],
                'macos_frozen_release': 'v0.5.0-r43',
                'license': proj['license'],
            },
            'model': entry,
        }
    return 0, {
        'ok': True,
        'action': 'models',
        'project': {
            'name': proj['name'],
            'version': proj['version'],
            'desktop_revision': proj['desktop_revision'],
            'mobile_version': pin['version'],
            'macos_frozen_release': 'v0.5.0-r43',
            'required_os': carrier_policy.OS_VERSION,
            'license': proj['license'],
        },
        'total_models': len(carrier_policy.MODELS),
        'total_carrier_entries': len(carrier_policy.MODELS) * 3,
        'auto_root_recipe_variants': root_setup.catalog().get('auto_root_variants', []),
        'models': [variant_entry(v) for v in carrier_policy.MODELS],
    }


def cmd_detect(args):
    usb_raw = root_setup.local_usb_state()
    discovery = {k: usb_raw['device'][k] for k in SAFE_DISCOVERY_KEYS if k in (usb_raw.get('device') or {})}
    os_state = firmware_policy.assess_version(discovery.get('PlatformVersion'))
    usb_summary = {
        'usb_present': usb_raw.get('usb_present'),
        'usb_count': usb_raw.get('usb_count'),
        'driver_ready': usb_raw.get('driver_ready'),
        'usb_network': usb_raw.get('usb_network'),
        'link_target_ready': bool(usb_raw.get('usb_peer') and usb_raw.get('usb_source_address')),
        'discovery': discovery,
    }
    root_verified = False
    ssh_error = None
    probe_summary = None
    mobile_summary = None
    usb_count = usb_raw.get('usb_count')
    usb_absent_on_default_link = (
        usb_raw.get('usb_present') is False
        and usb_raw.get('usb_network') is False
        and not discovery
        and not args.ssh_config
        and args.host in connection.ALIASES
        and not getattr(args, 'force_ssh', False)
    )
    if usb_absent_on_default_link and not args.skip_ssh:
        ssh_error = 'usb_not_connected'
    elif not args.skip_ssh and not (isinstance(usb_count, int) and usb_count > 1):
        try:
            choice = root_setup.verify_root(args.host, args.ssh_config or '')
            root_verified = True
            client, _ = connection.resolve_connection(choice['host'], choice['config'])
            probe_raw = AutoClient(client).probe()
            probe_summary = sanitize_probe(probe_raw)
            try:
                mobile_raw = MobileAppInstaller(client).inspect()
                mobile_summary = sanitize_mobile_app(mobile_raw)
            except WorkflowError as app_err:
                mobile_summary = {'error': app_err.code}
        except WorkflowError as err:
            ssh_error = err.code
        except root_setup.SetupError as err:
            ssh_error = str(err)

    effective_variant = (probe_summary or {}).get('variant') or discovery.get('ModelName')
    guide = connection_flow.guidance(usb_raw, error=ssh_error, verified=root_verified)
    kits = [
        {'variant': item['variant'], 'stage': item['stage'], 'platform': item['platform'], 'kit_name': Path(item['folder']).name}
        for item in root_setup.prepared_kit_history()
    ]
    upgrades = [
        {'variant': item['variant'], 'stage': item['stage'], 'platform': item['platform'], 'kit_name': Path(item['folder']).name}
        for item in firmware_upgrade.pending_upgrades()
    ]
    pairings = [
        {'request_id': item['script'].stem.removeprefix('bb10-pair-'), 'step': item['step']}
        for item in connection_recovery.pending_pairings()
    ]
    next_step = synthesize_next_step(usb_summary, os_state, discovery, root_verified, ssh_error, probe_summary, mobile_summary)
    return 0, {
        'ok': True,
        'action': 'detect',
        'effective_variant': effective_variant,
        'model_info': variant_entry(effective_variant) if effective_variant in carrier_policy.MODELS else None,
        'usb': usb_summary,
        'os_baseline': {
            'state': os_state.state,
            'observed_discovery_os': os_state.current,
            'required_os': os_state.target,
        },
        'ssh_root': {
            'verified_uid0': root_verified,
            'error': ssh_error,
            'unrooted_proven': False,
            'guidance': {'state': guide.state, 'title': guide.title, 'detail': guide.detail, 'action': guide.action},
        },
        'volte_probe': probe_summary,
        'mobile_app': mobile_summary,
        'local_preparation_state': {
            'saved_connection_configured': connection.saved_connection() is not None,
            'candidate_ssh_profiles_count': len(connection.candidate_connections()),
            'prepared_root_kits': kits,
            'pending_firmware_upgrades': upgrades,
            'pending_pairings': pairings,
        },
        'recommended_next_step': next_step,
    }


def cmd_pair(args):
    if args.pair_action == 'prepare':
        export_dir = args.export_dir.resolve()
        export_dir.mkdir(parents=True, exist_ok=True)
        pending = connection_recovery.pending_pairings() if args.resume else []
        if pending:
            script = connection_recovery.refresh_pairing_script(pending[-1]['script'])
        else:
            script = connection_recovery.prepare_pairing()
        pairing_instructions.export_pairing_files(script, export_dir)
        connection_recovery.save_pairing_step(script, 2)
        request_id = script.stem.removeprefix('bb10-pair-')
        pub_key = (script.parent / 'identity.pub').read_text(encoding='ascii')
        return 0, {
            'ok': True,
            'action': 'pair.prepare',
            'request_id': request_id,
            'computer_key_fingerprint': connection_recovery.fingerprint(pub_key),
            'exported_files': {
                'request_json': str(export_dir / (script.stem + '-request.json')),
                'terminal_script': str(export_dir / script.name),
                'instructions_txt': str(export_dir / (script.stem + '-instructions.txt')),
            },
            'next_steps': [
                'Copy the exported -request.json (or .py for older terminals) to the phone Downloads folder (/accounts/1000/shared/downloads).',
                'Recommended (if BB10 VoLTE app is installed): open BB10 VoLTE -> Management & Recovery -> Connect Computer, choose the -request.json file, verify request_id, and tap Authorize.',
                'Fallback (existing Root terminal __root or u_root): verify `id -u` outputs 0, then run the guarded command block in -instructions.txt and type uppercase PAIR when prompted.',
                f'Copy bb10-pair-{request_id}-result.json back to this computer and run `pair finish --result <PATH> --confirm-host-key`.',
            ],
        }

    if args.pair_action == 'finish':
        folder, host_key, ssh_startup = connection_recovery.read_pairing_result(args.result)
        fp = connection_recovery.fingerprint(host_key)
        if not args.confirm_host_key:
            return 2, {
                'ok': False,
                'action': 'pair.finish',
                'error': 'host_confirmation_required',
                'request_id': folder.name.removeprefix('recovery-'),
                'phone_host_key_fingerprint': fp,
                'ssh_startup_configured': ssh_startup,
                'next_step': 'Verify the phone_host_key_fingerprint with the owner/result file, then re-run with `--confirm-host-key`.',
            }
        choice = connection_recovery.finish_pairing(args.result, confirmed=True)
        verified = root_setup.verify_root(choice['host'], choice['config'])
        connection_recovery.complete_pairing(verified['config'])
        return 0, {
            'ok': True,
            'action': 'pair.finish',
            'root_uid0_verified': True,
            'phone_host_key_fingerprint': fp,
            'ssh_startup_configured': ssh_startup,
            'saved_host': verified['host'],
        }

    if args.pair_action == 'import-ssh':
        scan = connection_materials.scan_materials(args.folder, recursive=not args.non_recursive)
        if scan['state'] != 'ready':
            return 2, {
                'ok': False,
                'action': 'pair.import-ssh',
                'error': 'materials_' + scan['state'],
                'scan_state': scan['state'],
                'identities_found': len(scan['identities']),
                'hosts_found': len(scan['hosts']),
                'configs_found': len(scan['configs']),
                'hint': 'Provide the exact single-device Root kit folder containing one private login key and one host public key / known_hosts.',
            }
        identity = scan['identities'][0]
        host_key, _ = scan['hosts'][0]
        fp = connection_recovery.fingerprint(host_key)
        if not args.confirm_host_key:
            return 2, {
                'ok': False,
                'action': 'pair.import-ssh',
                'error': 'host_confirmation_required',
                'phone_host_key_fingerprint': fp,
                'next_step': 'Confirm with the owner that this folder belongs to the connected phone, then re-run with `--confirm-host-key`.',
            }
        choice = connection_recovery.import_identity(identity, host_key, confirmed=True)
        verified = root_setup.verify_root(choice['host'], choice['config'])
        return 0, {
            'ok': True,
            'action': 'pair.import-ssh',
            'root_uid0_verified': True,
            'phone_host_key_fingerprint': fp,
            'saved_host': verified['host'],
        }
    return 2, {'ok': False, 'error': 'invalid_pair_action'}


def cmd_mobile_app(args):
    bar = bundled_bar()
    pin = mobile_release()
    choice = root_setup.verify_root(args.host, args.ssh_config or '')
    client, _ = connection.resolve_connection(choice['host'], choice['config'])
    installer = MobileAppInstaller(client)
    inspection = installer.inspect()
    if args.app_action == 'inspect':
        return 0, {
            'ok': True,
            'action': 'mobile-app.inspect',
            'bundled_bar': BUNDLED_BAR,
            'bundled_version': pin['version'],
            'inspection': sanitize_mobile_app(inspection),
        }
    device_id = inspection.get('device_id')
    if not device_id or inspection.get('can_install') is False:
        return 2, {
            'ok': False,
            'action': 'mobile-app.install',
            'error': inspection.get('reason') or 'mobile_app_preflight_blocked',
            'inspection': sanitize_mobile_app(inspection),
        }
    result = installer.install(bar, device_id)
    return (0 if result.get('state') == 'completed' else 2), {
        'ok': result.get('state') == 'completed',
        'action': 'mobile-app.install',
        'bundled_version': pin['version'],
        'result': sanitize_mobile_app(result),
        'next_step': (
            'The native BB10 VoLTE app (' + pin['version'] + ') is installed on the phone. '
            'The owner can now check status, back up original configs, activate 3-carrier VoLTE, and manage recovery directly on the phone without a computer.'
        ),
    }


def cmd_volte(args):
    if args.volte_action == 'verify-package':
        from auto_carrier import verify_package
        manifest = verify_package()
        return 0, {
            'ok': True,
            'action': 'volte.verify-package',
            'owner': manifest['owner'],
            'version': manifest['version'],
            'desktop_revision': manifest['desktop_revision'],
            'payload_files': len(manifest['files']),
        }
    choice = root_setup.verify_root(args.host, args.ssh_config or '')
    client, _ = connection.resolve_connection(choice['host'], choice['config'])
    auto = AutoClient(client)
    if args.volte_action == 'probe':
        raw = auto.probe()
        return 0, {'ok': True, 'action': 'volte.probe', 'probe': sanitize_probe(raw)}
    if args.volte_action == 'install':
        result = auto.install()
        status = public_status(result.get('status') or {}) if isinstance(result.get('status'), dict) else {}
        view = status_view(status) if status else None
        return 0, {
            'ok': True,
            'action': 'volte.install',
            'variant': result.get('variant'),
            'updated_existing_payload': 'phone_backup' in result,
            'desktop_backup_saved': bool(result.get('desktop_backup')),
            'status': status,
            'status_view': (
                {'ready': view['ready'], 'check_code': view['check_code'], 'title': view['title'], 'guidance': view['guidance']}
                if view else None
            ),
            'next_step': (
                'Use the phone power menu to perform a normal restart, unlock the phone, wait 3-5 minutes, '
                'and run `python tools/ai_skill.py volte status`. Follow any extra normal-restart prompt on Passport.'
            ),
        }
    raw = auto.action(args.volte_action)
    if args.volte_action == 'status':
        pub = public_status(raw)
        view = status_view(pub)
        return 0, {
            'ok': True,
            'action': 'volte.status',
            'variant': raw.get('variant'),
            'registration_ready': registration_ready(pub),
            'status': pub,
            'status_view': {
                'ready': view['ready'],
                'check_code': view['check_code'],
                'title': view['title'],
                'guidance': view['guidance'],
            },
            'manual_acceptance_reminder': (
                'IMS 200 OK alone is not final acceptance. Unplug USB and ask the human owner to verify outbound and inbound '
                'native dialer calls (>= 00:35 connected audio each), LTE retention during calls, and SMS.'
            ),
        }
    out = {'ok': True, 'action': 'volte.' + args.volte_action}
    for key in ('variant', 'phase', 'enabled', 'restored', 'uninstalled', 'reboot_required'):
        if key in raw:
            out[key] = raw[key]
    if isinstance(raw.get('status'), dict):
        pub = public_status(raw['status'])
        view = status_view(pub)
        out['status'] = pub
        out['status_view'] = {'ready': view['ready'], 'check_code': view['check_code'], 'title': view['title'], 'guidance': view['guidance']}
    return 0, out


def require_python_314_for_windows_prep():
    if sys.platform == 'win32' and sys.version_info < (3, 14):
        raise root_setup.SetupError(
            f'python_3_14_required_for_windows_root_prep (current: {sys.version.split()[0]}; '
            'lzo2 .tar.zst extraction in prepare_root.py uses Python 3.14 tarfile zstd)'
        )


def resolve_kit_arg(raw):
    candidate = Path(raw)
    if candidate.exists():
        return candidate
    in_private = private_root() / str(raw)
    if in_private.exists():
        return in_private
    return candidate


def cmd_firmware(args):
    progress_log = []

    def record_progress(message):
        progress_log.append(str(message))

    if args.fw_action == 'status':
        usb = root_setup.local_usb_state()
        discovery = {k: usb['device'][k] for k in SAFE_DISCOVERY_KEYS if k in (usb.get('device') or {})}
        variant, _ = normalize_variant(args.variant or discovery.get('ModelName'))
        free_gb = round(shutil.disk_usage(private_root().parent if not private_root().exists() else private_root()).free / (1024 ** 3), 2)
        stock = None
        if variant in set(root_setup.catalog().get('auto_root_variants', ())):
            fw = root_setup.stock_firmware(variant)
            stock = {
                'firmware_id': fw['id'],
                'file': fw['file'],
                'sha256': fw['sha256'],
                'size_bytes': fw.get('size'),
                'manual_download_url': fw.get('manual_download_url'),
                'backup_manual_download_url': fw.get('backup_manual_download_url'),
            }
        return 0, {
            'ok': True,
            'action': 'firmware.status',
            'platform': sys.platform,
            'python_version': sys.version.split()[0],
            'free_disk_gb': free_gb,
            'variant': variant,
            'auto_root_supported': variant in set(root_setup.catalog().get('auto_root_variants', ())) if variant else None,
            'stock_firmware': stock,
            'usb_discovery': discovery,
            'os_baseline': firmware_policy.assess_version(discovery.get('PlatformVersion')).__dict__,
            'prepared_root_kits': [
                {'variant': item['variant'], 'stage': item['stage'], 'platform': item['platform'], 'kit_name': Path(item['folder']).name}
                for item in root_setup.prepared_kit_history()
            ],
            'pending_upgrades': [
                {'variant': item['variant'], 'stage': item['stage'], 'platform': item['platform'], 'kit_name': Path(item['folder']).name}
                for item in firmware_upgrade.pending_upgrades()
            ],
        }

    if args.fw_action == 'import-stock':
        variant, _ = normalize_variant(args.variant)
        if not variant:
            raise root_setup.SetupError('firmware_model_required')
        imported = root_setup.import_stock_firmware(args.file, record_progress, variant=variant)
        return 0, {'ok': True, 'action': 'firmware.import-stock', 'variant': variant, 'cached_file_name': Path(imported).name, 'log': progress_log}

    if args.fw_action == 'prepare-driver':
        require_python_314_for_windows_prep()
        folder = root_setup.prepare_driver_kit(record_progress, proxy=args.proxy)
        return 0, {'ok': True, 'action': 'firmware.prepare-driver', 'driver_kit': Path(folder).name, 'log': progress_log}

    if args.fw_action == 'install-driver':
        res = root_setup.install_driver_kit(resolve_kit_arg(args.kit))
        return 0, {'ok': True, 'action': 'firmware.install-driver', **res}

    if args.fw_action == 'prepare-root':
        variant, _ = normalize_variant(args.variant)
        if not variant:
            raise root_setup.SetupError('firmware_model_required')
        require_python_314_for_windows_prep()
        folder = root_setup.prepare_root_kit(variant, record_progress, proxy=args.proxy, offline=args.offline)
        return 0, {
            'ok': True,
            'action': 'firmware.prepare-root',
            'variant': variant,
            'kit_name': Path(folder).name,
            'phone_modified': False,
            'log': progress_log,
            'next_step': (
                'Offline Root kit is verified and ready. Before running `firmware flash-root --kit ' + Path(folder).name + '`, confirm with the human owner '
                'that initial Root flashing erases phone data and ensure exactly one matching phone on OS 10.3.3.3216 is connected.'
            ),
        }

    if args.fw_action == 'prepare-upgrade':
        variant, _ = normalize_variant(args.variant)
        if not variant:
            raise root_setup.SetupError('firmware_model_required')
        require_python_314_for_windows_prep()
        folder = firmware_upgrade.prepare_upgrade(variant, record_progress, proxy=args.proxy, offline=args.offline)
        return 0, {
            'ok': True,
            'action': 'firmware.prepare-upgrade',
            'variant': variant,
            'kit_name': Path(folder).name,
            'phone_modified': False,
            'log': progress_log,
            'next_step': (
                'Stock 10.3.3.3216 upgrade + Root kit is verified offline. Ask the human owner to confirm full device data erasure '
                'before running `firmware flash-upgrade --kit ' + Path(folder).name + ' --current-os <OS> --confirm-erase-device`.'
            ),
        }

    if args.fw_action == 'flash-upgrade':
        if not args.confirm_erase_device:
            return 2, {
                'ok': False,
                'action': 'firmware.flash-upgrade',
                'error': 'flash_confirmation_required',
                'summary': 'Flashing stock 10.3.3.3216 erases phone data. Obtain explicit confirmation from the human owner, then pass `--confirm-erase-device`.',
            }
        folder = firmware_upgrade.upgrade(resolve_kit_arg(args.kit), confirmed=True, current_version=args.current_os, progress=record_progress)
        return 0, {
            'ok': True,
            'action': 'firmware.flash-upgrade',
            'kit_name': Path(folder).name,
            'log': progress_log,
            'next_step': (
                'Stock loader finished. Wait for the phone to boot, then run `firmware verify-upgrade-boot --kit ' + Path(folder).name + '` '
                'and ask the owner to complete initial BB10 setup and re-enable Development Mode before `firmware flash-root`.'
            ),
        }

    if args.fw_action == 'verify-upgrade-boot':
        verified = firmware_upgrade.verify_boot(resolve_kit_arg(args.kit))
        return 0, {
            'ok': True,
            'action': 'firmware.verify-upgrade-boot',
            'variant': verified['variant'],
            'stage': verified['stage'],
            'verified_os': verified['verified_os'],
            'next_step': 'Target OS 10.3.3.3216 boot is confirmed. Complete OOBE and enable Development Mode if needed, then run `firmware flash-root`.',
        }

    if args.fw_action == 'flash-root':
        if not args.confirm_erase_device:
            return 2, {
                'ok': False,
                'action': 'firmware.flash-root',
                'error': 'flash_confirmation_required',
                'summary': 'Initial AutoRoot flashing erases phone data. Obtain explicit confirmation from the human owner, then pass `--confirm-erase-device`.',
            }
        conn = root_setup.flash_root(resolve_kit_arg(args.kit), confirmed=True, progress=record_progress)
        return 0, {
            'ok': True,
            'action': 'firmware.flash-root',
            'ssh_host': conn['host'],
            'log': progress_log,
            'next_step': (
                'Root OS (expected AutoRoot v4 exit 73 after 100% write) and matching radio (exit 0) completed. '
                'Wait for the phone to boot, unlock, complete setup if prompted, re-enable Development Mode, wait for the Root notification, '
                'and run `python tools/ai_skill.py detect` to verify UID 0 and native hashes.'
            ),
        }
    return 2, {'ok': False, 'error': 'invalid_firmware_action'}


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--lang', choices=('zh', 'en'), default=argparse.SUPPRESS, help='Override output guidance language (zh or en)')

    parser = argparse.ArgumentParser(
        prog='ai_skill.py',
        parents=[common],
        description='Structured JSON CLI for AI coding agents to inspect models, identify BB10 phones and run safe workflows.',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    p_models = sub.add_parser('models', aliases=('catalog',), parents=[common], help='List all 16 supported BB10 models or inspect a specific variant/family')
    p_models.add_argument('--variant', help='Exact hardware suffix (e.g. SQC100-1, SQW100-4, SQN100-3, SQK100-1) or family alias (q10, q20, passport, p9983)')
    p_models.add_argument('--operator', choices=('mobile', 'unicom', 'telecom'), help='Optional carrier filter for assessment')

    p_detect = sub.add_parser('detect', aliases=('identify',), parents=[common], help='Read-only detection of USB, OS baseline, Root SSH, SIM, VoLTE and mobile app state')
    p_detect.add_argument('--host', default='bb10-root', help='SSH host alias (default: bb10-root)')
    p_detect.add_argument('--ssh-config', help='Optional explicit ssh_config file path')
    p_detect.add_argument('--skip-ssh', action='store_true', help='Inspect local USB and anonymous discovery only without opening SSH')
    p_detect.add_argument('--force-ssh', action='store_true', help='Attempt SSH even when local USB enumeration reports no attached 0x0FCA device')

    p_pair = sub.add_parser('pair', parents=[common], help='Authorize or import SSH access on an already-rooted BB10 phone without reflashing')
    pair_sub = p_pair.add_subparsers(dest='pair_action', required=True)
    p_pair_prep = pair_sub.add_parser('prepare', parents=[common], help='Generate public computer-pairing files for phone authorization')
    p_pair_prep.add_argument('--export-dir', type=Path, required=True, help='Empty or dedicated directory to export pairing request files')
    p_pair_prep.add_argument('--resume', action='store_true', help='Resume the latest pending pairing request if present')
    p_pair_fin = pair_sub.add_parser('finish', parents=[common], help='Import phone pairing -result.json and verify UID 0 SSH')
    p_pair_fin.add_argument('--result', type=Path, required=True, help='Path to bb10-pair-<id>-result.json copied back from phone Downloads')
    p_pair_fin.add_argument('--confirm-host-key', action='store_true', help='Confirm pinning the phone SSH host key from the pairing result')
    p_pair_imp = pair_sub.add_parser('import-ssh', parents=[common], help='Import an existing Root kit folder containing private login key + host key')
    p_pair_imp.add_argument('--folder', type=Path, required=True, help='Path to existing Root kit folder')
    p_pair_imp.add_argument('--non-recursive', action='store_true', help='Inspect only the top-level directory')
    p_pair_imp.add_argument('--confirm-host-key', action='store_true', help='Confirm pinning the discovered phone SSH host key')

    p_app = sub.add_parser(
        'mobile-app',
        parents=[common],
        help='Inspect or install the bundled native BB10 VoLTE phone app ('
        + str(project_metadata().get('mobile_version', ''))
        + ' BAR)',
    )
    app_sub = p_app.add_subparsers(dest='app_action', required=True)
    for name in ('inspect', 'install'):
        sub_p = app_sub.add_parser(name, parents=[common])
        sub_p.add_argument('--host', default='bb10-root')
        sub_p.add_argument('--ssh-config')

    p_volte = sub.add_parser('volte', parents=[common], help='Operate the unified 3-carrier VoLTE service across all 16 supported BB10 models')
    volte_sub = p_volte.add_subparsers(dest='volte_action', required=True)
    for name in ('verify-package', 'probe', 'install', 'status', 'start', 'enable', 'disable', 'rollback', 'uninstall'):
        sub_p = volte_sub.add_parser(name, parents=[common])
        if name != 'verify-package':
            sub_p.add_argument('--host', default='bb10-root')
            sub_p.add_argument('--ssh-config')

    p_fw = sub.add_parser('firmware', parents=[common], help='Model-bound USB driver, stock 10.3.3.3216 upgrade and AutoRoot v4 workflows')
    fw_sub = p_fw.add_subparsers(dest='fw_action', required=True)
    p_fw_status = fw_sub.add_parser('status', parents=[common], help='Check USB baseline, disk space, required stock archive and prepared kits')
    p_fw_status.add_argument('--variant', help='Optional target hardware variant (e.g. SQN100-3, SQC100-1, SQW100-4, SQK100-1)')
    p_fw_imp = fw_sub.add_parser('import-stock', parents=[common], help='Verify SHA-256 and import a user-downloaded stock 10.3.3.3216 firmware archive')
    p_fw_imp.add_argument('--variant', required=True)
    p_fw_imp.add_argument('--file', type=Path, required=True)
    p_fw_drv_prep = fw_sub.add_parser('prepare-driver', parents=[common], help='Download and verify BlackBerry Windows USB driver package')
    p_fw_drv_prep.add_argument('--proxy')
    p_fw_drv_inst = fw_sub.add_parser('install-driver', parents=[common], help='Install a prepared BlackBerry Windows USB driver kit via standard UAC')
    p_fw_drv_inst.add_argument('--kit', type=Path, required=True)
    p_fw_root_prep = fw_sub.add_parser('prepare-root', parents=[common], help='Offline preparation and partition verification of a model-bound AutoRoot v4 kit')
    p_fw_root_prep.add_argument('--variant', required=True)
    p_fw_root_prep.add_argument('--offline', action='store_true')
    p_fw_root_prep.add_argument('--proxy')
    p_fw_upg_prep = fw_sub.add_parser('prepare-upgrade', parents=[common], help='Offline preparation of stock 10.3.3.3216 upgrade + Root kit')
    p_fw_upg_prep.add_argument('--variant', required=True)
    p_fw_upg_prep.add_argument('--offline', action='store_true')
    p_fw_upg_prep.add_argument('--proxy')
    p_fw_upg_flash = fw_sub.add_parser('flash-upgrade', parents=[common], help='Flash stock 10.3.3.3216 in a native console (requires explicit owner erase confirmation)')
    p_fw_upg_flash.add_argument('--kit', type=Path, required=True)
    p_fw_upg_flash.add_argument('--current-os', required=True, help='Currently observed discovery PlatformVersion (e.g. 10.3.2.2876)')
    p_fw_upg_flash.add_argument('--confirm-erase-device', action='store_true')
    p_fw_upg_boot = fw_sub.add_parser('verify-upgrade-boot', parents=[common], help='Verify that the upgraded phone booted OS 10.3.3.3216 before flashing Root')
    p_fw_upg_boot.add_argument('--kit', type=Path, required=True)
    p_fw_root_flash = fw_sub.add_parser('flash-root', parents=[common], help='Flash prepared model-bound Root OS + radio in a native console (requires explicit owner erase confirmation)')
    p_fw_root_flash.add_argument('--kit', type=Path, required=True)
    p_fw_root_flash.add_argument('--confirm-erase-device', action='store_true')
    return parser


def run(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    previous_language = i18n.LANGUAGE
    try:
        if getattr(args, 'lang', None):
            set_language(args.lang)
        try:
            cmd = args.command
            if cmd in ('models', 'catalog'):
                return cmd_models(args)
            if cmd in ('detect', 'identify'):
                return cmd_detect(args)
            if cmd == 'pair':
                return cmd_pair(args)
            if cmd == 'mobile-app':
                return cmd_mobile_app(args)
            if cmd == 'volte':
                return cmd_volte(args)
            if cmd == 'firmware':
                return cmd_firmware(args)
            return 2, {'ok': False, 'error': 'unknown_command'}
        except WorkflowError as err:
            payload = {
                'ok': False,
                'error_type': 'WorkflowError',
                'error': err.code,
                'message': device_support.error_message(err.code) or err.code,
            }
            if isinstance(err.report, dict):
                payload['probe'] = sanitize_probe(err.report)
            return 1, payload
        except (root_setup.SetupError, connection_recovery.RecoveryError, ValueError, OSError) as err:
            code = str(err)
            return 1, {
                'ok': False,
                'error_type': type(err).__name__,
                'error': code,
                'message': device_support.error_message(code) or code,
            }
    finally:
        i18n.LANGUAGE = previous_language


def main(argv=None):
    configure_stdio()
    exit_code, payload = run(argv)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
