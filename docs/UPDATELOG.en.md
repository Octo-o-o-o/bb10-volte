# r44 / mobile 0.1.0.44

Admitted models can start fresh when no known legacy service remains. Unknown models and legacy leftovers stay blocked, and another model's recovery directory is never reused. Mobile is now 0.1.0.44. macOS stays at r43. See the [release notes](RELEASE-r44.en.md).

# r42 / mobile 0.1.0.43

All catalog models open, honest per-model evidence, P’9983 owner feedback, integrated pairing/lifecycle/network improvements. See [release notes](RELEASE-r42.md).

# Update log

Local r41 / mobile 0.1.0.42: explicit VoLTE installation or enablement attempts to turn Mobile Network on when OFF is confirmed, then verifies ON and rechecks SIM compatibility. Status checks and boot monitoring do not change the switch. Failures retain the task and backups. This candidate has not been installed on hardware; device acceptance is pending.

Local r40/mobile 0.1.0.41 adds exact SQC100-1/CLASSICROW/OS3216 three-carrier trial admission with native-image and recovery checks. Owner results remain separately recorded; other models are not broadened.

Local r39/mobile 0.1.0.40 adds exact P’9983 SQK100-1/KHANE three-carrier trial admission and identity/recovery checks. Manual results await owner testing; other model scopes are unchanged.

## Local candidate r36 / mobile 0.1.0.37 · preserving calls and waiting for events

Unknown SIM state and monitoring/log/status-write failures no longer authorize stopping a running IMS process. A real replacement requires repeated consistent identity and idle-call checks. Stable monitoring uses read-only PPS subscriptions, a 30-second stop/SIM guard and five-minute full checks; unsupported event streams fall back to low-frequency observation. Prolonged waiting also ends fast polling, and identical status is no longer rewritten. Both clients guide a manual restart, status check and the next confirmed step after a SIM change.

Native IMS and necessary same-SIM boot initialization remain; the UI can close. This candidate has not been installed on a handset or published. Call continuity, actual event delivery, standby power and reboot after deleting the BAR remain unverified. [Behavior and scope](MOBILE-LIFECYCLE-2026-11-08.md).

## Local candidate r35 / mobile 0.1.0.36 · idle work and conservative notices

Each foreground screen hold is capped at ten minutes; background UI polling stops. Startup retains three-second checks, while a full minute of confirmed connection allows thirty-second monitoring and fewer persistent writes/log scans. The new backend defaults to LTE only; disabling restores the exact original network mode. Only known restart, configuration failure, restoration failure or completed task outcomes may request attention. Unknown, interrupted and waiting states stay silent.

This local candidate has not been installed on the acceptance handset or publicly released. Battery, LTE-only calling/SMS and automatic notices require separate device acceptance. [Behavior and scope](MOBILE-IDLE-NOTICES-2026-11-07.md).

Confirmed SIM changes now request a normal restart within the same boot, or app review after a real reboot. Unknown identity stays silent; the existing checks are reused without another watcher.

## Local candidate r34 / mobile 0.1.0.35 · stale SMS busy state

A Telecom SMS stall left a persisted busy flag after switching the SQW100-4 to Mobile. Native SMS and modem queues were idle. Reconciliation plus a normal boot restored Mobile registration; owner call, audio, LTE/data, short/long and identical-message tests passed. The candidate checks pinned native images and live code, stable SIM/boot and both idle layers before the first Mobile/Unicom IMS launch on exact SQW100-1/SQW100-4 builds. It saves evidence and changes one PPS field only. Unknown builds or active work are preserved. Both clients identify SMS-busy registration waits. Message outcomes and the Telecom SMS completion defect are unchanged. Installation and boot validation remain separate from these source changes.

