# Desktop storage and manual cleanup

The manual instructions apply to r42 and later. The r43 EXE/DMG includes the automatic reuse and cleanup changes described below.

| Application | Personal materials | Download cache |
| --- | --- | --- |
| Windows EXE | `%LOCALAPPDATA%\bb10-volte\private` | `%LOCALAPPDATA%\bb10-volte\private\downloads` |
| macOS app | `~/Library/Application Support/bb10-volte/private` | `~/Library/Application Support/bb10-volte/private/downloads` |
| Source | Repository `private/` | Repository `downloads/` |

Open Windows paths with Win+R, or Mac paths with Finder's Shift+Command+G. Close every application instance, driver installer and flashing window first.

The download cache can be removed; missing inputs will be downloaded again and partial progress will be lost. If only computer-side downloading, extraction or building failed and you can confirm phone flashing never started, remove the failed kit's `stock`, `images` and `stock-upgrade` subdirectories and prepare again. These subdirectories can also be removed once the phone boots normally, Root and connectivity are confirmed, and no further flashing or recovery is needed. They are inside `root-kit` or `root-kit-*` and contain stock firmware, generated Root images and Mac stock-upgrade partitions. Removing them prevents continued flashing with that preparation. Finished `windows-usb`/`windows-usb-*` extraction directories can also be deleted once their installation logs are no longer needed; this does not uninstall Windows drivers.

**Keep the parent `private` and `root-kit*` folders**, personal `q10_root_rsa`/`q10_host_rsa` keys and their `.pub` files, `ssh_config`, `known_hosts`, connection settings, original backups, setup/upgrade journals and logs. Do not delete `root-flash.lock` to bypass an uncertain flash. Preserve all Root/upgrade materials if flashing was interrupted, the phone has not booted, or recovery is still needed.

Windows one-file applications extract into `%TEMP%\_MEI...` and normally clean up on exit. Only remove a leftover after identifying it as bb10-volte, for example through its `project.json`, and confirming all related processes have exited. Other applications use the same `_MEI` prefix. Browser downloads and duplicate EXE/DMG files remain in the user's chosen folders and are not managed automatically.

The subsequent source checks the exact model, platform, recipe, finished images, stock input and personal keys before reusing a preparation, including sufficiently evidenced compatible legacy kits. Reuse is checked before requiring space for a fresh build. Previously flashed or uncertain journals are never reset. An OS lock prevents simultaneous preparation; newly managed failed/interrupted builds discard large scratch directories while preserving keys and logs. Successful builds discard verified intermediate partitions. A typical old Q10 preparation retains approximately 9 GB of intermediates; temporary build space is still required.

Verified imported firmware is reused without another copy. Completed downloads/imports remove redundant progress; rejected bytes are replaced by small diagnostic records while usable partial downloads remain resumable. Q20's identical stock EXE uses a hard link where supported, with a copy fallback; disk space is released only after the last hard link is removed. Driver kits are verified and reused, and new extraction intermediates are cleaned. The first-use and upgrade windows now show the actual storage locations and cleanup instructions.

These are offline desktop changes, not new phone or carrier acceptance results. See the [detailed Chinese guide](DISK-CLEANUP.md) for the directory-by-directory table.
