# Community research integration (0.3.3)

[简体中文](COMMUNITY-RESEARCH.md) | **English**

[Issue #1](https://github.com/Octo-o-o-o/bb10-volte/issues/1) introduced [imqinyu/BB10DeviceVoLTEResearch](https://github.com/imqinyu/BB10DeviceVoLTEResearch). This integration pins commit [376f492](https://github.com/imqinyu/BB10DeviceVoLTEResearch/tree/376f492ade10efad371dca64d49fe39549820844), reviewed on October 28, 2026. [community-research.json](../materials/community-research.json) records provenance, evidence levels, limitations and research candidates.

## Included in this version

- Desktop/CLI preflight and exported reports attach community observations only when the public board name (or exact Z30 variant), OS and actual SIM MCC/MNC match. The selected profile cannot substitute for observed SIM facts.
- Allowlisted board names supplement model recognition. They do not replace model, ABI, OS or native hash checks; contradictory identities are rejected.
- Read-only diagnostics retain finite values for IMS status, normalized LTE spelling, provisioning, engineering voice preference, DCA voice preference and IR92 preconditions. Missing or malformed values are null, with no arbitrary PPS content, SIM identities or exception text exported.
- Desktop registration detection accepts LTE and lte, while still requiring a live project manager/native process, 200 OK and the current LTE radio.
- Passport automatic installation, update, start and restore operations that may unregister the provider are paused. Preflight, status and report export remain available. Desktop and phone entry points enforce the restriction.
- The existing Q10 binary patch, voice policy, provider implementation and restoration remain in place. No upstream programs, binaries, distribution ZIPs or stock carrier XML are bundled.

Community observations never establish project hardware acceptance or relax hash checks. No calls are initiated and the additional diagnostics do not change phone configuration. This version has not been tested on hardware; previous Q10 call acceptance belongs to version 0.3.2 and earlier.

## Evidence distinctions

| Exact combination, OS 10.3.3.3216 | Evidence origin | Reported result | Still unestablished |
| --- | --- | --- | --- |
| Classic AT&T / CLASSICATT / Mobile 460-00 | Upstream author's local experiment | Registration, manual outgoing call, session observations of bidirectional RTP | Incoming calls, boot recovery, installation through this project |
| Classic Verizon / CLASSICVZW / Unicom 460-01 | Contributed report collected upstream | Registration | Independently validated incoming/outgoing calls |
| Passport / WINDERMERE4ROW / Unicom 460-01 | Contributed report collected upstream | Outgoing and normal-handset incoming calls | Universal Passport support, isolated parameter causality, this project's safe rollback |
| Z30 STA100-3 / Mobile 460-00 | Upstream local negative test | No LTE attachment on the tested network; reported bands B4/B13 | Results for all Z30 variants or a remedy through IMS settings |

The fresh October 28 Q20 snapshot showed LTE attachment with IMS idle; it was not a successful call retest. Q20 incoming failures lack complete per-variant traces. “Upstream local” does not mean independent validation by this project's maintainers. See the pinned [evidence ledger](https://github.com/imqinyu/BB10DeviceVoLTEResearch/blob/376f492ade10efad371dca64d49fe39549820844/docs/05-validation-and-evidence.md).

## Passport lifecycle hold

The contributed Passport implementation reports an io-pkt restart and USB interruption after provider disable; it retains the provider until reboot. Our Q10 restoration stops owned IMS, cleans owned VPN state and checks for active VPNs before unregistering the provider. Those checks have not been shown to prevent the reported Passport failure.

The hold conservatively covers the Passport family; it is not a claim that every Passport fails. Experimental consent cannot bypass it. Existing old installations are not automatically stopped, overwritten or migrated by the new desktop. Preserve their state, inspect status and supply a sanitized report so maintainers can determine a recovery procedure for the actual Root/addon, IMS/SA cleanup and module-loading state. Updating only the desktop does not patch old phone-side code.

Reopening needs provider lifecycle evidence, usable network/USB after cleanup, repeat enable, normal reboot and real two-way calls. Leaving the provider loaded until reboot would need an explicit partial-restoration state, not a claim of complete restoration.

## Incoming-call investigation

The incoming_diagnostics snapshot always marks call_acceptance as not_assessed. Provisioning=1 or UsePreconditions=0 cannot prove incoming service.

Use a normal handset caller. Determine whether INVITE reaches BB10, then distinguish device rejection, ringing, caller CANCEL, answer/ACK and media failure. Compare the current carrier's own settings; investigate provisioning, engineering voice preference and IR92 parameters one variable at a time with original state preserved. Acceptance includes both audio directions, continued LTE, USB-disconnected use, normal reboot and longer calls.

Engineering override=5 and DCA voice preference=3 use different interfaces and are not interchangeable. Unicom carrier 36 files must not be copied onto Mobile carrier 404. The final successful Passport report still included 183/PRACK, so disabling preconditions was not isolated as the sole fix. This release does not write these candidate settings.

Navigator dots are retained as an optional feature candidate. No monitor or Navigator writes are included. Any future implementation needs validation of case handling, stale status, restoration and airplane-mode transitions, without presenting registration as call acceptance.

## Provenance and licensing

Upstream NOTICE states that no project-wide license has been chosen and the archive includes other contributors' material. Following the author's invitation, our [confirmation request](https://github.com/Octo-o-o-o/bb10-volte/issues/1#issuecomment-6472384217) asks for explicit reusable files, licensing terms and contributed-material permissions.

New code here is written for this project; evidence entries are independently summarized facts and source links. Upstream materials are not relicensed as MIT or redistributed. Any later code/binary reuse must retain the confirmed licenses, notices and attribution. Both READMEs acknowledge the project at the bottom.