Installation and final verification are complete on this SQW100-4 / Mobile 460-00 unit: automatic registration after normal boot, mobile 0.1.0.35 status/web use, and Windows r34 handset preflight passed. All 18 backend files, 57 signed management components and backups were verified. The 17-check verdict explicitly reuses this unit’s previous call/SMS and restoration evidence within the unchanged-code scope recorded in 118. The final clean boot did not deliberately recreate the stale-write branch. New Unicom results on this unit remain pending. See the [device record](SQW100-4-RETEST-2026-11-07.md).

## Local r33 / mobile 0.1.0.34 · 2026-11-07

The new SQW100-4 unit passed Telecom calls, two-way audio, LTE/data, HTTP/HTTPS, normal startup and the phone status page. The owner accepts the known defect where SMS reaches its recipient but remains pending locally. Both clients now explain this limitation and retain automatic activation for Mobile 460-00, Unicom 460-01 and Telecom 460-11. Only client guidance and evidence change; backend files remain identical. Mobile and Unicom tests on this physical unit will be reported by the owner separately. See the [device record](SQW100-4-RETEST-2026-11-07.md).

## Local r32 / mobile 0.1.0.33 · 2026-11-07

Correct JSON filtering on the pairing page and add **Load request from Downloads**. A single matching request can be loaded directly; multiple requests still require explicit selection. During mobile 0.1.0.32 handset testing, the picker did not show a request whose transfer and readback were verified, so that version did not pass pairing acceptance. Authorization checks and backend files are unchanged. See the [SQW100-4 retest](SQW100-4-RETEST-2026-11-07.md).

## Local r31 / mobile 0.1.0.32 · 2026-11-07

Add optional **Manage → Connect computer** in the main phone app: select the desktop public-key request, compare fingerprints and authorize without terminal commands. The desktop retains its terminal fallback and verifies the returned material and actual Root connection. Correct the canonical manifest fingerprint for verified r21 payloads so the existing stop, restore and update workflow recognizes them; active or independently modified installations remain blocked. Build and handset evidence is separate in the [SQW100-4 retest](SQW100-4-RETEST-2026-11-07.md). Not publicly released.

## Local r30 / mobile 0.1.0.31 · 2026-11-07

Update the SQC100-4 Mobile field result: the 460-00 SIM is recognized and LTE is enabled in both the system and modem, but no Mobile LTE was found. Activation stays blocked. Carrier admission and native voice/SMS code are unchanged; accepted Telecom scope, the closed Unicom route and other models are preserved. Build and installation evidence is separate in the [SQC100-4 record](SQC100-4-INTAKE-2026-11-06.md).

## Local r28 / mobile 0.1.0.29 · 2026-11-07

Mark SQC100-4 Unicom adaptation unsupported at the owner’s request and remove both trial entries. Shared automatic and manual checks reject this combination, including imported old profiles; restoration remains available. Preserve accepted Telecom scope and its SMS notice; Mobile awaits handset testing. Both candidates were built in isolated directories; signatures and the Windows offline self-test passed. They have not been installed on a phone or published. See the [SQC100-4 record](SQC100-4-INTAKE-2026-11-06.md).

## Local r27 preview / mobile 0.1.0.28 · 2026-11-07

Admit only SQC100-4 / CLASSICNA / 10.3.3.3216 / Telecom 460-11 / USIM without ISIM. The owner explicitly accepts the known outgoing SMS pending-state and subsequent-queue defect; both clients disclose it, and SMS is not marked passed. Other carriers remain restricted. Windows r27 actual preflight, phone v28 installation and connected page, configuration restoration and normal-boot automatic registration were verified. No public release. See the [SQC100-4 intake record](SQC100-4-INTAKE-2026-11-06.md).

## Local r22 preview / mobile 0.1.0.22 · 2026-11-06

