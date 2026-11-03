# Native mobile installation and use

[简体中文](MOBILE-INSTALL.md) | **English**

Current source candidate: desktop r21 / mobile 0.1.0.19, management protocol 2. The earlier public version is documented in [r20 release notes](RELEASE-r20.md); see the [desktop installer](https://bb10-volte.octoooo.com/en/mobile-installer.html) or [manual BAR](https://bb10-volte.octoooo.com/en/mobile-manual.html) entry.

**Recommended approach: Root ready → native BAR → BB10 system registration → backup and activation on the phone.** A local installer and desktop assistance are alternative first-install routes. Installing the icon does not enable the service. This candidate includes the Telecom CTNET proxy correction; see the [validation record](MOBILE-VALIDATION.md) for exact version and device coverage.

Use the [manual checklist](MOBILE-MANUAL-ACCEPTANCE.md) for the current candidate. Existing tasks are preserved. After a normal restart, wait for the system Root success notification, open the app once and explicitly check the original task; do not submit another enable or update to replace it.

## Installation paths

| Starting state | First step | Entirely on the phone? |
| --- | --- | --- |
| Rooted, working local BAR installer | Download the BAR and open it with that installer | A local route exists; verify Root, final installation version and permissions |
| Rooted, no usable local BAR installer | Use r19 desktop **More → Install phone app** once | A computer is needed for setup; later management is on the phone |
| Working Root terminal and AutoRoot v4 installer | Optional bootstrap ZIP with its version-specific command | Retained alternative; ordinary users need not type terminal commands |
| Stock, unrooted | Existing Windows/Mac first-Root workflow | No current complete on-phone route |
| AutoRoot v2/v3 or other Root | Validate helper, installer and sandbox behavior separately | Do not inherit v4 bootstrap results |

[AutoRoot v4 documentation](https://bb10.root.sx/blog/autoroot-v4) describes unsigned BAR support and local privilege helpers. A Root label alone does not establish those capabilities. The app does not flash firmware, exploit a stock phone or change global PathTrust.

**Recommended click flow:** use an existing on-phone BAR installer, or r19 desktop **More → Install phone app** for one-time setup. Check the rooted phone, select the matching BAR and confirm installation, then manage service from the phone. Existing r18 desktop artifacts do not have this menu. Final candidate artifacts still require acceptance. An Android-to-Root helper experiment caused a Q20 kernel reset; that route was retired and no APK bootstrap is shipped. An ordinary ZIP is not a clickable native installer.

Obtain the target **0.1.0.18** BAR and checksums from the same candidate handoff or official HTTPS Release. Do not guess an unpublished download URL. With an existing BAR installer, open the `.bar` and confirm system prompts normally. Otherwise connect the rooted phone to r19 desktop, choose **More → Install phone app**, check the model, select the BAR and confirm. The wizard checks the complete package, identity, installation result and installed files. An unknown result is reconciled using the original task, never a repeated submission. Experienced Root-terminal users may instead use the same-version bootstrap ZIP and its `INSTALL.txt`; this is optional.

Installation passes only with **the same job's final SUD success and an actual registered app version of 0.1.0.18**. The desktop wizard performs these checks before reporting success. An earlier v2 attempt printed completed after a timeout while the actual version stayed unchanged. Each new artifact needs its own verification. A completed message, extracted files, icon or working older version is insufficient.

Unlock normally, accept the first-use system app permissions and check the actual UI application version. Reaching a permission dialog does not establish that Cascades loaded. Restore an unavailable Root entry through its original method; do not bypass system permissions or the lock screen.

The release page must publish hashes and the pinned publisher key fingerprint. A public key bundled with an untrusted first download does not authenticate that download. BAR, bootstrap ZIP and signed runtime update ZIP are different artifacts.

## Enable VoLTE

**Check an existing recovery task first.** Follow its instructions without replacing it. If an older multi-stage task lacks current safety protections, the app retains it and asks you to export diagnostics instead of resuming it automatically. After a supported old service is stopped, restored and normally restarted, the primary action offers the bundled update to r18. Do not import the same-version ZIP for that step. An intact r18 service needs no update merely to use the v18 UI. The first-install steps below apply only when the service is genuinely absent.

1. Open **BB10 VoLTE** and tap **Check**. It verifies the entry hash, signed payload, Root environment and actual phone/SIM state.
2. Choose the backup location. A mounted SD card is preferred; internal Documents is allowed but cannot protect against losing the phone or storage failure.
3. Tap **Enable VoLTE**. The Root engine repeats device and idle-call checks, saves originals, exports them and verifies every copied hash before activation. A waiting dialog prevents duplicate actions during submission and reconciliation. Background tasks survive closing the UI; after reopening, explicitly check the same task.
4. Restart normally from the power menu when asked. Unlock, wait for the system Root success notification, then open the app once and tap **Check**. Before Root, the OS may reject launch before the waiting page can run; do not tap an unresponsive icon repeatedly. Network readiness may take 3–5 minutes; check again manually when needed. Passport may require another normal restart when its network policy changes; the app explains this separately.
5. Once IMS is connected, make and receive a call, each connected for at least two minutes, followed by one more outgoing call. Confirm audio in both directions and LTE during the call. Then save the four manual checks and wait for the result. A delayed reply triggers a check of the saved record without another save or radio changes. Acceptance should remain after closing and reopening. The app does not place calls, and registration alone is not calling acceptance.
6. Test SMS separately: incoming/outgoing, short/long, Chinese/English and notifications. The manual call record is bound to the current boot, SIM and payload; changes require revalidation.

Power off before later SIM changes. The automatic engine then selects a supported carrier without USB, SSH or a running computer.

The first launch without a cache also requires one manual check. Later launches, foreground returns and unlocks show the explicitly labelled last observation without an automatic check. Check manually after a restart or SIM change, or whenever current status matters. Cached data does not authorize changes: saving a call check revalidates the current SIM, boot and IMS. The app's Root request times out after 150 seconds without actual verification progress, with a 15-minute total limit; independent lower-level deadlines are unchanged.

## Manage and recover

After an old installation is stopped and restored, the bundled-update action applies the current BAR's signed payload without another download. Online update checks and offline signed `-update.zip` import require a newer runtime version; same-version or older ZIPs are not ordinary updates. Downloads enforce HTTPS, domain and size restrictions; the Root verifier independently checks the publisher signature and creates a protected private snapshot. Runtime updates do not replace the native C++/QML app: install a newer same-identity BAR for UI updates.

Supported old payloads require disable, restoration and a normal restart before updating to r18; accept each starting version separately. Use desktop r19. Existing r18 desktop can still manage the unchanged r18 service, but lacks the graphical app installer. New desktop and mobile writers share a device lock and persistent transaction records; this cannot stop an old process that already passed its old write checks.

Rollback uses the verified archive to restore the previous service or management component after any shutdown and normal restart steps the app requires. Newer management may be retained for task safety, and unsafe component-only downgrades are refused. It never invents a desktop backup receipt when only a mobile copy exists. Full service uninstall restores and restarts, verifies/removes owned files and hooks, then requests the final normal restart to verify stock state. Originals and diagnostics remain. Delete the app icon separately afterward; deleting it alone does not remove the service.

Exports use `BB10-VoLTE/<random operation ID>/` in the selected storage. **Keep original backups private.** Shareable diagnostics and compatibility reports use allowlisted fields and exclude IMSI, ICCID, IMEI, phone numbers, SIM digests and raw logs.

## Compatibility

The automatic route retains exact existing gates: OS `10.3.3.3216`; Q10 `SQN100-3`, Classic `SQC100-2`, Passport `SQW100-4`; eligible USIMs for China Mobile `460-00`, Unicom `460-01`, Telecom `460-11`. Current phone and carrier provisioning checks still apply.

Advanced provides **23 explicit options**: four existing carrier profiles plus 19 exact-variant trial profiles generated from the shared definitions and included in the signed bundle. These comprise 13 controlled manual candidates and six read-only Passport combinations. Generic legacy profiles accept only SQN100-3, SQC100-2 and SQW100-4; other variants must use their exact trial profile. Native hashes, ABI, network, stock baseline and restoration checks still apply. Every manual start rechecks eligibility and the installed profile. Autostart stays disabled. SQC100-4 remains a candidate, not hardware call acceptance; Passport's legacy restoration gate remains enforced.

### Experimental restoration has a separate scope

The original-file export, activation and full update/rollback/uninstall workflow above belongs to **automatic protocol 2**. It does not automatically apply to legacy trials. The 13 ordinary trials do not use Telecom attach modification; restoration uses the PPS journal captured at each start. This is not a protocol-2 original-file export receipt. Back up personal data separately. Exported trial observations carry `last_checked_not_live`: they describe the last check, not live state or accepted calls.

- Stopping an experiment disables its legacy autostart marker and waits for restoration.
- Updating an experiment requires prior disable/restoration and no pending install transaction, then uses the existing legacy updater. An interrupted install-transaction remains; do not retry blindly or delete its record.
- Uninstalling experimental startup entries uses the legacy uninstaller and retains private payloads and backups. It is not automatic protocol-2 full file removal.
- No legacy rollback has been added. Do not apply automatic rollback or backup-receipt promises to legacy trials. Read-only Passport options never authorize writes.

Unknown devices can export partial compatibility evidence before installation eligibility is evaluated. Further support needs actual Root, native ABI/radio, restore and call evidence. Adding a model name or bypassing hashes does not establish support.

Desktop r15 and mobile share the exact-variant and trial definitions. These are eligibility/diagnostic routes, not new mobile hardware acceptance. See [build/release instructions](MOBILE-RELEASE.md) and the [UI contract](MOBILE-UX.md).
