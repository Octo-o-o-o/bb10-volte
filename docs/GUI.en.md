# Q10 VoLTE Desk

[简体中文](GUI.md)

The Windows GUI uses the same fixed workflow as the CLI. Requirements: Windows 11, Python 3.14 including Tk, OpenSSH, and your own verified root SSH configuration. No AI account, cloud service or third-party Python package is needed. The first UI is in Chinese; this guide describes its controls.

Extract the complete release and double-click `Start-GUI.cmd`, or run `python tools/gui.py`. Keep the complete directory. Do not regenerate a manifest on a customer's machine to bypass a package mismatch.

1. Select the phone's `ssh_config`; the default alias is `q10-root`. A blank config field uses the existing OpenSSH configuration. Strict host-key checking remains enabled.
2. Click **运行预检 / Preflight**. This checks model, OS, Root, native hashes, SIM/MCC/MNC, LTE, 3gnet, installed files and the original baseline. It temporarily uploads and individually trusts two probe scripts, then removes them. It does not modify telephony configuration. A disconnected session may leave the temporary probe directory.
3. Resolve blocked or waiting checks. Confirm the backup, carrier VoLTE provisioning and absence of an active call. **安装并验证 / Install and verify**, or **更新并验证 / Update and verify**, becomes available only when the required checks pass. An existing active service must first be stopped and restored.
4. Installation verifies the pinned package, preflights again on the phone, writes the release, reads it back, starts the service and waits up to 180 seconds for IMS registration. Keep USB connected; do not change SIMs or use another installer during this operation. The addon enables boot startup. First activation may briefly reload the radio.
5. IMS registration requires a live manager, live native process, LTE and connected IMS with `200 OK`. It does not prove calls work. Verify incoming/outgoing calls, audio in both directions, continued LTE, unplugged operation and a normal reboot. The existing reboot trial needed approximately 7 minutes 42 seconds from reboot to registration. A desktop timeout reports pending registration, not automatic success or a repeated installation.

**启动验证 / Start and verify** starts a complete current installation. **查看状态 / Status** reads current state. **停用并恢复 / Disable and restore** turns off startup and checks restoration of the project's changes. **导出脱敏报告 / Export sanitized report** saves only allowlisted diagnostic fields, without full SIM/device identifiers, keys, host addresses or raw SIP logs. Reports are never uploaded automatically.

After a connection failure, recheck before retrying. Interrupted writes leave an installation transaction receipt or an incomplete directory and block replacement. Arbitrary interrupted installs do not yet have automatic repair; preserve the files for maintainer inspection. Initial Root flashing is separate, erases user data and is not started by the GUI; follow [INSTALL.en.md](INSTALL.en.md).

Hardware call evidence remains limited to one Beijing Unicom Q10. Other provinces with the same technical conditions are eligible for experimental acceptance, not certified nationwide support. Other MNCs, ISIM, China Mobile and China Telecom require separate adaptation. See [the compatibility matrix](COMPATIBILITY.en.md).
