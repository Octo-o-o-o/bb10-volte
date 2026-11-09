# First use and connection setup

The current branch shows exact-variant support before downloads and flashing. Automatic VoLTE currently covers SQN100-3, SQC100-2 and SQW100-4. A Root recipe does not establish VoLTE support. Unsupported activation preparation pauses early; users who only need stock recovery or standalone Root can select that purpose explicitly. See the [complete variant plan (Chinese)](ALL-VARIANTS-COVERAGE-PLAN.md). These early checks are not included in the published r14.

`0.3.3-r3` starts with **Connect phone / Connection help**, with SSH paths under advanced settings. Released r6 and earlier applications may still use the older labels below; this flow is included in the new Windows EXE and Mac DMG. Reopening rechecks the last successful connection once. Pairing requests and completed image preparation can be resumed. Connection failure never establishes that a phone is unrooted.

[简体中文](FIRST-RUN.md) · [GUI](GUI.en.md)

The `0.5.0-r12` candidate adds [stock OS upgrades](FIRMWARE-UPGRADE.en.md). An OS below 10.3.3.3216 requires matching stock preparation, explicit erase confirmation, and boot readback before separate Root confirmation. Unknown and newer versions stop. Combined stock/Root preparation needs 24 GB free; the Root-only 15 GB requirement below is insufficient for this flow. Physical old-OS upgrade acceptance is pending.

The First use wizard provides connection checks, Windows SSH components, USB drivers and initial Root preparation. The local `0.5.0-r11` candidate supports matching firmware, image preparation and staged flashing for Q10, Q20 and Q30.

## First connection on a Mac

Start with the [Mac phone guide](MACOS.en.md). Source integrates experimental native preparation and separately confirmed staged execution for Q10, Q20 and Q30 on macOS 14+. This change has no new DMG build or hardware first-flash acceptance. A rooted phone with personal connection materials can import them or use Check device. A rooted phone with no old Windows files can authorize a fresh Mac key in an existing working phone Root terminal. With neither valid materials nor a working Root terminal, direct connection is unavailable. New authorization persistently appends a public key to phone SSH access and requires the owner's explicit `PAIR`; development mode does not grant Root.

