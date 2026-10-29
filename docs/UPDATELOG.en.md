# Update log

[简体中文](UPDATELOG.md)

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
