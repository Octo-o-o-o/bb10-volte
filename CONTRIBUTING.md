# Contributing / 参与贡献

English and Chinese reports and pull requests are welcome.

欢迎使用中文或英文提交问题和改进。中文问题说明见 [ISSUES.md](docs/ISSUES.md)。

Other BB10 OS versions, Q10 variants and device models are welcome in issues and pull requests, including failure reports and proposed ports. State the full OS version and device variant so that compatibility can be evaluated. Only Q10 SQN100-3 / BB10 OS 10.3.3.3216 has been hardware-tested so far.

其他系统版本、Q10 版本或机型遇到问题，也欢迎提交 issue；欢迎通过 PR 提供适配、修复和测试结果。请写明完整系统版本和具体机型，便于判断差异。当前仅有 Q10 SQN100-3 / BB10 OS 10.3.3.3216 的实机验证记录。

## Report a problem

Include the model and variant, BB10 version, carrier MCC/MNC, project version or commit, host OS/Python version, command/stage and the redacted error. For calls, state the time and timezone, incoming/outgoing direction, ringing/answering, audio in each direction and whether LTE remained active.

Do not attach `private/`, Root images, SSH keys, raw SIP traces, phone numbers, IMSI/ICCID/IMEI/PIN or authentication material. Share non-identifying status fields and firmware hashes. Review text before posting it publicly.

## Change the project

1. Keep device code compatible with **Python 3.2**. Desktop tools use Python 3.14.
2. Preserve original-file hash checks, process/configuration ownership checks and recoverability. Support for another device requires separate native ABI, patch and hardware validation; removing a hash guard is not evidence of compatibility.
3. Update both [README.md](README.md) and [README.en.md](README.en.md) when requirements, commands or validation claims change.
4. Run the tests and [build/release checks](docs/BUILD.en.md). If a device payload changes, regenerate its manifest using `python tools/q10.py manifest` and review the diff.
5. Keep public additions in the explicit allowlist in `tools/check_release.py`. Stage them, then run `python tools/check_release.py --check-git` before committing.
6. Describe what changed, why, the validation performed and the remaining hardware limitations in the pull request.

Contributions to original project code and documentation use the existing [MIT License](LICENSE). Retain third-party attribution; do not add proprietary firmware or device-specific credentials to the repository.
