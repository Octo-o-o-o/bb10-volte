# Update log

[简体中文](UPDATELOG.md)

## 0.5.0-r4 · Startup restoration and reboot decisions · 2026-10-31

- Track modem-policy changes separately from DCA source repairs. Recreated source files alone no longer require another Passport restart; actual policy changes still require a normal restart.
- Restore only carrier fields that differ from their originals, avoiding repeated deletion of absent voice settings.
- Upgrade known r1/r2/r3 payloads with backups. Add regressions for consecutive boots and preservation of a required reboot within the current boot. Hardware SIM-switch acceptance remains ongoing.

## 0.5.0-r3 · Telecom policy publication fix · 2026-10-31

- Fix ineffective repeated publication when PPS is already data-centric but modem readback remains original. Original-to-data publication restored usage 1 on Passport; restart/call acceptance is still pending.
- Add inactive upgrades of known r1/r2 payloads, previous-version backups and interrupted-update recovery without changing system binaries or boot entries.
- Do not present cached REGISTER 200 as current registration.

## 0.5.0-r2 · Automatic carrier candidate · 2026-10-31

- Windows and Mac share installation, original backups, legacy migration and SIM selection during phone startup. After installation, change SIM and restart without another flash. See [scope](AUTO-CARRIERS.en.md).
- Main-window management prioritizes the unified service and blocks legacy reinstallation; add re-enable control.
- r2 changes desktop management only; phone payload bytes match r1. Q20 Mobile passed restart, USB-disconnected and bidirectional short calls; other combinations and SIM changes remain under acceptance.

## 0.4.0-r1 · Local Telecom candidate · 2026-10-31

Accepted Q20 SQC100-2 Telecom bidirectional short calls, normal restart recovery and calls without USB. Added hash-pinned management of its existing legacy Root adapter, and a manual Q10 SQN100-3 / 460-11 attach port with independently verified desktop backups and the original LTE-before-IMS gate. Passport lifecycle restrictions remain. Added peer-report comparison and carrier path/content verification. See [scope and limits](TELECOM-PORT.en.md).

## 0.3.3-r9 · Baidu Netdisk backup download · 2026-10-31

- Add a browser backup for Q10, Classic / Q20, and Passport / Q30, displaying the access code and copying the complete share information.
- Retain ZSpace and model-specific import verification. Baidu share pages are excluded from automatic speed ranking, raw-file downloads and resumable transfers.

## 0.3.3-r8 · Firmware downloads by hardware model · 2026-10-30

- Add **China download (ZSpace)** with three uploaded stock files and verification lists. Browser shares remain separate from automatic raw-file mirrors; model-specific import verification is retained.
- Automatic downloads, browser links, and local import verification share one exact-model mapping for Q10, Classic / Q20, and Passport / Q30, without a Q10 default.
- Unknown, conflicting, and multiple-device identities stop the action. Explicit offline selection is available. Downloads and Root preparation recheck the connected model; model changes clear old image selections.
- Pin Q20 / Passport stock file sizes, SHA-256 digests, and checked download servers. Automatic Root building and flashing remain Q10-only, with existing phone compatibility gates preserved.

## 0.3.3-r7 · Combined network-service flag correction · 2026-10-29

- Fix r6's equality-to-1 check: combined emergency flags such as 33555457 also block installation, update and start.
- Require the LTE data-service bit and no emergency bit, retaining unknown for missing/invalid bitmaps. cnice connected=true alone cannot authorize actions; reports and UI explain both bits.
- Preserve APN-overlay restrictions. This corrects the misleading preflight result and does not establish recovery of the reported device's actual network access.

## 0.3.3-r6 · Local Q20 network diagnostic test build · 2026-10-29

- Stop reporting the LTE check as passed when the snapshot explicitly reports emergency-only service. Negative service observations also block stale connected=true readings.
- Observe actual data-service status separately from the configured mode, plus internet presence/enabled/connectable/active flags. Missing APN/connected values stay unknown; active never substitutes for connection proof.
- Show the same bounded network service and LTE band masks in details and troubleshooting summaries without inferring the operator or successful registration.
- Preserve APN overlays and existing configuration-baseline restrictions. This is a diagnostic fix, not Q20/Telecom network acceptance; see the [evidence and limits](NETWORK-DIAGNOSTICS.md).

## Unreleased · Incoming configuration explanations and upstream comparison · 2026-10-29

- Show the same six existing incoming-configuration observations in check details and copied/exported troubleshooting summaries, with interface-specific explanations and stable references. Missing or invalid values remain unknown; observations do not establish call acceptance or action permission.
- Record the pinned bb10root VoLTE Addon source comparison, configuration differences, experimental candidates and alternatives not adopted in bilingual guides and machine-readable provenance.
- Changes are limited to desktop explanations and reference materials. Phone payload, carrier templates, registration checks, installation/restoration gates and hardware acceptance retain their existing scope. No new EXE/DMG has been built or published.

## 0.3.3-r5 · Cross-platform diagnostics and complete source release · 2026-10-29

- Current and required values with next steps for voice policy, crypto, IMS processes, VPN sessions and configuration checks; missing values remain unknown.
- Independent native reads retain successful observations when another read fails; existing installation gates remain enforced.
- Pending-first rows, filtering and a wrapping explanation pane; copy a versioned troubleshooting summary with stable diagnostic references or export the same snapshot as JSON.
- Distinguish absent installations, running services and read failures; passed autostart checks now use success wording.
- Includes r4 China Telecom `ctlte` and APN diagnostics, with Windows EXE, Mac universal2 DMG and source ZIP from the same sources; signing, notarization and validation records accompany the release.
- Adds the previously recorded Q10 portrait demo, subtitles, cover, review evidence and recording scripts. Public inputs use relative paths and an explicit hash manifest; build caches stay local.
- Remains experimental; packaging and regression checks do not establish new device, carrier or phone-call acceptance.

