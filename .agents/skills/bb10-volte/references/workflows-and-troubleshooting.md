# Workflows, Edge Cases & Troubleshooting Runbook

Detailed reference guides in `docs/`:
- Unified 3-carrier setup & SIM switching: [AUTO-CARRIERS.md](../../../../docs/AUTO-CARRIERS.md)
- r49 network waiting, safe retries and explicit PLMN assistance: [NETWORK-RESILIENCE.en.md](../../../../docs/NETWORK-RESILIENCE.en.md)
- First-time Root preparation & staged flashing: [FIRST-RUN.md](../../../../docs/FIRST-RUN.md)
- Old-OS (`< 10.3.3.3216`) stock upgrade: [FIRMWARE-UPGRADE.md](../../../../docs/FIRMWARE-UPGRADE.md)
- Pairing an already-rooted phone: [COMPUTER-PAIRING.md](../../../../docs/COMPUTER-PAIRING.md)
- Recovering lost SSH connection materials: [RECOVER-CONNECTION.md](../../../../docs/RECOVER-CONNECTION.md)
- Disk cache locations & cleanup: [DISK-CLEANUP.md](../../../../docs/DISK-CLEANUP.md)

---

## 1. USB Discovery & Multi-Device Isolation

- BlackBerry 10 phones enumerate with USB Vendor ID `0x0FCA` and create a link-local `/30` USB network interface (typically host `169.254.0.2` ↔ phone `169.254.0.1`, or a stock DHCP `/30` lease before AutoRoot).
- **Multiple Phones Attached (`usb.usb_count > 1`)**:
  - Two BB10 phones attached simultaneously can both claim `169.254.0.1` on separate USB NICs.
  - [ai_skill.py](../../../../tools/ai_skill.py) refuses ambiguous discovery and flashing when `usb_count > 1`. Instruct the user to unplug extra BB10 devices so only the single target phone remains connected.
- **USB Hardware Present, No USB Network (`usb_present == true`, `usb_network == false`)**:
  - First ask the user to unlock the phone screen and verify a data-capable USB cable.
  - On Windows, if drivers are missing (`driver_ready == false`), run:
    ```bash
    python tools/ai_skill.py firmware prepare-driver
    python tools/ai_skill.py firmware install-driver --kit <DRIVER_KIT_NAME>
    ```

---

## 2. Initial Setup (`OobeCompleted=0`) & Development Mode

- After a fresh stock `10.3.3.3216` upgrade or factory wipe, `/cgi-bin/discovery.cgi` reports `OobeCompleted=0`.
- While `OobeCompleted=0`, BB10 blocks normal app-management/development sessions even if the device password is correct.
- **If the user is stuck in BB10 Initial Setup** (because BlackBerry ID / software update servers are retired):
  1. On the **Mobile Network** setup screen, triple-press the **Power button** to enable BB10 Screen Reader and use the skip interaction if Wi-Fi setup blocks "Next" without internet/BBID.
  2. If **BlackBerry ID** prompts appear, skip BBID.
  3. On **Regional Update** / **Software Update**, press physical key `N` (or tap Next), wait for the update check failure prompt, and swipe left as instructed to finish setup (`OobeCompleted=1`).
  4. Enable **Settings → Security and Privacy → Development Mode**.

---

## 3. Expected AutoRoot v4 Exit Code `73` vs Real Flash Errors

- During `firmware flash-root`, AutoRoot v4 writes the modified OS image to `100%` and then BB10's bootloader prints:
  - `Error: Failed to load images.`
  - `Error: Security error.`
  - Process exit code `73`.
- [root_flash.py](../../../../tools/root_flash.py) explicitly validates `writing_complete == True` + `exit_code == 73` + expected security lines (`expected_v4_os_security_result == True`) and automatically proceeds to flash the matching signed `radio` image (`Done.` + `exit_code == 0`).
- **Uncertain / Interrupted Flash (`flash_state_unknown`)**:
  - If a flash stage fails mid-write or times out, `root-flash.lock` and the kit journal remain locked intentionally. **Never delete the lock and blindly re-run**—first check physical phone boot/USB state via `python tools/ai_skill.py detect --skip-ssh`.

---

## 4. Apps Disappear & Blue Notification LED After Normal Reboot (`KB36747`)

- **Symptom**: Everything installs and verifies cleanly (`83`/`65` app files, `/var/bb10_volte` payload, `EUID == 0`), yet after a normal reboot `/apps/com.octolab.bb10volte.*` and `/var/bb10_volte` vanish (often accompanied by a solid **blue LED** during/after boot).
- **Root Cause**: A known historical BB10 eMMC/filesystem rollback issue (`KB36747`) on affected hardware units where `/var` and user data revert across reboots—**not** caused by `bb10-volte`, and reflashing stock `3216` + AutoRoot alone does **not** clear it.
- **Resolution**:
  - Direct the user to the dedicated recovery guide and hash-verified historical utility notes at `https://github.com/Octo-o-o-o/bb10-blue-led-recovery`.
  - After running `BlackBerryFix`, **do not trust `"Fixed"` alone**: verify that a small test file created and `fsync`ed on the data partition survives two normal reboots before reinstalling `bb10-volte`.

---

## 5. Maintainer Verification Before Committing Changes

Whenever modifying code, documentation, or skill files in this repository, run the full public-release and regression gate before pushing to GitHub:

```bash
python -m unittest discover -s tests -v
python -m compileall -q device tools tests mobile/runtime .agents/skills
python tools/check_release.py --check-git
git status -sb
```

- Note: `python tools/package_release.py` (run automatically on clean checkouts in CI) writes `dist/bb10-volte-<version>-experimental.zip`; on a maintainer machine that keeps frozen release artifacts inside `dist/`, bump `desktop_revision` first or run in an isolated checkout before invoking `package_release.py`.

- [check_release.py](../../../../tools/check_release.py) enforces an **exact bidirectional match** between `git ls-files` and the audited public allowlist (`TOP` + `PATTERNS`), verifies every payload/helper/BAR SHA-256 manifest, checks every relative Markdown link, rejects symlinks, and scans all text files for accidental tokens, keys, IMSI/ICCID, phone numbers, and local user paths.
- Never overwrite immutable published release tags or binary assets (`v0.5.0-r42`–`v0.5.0-r47`, `0.1.0.43`–`0.1.0.47`, or frozen macOS `v0.5.0-r43`) unless explicitly cutting a new release revision authorized by the maintainer.