Add the exact SQW100-1 / WINDERMEREEMEA / Mobile 460-07 case, including a number ported from Unicom. Shared policy, desktop guidance and phone catalogs agree on this restricted scope. The final phone app passed installation readback, normal-restart registration, incoming/outgoing calls and a current saved four-check record. The frozen Windows executable passed actual-device preflight. Earlier backend SMS, data and full-restoration tests are recorded separately; unperformed GUI operations remain unknown. No public release. See the [intake record](SQW100-1-INTAKE-2026-11-06.md).

## 0.5.0-r15 — Early variant checks, local trials and first-use help

Preserve prepared Root images across transient connection failures and allow a retry on the Root page. Explain exact-variant and carrier limits before preparation. Add 13 gated manual candidate combinations and six read-only Passport combinations, with six native-file checks, separate install/start and autostart off. The accepted automatic whitelist is unchanged; new variants have no hardware acceptance.

Include the nine-step bilingual illustrated tutorial, a 3:39 Chinese narrated/subtitled video and local redacted feedback ZIPs. Feedback keeps earlier failures, candidate binding and native digest summaries without automatic upload. Windows, signed/notarized Mac, website and READMEs use the same release source. The mobile branch remains independent. See the [release review](RELEASE-REVIEW-R15-2026-11-02.md).

## 0.5.0-r14 — Hardware SMS fix and Mac/Windows first Root

Enables native SMS ACK correlation. Q20/Unicom and Passport/Mobile passed short, two-part and independent identical-text messages without extra delivery, plus short bidirectional audio/LTE calls. Mac/Q20 and Windows/Passport passed first Root and normal-restart autostart. Repairs fresh addon setup, USB discovery, native prompt buffering, Windows completion classification and pinned Mac loader/final reconnect. Failed receipts and strict stop conditions are retained. See the [scope and evidence](SMS-ROOT-ACCEPTANCE-2026-11-01.md).

[简体中文](UPDATELOG.md)

## 0.5.0-r13 · Integrated fixes, firmware workflows and SMS diagnostics · 2026-11-01

Integrates r11/r12 model-bound Root preparation, old-OS upgrades and pairing fixes, plus precise SQC100-4 network guidance without weakening device admission. Standalone Mac downloads use system CA roots with TLS verification. Firmware import errors now cover stock EXE inputs as well as archives.

Recognizes the previously omitted accepted Q20 Mobile autostart payload `a517c79c…`, retaining existing versions and per-file checks. Regression tests use the real historical manifest and reject altered bytes before upload.

Includes SMS send-domain policy, original-value restoration, backed-up payload upgrades and redacted offline diagnostics. The native MT ACK candidate passes reproducible builds, ARM emulation and nine-combination/three-load-address checks, but lacks QNX and gateway acceptance. It is disabled by default; normal startup retains the known voice IMS images. Duplicate elimination is not claimed. Physical old-OS upgrades, initial Root, Intel Mac execution and long-term stability remain untested.

See the [release review](RELEASE-REVIEW-2026-11-01.md). Windows EXE, signed/notarized universal Mac DMG, full source and checksums share one frozen source. Both website languages point to r13.

## 0.5.0-r12 · OS checks, stock upgrades and phone pairing · Local candidate

Integrate r11 Root preparation for Q10/Q20/Passport, then add exact OS routing, explicit stock-upgrade erase confirmation, stock write and boot readback, separate Root confirmation, and resumable preparation records. Unknown/newer OS, multiple devices, mismatched materials and uncertain writes stop. Stock flashing never accepts the Root-only exit-73 exception. Mac signed OS/radio have independent pinned hashes; all three real stock inputs were freshly split and compared.

Phone pairing exports matching instructions and checks UID 0, the file path and pathtrust success before Python. Explain the two-underscore helper and uppercase PAIR; keep resumed step labels synchronized. Public r10 downloads remain the existing release. Physical old-OS upgrade acceptance is still pending; see [Firmware upgrades](FIRMWARE-UPGRADE.en.md).

## 0.5.0-r11 · Three-model initial Root and ZSpace downloads · Local candidate

