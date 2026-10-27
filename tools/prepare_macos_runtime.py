"""Prepare a pinned Python/Tk build environment in a new, user-owned directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root', required=True, type=Path, help='New empty build directory outside the source tree')
    parser.add_argument('--installer', type=Path, help='Optional already downloaded official installer')
    args = parser.parse_args()
    assert sys.platform == 'darwin', 'Run the preparation on macOS'
    root = args.build_root.expanduser().resolve()
    assert not root.exists(), 'Choose a new build directory; existing files are not overwritten'
    root.mkdir(parents=True)
    spec = json.loads((ROOT/'materials/macos-runtime.json').read_text(encoding='utf-8'))
    item = spec['python_installer']
    package = root / item['file']
    if args.installer:
        shutil.copyfile(args.installer, package)
    else:
        partial = package.with_suffix('.pkg.partial')
        subprocess.run(['/usr/bin/curl', '--fail', '--location', '--silent', '--show-error',
                        '--connect-timeout', '20', '--max-time', '300', '--output', str(partial), item['url']], check=True)
        assert hashlib.sha256(partial.read_bytes()).hexdigest() == item['sha256']
        partial.replace(package)
    assert hashlib.sha256(package.read_bytes()).hexdigest() == item['sha256'], 'Installer hash mismatch'
    signature = subprocess.run(['/usr/sbin/pkgutil', '--check-signature', str(package)], capture_output=True, text=True, check=True)
    assert item['signer'] in signature.stdout, 'Unexpected Python installer signer'
    expanded = root/'expanded'
    subprocess.run(['/usr/sbin/pkgutil', '--expand-full', str(package), str(expanded)], check=True)
    payload = expanded/'Python_Framework.pkg/Payload'
    framework = root/'Frameworks/Python.framework'
    framework.parent.mkdir()
    shutil.copytree(payload, framework, symlinks=True)
    base = framework/'Versions/3.14'
    env = os.environ.copy()
    env['DYLD_FRAMEWORK_PATH'] = str(framework.parent) + ':' + str(base/'Frameworks')
    env.pop('PYTHONHOME', None)
    env.pop('PYTHONPATH', None)
    python = base/'bin/python3.14'
    venv = root/'venv'
    subprocess.run([str(python), '-m', 'venv', str(venv)], env=env, check=True)
    venv_python = venv/'bin/python'
    subprocess.run([str(venv_python), '-m', 'pip', 'install', '-r',
                    str(ROOT/'tools/macos-freeze-requirements.txt')], env=env, check=True)
    settings = {'python': str(venv_python), 'DYLD_FRAMEWORK_PATH': env['DYLD_FRAMEWORK_PATH'],
                'framework': str(framework), 'installer_sha256': item['sha256']}
    (root/'build-environment.json').write_text(json.dumps(settings, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'prepared': True, 'build_root': str(root), 'python': str(venv_python),
                      'installer_sha256': item['sha256'], 'system_installation_performed': False}))


if __name__ == '__main__':
    main()
