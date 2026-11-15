---
name: bb10-volte
description: >-
  Identifies BlackBerry 10 (QNX OS 10.3.3.3216) hardware variants and operates
  unified 3-carrier VoLTE (China Mobile, Unicom, Telecom), native BB10 phone app
  installation, SSH pairing, stock 10.3.3.3216 firmware upgrade, AutoRoot v4
  preparation/flashing, and configuration rollback across all 16 supported models
  (Q10 SQN100-1..5, Classic/Q20 SQC100-1..5, Passport/Q30 SQW100-1..4, Porsche
  Design P'9983 SQK100-1..2). Use whenever the user asks to detect, root, pair,
  install, update, troubleshoot, or restore VoLTE on a BlackBerry 10 device in
  this repository.
---

# BB10 VoLTE Agent Skill (`bb10-volte`)

Operate `bb10-volte` safely and deterministically across all **16 supported BlackBerry 10 hardware variants** (`SQN100-1..5`, `SQC100-1..5`, `SQW100-1..4`, `SQK100-1..2`) and **3 Chinese carriers** (`460-00/02/04/07/08` China Mobile, `460-01/06/09` China Unicom, `460-03/05/11/12` China Telecom) using the headless JSON CLI [ai_skill.py](../../../tools/ai_skill.py) (also callable via [bb10_skill.py](./scripts/bb10_skill.py)).

## 0. Scope & Non-Negotiable Safety Rules

1. **Stock BB10 (QNX `10.3.3.3216`) Only**:
   - This project targets **BlackBerry 10 OS `10.3.3.3216` (32-bit ARM QNX)** using verified `/radio/bin/ims_rrm` runtime copies and SSH/BAR provisioning.
   - If the user's BlackBerry Passport has been flashed to **Android 11 (LineageOS 18.1)**, stop immediately and direct them to the sister project: `https://github.com/Octo-o-o-o/qcom32-volte` (`https://qcom32-volte.octoooo.com/`).
2. **Use `tools/ai_skill.py`, Never Legacy `tools/bb10.py`**:
   - [ai_skill.py](../../../tools/ai_skill.py) drives the current 16-model unified 3-carrier engine (`AutoClient`), native mobile app installer (`MobileAppInstaller`), pairing helper, and firmware/Root workflows.
   - Do **not** run legacy single-carrier `tools/bb10.py` for normal user setups.
3. **Zero Credential & PII Persistence**:
   - **Never** ask for or pass the phone lock/device password in CLI flags, scripts, logs, commits, or reports. Native flashing tools prompt interactively in their own console window when needed.
   - **Never** print or commit SSH private keys, `private/` contents, IMSI, ICCID, PIN, or phone numbers.
4. **SSH Failure Never Proves "Unrooted"**:
   - `connection_refused`, `authentication_failed`, or `connection_setup_required` only means SSH is not currently connected—the phone may already be rooted (e.g. AutoRoot SSH not yet triggered after boot, or this computer not paired yet). Always ask the owner or pair before suggesting a destructive reflash.
5. **Destructive Operations Require Explicit Human Confirmation**:
   - Stock `10.3.3.3216` upgrade (`firmware flash-upgrade`) and initial AutoRoot flashing (`firmware flash-root`) **erase all user data on the phone**. Never pass `--confirm-erase-device` without explicit confirmation from the user in the current conversation.
6. **Never Force-Kill Radio Daemons & Never Fake Call Acceptance**:
   - Never run `kill`/`slay` on `ims_rrm`, `qct_rrm`, or `io-pkt`. Follow normal power-menu restart prompts.
   - IMS `200 OK` registration is necessary but **not** final acceptance: always ask the human user to verify outbound + inbound native dialer calls (`>= 00:35` connected audio), LTE retention, and SMS.
7. **License Boundary**:
   - Licensed under [PolyForm Noncommercial License 1.0.0](../../../LICENSE): free for personal/noncommercial use; paid flashing/installation services, pre-installed phone sales, or commercial redistribution require prior paid commercial licensing via `octoooo@octoooo.com`.
   - macOS desktop builds are frozen at `v0.5.0-r43`; Windows desktop (`r47`) and the native BB10 mobile app (`0.1.0.47`) continue to receive updates.

---

## 1. Always Start Here: Identify Device & Model

Run the read-only detector first (performs zero writes to the phone):

```bash
python tools/ai_skill.py detect
```

- Prefer the workspace Python 3.14 environment when available (e.g. `.venv/Scripts/python.exe` on Windows); `detect`, `models`, `pair`, `mobile-app`, and `volte` also run on Python 3.10+, while Windows offline Root archive `.tar.zst` extraction requires **Python 3.14**.
- To inspect model support, LTE bands, required stock firmware SHA-256, and carrier notes for any variant (or family alias `q10`, `q20`, `classic`, `passport`, `q30`, `p9983`, `9983`) even without a phone attached:

```bash
python tools/ai_skill.py models
python tools/ai_skill.py models --variant SQC100-1
python tools/ai_skill.py models --variant passport
```

Read `recommended_next_step.code` from `detect` JSON output and follow the matching workflow below. For the full 16-model hardware/board/band/firmware matrix, read [models-and-carriers.md](./references/models-and-carriers.md).

---

## 2. Operate Any Supported Model by State

### Branch A — Phone Already Rooted (`ssh_root.verified_uid0 == true`)

Once Root SSH (`EUID == 0`), OS `10.3.3.3216`, and the 6 stock QNX native binary hashes are verified:

1. **Install or Update the Standalone Native BB10 Phone App (`0.1.0.47`)** *(Recommended for all rooted users so they can manage, back up, activate, and switch SIMs directly on the phone without a computer)*:
   ```bash
   python tools/ai_skill.py mobile-app inspect
   python tools/ai_skill.py mobile-app install
   ```
2. **Install & Activate Unified 3-Carrier VoLTE Directly from Computer** *(Requires a ready China Mobile `460-00/02/04/07/08`, Unicom `460-01/06/09`, or Telecom `460-03/05/11/12` USIM without ISIM)*:
   ```bash
   python tools/ai_skill.py volte probe
   python tools/ai_skill.py volte install
   ```
   - `volte install` automatically backs up and verifies the original configuration files on both phone and computer before activating.
3. **Normal Reboot & Post-Boot Verification**:
   - Ask the user to **restart normally via the phone power menu**, unlock the phone, and wait **3–5 minutes**, then check:
   ```bash
   python tools/ai_skill.py volte status
   ```
   - **Passport (`SQW100-1..4`) China Telecom (`460-11`) Rule**: When `status_view.check_code` is `unified_carrier_reboot_required` (`phase == "carrier_reboot_required"`), the attach policy has been saved and the Passport baseband needs **one additional normal power-menu restart** (Airplane Mode does not substitute).
   - When `registration_ready == true` (`ims == "connected"`, `register_status == "200 OK"`, `ran == "LTE"`), instruct the user to unplug USB and test outbound + inbound calls (`>= 00:35` each) and SMS.

### Branch B — Phone Already Rooted, Computer Not Yet Paired (`ssh_root.verified_uid0 == false`)

Do **not** reflash an already-rooted phone! Establish SSH trust instead:

- **Case B1 (`ssh_error == "connection_refused"` on AutoRoot v4)**:
  Ask the user to open **BlackBerry World** once on the phone and wait ~30 seconds (AutoRoot hooks its startup to launch `sshd` on `169.254.0.1:22`), then re-run `python tools/ai_skill.py detect`.
- **Case B2 (User has the previous Root kit folder on this PC)**:
  ```bash
  python tools/ai_skill.py pair import-ssh --folder <PATH_TO_KIT>
  # Verify phone_host_key_fingerprint with the user, then confirm:
  python tools/ai_skill.py pair import-ssh --folder <PATH_TO_KIT> --confirm-host-key
  ```
- **Case B3 (Authorize this computer from the phone)**:
  ```bash
  python tools/ai_skill.py pair prepare --export-dir ./private/pair-export
  ```
  1. Have the user copy `bb10-pair-<id>-request.json` (or `.py` if the BB10 VoLTE app is not installed yet) to phone `Downloads` (`/accounts/1000/shared/downloads`).
  2. Authorize via **BB10 VoLTE app → Management & Recovery → Connect Computer**, or run the guarded snippet from `-instructions.txt` in an existing `__root` / `u_root` terminal.
  3. Copy `bb10-pair-<id>-result.json` back to the computer and finish:
     ```bash
     python tools/ai_skill.py pair finish --result <PATH_TO_RESULT_JSON>
     python tools/ai_skill.py pair finish --result <PATH_TO_RESULT_JSON> --confirm-host-key
     ```

### Branch C — Unrooted Phone Already on OS `10.3.3.3216`

Supported for the **15 AutoRoot recipe variants** (`SQN100-1..5`, `SQC100-1..5`, `SQW100-1..4`, `SQK100-1`). Note: `SQK100-2` has no verified local first-flash recipe. Require at least **15 GB** free disk space and **Python 3.14** on Windows (or macOS 14+ if using a Mac source setup):

1. Check firmware cache & import user-downloaded stock archive if needed:
   ```bash
   python tools/ai_skill.py firmware status --variant <SQX100-Y>
   # Optional if downloaded via browser (ZSpace / Baidu / Archive.org):
   python tools/ai_skill.py firmware import-stock --variant <SQX100-Y> --file <ARCHIVE_PATH>
   ```
2. Prepare and hash-verify the model-bound Root kit offline (does **not** touch the phone):
   ```bash
   python tools/ai_skill.py firmware prepare-root --variant <SQX100-Y>
   ```
3. **Ask the human user for explicit data-erasure confirmation**, ensure only **1** matching phone is attached on USB, then launch native staged flashing:
   ```bash
   python tools/ai_skill.py firmware flash-root --kit <KIT_NAME> --confirm-erase-device
   ```
   - During `os` stage on AutoRoot v4, `writing 100%` followed by exit code `73` (`Failed to load images` / `Security error`) is **expected**; `flash-root` automatically verifies this and proceeds to the matching `radio` stage (exit `0`).
4. After boot: ask the user to complete initial BB10 setup (`OobeCompleted=1`), enable Development Mode, wait for the Root notification, then run `python tools/ai_skill.py detect` and proceed to **Branch A**.

### Branch D — Phone on Older OS (`< 10.3.3.3216`, e.g. `10.3.1` / `10.3.2` / `10.3.3.2xxx`)

Never flash `3216` Root partitions directly onto an older OS. Upgrade to stock `10.3.3.3216` first (requires **24 GB** free space and explicit human wipe confirmation):

```bash
python tools/ai_skill.py firmware prepare-upgrade --variant <SQX100-Y>
# After explicit human data-wipe confirmation:
python tools/ai_skill.py firmware flash-upgrade --kit <KIT_NAME> --current-os <OBSERVED_OS> --confirm-erase-device
# Wait for phone to boot, then verify discovery reads back 10.3.3.3216:
python tools/ai_skill.py firmware verify-upgrade-boot --kit <KIT_NAME>
```

Then have the user complete initial setup / enable Development Mode and run `firmware flash-root --kit <KIT_NAME> --confirm-erase-device`.

---

## 3. Lifecycle: Upgrade, SIM Swap, Disable, Rollback & Uninstall

- **In-Place Payload Update (`r42`–`r46` → `r47`)**:
  - If `probe.update_available == true` and `probe.can_update == false`, stop VoLTE first (`python tools/ai_skill.py volte disable`), have the user **restart normally via power menu**, then run `python tools/ai_skill.py volte install` and restart normally once more.
- **Swapping SIM Cards**:
  - Power off before swapping SIMs (hot-swapping is not supported). Boot normally; the unified service automatically selects China Mobile / Unicom / Telecom by home PLMN (`460-00/02/04/07/08`, `460-01/06/09`, `460-03/05/11/12`). Passport entering or leaving China Telecom requires waiting ~5 minutes after boot and performing one extra normal restart.
- **Temporarily Disable / Re-enable**:
  ```bash
  python tools/ai_skill.py volte disable
  python tools/ai_skill.py volte enable
  ```
- **Full Configuration Rollback or Clean Uninstall**:
  ```bash
  python tools/ai_skill.py volte rollback
  python tools/ai_skill.py volte uninstall
  ```

For edge cases (multi-USB conflicts, `OobeCompleted=0` setup hangs, Blue-LED post-reboot data loss `KB36747` / `bb10-blue-led-recovery`, Windows USB drivers, and maintainer release checks), read [workflows-and-troubleshooting.md](./references/workflows-and-troubleshooting.md).
