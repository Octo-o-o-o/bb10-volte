# r49 integration review — 2026-11-17

The reviewed candidate integrates the post-r48 network-resilience implementation and call-rejection investigation, followed by the r49 / mobile 0.1.0.49 packaging changes. This is the integrating maintainer's review and verification, not an independent second review. macOS remains frozen at r43.

## Scope and findings

- Reviewed all incoming changes against the r48 release, including network waiting, native-attempt stages, SIM transitions, radio/selection ownership and restoration, USB transport and host-key pinning, desktop/mobile state mapping, diagnostic privacy, release inputs and bilingual guidance.
- Reproduced and fixed a disable race before the first IMS journal: a live manager interrupted during handoff or SIM waiting previously left an owned manual selection untouched. `unified_service.locked_prepare()` now verifies the installation and restores owned selection and radio mode under the management lock when explicitly disabled. Normal shutdown and journal-backed restoration retain their existing paths. Failure-injection tests failed before the fix and pass afterward, including cleanup failure propagation.
- Verified the exact published r48 payload's canonical hash is accepted for upgrade and every changed file is in the permitted update set. Existing original-backup, native ABI, same-SIM and provider/reboot boundaries remain in place.
- The call-rejection tests disprove two proposed native patch locations; they do not reproduce or fix the reported repeated incoming-call UI. The production IMS transformation remains unchanged from r48. The offline analyzer exports only bounded counts/status codes and refuses to overwrite existing files.
- All eight pre-existing remote branch tips are already ancestors of main. The old pre-r13 stash describes changes integrated at the recorded r13 commit; it is not reapplied over later work. Local recovery snapshots preserve its original objects and the initial working-tree changes.

## Completed candidate checks

| Check | Observed result |
| --- | --- |
| Full Windows Python 3.14.9 suite | 1,198 tests; 1,133 passed, 65 skipped; no failures/errors |
| Network resilience and cancellation suite | 34 passed, including the three new cancellation-boundary tests |
| ARM/Thumb SMS matrix | 192 model/PLMN combinations across three ASLR bases: 576 executions; ELF structure checks passed |
| Call-rejection coverage | Native-path and privacy regressions executed in the full local suite |
| Public inputs | Git allowlist, payload hashes, privacy scan, Markdown links, generated translations and compile checks passed |
| Native mobile package | Pinned toolchain build passed; publisher signature, 65 installed files and 64 BAR SHA-512 asset digests verified |
| Website | JavaScript checks, 23 static tests and 32 browser tests passed |

Release-specific Windows executable self-test, source-archive round trip, final Ubuntu/Windows CI and anonymous GitHub/R2/website checks are recorded with the published release. A test skip is not a pass; platform-specific POSIX and private-native-fixture coverage differs between local Windows and public CI.

## Remaining limits

No handset was contacted or changed. Network waiting, radio reconciliation, safe retry, explicit selection and dynamic USB need version-specific device testing. Existing model/carrier/call/SMS/data evidence stays tied to its original device and version. Battery usage has not been measured. No new Windows 10, Intel Mac or macOS release acceptance is claimed.

The repeated incoming-call UI report remains unresolved. See [the investigation](CALL-REJECTION-INVESTIGATION-2026-11-17.md), [the network guide](NETWORK-RESILIENCE.en.md) and [release notes](RELEASE-r49.en.md).
