"""Build the offline Windows GUI from explicit, verified public inputs."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import urllib.request
import uuid
import zipfile

from check_release import ROOT, check
from workflow import FILES, verify_package
from desktop_paths import desktop_release_version


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(item, offline=False):
    folder = ROOT / 'downloads'
    folder.mkdir(exist_ok=True)
    path = folder / item['file']
    assert path.parent == folder and not path.is_symlink()
    if not path.exists():
        if offline:
            raise RuntimeError('Offline input missing: ' + item['file'])
        temporary = path.with_name(path.name + '.' + uuid.uuid4().hex[:8] + '.partial')
        with urllib.request.urlopen(item['url'], timeout=45) as response, temporary.open('xb') as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
        assert digest(temporary) == item['sha256'], 'Downloaded input hash mismatch'
        temporary.replace(path)
    assert digest(path) == item['sha256'], 'Cached input hash mismatch: ' + item['file']
    return path


def runtime_data():
    """Include the QNX cleanup resource, never keys, root images or download tools."""
    names = set(FILES) | {'project.json', 'materials/payload-manifest.json',
                         'materials/windows-runtime.json', 'LICENSE', 'NOTICE.md',
                         'assets/icon.png', 'assets/icon-96.png', 'assets/app.ico', 'tools/stage_cleanup.py',
                         'tools/phone_pairing.py', 'tools/root_probe.py', 'materials/desktop-diagnostics.json',
                         'materials/macos-root-tools.json', 'materials/macos-device-validation-2026-10-28.json',
                         'materials/macos-development-2026-10-29.json',
                         'tools/install_usb_drivers.ps1', 'tools/verify_signature.ps1',
                         'materials/sources.json', 'materials/stock-partitions.json',
                         'materials/usb-drivers.json', 'materials/first-run-tools.json',
                         'materials/community-research.json', 'materials/upstream-addon-research.json'}
    names.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'profiles').glob('*.json'))
    names.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'docs').glob('*.md'))
    return sorted(names)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='Require cached, hash-verified build inputs; no downloads')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist', help='Destination for this build and its records')
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    assert sys.platform == 'win32' and platform.machine().lower() in ('amd64', 'x86_64')
    spec = json.loads((ROOT / 'materials/windows-runtime.json').read_text(encoding='utf-8'))
    assert platform.python_version() == spec['python'], 'Use the pinned Python build'
    for line in (ROOT / 'tools/windows-freeze-requirements.txt').read_text().splitlines():
        name, version = line.split('==')
        assert importlib.metadata.version(name) == version, 'Build dependency differs: ' + name
    import tkinter as tk
    interp = tk.Tcl()
    assert interp.call('info', 'patchlevel') == spec['tcl']
    source_report = check()
    verify_package()
    project = json.loads((ROOT / 'project.json').read_text(encoding='utf-8'))
    archive = fetch(spec['openssh'], args.offline)
    vendor = ROOT / 'build/windows-vendor/openssh'
    vendor.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for name, expected in spec['openssh']['files'].items():
            data = z.read(spec['openssh']['prefix'] + name)
            assert hashlib.sha256(data).hexdigest() == expected
            (vendor / name).write_bytes(data)
    # Published hashes are mandatory in both modes. Authenticode is an extra
    # online-build check; certificate chain retrieval can itself use the network.
    signatures = {}
    if not args.offline:
        powershell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
        for name in ('ssh.exe', 'scp.exe', 'ssh-keygen.exe', 'libcrypto.dll'):
            signatures[name] = json.loads(subprocess.check_output([
                powershell, '-NoProfile', '-File', str(ROOT / 'tools/verify_signature.ps1'),
                '-Path', str(vendor / name)], text=True))
    work = ROOT / 'build/windows'
    work.mkdir(parents=True, exist_ok=True)
    # The contrib hook named workflow belongs to an unrelated PyPI package.
    hooks = work / 'hooks'
    hooks.mkdir(exist_ok=True)
    (hooks / 'hook-workflow.py').write_text('# Local bb10-volte module; no third-party workflow package.\n', encoding='utf-8')
    license_parts = [('bb10-volte ' + project['version'], ROOT / 'LICENSE'),
                     ('Python ' + spec['python'], Path(sys.base_prefix) / 'LICENSE.txt'),
                     ('PyInstaller ' + spec['pyinstaller'] + ' (bootloader exception included)',
                      Path(importlib.metadata.distribution('pyinstaller').locate_file(
                          'pyinstaller-' + spec['pyinstaller'] + '.dist-info/licenses/COPYING.txt')))]
    license_parts += [(item['component'], fetch(item, args.offline)) for item in spec['licenses']]
    license_parts += [('Microsoft Win32-OpenSSH LICENSE', vendor / 'LICENSE.txt'),
                      ('Microsoft Win32-OpenSSH NOTICE', vendor / 'NOTICE.txt')]
    notices = work / 'THIRD-PARTY-NOTICES.txt'
    notices.write_text('\n\n'.join(title + '\n' + '=' * len(title) + '\n' +
                                  path.read_text(encoding='utf-8') for title, path in license_parts), encoding='utf-8')
    version = tuple(int(p) for p in project['version'].split('.')) + (project.get('desktop_revision', 0),)
    version_file = work / 'version.txt'
    version_file.write_text(
        'VSVersionInfo(ffi=FixedFileInfo(filevers={0!r}, prodvers={0!r}, mask=0x3f, flags=0, OS=0x40004, '
        'fileType=0x1, subtype=0, date=(0,0)), kids=[StringFileInfo([StringTable("040904B0", ['
        'StringStruct("FileDescription", "bb10-volte"), StringStruct("ProductName", "bb10-volte"),'
        'StringStruct("FileVersion", "{1}"), StringStruct("ProductVersion", "{1}"),'
        'StringStruct("OriginalFilename", "bb10-volte.exe")])]), VarFileInfo([VarStruct("Translation", [1033,1200])])])'
        .format(version, desktop_release_version(project)), encoding='utf-8')
    build_name = project['name'] + '-' + desktop_release_version(project) + '-windows-x64'
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed', '--noupx',
               '--name', build_name, '--distpath', str(output_dir), '--workpath', str(work / 'pyinstaller'),
               '--specpath', str(work), '--paths', str(ROOT / 'tools'), '--paths', str(ROOT / 'device'),
               '--additional-hooks-dir', str(hooks),
               '--icon', str(ROOT / 'assets/app.ico'), '--version-file', str(version_file),
               '--exclude-module', 'PIL', '--exclude-module', 'pip', '--exclude-module', 'setuptools']
    bundled = {name: ROOT / name for name in runtime_data()}
    bundled.update({'vendor/openssh/' + name: vendor / name for name in spec['openssh']['files']})
    bundled['licenses/THIRD-PARTY-NOTICES.txt'] = notices
    for name, source in sorted(bundled.items()):
        command += ['--add-data', str(source) + ':' + str(Path(name).parent)]
    command.append(str(ROOT / 'tools/windows_main.py'))
    subprocess.run(command, cwd=ROOT, check=True)
    output = output_dir / (build_name + '.exe')
    from PyInstaller.archive.readers import CArchiveReader
    reader = CArchiveReader(str(output))
    index = {n.replace('\\', '/'): n for n in reader.toc}
    for name, path in bundled.items():
        assert hashlib.sha256(reader.extract(index[name])).hexdigest() == digest(path), 'Bundled data changed: ' + name
    forbidden = ('private/', 'downloads/', 'ssh_config', 'known_hosts', 'q10_root_rsa', 'q10_host_rsa')
    assert not any(any(token in name for token in forbidden) for name in index)
    archive_modules = reader.open_embedded_archive('PYZ.pyz').toc
    assert {'root_setup', 'setup_wizard', 'prepare_root', 'prepare_usb_drivers', 'build_root',
            'connection_recovery', 'recovery_gui', 'phone_pairing', 'connection_dialog',
            'connection_flow', 'connection_materials', 'ui_theme'} <= set(archive_modules)
    assert 'build_windows' not in archive_modules
    sha = digest(output)
    output.with_suffix('.exe.sha256').write_text(sha + '  ' + output.name + '\n', encoding='ascii')
    report = {'project': project['name'], 'version': project['version'], 'artifact': output.name,
              'desktop_revision': project.get('desktop_revision'),
              'sha256': sha, 'bytes': output.stat().st_size, 'python': spec['python'],
              'pyinstaller': spec['pyinstaller'], 'openssh': spec['openssh']['version'],
              'source_files': source_report['files'], 'bundled_data_files': len(bundled),
              'bundled_data_hashes_verified': True, 'private_inputs_excluded': True,
              'first_run_setup_included': True, 'normal_operation_runtime_downloads': [],
              'first_run_downloads_require_user_action': True, 'authenticode_signed': False,
              'openssh_authenticode': signatures, 'build_inputs_from_cache_only': args.offline}
    output.with_suffix('.build.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('source_files', 'openssh_authenticode')}, indent=2))


if __name__ == '__main__':
    main()
