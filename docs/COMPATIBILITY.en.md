# Exact Models and Test Progress

[简体中文](COMPATIBILITY.md)

Desktop r42 / mobile 0.1.0.43 opened three-carrier activation across all 16 catalog entries. Desktop r44 / mobile 0.1.0.44 fixed fresh-phone preflight when no legacy service remains; desktop r45 / mobile 0.1.0.45 unified three-carrier incoming SIP/SDP signaling; desktop r46 / mobile 0.1.0.46 fixed China Telecom outbound SMS stalling on local "Sending..." and automatically lit the status-bar BlackBerry icon on LTE VoLTE registration (verified on SQC100-2 with Telecom); desktop r47 / mobile 0.1.0.47 expanded HPLMN admission across China Mobile (`460-00/02/04/07/08`), Unicom (`460-01/06/09`) and Telecom (`460-03/05/11/12`) with verified read-only stock `0.xml` fallback and fixed the Passport Telecom incoming-audio regression (restoring `Omit200OkSdp=1` while keeping `EarlySdp=0`); desktop r48 / mobile 0.1.0.48 hardened 3GPP OI-suffixed and MME-default APN bootstrap, extended 12-MNC SE.13/numeric ONS operator-name fallback, added QNX Python 3.2 `IOError` and bounded-log guards, and improved first-tap mobile SIM diagnostics and BAR asset hygiene. Historical evidence status does not block activation; working Root, OS `10.3.3.3216`, pinned native file hashes, a valid USIM without ISIM, verified backups and clean restoration remain required. The table below records historical version- and unit-specific evidence, not re-testing of every model on the newest build.

| Model | Mobile | Unicom | Telecom |
| --- | --- | --- | --- |
| SQN100-1 | Theoretical / untested | Theoretical / untested | Theoretical / untested |
| SQN100-2 | Theoretical / untested | Theoretical / untested | Theoretical / untested |
| SQN100-3 | Tested usable | Tested usable | Tested with issues |
| SQN100-4 | Theoretical / untested | Theoretical / untested | Theoretical / untested |
| SQN100-5 | Theoretical / untested | Theoretical / untested | Theoretical / untested |
| SQC100-1 | Tested usable | Tested usable | Tested usable |
| SQC100-2 | Tested usable | Tested usable | Tested usable |
| SQC100-3 | Tested usable | Tested usable | Tested usable |
| SQC100-4 | Tested unsuccessful | Tested unsuccessful | Tested with issues |
| SQC100-5 | Theoretical / untested | Theoretical / untested | Theoretical / untested |
| SQW100-1 | Tested usable | Tested usable | Tested with issues |
| SQW100-2 | Theoretical / untested | Theoretical / untested | Theoretical / untested |
| SQW100-3 | Theoretical / untested | Theoretical / untested | Theoretical / untested |
| SQW100-4 | Tested usable | Tested usable | Tested with issues |
| SQK100-1 | Tested usable | Tested usable | Tested usable |
| SQK100-2 | Theoretical / untested | Theoretical / untested | Theoretical / untested |

Per-model scope, known issues and provenance are recorded in the [shared compatibility matrix](../materials/compatibility-matrix.json), and deduplicated handset test progress is tracked in [manual progress](INTAKE-MANUAL-PROGRESS.md). `SQW100-2` has no verified production identity; `SQK100-2` is an officially certified variant without a local test unit or verified first-flash recipe.

On 2026-11-10, an additional `SQN100-3` (`R085` / `10.3.3.3216`) with Telecom `460-11` and mobile `0.1.0.43` / desktop engine `r43` completed installation and reboot after blue-LED recovery, registered IMS, and passed owner-confirmed incoming/outgoing calls, two-way audio, basic SMS and in-call mobile web browsing; historical Telecom notes and detailed HTTP/HTTPS or message-count sub-items remain scoped as recorded in [manual progress](INTAKE-MANUAL-PROGRESS.md).