## 0.3.3-r4 · Local diagnostic test build · 2026-10-29

- Recognize Telecom `ctlte` while retaining actual data connectivity, stock-carrier and baseline gates.
- Distinguish an APN/profile mismatch, disconnected data and unknown status; export fixed allowlisted APN names and independent connection flags.
- Expose individual read-only baseline observations without deleting or resetting non-default settings. An LTE snapshot does not establish registration or the serving band.
- Local regression and packaging checks do not constitute Q20 Telecom hardware acceptance. This build is not published.

## 0.3.3-r3 · 2026-10-29

- Ranks download nodes by observed payload speed, switches on failures or sustained low speed, and retains usable progress.
- Verifies overlapping bytes for cross-mirror resume, scopes ETags to their source, and requires the complete pinned SHA-256. Adds Q10 archive replicas and verified tool mirrors.
- Adds browser source selection, link copying, file selection and pasted-path firmware import. Import is offline; verified firmware is reused during preparation.
- Windows EXE and universal Mac DMG share the downloader. Phone payload remains `0.3.3`; this release adds no phone flashing or call acceptance.

Get packages and checksums from [this Release](https://github.com/Octo-o-o-o/bb10-volte/releases/tag/v0.3.3-r3). See [download details](FIRST-RUN.en.md#interrupted-or-failing-downloads).

## 0.3.3-r2 · 2026-10-29

Fix an import obstacle found during real Q10 acceptance: old Root folders may contain large or deep build trees. Choose “Check this folder only” to inspect the files directly inside the selected folder, without moving keys or editing SSH configuration. The scope is displayed explicitly. Ambiguous keys, missing trusted phone identity, or incomplete scans still block import, and connections are remembered only after successful Root verification.

Also fixes phone pairing on QNX mount aliases: authorization and host-key paths must refer to the same actual files, rather than have identical path spelling. Re-export an existing request from step one after upgrading to use the current helper while preserving its key and progress.

This updates the desktop app only; phone payload remains `0.3.3`. Windows EXE, notarized universal Mac DMG, hashes, and the exact hardware acceptance scope are provided with the [release](https://github.com/Octo-o-o-o/bb10-volte/releases/tag/v0.3.3-r2). Existing phone services can be checked without repeating Root preparation.

## 0.3.3-r1 · 2026-10-29

This release integrates all local development branches. The desktop version is `0.3.3-r1`, with phone payload `0.3.3`. It remains an experimental prerelease.

- **Phone connection:** Connect phone / Connection help distinguishes USB, networking, phone identity, authorization and effective Root. Import personal materials from the original Root folder; SSH paths and aliases live in advanced settings. Connection failure does not route automatically to initial Root.
- **Resume setup:** Reopening rechecks the last successful connection. Unfinished pairing retains its original key, request ID and step. Completed image preparation can be revalidated and resumed; uncertain flashing results remain blocked.
- **Recover downloads:** Pinned materials support range resumption, bounded retries, size/speed progress and actionable errors. Unsupported range requests safely restart downloads. Completed files must still pass SHA-256 verification; failed caches never become valid inputs.
- **Desktop controls:** Consistent buttons, fields, selectors, tabs, progress indicators and scrollbars, with improved compact-window and wizard scrolling and native keyboard behavior.
- **Community research:** Attributed, scoped community evidence and read-only incoming configuration diagnostics appear under More → Community research and adaptation progress and in exported reports. Community reports do not establish project hardware acceptance.
- **Compatibility guards:** Untested model/carrier combinations require autostart disabled and manual startup. Passport installation, startup and automatic restoration remain paused pending provider lifecycle validation; experimental opt-in cannot bypass this guard.
- **Integration:** Retains the earlier Mac connection diagnostics, experimental native Q10 Root flow, IMS startup changes and corrected acceptance records. Historical branch merges preserve subsequent fixes and update both language guides.
- **Cross-platform fixes:** Resets stale Mac wizard scrolling when content shrinks, supplies isolated SSL/library paths to build subprocesses, and explicitly bundles SSL/crypto libraries. An offline packaged-app self-test without build-environment overrides now runs before notarization.

### Downloads and updating

Get the Windows x64 EXE, universal Apple Silicon / Intel Mac DMG or public source ZIP from [this Release](https://github.com/Octo-o-o-o/bb10-volte/releases/tag/v0.3.3-r1), and verify its SHA-256. Build, self-test, notarization and final verification records accompany the Release.

If calling already works, update the desktop app and connect to inspect the existing service. Desktop updates do not require rooting or flashing again. Updating the phone payload requires a separate preflight and confirmation. Personal keys and connection materials are excluded from the packages.

### Validation scope

Release checks cover source regressions, public-file allowlisting and hashes, bundled resources and offline application self-tests on both platforms. Consult the Release attachments for final results. The Windows EXE has no Authenticode signature. Mac packaging uses Developer ID signing, Apple notarization and stapled tickets.

This release adds no hardware acceptance for first flashing, persistent pairing, phone reboot, calling, sustained stability or Intel execution. Earlier Q10/Unicom and Mac r5 hardware records retain their original versions and scope; they do not establish acceptance of phone payload `0.3.3`. Q20/Passport must not use Q10 initial-flash images.

## 0.3.2-r6 · 2026-10-29

Fixed Mac Root probing and USB diagnostics, documented three phone connection situations, integrated experimental native Q10 preparation and staged flashing on macOS 14+, and fixed Windows permission/console-encoding test portability. See the [r6 Release](https://github.com/Octo-o-o-o/bb10-volte/releases/tag/v0.3.2-r6) for its original validation scope.
