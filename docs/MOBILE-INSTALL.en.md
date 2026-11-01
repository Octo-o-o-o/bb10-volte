# Native mobile installation and use

[简体中文](MOBILE-INSTALL.md) | **English**

The native Cascades app (`com.octolab.bb10volte`) coexists with the desktop manager. The current target is mobile **0.1.0.6**, desktop **r16**, management protocol **2**. It remains a candidate awaiting acceptance; pre-merge v5 tests do not validate v6. Consult the [validation record](MOBILE-VALIDATION.md) before publishing. Installing the icon does not activate VoLTE or change radio configuration.

Use the [consolidated manual checklist](MOBILE-MANUAL-ACCEPTANCE.md) for this acceptance session. On the current Passport, v5 management disabled and restored the old r14 configuration, leaving a waiting_reboot task. A normal restart was performed, but Root SSH had not returned when recorded; the cause is unknown. No new engine migration or new-candidate IMS/call success has been established. Unlock normally, recover the original entry point and query/resume the existing task. Do not reinstall or submit another disable operation to replace it.

## Installation paths

| Starting state | First step | Entirely on the phone? |
| --- | --- | --- |
| Rooted, working local BAR installer | Download the BAR and open it with that installer | A local route exists; verify Root, final installation version and permissions |
| Working Root terminal and AutoRoot v4 installer | Download the bootstrap ZIP; run its version-specific command | Candidate route; successful v1 installation does not establish v6 installation |
| Rooted, no usable local installer or Root terminal | Restore that existing entry, or install the BAR once from desktop | Browser-only bootstrap is not established |
| Stock, unrooted | Existing Windows/Mac first-Root workflow | No current complete on-phone route |
| AutoRoot v2/v3 or other Root | Validate helper, installer and sandbox behavior separately | Do not inherit v4 bootstrap results |

[AutoRoot v4 documentation](https://bb10.root.sx/blog/autoroot-v4) describes unsigned BAR support and local privilege helpers. A Root label alone does not establish those capabilities. The app does not flash firmware, exploit a stock phone or change global PathTrust.

Obtain the target **0.1.0.6** BAR and checksums from the same candidate handoff or official HTTPS Release. Do not guess an unpublished download URL. With an existing BAR installer, open the `.bar` and confirm system prompts normally. With only a Root terminal, download the same-version `-bootstrap.zip` to Downloads and execute the exact command in its `INSTALL.txt`, using the phone's existing `/var/rootdata/installer`.

Installation passes only with **the same job's final SUD success and an actual registered app version of 0.1.0.6**. Only v1 was confirmed installed as 0.1.0.1. The v2 installer printed completed after a 120-second timeout, without SUD success, while the registered version remained 0.1.0.1. Keep the input and query the original job. A completed message, extracted files, icon or working older version is insufficient; do not repeatedly resubmit an unknown result.

Unlock normally, accept the first-use system app permissions and check the actual UI application version. Reaching a permission dialog does not establish that Cascades loaded. Restore an unavailable Root entry through its original method; do not bypass system permissions or the lock screen.

The release page must publish hashes and the pinned publisher key fingerprint. A public key bundled with an untrusted first download does not authenticate that download. BAR, bootstrap ZIP and signed runtime update ZIP are different artifacts.

## Enable VoLTE

**Resume an existing recovery task first.** Complete the current waiting_reboot stop/restore task after the restart. Once an r14 or r15 installation is stopped and restored, the primary action can offer a phone-service update; management also provides the bundled-update action. Use the final BAR's included signed payload to migrate to r16. Do not import the same-version ZIP for that step. The first-install steps below apply only when the service is genuinely absent.

1. Open **BB10 VoLTE**. It verifies the entry hash, signed payload, Root environment and actual phone/SIM state.
2. Choose the backup location. A mounted SD card is preferred; internal Documents is allowed but cannot protect against losing the phone or storage failure.
3. Tap **Enable VoLTE**. The Root engine repeats device and idle-call checks, saves originals, exports them and verifies every copied hash before activation. Background tasks survive closing the UI; reopening queries the same task.
4. Restart normally from the power menu when asked. Unlock, wait about 3–5 minutes and check again. Passport may need a second normal restart when entering or leaving China Telecom attach policy; the app explains this separately.
5. Once IMS is connected, make and receive a call, each connected for at least 35 seconds. Confirm audio in both directions and LTE during the call. Only then record the four manual checks. The app does not place calls, and registration alone is not calling acceptance.
6. Test SMS separately: incoming/outgoing, short/long, Chinese/English and notifications. The manual call record is bound to the current boot, SIM and payload; changes require revalidation.

Power off before later SIM changes. The automatic engine then selects a supported carrier without USB, SSH or a running computer.

## Manage and recover

After an old installation is stopped and restored, the bundled-update action applies the current BAR's signed payload without another download. Online update checks and offline signed `-update.zip` import require a newer runtime version; same-version or older ZIPs are not ordinary updates. Downloads enforce HTTPS, domain and size restrictions; the Root verifier independently checks the publisher signature and creates a protected private snapshot. Runtime updates do not replace the native C++/QML app: install a newer same-identity BAR for UI updates.

Both r14 → r16 and r15 → r16 adoption require disable, restoration and a normal restart before updating; accept these paths separately. Upgrade the desktop manager to the corresponding r16 version too. Old r14/r15 clients cannot manage the new protocol-2 payload. New desktop and mobile writers share a device lock and persistent transaction records; this cannot stop an old process that already passed its old write checks.

Rollback restores the recorded previous version only after service shutdown and a normal restart. It never invents a desktop backup receipt when only a mobile copy exists. Full service uninstall restores and restarts, verifies/removes owned files and hooks, then requests the final normal restart to verify stock state. Originals and diagnostics remain. Delete the app icon separately afterward; deleting it alone does not remove the service.

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