Add model-specific Root preparation, partition verification and staged flashing for Q20 and Passport. Preserve model/image/confirmation/uncertain-state gates. Place preparation after import with actionable disabled-state guidance; add ZSpace copy links and download instructions. Real offline Windows builds passed for all three firmware families; no phone was flashed.

See the [three-model Root workflow record](../materials/root-workflow-validation-2026-11-01.json): Windows source offline builds passed for all three families; frozen EXE preparation passed for Q20/Q30 along with the runtime self-test. No hardware first flash was performed. ZSpace folder access and a small checksum download passed; full firmware download/hash verification did not complete in this run.

## Source candidate · MT ACK correlation · 2026-11-01

The native raw 3GPP SMS path does not carry the incoming Call-ID into the report's In-Reply-To. The candidate caches context by manager and RP reference, sets the report correlation and its MT gateway, and preserves RPDU, its own Call-ID and send count. Conflicts, expiry and missed captures never guess a correlation. Known-payload upgrades back up and replace `ims_image.py`.

Adds reproducible C/ARM code, a generated manifest, instruction-emulation regression tests and ELF/call-site verification for all nine combinations. QNX loading, SIP gateway acceptance and single Hub delivery remain untested on devices. Not deployed or released; see [native analysis and validation limits](SMS-ACK-NATIVE.en.md).

## Source candidate · SMS policy and diagnostics · 2026-11-01

Explicitly applies native `SMS_Over_IP_Network_Indication` alongside SMS service advertisement, preserving original values for restoration and backing up known payloads during upgrade. Native retry counts are unchanged. Adds offline SIP/RP correlation analysis without exporting numbers, Call-IDs or message content.

Review of 19 historical captures found a Q20 Mobile ACK receiving SIP 400 and a Passport Telecom ACK receiving `400 Cannot find In-Reply-To`. Other combinations lack SMS transactions and cannot pass SMS acceptance. This candidate is neither deployed nor released; successful MO and single MT delivery still require device testing. Prior acceptance remains scoped to recorded voice, SIM-change and display checks. See [SMS diagnostics](SMS-DIAGNOSTICS.en.md).

## Unreleased · SQC100-4 Telecom feedback diagnostics · 2026-11-01

Prioritizes network blockers over the IMS process count and distinguishes an ON data setting from an OFF service status. A process count on an uninstalled phone no longer implies a leftover installation. Selecting a pending row displays its full, wrapped guidance below the table; copied summaries also explain the exact hardware boundary for automatic carrier adaptation.

This changes desktop diagnostics only. SQC100-4 remains outside automatic carrier adaptation; phone payloads and admission conditions are unchanged. The reported phone was unavailable, so actual network registration and calls have not been repaired or verified. See the [network investigation record (Chinese)](NETWORK-DIAGNOSTICS.md).

## Desktop update · completion, sharing and public documentation · 2026-11-01

Adds localized sharing, OctoLab, GitHub Star, contact and optional coffee support to both packages. Completion requires current-boot registration and respects Passport extra restarts and USB reconnects. Only verified branded QR presentation images are public; original receipt screenshots stay private. README now includes the nine-combination infographic and Windows UI illustration. User-facing support labels say “supported in the latest release”; release records retain exact versions and hashes. The accepted phone payload is unchanged.

## 0.5.0-r8 · Q10 and Passport own-number display · 2026-11-01

Q10 could call after switching to Unicom while its dialer number remained blank; the unified service previously invoked authenticated number filling only on Q20. r8 enables it for all three supported models, retaining current-boot, current-SIM and native-process REGISTER-200 proof. Display-cache updates and restoration do not write SIM records or radio settings.

The update also prevents a previous SIM's number from becoming the new SIM's rollback value, preserves rollback state across interrupted writes, and caches fresh authentication even when the display is already correct. Recognized r7 payloads can be backed up and upgraded. Attach policy and the IMS engine retain r7 content.

