# Windows r63 and mobile 0.2.5.0

- Feedback bundle collection now skips hidden or unmapped status labels (such as the inactive flash-pause banner), and both `SetupWizard` and `FirmwareDialog` clear that label text when unlocked so exported feedback logs no longer report a phantom flash lock.
- When Windows driver installation stops because of a conflicting running process (such as `nginx`, `RimDeviceManager`, `PeerManager`, or `tunmgr`), the status message now names the exact process, and the Windows driver tab adds a pre-install reminder.
- When USB networking is up but model detection returns empty metadata, local USB probing now records a scrubbed `discovery_reason` code (such as `no_link_local_30`, `http_401`, `http_403`, `timeout`, `connection_refused`, or `multiple_usb_links`), shows targeted troubleshooting guidance in the wizard, exports the code in feedback bundles, and notes that offline firmware download works after unplugging USB.

Mobile remains 0.2.5.0 with no phone payload changes. macOS downloads remain frozen at r43. No new call, SMS or data acceptance is claimed in this release.
