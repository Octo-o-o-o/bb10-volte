# Desktop r43: Windows UI stalls and preparation storage

2026-11-09. Mobile remains **0.1.0.43**. Phone payloads and hardware acceptance are unchanged.

- Windows uses built-in control drawing instead of repeatedly tiling small translucent images. Local page-opening and resize measurements improved from stalls lasting seconds to tens of milliseconds; other computers still need user validation. Progress animation uses the default 50 ms interval instead of 12 ms.
- Revalidate and reuse complete preparations for the same model, platform and recipe. Repeated firmware imports and driver preparation avoid extra copies; concurrent preparation does not create duplicate kits.
- Remove owned failed-build leftovers and redundant download partials while preserving keys, connection files, backups, logs and uncertain flash records. Add in-app storage locations and manual cleanup guidance.
- Update Windows, the universal Mac package and source together. Mac retains the rounded theme. The website separates concise presentation from canonical compatibility evidence without changing historical model results.

Exit the old desktop app before replacing it. **This desktop update does not require reflashing, Root, reactivation or reinstalling the phone app.** Existing connection and recovery materials retain their locations. It does not fix phone performance, battery life or the known Telecom pending-send status; do not resend messages already delivered.

See [UI measurements](WINDOWS-UI-PERFORMANCE.en.md) and [storage guidance](DISK-CLEANUP.en.md). New regression and packaged checks measure actual mapped-window painting, resize, tab changes and animation. Build, CI, Mac signing/notarization and public-download results are retained with release evidence; offline checks are not new phone-call acceptance. Windows remains unsigned with Authenticode.
