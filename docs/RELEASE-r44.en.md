# Desktop r44 / mobile 0.1.0.44: fresh-device checks for admitted models

2026-11-10. macOS remains at **v0.5.0-r43**. This release has no new Mac package.

- An admitted model without its own legacy migration path can be checked and installed as a fresh phone only when every known legacy service directory is absent. Unknown models and any known legacy installation remain blocked. A recovery directory from another suffix is never reused.
- Published r42/r43 service payloads remain eligible for their existing checked upgrade. Original backups and recovery behavior stay in place.
- The phone app is now **0.1.0.44**. On SQC100-5, the signed app's runtime check returned “ready to enable VoLTE,” and the owner confirmed that screen. That confirms the check screen only. It is not call, audio, SMS or data acceptance.
- The Windows package still includes the r43 interface-redraw fix and preparation-cache reuse. A phone that is already working does not need another firmware flash or a new Root for this update. Install 0.1.0.44 if a fresh-device check fails.

Historical tested, untested and known-issue results remain tied to their original versions and handsets. Offline builds and download verification are not new handset acceptance. The Windows EXE still has no Authenticode publisher signature.
