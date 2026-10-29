# BB10 VoLTE Addon comparison (2026-10-29)

[简体中文](UPSTREAM-ADDON-COMPARISON.md) | **English**

This record compares the [announcement](https://bb10.root.sx/blog/volte) and `bb10root/bb10-volte` at [8ac271b](https://github.com/bb10root/bb10-volte/tree/8ac271b5b1170ae98c60dd248dc5c4485edf95f3) with this project's baseline `08224a8`. Findings come from source inspection; the addon was not installed or executed on a phone. See [upstream-addon-research.json](../materials/upstream-addon-research.json) for the machine-readable record.

## Changes adopted here

Desktop check details and copyable/exportable support summaries explain the six existing allowlisted `incoming_diagnostics` fields: IMS state, bearer network, VoLTE provisioning, engineering voice domain, DCA voice domain and IR92 preconditions. Missing or invalid values remain unknown. Observations are not graded as pass/fail, and the two voice-domain enumerations remain distinct. Registration and configuration snapshots cannot establish incoming-call acceptance or two-way audio.

This change adds desktop presentation and offline research only. Phone probes, device payloads, patches, carrier parameters, installation/recovery gates and support scope remain unchanged; no additional phone reads or configuration writes are added. The source record does not enter per-device successful-call evidence or change `hardware_validation` or `call_acceptance`. Existing evidence and limitations are in [community research](COMMUNITY-RESEARCH.en.md) and [validation](VALIDATION.en.md).

## Research candidates, not adopted

| Area | Upstream observation | Decision and validation needed |
| --- | --- | --- |
| Stock IMS launch | The [manager](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L391) starts stock `ims_rrm` after DCA, provisioning and engineering-voice changes. | Worth investigating reduced binary-patch dependence. It does not establish that the verified Q10 can omit the VoPS patch. Separate experiments must verify real calls and restoration. |
| Carrier parameters | Includes Unicom 36, Mobile 404 and Vodafone Ukraine 339 profiles, compared below. | Use as parameter-difference samples. Do not import whole XML files or add supported combinations. Change one parameter at a time to distinguish effects. |
| Berry indicator | The [monitor](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/berry_monitor.c#L34) reads IMS PPS and writes Navigator; an exit routine attempts BBM/RCP-based restoration. | Useful visibility, but entails phone UI writes and needs stale-state, case, exit, flight-mode and conflict checks. Remains a candidate, never a call-success indicator. |
| Event and recovery statistics | [PPS monitoring](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L572) records drops and reconnection results. | A reference for future observability and validation. No resident monitor is added, and its forced IMS restart policy is not adopted. |
| Software-provider argument | The [helper](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/devnp-volte-swcrypto.c#L13) calls `swcryptoattach(0)`; this project's argument is `1`. | The difference does not establish BB10 semantics or a Passport lifecycle fix. Retain the argument, ownership/VPN checks and model restrictions. |

The comparison below concerns the **IMS service section** in the three upstream XML files and this project's [IMS-section generator](../device/profiles.py). It is not network certification. An omitted field is not equivalent to `false`; its runtime default was not verified here.

| Field | All three upstream samples | This project |
| --- | --- | --- |
| `AlwaysOn` | `false` | `true` |
| `DisableDAD` | `true` | Not explicitly set |
| `RequestSignallingBearerViaPCO` | `true` | Not explicitly set |
| `RequestPCSCFViaPCO` | `true` | `true` |
| IP family | `IPv4v6` | `IPv4v6` by default; configurable |

Sources: [Unicom](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/pkg/data/carrier-36-volte.xml#L88), [Mobile](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/pkg/data/carrier-404-volte.xml#L88), [Vodafone Ukraine](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/pkg/data/carrier-339-volte.xml#L75).

The indicator has additional details needing verification. Its [connection check](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/berry_monitor.c#L34) uses public PPS and a case-sensitive `LTE` comparison without owned-process liveness or a current REGISTER 200 check. Its [off write](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/berry_monitor.c#L89) uses the shorter on-string length and omits the final newline. PPS acceptance of that write was not tested, so indicator failure is not established. This project's registration conclusion continues to combine manager/native IMS liveness and current registration observations.

## Behaviors not adopted and existing safeguards retained

| Trigger and source observation | Consequence | Behavior retained here |
| --- | --- | --- |
| With multiple carrier XML files, [find_carrier_xml](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L300) returns the first matching entry without comparing the SIM's carrier ID; its fallback uses MNC. The separate provisioning carrier-ID resolver is not used for this choice. | CDSC may select another operator's configuration; directory order cannot establish a match. | Validate the current SIM's stock selection and data APN, then replace only its IMS section. |
| [incoming_ready_pps](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L250) checks only provisioning and preconditions. | `INCOMING_READY` does not establish a real incoming call, ringing, answering or two-way audio. | Separate configuration observations from call acceptance; keep `call_acceptance=not_assessed`. |
| [Enable](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L457) overwrites voice-domain configuration under four DCA sources and changes provisioning XML. The inspected [termination path](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L688) has no configuration rollback, IMS/VPN cleanup or provider unregister. | Manager exit does not prove baseline restoration. Deployment-specific cleanup outside these paths has not been verified. | Restore owned state using the journal, ownership evidence, concurrent-change checks and readback. Keep Passport provider recovery restricted. |
| The [network monitor](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L627) stops IMS when LTE/SIM/Data readiness is lost; [reconnect](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/ims_manager.c#L520) also lacks a fresh call-idle check. The stop helper matches a [command-line substring](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/src/sys_utils.c#L319) and can escalate TERM to KILL. | Could interrupt a surviving call/session or IMS instance not owned by this manager. Source inspection does not establish that every device will fail. | Leave transient runtime LTE recovery to native IMS; retain startup handoff limited to the verified combination and exact-process/idle evidence. |

See the [design](DESIGN.md) for the existing Q10 patch scope, recovery journal and startup handoff. No new reboot, long-call, long-standby, flight-mode or provider-lifecycle evidence was collected. Unverified combinations remain manual-start only, and Passport automatic operations remain suspended.

## Attribution and license

Upstream [README](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/README.md) and [LICENSE](https://github.com/bb10root/bb10-volte/blob/8ac271b5b1170ae98c60dd248dc5c4485edf95f3/LICENSE) declare GPL-3.0. This change records independently summarized facts and source links. No upstream source, carrier XML, binary or release ZIP was imported or relicensed as MIT. Any later code reuse or distribution needs a separate review of licensing and third-party provenance.
