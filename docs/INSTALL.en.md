# Installation on Windows

[简体中文](INSTALL.md) | **English**

This recipe was tested with a **Q10 SQN100-3, BB10 10.3.3.3216 and a China Unicom 460-01 USIM in Beijing**. The persistent service remains experimental; see the [validation record](VALIDATION.en.md). Run commands from the repository root with Python 3.14.

## 1. Check the baseline

Confirm working LTE data on the Q10 and VoLTE service on the subscription, preferably by checking the SIM on a supported phone. Keep a matching stock recovery image, charge the Q10 and use a reliable USB data cable. Initial Root flashing erases user data; back it up first.

If root SSH and USB networking already work and the native file hashes match, skip to step 4 with your existing, verified SSH configuration. The installer checks the actual files rather than relying only on the displayed firmware version.

## 2. Prepare USB drivers if needed

No driver reinstall is required when Windows already recognizes the phone and its USB network reliably. Otherwise:

```powershell
python tools/fetch_materials.py --with-usb-drivers
python tools/prepare_usb_drivers.py --seven-zip "C:\Program Files\7-Zip\7z.exe"
```

The fetch command obtains both the Root inputs and optional driver parts. Preparation checks the seven archive parts, BlackBerry-signed EXE, package-contained x64 MSI and Microsoft-signed driver catalog against [usb-drivers.json](../materials/usb-drivers.json). It only extracts and verifies files under `private/windows-usb/`.

If installation is necessary, save your work and run the following from an administrator PowerShell in the repository root:

```powershell
.\tools\install_usb_drivers.ps1
```

The script installs the verified RIM USB INF and x64 Device Manager MSI, records a private log and prevents automatic reboot. Exit code `3010` requests a later Windows restart. The old vendor MSI can stop named processes; the script refuses installation when potentially affected processes are running. Investigate the reported process before continuing. Driver-signature checks and UAC do not need to be disabled. More detail is in [WINDOWS-USB.md (Chinese)](WINDOWS-USB.md).

## 3. Prepare initial Root and your own SSH identity

Install 7-Zip and the pinned Git for Windows/OpenSSL combination listed in [the requirements](../README.en.md). Allow approximately 15 GB of local workspace. Material versions and hashes are fixed in [sources.json](../materials/sources.json).

```powershell
# Download missing inputs, or place the specified files in downloads/ yourself.
python tools/fetch_materials.py
python tools/fetch_materials.py --verify-only

# Offline only: create fresh keys and prepare the build directory.
python tools/prepare_root.py --seven-zip "C:\Program Files\7-Zip\7z.exe"

# Offline only: build and verify the owner-specific images.
python tools/build_root.py
```

The output is `private/root-kit/`. Preparation preserves BlackBerry World, omits broad BerryCore application grants, generates individual SSH client and host keys and replaces the package's shared authorization. It refuses to overwrite an existing kit. `build_root.py` invokes the image builder's batch operation, not a flashing command. Original IFS/RCFS/SIG2/MBR partitions and radio must match [stock-partitions.json](../materials/stock-partitions.json).

Following [the AutoRoot v4 author's instructions](https://bb10.root.sx/blog/autoroot-v4), flash the generated `private/root-kit/images/Q10_10.3.03.3216_SQN100-1-2-3-4-5_os.exe`, then the matching `Q10_10.3.03.3216_SQN100-1-2-3-4-5_radio.exe`. Both must come from the same build. In the recorded trial the radio stage returned `Done` and the phone booted; the OS stage had reported an error. Treat any error according to the complete logs, subsequent radio result and actual boot state; do not assume errors are harmless.

Once the phone boots, open **BlackBerry World** once and wait for Root. The store can remain on its loading screen; that does not prevent the Root trigger. A Term49 icon alone is not root verification: confirm effective UID `0` over SSH.

The prepared authorization allows only the USB computer address `169.254.0.2`; the Q10 address is `169.254.0.1`. Test:

```powershell
ssh -F private/root-kit/ssh_config q10-root "echo connected"
ssh -F private/root-kit/ssh_config q10-root "id -u"
```

The host key is pinned to the key generated for your own images. If the phone was rooted with a different key set, use that verified configuration instead. A key mismatch needs investigation rather than disabling host-key checks.

## 4. Install and start the VoLTE service

Keep the phone powered on with USB connected and its own SIM inserted. Replace the SSH configuration path if yours differs; use `--host` if the alias is not `q10-root`.

```powershell
python tools/q10.py install --ssh-config private/root-kit/ssh_config
python tools/q10.py check --ssh-config private/root-kit/ssh_config
python tools/q10.py start --ssh-config private/root-kit/ssh_config
```

Before changing network configuration, the installer checks native hashes, the original voice policy `00`, existing IMS/VPN state and software provider state. Finish any previous experiment before proceeding; do not delete unknown objects to pass preflight.

Files are installed under `/var/rootdata/q10_volte`; the startup entry is `/var/addons/q10-unicom-volte/init/start.sh` through AutoRoot v4's addon mechanism. The stock IMS binary remains unchanged. The manager runs on the phone after the desktop command returns. First start sets IMS-preferred voice through the native API and may briefly reload the radio; it then waits for LTE/SIM readiness, establishes the IMS APN and starts native IMS.

## 5. Check status and calls

After approximately one minute:

```powershell
python tools/q10.py status --ssh-config private/root-kit/ssh_config
```

Expect `phase=running`, `manager_alive=true`, `register_status="200 OK"` and `ran="LTE"`. Confirm the current native process is alive and IMS is connected. Complete [incoming, outgoing, audio, reboot and unplugged acceptance](VALIDATION.en.md).

The startup entry runs after Root is ready. If Root/SSH has not appeared after a reboot, open BlackBerry World once and wait. Fully automatic recovery of the revised service remains pending hardware acceptance.

## 6. Stop, restore, update and collect

Hang up before stopping. These commands manage only this project's processes and changes:

```powershell
# Stop and restore original voice policy, APN and owned VPN/provider state.
python tools/q10.py stop --ssh-config private/root-kit/ssh_config
python tools/q10.py status --ssh-config private/root-kit/ssh_config
python tools/q10.py check --ssh-config private/root-kit/ssh_config

# Stop and disable startup on the next Root initialization.
python tools/q10.py disable --ssh-config private/root-kit/ssh_config

# Save private diagnostic data locally.
python tools/q10.py collect --ssh-config private/root-kit/ssh_config

# Remove the startup entry; keep programs and recovery records for inspection.
python tools/q10.py uninstall --ssh-config private/root-kit/ssh_config
```

Stopping takes time. Verify `stopped`, `manager_alive=false`, no project IMS process, original voice policy `0` and provider `-1`. A leftover PPS `register_status="200 OK"` can be stale after stop. `cleanup_required` indicates a recovery conflict; preserve diagnostics rather than repeatedly reinstalling.

If native IMS exits independently, `native_exited` retains the journal and avoids reloading the radio during possible system shutdown. Once the device is stable, collect diagnostics, explicitly stop and verify restoration.

For an update, first stop and complete the restoration checks above, then run:

```powershell
python tools/q10.py update --ssh-config private/root-kit/ssh_config
python tools/q10.py start --ssh-config private/root-kit/ssh_config
```

Update checks the previous installation's file ownership and preserves the recovery journal. Collected logs go under ignored `private/` and may contain phone numbers, SIM identifiers and authentication data. Do not attach them directly to public issues; see [CONTRIBUTING.md](../CONTRIBUTING.md).