The shared Windows/Mac workflow now shows an explicit additional-restart stage, its reason and a **Restarted — check again** button. Both windows derive readiness from the current boot; old registration cache, LTE alone or just enabling startup cannot show registration success. Reconnection triggers a fresh check, and a disabled update first prompts enabling, avoiding repeated restarts or reinstalls.

The full regression run contains 474 tests: 473 passed and one skipped. The owner confirmed Q10's correct Unicom number; its r8 USB-disconnected outgoing call lasted 48.268 seconds, with all samples on LTE. Passport r8 registered automatically on Telecom after its second normal boot. Hardware calls, SIM changes and number-display checks retain their actual payload versions. See the current [acceptance matrix](../materials/unified-carrier-acceptance.json) and [unified workflow](AUTO-CARRIERS.en.md).

Final acceptance on 2026-11-01: all nine exact-model/carrier combinations passed functional checks on recorded r7/r8 payloads; all three phones now have r8. The final phone-only swaps passed Q10 Telecom, Q20 Unicom and Passport Mobile, with both calls over 35 connected seconds, audio, LTE and own-number display confirmed. Passport also displayed China Mobile correctly. Q10 Telecom uses the final pair, with earlier peer-number failures excluded and first-attempt success unassessed. Six cases document phone-only swaps; three initial-card baselines remain distinct. Retained SIP timing and owner-confirmed duration are recorded separately. Current Mac physical USB acceptance is deferred; software packaging, signatures and notarization do not replace it.

The bilingual website now documents one installation followed by automatic carrier selection after powered-off SIM swaps, the extra Passport restart, the acceptance matrix and version-matched R2/GitHub downloads. Website source is included in this repository and source archive.

## 0.5.0-r7 · Q10 Mobile LTE retention policy · 2026-10-31

r7 acceptance update: r6 passed automatic registration after normal boot and USB-disconnected bidirectional calls on Q20 Telecom and Passport Unicom. Established calls lasted 58.3/54.1 and 36.9/37.7 seconds respectively; all 450 samples on each device were LTE. The owner cancelled an earlier unanswered Q20 outgoing call. Q10 Mobile r6 initially registered but later received network rejection cause 18; the modem removed LTE from its enabled technologies (19 to 3), and calls failed. This run did not pass. r7 adds backed-up data-centric setup specifically for Q10 Mobile, retains the existing Telecom policy, and restores the original policy on switching to Unicom. Hardware retesting remains pending; all nine combinations have not passed. Passport Unicom still has a blank own-number field, recorded separately as a display limitation. A number or 4G icon does not establish calling acceptance.

## 0.5.0-r6 · Wait for idle startup resources · 2026-10-31

r6 acceptance update: Q10 Telecom r5 passed USB-disconnected calls lasting over 35 seconds in both directions. The owner confirmed bidirectional calls after a phone-only power-off SIM switch to Mobile; log collection is pending. Q20 switching to Telecom and Passport switching to Unicom selected the correct carriers but stopped at the idle-resource check before IMS startup. r6 waits for two consecutive idle observations of call services, IMS and VPN, bounded to 180 seconds. Timeout or stop does not proceed to new policy writes. Hardware retesting is pending; the nine combinations have not all passed. A 4G icon or own-number display alone does not prove voice registration.

## 0.5.0-r5 · Restore LTE in the saved technology selection · 2026-10-31

- Q10 retained a 2G/3G-only selection despite correct attach policy. Use the pinned stock `configure_rats` interface to add LTE, retain other technologies, and require its reply plus both status readbacks.
- Record the original before writing and restore its technologies and preference on disable. Keep the original unset sentinel -1 in the backup; encode it as the protocol's no-preference mask 0. Preserve independent changes.
- Passport Telecom r4 passed automatic registration after restart and USB-disconnected bidirectional short calls. r5 and cross-carrier SIM switching still need hardware acceptance.

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
