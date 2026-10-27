"""Build a signed universal2 Mac app from an isolated, pinned Python/Tk environment."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import plistlib
import subprocess
import sys
import sysconfig
import tkinter as tk

from check_release import ROOT, check
from workflow import verify_package
from build_windows import runtime_data


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity', required=True, help='Developer ID Application signing identity or fingerprint')
    args = parser.parse_args()
    assert sys.platform == 'darwin'
    spec = json.loads((ROOT/'materials/macos-runtime.json').read_text(encoding='utf-8'))
    assert platform.python_version() == spec['python']
    for line in (ROOT/'tools/macos-freeze-requirements.txt').read_text().splitlines():
        name, version = line.split('==')
        assert importlib.metadata.version(name) == version, 'Build dependency differs: '+name
    t = tk.Tk()
    t.withdraw()
    tcl_version, tk_version = t.tk.call('info', 'patchlevel'), t.tk.call('package', 'provide', 'Tk')
    t.destroy()
    assert tcl_version == spec['tcl'] and tk_version == spec['tk'], (tcl_version, tk_version)
    report = check()
    verify_package()
    project = json.loads((ROOT/'project.json').read_text(encoding='utf-8'))
    work = ROOT/'build/macos'
    work.mkdir(parents=True, exist_ok=True)
    hooks = work/'hooks'
    hooks.mkdir(exist_ok=True)
    (hooks/'hook-workflow.py').write_text('# Local bb10-volte module, not the unrelated workflow package.\n', encoding='utf-8')
    base = Path(sys.base_prefix)
    license_parts = [
        ('bb10-volte '+project['version'], ROOT/'LICENSE'),
        ('Python '+spec['python'], Path(sysconfig.get_path('stdlib'))/'LICENSE.txt'),
        ('PyInstaller '+spec['pyinstaller']+' (bootloader exception included)',
         Path(importlib.metadata.distribution('pyinstaller').locate_file(
             'pyinstaller-'+spec['pyinstaller']+'.dist-info/licenses/COPYING.txt'))),
        ('Tcl '+tcl_version, base/'Frameworks/Tcl.framework/Versions/9.0/Resources/license.terms'),
        ('Tk '+tk_version, base/'Frameworks/Tk.framework/Versions/9.0/Resources/license.terms'),
    ]
    notices = work/'THIRD-PARTY-NOTICES.txt'
    notices.write_text('\n\n'.join(title+'\n'+'='*len(title)+'\n'+path.read_text(encoding='utf-8')
                                   for title, path in license_parts), encoding='utf-8')
    resources = {name: ROOT/name for name in runtime_data() if name != 'materials/windows-runtime.json'}
    resources['materials/macos-runtime.json'] = ROOT/'materials/macos-runtime.json'
    resources['licenses/THIRD-PARTY-NOTICES.txt'] = notices
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir', '--windowed', '--noupx',
               '--name', 'bb10-volte', '--distpath', str(ROOT/'dist'), '--workpath', str(work/'pyinstaller'),
               '--specpath', str(work), '--paths', str(ROOT/'tools'), '--paths', str(ROOT/'device'),
               '--additional-hooks-dir', str(hooks), '--icon', str(ROOT/'assets/app.icns'),
               '--target-architecture', spec['architecture'], '--osx-bundle-identifier', 'org.bb10volte.desktop',
               '--codesign-identity', args.identity, '--exclude-module', 'pip', '--exclude-module', 'setuptools']
    for name, source in sorted(resources.items()):
        command += ['--add-data', str(source)+':'+str(Path(name).parent)]
    command.append(str(ROOT/'tools/macos_main.py'))
    subprocess.run(command, cwd=ROOT, check=True)
    app = ROOT/'dist/bb10-volte.app'
    info_path = app/'Contents/Info.plist'
    with info_path.open('rb') as f:
        info = plistlib.load(f)
    info.update(CFBundleName='bb10-volte', CFBundleDisplayName='bb10-volte',
                CFBundleShortVersionString=project['version'], CFBundleVersion=project['version'],
                NSHighResolutionCapable=True)
    with info_path.open('wb') as f:
        plistlib.dump(info, f)
    subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--options', 'runtime', '--timestamp',
                    '--sign', args.identity, str(app)], check=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2', str(app)], check=True)
    for name, source in resources.items():
        paths = [app/'Contents/Resources'/name, app/'Contents/Frameworks'/name]
        assert any(p.is_file() and sha(p) == sha(source) for p in paths), 'Bundled resource mismatch: '+name
    forbidden = {'private', 'downloads', 'ssh_config', 'known_hosts', 'q10_root_rsa', 'q10_host_rsa'}
    assert not any(any(part in forbidden for part in p.relative_to(app).parts) for p in app.rglob('*'))
    exe = app/'Contents/MacOS/bb10-volte'
    archs = subprocess.check_output(['/usr/bin/lipo', '-archs', str(exe)], text=True).split()
    assert set(archs) == {'arm64', 'x86_64'}, archs
    result = {'project': project['name'], 'version': project['version'], 'app': app.name,
              'architecture': archs, 'python': spec['python'], 'tcl': tcl_version, 'tk': tk_version,
              'pyinstaller': spec['pyinstaller'], 'bundled_data_files': len(resources),
              'bundled_data_hashes_verified': True, 'private_inputs_excluded': True,
              'source_files': report['files'], 'signed_developer_id': True, 'notarized': False}
    (ROOT/'dist'/('bb10-volte-'+project['version']+'-macos-build.json')).write_text(
        json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'source_files'}, indent=2))


if __name__ == '__main__':
    main()
