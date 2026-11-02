# r20 / mobile 0.1.0.15 integration and release scope

The public mobile scope is rooted Q20 SQC100-2 and Passport SQW100-4 on OS 10.3.3.3216. Q10 native installation remains under independent testing. This release does not claim a Q10 install result or change a connected device.

The integrated base includes desktop r15, firmware pairing, screenshot onboarding, the protocol-2 native manager (227467d), deployed website compatibility work (4ee3949), and the mobile OctoLab support sheet (b795792). Uncommitted mobile installer fixes were snapshotted without changing their active checkout: QNX start_new_session, regular-file ZIP metadata and unknown-result guidance. Main-checkout Root UID failure handling was also retained.

Historical Passport operator-name and Telecom recovery experiments and their public evidence were imported from their branches. They are research sources, not runtime inputs. Other old Q20, unified-carrier and multi-model Root branch changes have been superseded by the integrated r18 management and current first-Root implementations; their histories are merged without rolling back service bytes, versions or current UI. Worktree-only recorder, firmware-routing and Baidu-backup changes were checked against their later integrated implementation. Private logs, keys, firmware and generated outputs are excluded from the source allowlist.

The active Q10 checkout, its uncommitted candidate version/pins, phone state, Mac mini USB connection and tunnels are not modified. Firmware remains on Baidu Netdisk and ZSpace. Small application artifacts use immutable R2 paths, with the same bytes/checksums as GitHub assets.

The native BAR is built using the pinned BB10 SDK, with the fixed app identity. Desktop packages bundle this exact BAR and verify its size and SHA-256 before installation. The system installer and actual installed files remain checked independently; an unknown result cannot be automatically resubmitted. The signed mobile runtime ZIP is not a C++/QML BAR upgrade.

Device evidence: v12/r18 Q20/Unicom and Passport/Mobile full lifecycle, calls and SMS; Q20/Mobile and Passport/Unicom swapped-SIM checks. r20/mobile15 adds UI and installation changes; build, signature, package and offline tests do not establish new hardware acceptance. The earlier isolated Passport wake reset is not claimed fixed. Latest source and build receipts accompany the release separately.

The guide hub separates desktop and mobile. Mobile has a recommended desktop-installer entry and a manual BAR entry; both work without JavaScript. The root native BAR route is a project recommendation, not a BlackBerry certification or a claim that all Root systems are compatible. Direct download probes from Windows and Mac exited through US/SJC and therefore do not establish mainland-China network acceptance.
