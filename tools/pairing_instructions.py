"""Public owner instructions; the shell stops before trust or pairing on failure."""
from pathlib import Path
import re
from i18n import tr


def phone_commands(name):
    if not re.fullmatch(r'bb10-pair-[a-f0-9]{12}\.py', name):
        raise ValueError('pairing_result_invalid')
    return ('bb10_pair_file=/accounts/1000/shared/downloads/' + name + '\n'
            'if [ "$(id -u)" != 0 ]; then\n'
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
            tr('将同名 .py 文件复制到手机内部存储 Downloads，保持文件名不变。') + '\n' +
            tr('先按原 Root 工具说明进入 Root 终端。__root 前有两个下划线；有些工具使用 u_root。找不到入口时，先恢复原 Root 访问。') + '\n' +
            tr('执行 id -u，输出必须是 0。然后复制并执行下面整个命令块；不要抄写终端的 $ 或 # 提示符。') + '\n\n' +
            commands + '\n\n' +
            tr('ROOT_REQUIRED 表示当前权限不足；PAIR_FILE_NOT_FOUND 表示该路径没有授权文件。出现 Permission denied 时停止，先核对 Root 权限。') + '\n' +
            tr('仅在脚本提示后输入大写 PAIR；它不是 shell 命令。只有确需临时启动 SSH 时才在脚本提示后输入 START。') + '\n' +
            tr('将同编号的 result.json 带回原来生成请求的电脑。保留电脑私钥；不要换用其他请求或电脑的结果。') + '\n')


def export_pairing_files(script, directory):
    """Preflight both exports before creating anything. Never replace a file/link."""
    from connection_recovery import RecoveryError
    script, directory = Path(script), Path(directory)
    outputs = {script.name: script.read_bytes(),
               script.stem + '-instructions.txt': public_instructions(script.name).encode('utf-8')}
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
