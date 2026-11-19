# r50 / mobile 0.1.0.50

- Boot handoff retries a transient native probe timeout and obtains fresh evidence. If the service did not start on this boot, the app can offer a checked retry.
- Interrupted mobile installation can check its receipt and continue. A new release can archive a verified earlier preparation before system changes, or continue an already-started activation using its verified payload and original backups.
- DCA carrier configuration records each file write before touching it. An attributable interrupted write can be resumed. Conflicts with uncertain ownership are preserved.

## Upgrade and verification

Windows and mobile are updated. macOS is frozen at v0.5.0-r43. For an installed service, follow the app’s stop and update prompts and retain the original backups. A normal reboot still releases native resources loaded on the current boot and applies certain Passport network policy changes.

If an earlier mobile app is stuck at an unknown operation outcome and its in-app update is unavailable, use the Windows r50 installer to update the BAR. Open the original task and select **Check and continue**.

An older interrupted write may lack the required per-file record. Keep the originals and the report if there is a configuration conflict. Offline fault injection covers boot probes, partial writes and installation transactions. The cause on each reported phone and the new release’s behavior on hardware still need verification.
