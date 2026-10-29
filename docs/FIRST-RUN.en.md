# First use and connection setup

`0.3.3-r3` starts with **Connect phone / Connection help**, with SSH paths under advanced settings. Released r6 and earlier applications may still use the older labels below; this flow is included in the new Windows EXE and Mac DMG. Reopening rechecks the last successful connection once. Pairing requests and completed image preparation can be resumed. Connection failure never establishes that a phone is unrooted.

[简体中文](FIRST-RUN.md) · [GUI](GUI.en.md)

Desktop version `0.3.3-r3` provides a First use wizard for connection checks, Windows SSH components, USB drivers and initial Q10 Root preparation.

## First connection on a Mac

Start with the [Mac phone guide](MACOS.en.md). For an unrooted Q10, r6 adds experimental native preparation and separately confirmed staged execution on macOS 14+, without hardware first-flash acceptance or inclusion in old r5. A rooted phone with personal connection materials can import them or use Check device. A rooted phone with no old Windows files can authorize a fresh Mac key in an existing working phone Root terminal. With neither valid materials nor a working Root terminal, direct connection is unavailable. New authorization persistently appends a public key to phone SSH access and requires the owner's explicit `PAIR`; development mode does not grant Root.

An existing microSD card, Mac card reader and phone file manager can transfer the public script/result without assuming Finder can mount internal phone storage or requiring old Link. See the [recovery transfer steps](RECOVER-CONNECTION.en.md#mac-transfer-without-old-connection-files) and their untested limits.

Published `0.3.2-r5` passed daily Mac connection checks in the main window, but its First use Root probe can misreport a failure and its USB facts are incomplete. Repository source fixes do not update that DMG; see [Mac acceptance](../materials/macos-device-validation-2026-10-28.json).

## Already-rooted phones

Already-rooted devices can use Check device directly. The app discovers saved references, known owner-created kits, a configuration next to a portable executable and explicit `bb10-root` / `q10-root` aliases. Unsaved automatic discovery is limited to the direct USB address and keeps strict host verification. Other addresses require an explicitly imported configuration. Only configuration references are saved; private keys stay in their original kit.

Already-rooted phones without connection files can use Recover connection to import a login key or authorize this computer through an existing phone Root terminal. The flow is shared by Windows and macOS; see [connection recovery](RECOVER-CONNECTION.en.md).

**The connection field may remain empty.** Check device discovers both `root-kit/ssh_config` and `root-kit-*/ssh_config` in the owner's private directory, verifies the connection and fills the field. A successful selection is restored on the next launch. Auto preparation creates these files; after flashing and Root verification the wizard passes the configuration to the main window. Numbered kits remain discoverable after restarting before a connection has been saved. Multiple kits are selected by verified access, never merely by which file is newest. An already-rooted phone without its matching key needs original personal materials or new authorization through an existing working Root terminal.

An installed service is read as an existing installation. Normal registration/LTE displays enabled; startup displays pending. Its active configuration is expected rather than an installation failure. USB, development mode, SSH, Root and IMS are distinct. Development mode being disabled does not establish missing Root, and working Root SSH does not require development mode to remain enabled. Anonymous USB discovery reads only allowlisted model, OS and development-mode fields. Diagnostic checks do not open and abandon development sessions or raw SSH sockets.

On initial use, unlock and connect the phone. Use the wizard's USB/driver checks and on-phone instructions. Development mode is under Settings → Security and Privacy. A rooted device may need BlackBerry World opened once to trigger local startup; the store's network error or endless loading does not establish Root failure. If SSH still refuses, use a normal phone-menu reboot and wait for Root. A key mismatch requires the original trusted profile, not disabled checks or reflashing.

## Experimental Mac initial preparation and execution

On macOS 14+, r6 adds **First use → Initial Root** for private Q10 materials/images. The app obtains pinned architecture-matched bb10mt/7-Zip and private libusb/LZO libraries without a Homebrew installation. Preparation does not touch BootROM or flash; it preserves AppWorld and verifies stock partitions. Staged execution requires rechecking one phone, its variant, USB `169.254.0.2`, backup acknowledgement and the extra Mac acknowledgement that the phone is not rooted and first flashing is not hardware validated. A separate erase confirmation is still required before opening Terminal.

Unrooted Passport (Q30)/Q20 phones currently lack matching integrated initial-flash materials. Their actual `SQW100-*` / `SQC100-*` variant, firmware, loader and method need separate integration. Selecting a Q10 variant, editing configuration or enabling experimental VoLTE cannot make Q10 images valid for them. Already-rooted Q30 VoLTE recognition and initial Root are separate workflows.

Any Mac native error, missing completion evidence, cancellation or unknown outcome pauses with state preserved, without retry or radio continuation. **The Windows exit-73 exception does not apply on Mac.** Hardware Mac first flashing remains untested, and old r5 lacks this integration. See [Mac initial Root](MACOS.en.md#can-a-mac-perform-initial-root).

## Windows initial preparation

On Windows, choose the matching Q10 `SQN100-1` through `SQN100-5` variant, back up the phone and allow at least 15 GB of disk space. Auto preparation downloads and hashes AutoRoot v4, fixed Q10 firmware, libusb/LZO, portable 7-Zip and fixed OpenSSL DLLs from MinGit. Users do not separately install Git, 7-Zip or another Root project. Source users can obtain SSH components through the same wizard. Preparation generates independent personal keys and checks both OS/radio images; it does not flash the phone.

Flashing requires a separate, explicit data-erasure confirmation. The workflow rechecks the single USB phone's model, image hashes and existing Root access, runs OS then radio, and pauses on unknown outcomes. Passwords are entered in the vendor's native console, never GUI command arguments. For the pinned v4 recipe, only OS writing reaching 100%, both recorded security-error messages and exit code 73 allow the documented radio continuation; arbitrary errors are not accepted. See the [author's instructions](https://bb10.root.sx/blog/autoroot-v4). Complete phone setup, open BlackBerry World, verify effective UID 0, then continue with preflight and VoLTE installation.

Windows driver preparation downloads and verifies the BlackBerry bundle, embedded MSI and Microsoft-signed catalog. Actual installation requests standard Windows UAC. Existing working drivers need no replacement.

The Windows and experimental Mac initial-Root recipes are Q10-only. Q20/Passport need their own verified firmware; Q10 images are prohibited. The Mac app supports already-rooted workflows. r6 also adds experimental native initial preparation/staged execution on macOS 14+, without hardware first-flash acceptance or inclusion in old r5; see [scope](MACOS.en.md#can-a-mac-perform-initial-root). Actual Mac-to-phone acceptance remains separate from desktop startup testing.

This iteration verified portable inputs, personal-key generation, construction and hash checks of both Root images, driver extraction/signatures, and read-only access to an already-rooted Q10. The flashing branch has simulated regression coverage but **has not been exercised on an unrooted phone**, and the current working phone was not reflashed. The wizard remains experimental. First preparation needs Internet access or correctly cached materials; normal prepared use has no activation, billing or AI dependency.

## Interrupted or failing downloads

Desktop `0.3.3-r3` adds automatic mirror ranking, failover, cross-mirror resume and verified offline firmware import. Existing EXE/DMG installations need updating. The Q10 archive is about 1.57 GB; status shows the current host, bytes, percentage, speed and switch reason.

- Uncached multi-source files probe up to 256 KiB per node concurrently, measuring payload speed including connection time. Ranking waits at most six seconds and prefers the fastest observed usable source; unsuccessful probes remain fallback candidates. A sample cannot guarantee the fastest sustained transfer.
- Network, HTTP, certificate and invalid-response errors try another configured source. Multi-source transfers use a 15-second socket inactivity timeout. A 20-second window below 16 KiB/s triggers a switch, at most once per source, so slow connectivity does not cause endless switching.
- Each file permits at most `max(5, source count × 2)` transfer attempts. Temporary errors back off and honor up to 60 seconds of Retry-After per node without delaying healthy alternatives. Exhaustion preserves partial progress for another preparation or application restart. Disk and permission failures stop immediately.
- Partials remain bound to the pinned SHA-256. Cross-source resume compares up to 64 KiB of overlapping saved bytes and never sends another source's ETag. Servers ignoring ranges restart from zero. If all available sources disagree with a saved tail, the old partial is quarantined before one clean recovery. Only a complete matching SHA-256 can be extracted or executed; rejected bytes remain in `.invalid-*` files.
- Verified cache entries never probe or connect; concurrent applications cannot write the same file. Q10 alternatives are still Internet Archive replicas. Selected tool mirrors are Tsinghua, USTC, Huawei Cloud or SourceForge. No maintainer server, unverified public proxy or different firmware version is used. If every source is unreachable, configure a working proxy or import manually.

Manual browser download and import:

1. Open **Connect phone / Connection help → Initial Root**, then the manual Q10 firmware download/import section.
2. Select the original host or a backup in **Browser download source**, then use **Download firmware in browser** for `Q10_10.3.03.3216_SQN100-1-2-3-4-5.7z`, or **Copy download link** for a resumable download manager. Finish downloading the archive and **do not extract it**.
3. Choose the local file or paste its full path, then use **Verify and import firmware**. Quoted Windows “Copy as path” values and browser-added `(1)` filename suffixes are supported. The content is verified and stored under the canonical cache name.
4. After success, use **Auto prepare Root images**. The firmware is reused; other missing tools still need downloading. Import itself is fully offline and only copies/verifies the file; it neither builds images nor flashes a phone.

Import shows progress and leaves the selected original file in place. Incomplete, corrupt or wrong-version files are rejected without changing existing cache files or resume progress. The cache disk needs room for a complete copy; selecting that same file already in the cache only verifies it.

Older versions can still reuse a complete archive downloaded from the [Root manifest](../materials/sources.json). **Keep the exact manifest filename and do not extract it.** Put it in the cache below and retry preparation; the app verifies SHA-256 before reuse.

| Application | Download cache |
| --- | --- |
| Windows EXE | `%LOCALAPPDATA%\bb10-volte\private\downloads` (paste into Explorer's address bar) |
| macOS app | `~/Library/Application Support/bb10-volte/private/downloads` |
| Source | `downloads/` in the repository root |

Retries apply only to material downloads. Interrupted or uncertain phone flashing still pauses under the existing rules.

Pinned inputs: [first-use tools](../materials/first-run-tools.json), [Root materials](../materials/sources.json), [drivers](../materials/usb-drivers.json). Private kits and proprietary firmware remain outside public application/source bundles. Preserve the owner-specific kit for future connections and recovery.
