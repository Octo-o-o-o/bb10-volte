"""Public owner instructions; the shell stops before trust or pairing on failure."""
from pathlib import Path
import json
import re
from i18n import tr


def phone_commands(name):
    if not re.fullmatch(r'bb10-pair-[a-f0-9]{12}\.py', name):
        raise ValueError('pairing_result_invalid')
    return ('bb10_pair_file=/accounts/1000/shared/downloads/' + name + '\n'
            'bb10_pair_uid_status=0\n'
            'bb10_pair_uid=$(id -u) || bb10_pair_uid_status=$?\n'
            'case "$bb10_pair_uid" in \'\'|*[!0-9]*) bb10_pair_uid_status=1 ;; esac\n'
            'if [ "$bb10_pair_uid_status" != 0 ]; then\n'
            '  echo "ROOT_CHECK_FAILED: id -u did not confirm a UID; keep its error for diagnosis"\n'
            'elif [ "$bb10_pair_uid" != 0 ]; then\n'
            '  echo "ROOT_REQUIRED: enter your existing Root shell first"\n'
            'elif [ ! -f "$bb10_pair_file" ]; then\n'
            '  echo "PAIR_FILE_NOT_FOUND: $bb10_pair_file"\n'
            'else\n'
            '  /proc/boot/pathtrust "!$bb10_pair_file" &&\n'
            '    /usr/bin/python3.2 "$bb10_pair_file"\n'
            'fi')


def public_instructions(name):
    commands = phone_commands(name)
    return (tr('手机授权操作说明') + '\n\n' +
            tr('推荐：将同编号的 -request.json 复制到手机 Downloads，在新版 BB10 VoLTE 的“管理与恢复 → 连接电脑”中选择它，核对请求编号后点击“授权这台电脑”。无需输入终端命令。') + '\n' +
            tr('将生成的 -result.json 复制回原电脑并导入，继续核验手机身份和 Root。仅使用手机版时可以跳过电脑配对。') + '\n\n' +
            tr('以下终端步骤仅供未安装新版手机应用时使用。') + '\n\n' +
            tr('将同名 .py 文件复制到手机内部存储 Downloads，保持文件名不变。') + '\n' +
            tr('先按原 Root 工具说明进入 Root 终端。__root 前有两个下划线；有些工具使用 u_root。找不到入口时，先恢复原 Root 访问。') + '\n' +
            tr('执行 id -u，命令应成功并输出 0；报错或没有有效数字时，当前权限尚未确认。再复制执行下面整个命令块，不要抄写 $ 或 # 提示符。') + '\n\n' +
            commands + '\n\n' +
            tr('ROOT_CHECK_FAILED 表示权限检查未完成，请保留 id -u 的报错；ROOT_REQUIRED 表示读到的 UID 不是 0；PAIR_FILE_NOT_FOUND 表示该路径没有授权文件。出现 Permission denied 时停止，核对当前 Root 终端与命令路径。') + '\n' +
            tr('仅在脚本提示后输入大写 PAIR；它不是 shell 命令。只有确需临时启动 SSH 时才在脚本提示后输入 START。') + '\n' +
            tr('将同编号的 result.json 带回原来生成请求的电脑。保留电脑私钥；不要换用其他请求或电脑的结果。') + '\n')


def export_pairing_files(script, directory):
    """Preflight both exports before creating anything. Never replace a file/link."""
    from connection_recovery import RecoveryError
    script, directory = Path(script), Path(directory)
    outputs = {script.name: script.read_bytes(),
               script.stem + '-instructions.txt': public_instructions(script.name).encode('utf-8')}
    # Read only the sibling public key, never evaluate an exported Python file.
    from phone_pairing import pairing_request
    phone_commands(script.name)  # strict filename/request identifier check
    key_file = script.parent / 'identity.pub'
    if (not key_file.is_file() or key_file.is_symlink() or key_file.is_junction() or
            key_file.stat().st_size > 16384):
        raise RecoveryError('pairing_result_invalid')
    request = pairing_request(key_file.read_text(encoding='ascii'), script.stem[len('bb10-pair-'):])
    outputs[script.stem + '-request.json'] = (json.dumps(request, sort_keys=True, indent=2) + '\n').encode('ascii')
    for name, data in outputs.items():
        target = directory / name
        if target.is_symlink() or target.is_junction() or (target.exists() and
                (not target.is_file() or target.read_bytes() != data)):
            raise RecoveryError('pairing_export_conflict')
    for name, data in outputs.items():
        target = directory / name
        if not target.exists():
            with target.open('xb') as output:
                output.write(data)
