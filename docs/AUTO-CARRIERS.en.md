# Automatic carrier setup candidate

[简体中文](AUTO-CARRIERS.md)

Desktop `0.5.0-r2` uses the same installation workflow and phone payload on Windows and macOS. After the initial installation, a normal phone boot reads the current SIM and generates its IMS identity, carrier domain and data configuration. Subsequent SIM changes need no computer connection or flash.

The scope is **SQN100-3, SQC100-2 and SQW100-4 on OS 10.3.3.3216**, with Mobile **460-00**, Unicom **460-01** and Telecom **460-11** USIMs without ISIM. Other variants, operating systems, MNCs and SIM routes are rejected. Root and a trusted SSH connection must already work; this workflow does not perform the initial Root flash.

This unified payload needs its own hardware acceptance. Earlier model-specific trials are not proof that all nine new combinations work. As of 2026-10-31, Q20 Mobile passed installation, automatic registration after a normal restart and bidirectional calls with USB disconnected. The two established calls lasted about 4.2 and 4.8 seconds; the first outgoing attempt connected, the owner confirmed two-way audio and LTE, and all 151 radio samples were LTE. Calls longer than 30 seconds and cross-carrier SIM changes remain pending. Passport is installed and awaiting restart/call acceptance; Q10 is awaiting a working USB data connection.

## Use

1. Connect the target phone, open **Automatic carrier setup**, and check its exact model and current SIM.
2. Choose **Back up and install**. The app downloads and verifies the four original radio configuration files and, where applicable, the old Root boot script. It then retires the old manager and installs the new startup entry. Previous files and acceptance records remain available.
3. Restart from the phone's power menu. Wait for normal LTE and IMS registration before testing incoming/outgoing calls, two-way audio and LTE throughout.
4. For later SIM changes, power off, change SIM and boot normally. Configuration is generated on the phone. A hot-swap snapshot is not completed acceptance.
5. To restore automatic startup after disabling it, wait for the manager to finish restoring, choose **Enable automatic setup**, then restart. Main-window management prioritizes the unified service to prevent reactivating the migrated legacy service.
6. Passport may need one additional normal restart when changing the Telecom attach policy. The app reports this as **Carrier attach policy saved. Restart normally once more.** Airplane mode does not replace that restart.

## Integrated behavior

- Mobile uses an EarlySdp=0 runtime IMS copy, previously tested on Q20/Passport. Original system binaries remain intact.
- Telecom attach changes use verified DCA publication and original backups; changing away restores the original policy.
- Software crypto remains registered until normal reboot. Only one native IMS start is permitted per boot, avoiding repeated-start bearer failures.
- SIM identities stay in phone-private state. Q20's number display uses the current native REGISTER 200 result. Telecom name correction is scoped to the current home 460-11 SIM with normal LTE.
- Immutable code and SIM-generated configuration have separate integrity checks. Unknown system hashes, missing backup receipts, independently modified settings and active calls block relevant writes.

Registration is not call acceptance. Short calls do not establish long-call or long-term stability. Keep the candidate label until the nine combinations and SIM transitions have been accepted.
