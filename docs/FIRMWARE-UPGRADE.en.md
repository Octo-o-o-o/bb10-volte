# Phone firmware upgrades and model matching

[简体中文](FIRMWARE-UPGRADE.md) · [First run](FIRST-RUN.en.md) · [Connection recovery](RECOVER-CONNECTION.en.md)

`0.5.0-r13` provides stock firmware upgrades and integrates personal Root-image preparation for Q10, Classic / Q20, and Passport / Q30. The required **OS is exactly 10.3.3.3216**. This is not the desktop application version or a minimum supported OS. Numeric comparison also accepts the firmware filename spelling `10.3.03.3216`.

This is a full firmware reflash that erases phone data, existing Root, and authorization. Preparation can run automatically; connecting a phone never starts flashing. Software tests, offline image checks, and packaging tests do not establish physical upgrade acceptance. The candidate UI retains that limitation.

## Version routing

| Detected state | Behavior |
| --- | --- |
| Below 10.3.3.3216 | Open stock upgrade preparation; block direct Root flashing |
| Exactly 10.3.3.3216 | Skip the stock upgrade; continue according to verified Root / connection state |
| Above 10.3.3.3216 | Stop; never automatically downgrade |
| Missing or malformed version, or multiple devices | Block stock and Root flashing until detection succeeds |

The application reads anonymous metadata on the directly attached USB link. A terminal screenshot, helper name, or permission error does not establish the OS version.

## Prepare and execute

1. Connect only one phone, unlock it, and establish USB networking. Use the firmware action in Connection help, or “System upgrade / resume upgrade record” in the first-run wizard.
2. Verify the exact hardware variant: SQN100-1–5 for Q10, SQC100-1–5 for Classic, or SQW100-1–4 for Passport. Detected hardware takes precedence over manual selection. Recorded VoLTE acceptance still covers only SQN100-3, SQC100-2, and SQW100-4.
3. Prepare upgrade and Root materials with at least **24 GB** free. The application verifies pinned inputs and creates private keys and matching Root images. The download/import entry can populate the cache first. Offline selection authorizes computer-side preparation only.
4. Back up the phone, acknowledge data loss, and confirm the displayed model and old → target OS. The backend reads the phone again before starting. Windows runs the matching original EXE. Mac uses verified native tools to write the stock signed OS, then radio. Enter device passwords only in the native console.
5. Wait for the phone to boot, complete required phone setup, unlock it, restore USB networking, and verify the OS in the application. Successful loader output only establishes the write stage. Root remains separate until the phone reports the exact target OS.
6. Continue to Root and confirm that operation separately. The application reuses the prepared personal images, then verifies phone identity and effective UID 0 before returning to VoLTE checks.

This is not a lossless OTA update. It does not accept phone setup or password prompts automatically. A phone already rooted on the supported OS should use connection recovery.

## Interruptions and resumption

Preparation, awaiting-boot, and OS-verified records survive application restart. Selecting a record does not resume flashing or reuse a prior erase confirmation.

Any error, missing result, timeout, or interrupted write preserves the journal and shared flash lock. Stock and Root retry are blocked. Closing a window cannot undo a write. Keep the phone state and computer materials; establish whether the original loader is still running and which stage completed before any recovery. Do not delete the lock or replay console scripts blindly.

Stock upgrades require complete success. They **never accept the Windows exit-73 exception used by the specific AutoRoot OS recipe**. Native Mac flashing likewise requires complete evidence.

## Verification limits

Original EXEs are pinned by source SHA-256. Mac signed OS/radio components additionally require fixed sizes and independent SHA-256 values from [stock-upgrade.json](../materials/stock-upgrade.json). This establishes consistency with pinned inputs, not a separate manufacturer-signature certification. Personal Root outputs are bound to their model, platform, build receipt, and hashes.

Downloads always verify HTTPS certificates and hostnames. If the bundled Mac Python has no default CA store, it uses the OS-managed system certificates. Existing roots and explicit trust settings take priority; users do not need to install Python certificates separately.

All three original firmware inputs have been freshly split and compared offline. Fault-injection tests cover versions, models, corrupt materials, cancellation, interruptions, replay, and boot readback. The physical old-OS → stock → boot → Root → verified connection sequence still requires separate acceptance; existing nine-case VoLTE results do not replace it.