An existing microSD card, Mac card reader and phone file manager can transfer the public script/result without assuming Finder can mount internal phone storage or requiring old Link. See the [recovery transfer steps](RECOVER-CONNECTION.en.md#mac-transfer-without-old-connection-files) and their untested limits.

Published `0.3.2-r5` passed daily Mac connection checks in the main window, but its First use Root probe can misreport a failure and its USB facts are incomplete. Repository source fixes do not update that DMG; see [Mac acceptance](../materials/macos-device-validation-2026-10-28.json).

## Already-rooted phones

Already-rooted devices can use Check device directly. The app discovers saved references, known owner-created kits, a configuration next to a portable executable and explicit `bb10-root` / `q10-root` aliases. Unsaved automatic discovery is limited to the direct USB address and keeps strict host verification. Other addresses require an explicitly imported configuration. Only configuration references are saved; private keys stay in their original kit.

Already-rooted phones without connection files can use Recover connection to import a login key or authorize this computer through an existing phone Root terminal. The flow is shared by Windows and macOS; see [connection recovery](RECOVER-CONNECTION.en.md).

**The connection field may remain empty.** Check device discovers both `root-kit/ssh_config` and `root-kit-*/ssh_config` in the owner's private directory, verifies the connection and fills the field. A successful selection is restored on the next launch. Auto preparation creates these files; after flashing and Root verification the wizard passes the configuration to the main window. Numbered kits remain discoverable after restarting before a connection has been saved. Multiple kits are selected by verified access, never merely by which file is newest. An already-rooted phone without its matching key needs original personal materials or new authorization through an existing working Root terminal.

An installed service is read as an existing installation. Normal registration/LTE displays enabled; startup displays pending. Its active configuration is expected rather than an installation failure. USB, development mode, SSH, Root and IMS are distinct. Development mode being disabled does not establish missing Root, and working Root SSH does not require development mode to remain enabled. Anonymous USB discovery reads only allowlisted model, OS and development-mode fields. Diagnostic checks do not open and abandon development sessions or raw SSH sockets.

On initial use, unlock and connect the phone. Use the wizard's USB/driver checks and on-phone instructions. Development mode is under Settings → Security and Privacy. A rooted device may need BlackBerry World opened once to trigger local startup; the store's network error or endless loading does not establish Root failure. If SSH still refuses, use a normal phone-menu reboot and wait for Root. A key mismatch requires the original trusted profile, not disabled checks or reflashing.

## Experimental Mac initial preparation and execution

On macOS 14+, r6 adds **First use → Initial Root** for private Q10 materials/images. The app obtains pinned architecture-matched bb10mt/7-Zip and private libusb/LZO libraries without a Homebrew installation. Preparation does not touch BootROM or flash; it preserves AppWorld and verifies stock partitions. Staged execution requires rechecking one phone, its variant, USB `169.254.0.2`, backup acknowledgement and the extra Mac acknowledgement that the phone is not rooted and that the experimental validation scope is understood. A separate erase confirmation is still required before opening Terminal.

`0.5.0-r14` builds integrate automatic Root preparation and staged flashing for Q10, Classic (Q20), and Passport (Q30). Select firmware for the exact hardware variant; initial flashing erases data. Offline Windows builds and verification passed for all three firmware families. r14 passed first Root on Windows / Passport SQW100-4 and Apple Silicon Mac / Q20 SQC100-2, including new-key UID 0, fresh installation and normal-menu reboot autostart. Native stages ran through acceptance entry points; complete first-use GUI operation, Q10 first Root and Intel USB flashing remain unverified. Q20 uses its verified STA100/Z30 EXE, and Passport uses its own archive and partition baseline. Neither uses Q10 images.

Any Mac native error, missing completion evidence, cancellation or unknown outcome pauses with state preserved, without retry or radio continuation. **The Windows exit-73 exception does not apply on Mac.** Mac/Q20 native first Root is recorded separately, and old r5 lacks this integration. See [Mac initial Root](MACOS.en.md#can-a-mac-perform-initial-root).

## Windows initial preparation

On Windows, choose the exact Q10 `SQN100-*`, Q20 `SQC100-*`, or Passport `SQW100-*` variant, back up the phone and allow at least 15 GB of disk space. Auto preparation downloads and hashes AutoRoot v4, fixed firmware for the selected model, libusb/LZO, portable 7-Zip and fixed OpenSSL DLLs from MinGit. Users do not separately install Git, 7-Zip or another Root project. Source users can obtain SSH components through the same wizard. Preparation generates independent personal keys and checks both OS/radio images; it does not flash the phone.

Flashing requires a separate, explicit data-erasure confirmation. The workflow rechecks the single USB phone's model, image hashes and existing Root access, runs OS then radio, and pauses on unknown outcomes. Passwords are entered in the vendor's native console, never GUI command arguments. For the pinned v4 recipe, only OS writing reaching 100%, both recorded security-error messages and exit code 73 allow the documented radio continuation; arbitrary errors are not accepted. See the [author's instructions](https://bb10.root.sx/blog/autoroot-v4). Complete phone setup, open BlackBerry World, verify effective UID 0, then continue with preflight and VoLTE installation.

Windows driver preparation downloads and verifies the BlackBerry bundle, embedded MSI and Microsoft-signed catalog. Actual installation requests standard Windows UAC. Existing working drivers need no replacement.

`0.5.0-r14` builds integrate automatic Root preparation and staged flashing for Q10, Classic (Q20), and Passport (Q30). Select firmware for the exact hardware variant; initial flashing erases data. Offline Windows builds and verification passed for all three firmware families. r14 passed first Root on Windows / Passport SQW100-4 and Apple Silicon Mac / Q20 SQC100-2, including new-key UID 0, fresh installation and normal-menu reboot autostart. Native stages ran through acceptance entry points; complete first-use GUI operation, Q10 first Root and Intel USB flashing remain unverified. The Mac app supports already-rooted workflows. r6 also adds experimental native initial preparation/staged execution on macOS 14+, with r14 Mac/Q20 native first-Root acceptance; old r5 does not include it; see [scope](MACOS.en.md#can-a-mac-perform-initial-root). Actual Mac-to-phone acceptance remains separate from desktop startup testing.

The earlier offline iteration verified portable inputs, personal-key generation, construction and hash checks of both Root images, driver extraction/signatures, and read-only access to an already-rooted Q10. At that time the flashing branch had only simulated regression coverage. r14 native first-Root results are recorded above. The wizard remains experimental. First preparation needs Internet access or correctly cached materials; normal prepared use has no activation, billing or AI dependency.

## Prepare firmware by hardware model

Desktop `0.3.3-r8` uses the exact hardware model for automatic downloads, browser links, and local import verification. Neither the application package name nor a Q10 default determines the target. A single identified phone supplies the model; unknown, multiple, or conflicting devices stop selection. For offline preparation, disconnect phones and explicitly choose the model.

| Phone | Hardware variants | Pinned firmware | Size |
| --- | --- | --- | --- |
| Q10 | SQN100-1 through SQN100-5 | `Q10_10.3.03.3216_SQN100-1-2-3-4-5.7z` | 1.57 GB |
| Classic / Q20 | SQC100-1 through SQC100-5 | `Q20_10.3.03.3216_STA100-1-2-3-4-5-6.exe` | 3.07 GB |
| Passport / Q30 | SQW100-1 through SQW100-4 | `Passport_10.3.03.3216.7z` | 1.57 GB |

The Q20 STA100/Z30 filename reflects its shared stock package. The complete original EXE is downloaded without executing it. Import verifies stock firmware only. Continue with automatic Root preparation and confirm flashing. Root and VoLTE acceptance remain separate. The [source manifest](../materials/sources.json) pins each file size and SHA-256; caches use distinct filenames and hashes, and imports for the wrong model are rejected.

Source preparation: `python tools/fetch_materials.py --variant SQC100-1 --with-usb-drivers`, replacing the variant with the actual hardware model. Omitting `--variant` downloads shared tools only, with no default Q10 firmware.

For mainland China networks, use **China download (ZSpace)** in the app or the [stock firmware share](https://t3.znas.cn/9jkbxczhAK4), download the filename shown for the selected model, then import it. The read-only folder contains three stock files and verification lists, without login or a passcode. The share was created on 2026-10-30 with a 180-day duration and a maximum of 1,000 uses; current availability follows the share page. Browser share pages are excluded from automatic mirror ranking and resumable transfers. A long-term automatic mirror should expose stable HTTPS file URLs with Range support.

The backup is the [Baidu Netdisk firmware share](https://pan.baidu.com/s/1zLsoynq3nkOs7AwgSM7rqw?pwd=fp4r), access code `fp4r`. Select **Backup download (Baidu)** or **Copy backup link** in the app; copying includes the access code. Download the complete original filename shown for the selected model, then verify and import it. Availability follows the share page; it is not an automatic raw-file mirror.

## Interrupted or failing downloads

Desktop `0.3.3-r3` adds automatic mirror ranking, failover, cross-mirror resume and verified offline firmware import. Existing EXE/DMG installations need updating. The Q10 archive is about 1.57 GB; status shows the current host, bytes, percentage, speed and switch reason.

- Uncached multi-source files probe up to 256 KiB per node concurrently, measuring payload speed including connection time. Ranking waits at most six seconds and prefers the fastest observed usable source; unsuccessful probes remain fallback candidates. A sample cannot guarantee the fastest sustained transfer.
- Network, HTTP, certificate and invalid-response errors try another configured source. Multi-source transfers use a 15-second socket inactivity timeout. A 20-second window below 16 KiB/s triggers a switch, at most once per source, so slow connectivity does not cause endless switching.
- Each file permits at most `max(5, source count × 2)` transfer attempts. Temporary errors back off and honor up to 60 seconds of Retry-After per node without delaying healthy alternatives. Exhaustion preserves partial progress for another preparation or application restart. Disk and permission failures stop immediately.
- Partials remain bound to the pinned SHA-256. Cross-source resume compares up to 64 KiB of overlapping saved bytes and never sends another source's ETag. Servers ignoring ranges restart from zero. Only a complete matching SHA-256 can be extracted or executed. r42 and earlier retain rejected bytes in `.invalid-*` files; r43 and later discard invalid bodies and keeps small records instead. See [disk cleanup](DISK-CLEANUP.en.md).
- Verified cache entries never probe or connect; concurrent applications cannot write the same file. Q10 alternatives are still Internet Archive replicas. Selected tool mirrors are Tsinghua, USTC, Huawei Cloud or SourceForge. No maintainer server, unverified public proxy or different firmware version is used. If every source is unreachable, configure a working proxy or import manually.

Manual browser download and import:

1. Open **Connect phone / Connection help → Initial Root**, detect or explicitly choose the exact hardware model, then find the matching firmware download/import section.
2. Select the original host or a backup in **Browser download source**, then use **Download firmware in browser** for the model-specific filename shown in the app, or **Copy download link** for a resumable download manager. Finish downloading the archive and **do not extract it**.
3. Choose the local file or paste its full path, then use **Verify and import firmware**. Quoted Windows “Copy as path” values and browser-added `(1)` filename suffixes are supported. The content is verified and stored under the canonical cache name.
4. After import, Q10, Q20 and Q30 can all click **Prepare Root images automatically** below the import section. Once ready, acknowledge backup/data erasure and click **Flash Root**. The confirmation identifies the exact target variant, and an inline hint explains why flashing is disabled. The firmware is reused; other missing tools still need downloading. Import itself is fully offline and only copies/verifies the file; it neither builds images nor flashes a phone.

If images are ready but flashing remains disabled because the connection is unverified, click **Recheck connection and model** on the **Initial Root** page. Disconnection, multiple devices or temporarily missing model information retain the prepared image selection and clear the erase acknowledgement. After verifying the only connected phone, confirm again. Detecting a different exact model clears the old image selection. Rechecking does not flash the phone.

Import shows progress and leaves the selected original file in place. Incomplete, corrupt or wrong-version files are rejected without changing existing cache files or resume progress. The first import needs room for a complete copy. Subsequent source reuses any existing verified cache without another copy and removes redundant partials after successful verification.

Older versions can still reuse a complete archive downloaded from the [Root manifest](../materials/sources.json). **Keep the exact manifest filename and do not extract it.** Put it in the cache below and retry preparation; the app verifies SHA-256 before reuse.

| Application | Download cache |
| --- | --- |
| Windows EXE | `%LOCALAPPDATA%\bb10-volte\private\downloads` (paste into Explorer's address bar) |
| macOS app | `~/Library/Application Support/bb10-volte/private/downloads` |
| Source | `downloads/` in the repository root |

Retries apply only to material downloads. Interrupted or uncertain phone flashing still pauses under the existing rules.

Pinned inputs: [first-use tools](../materials/first-run-tools.json), [Root materials](../materials/sources.json), [drivers](../materials/usb-drivers.json). Private kits and proprietary firmware remain outside public application/source bundles. Preserve the owner-specific kit for future connections and recovery.

ZSpace and Baidu both download through the system browser. Open ZSpace, enter `BB10-Stock-Firmware-10.3.3.3216`, and click Download beside the matching firmware. Use Copy ZSpace link if the browser does not open; an access code is also displayed/copied when configured. Save the original file and return to import it. Do not run the original Q20 EXE. Share pages are not raw automatic-download mirrors; validity and quotas follow the provider page.
