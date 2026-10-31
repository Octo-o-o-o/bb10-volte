"""Check the explicit public-file allowlist before making a source release."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
TOP = {'.gitignore', '.gitattributes', 'README.md', 'README.en.md', 'CONTRIBUTING.md',
       'LICENSE', 'NOTICE.md', 'project.json', '.github/workflows/check.yml', 'Start-GUI.cmd',
       'tools/windows-freeze-requirements.txt', 'tools/macos-freeze-requirements.txt',
       'assets/icon.png', 'assets/icon-96.png', 'assets/app.ico', 'assets/app.icns',
       'website/.gitignore', 'website/README.md', 'website/package.json',
       'website/package-lock.json', 'website/playwright.config.mjs',
       'website/src/_headers', 'website/src/robots.txt',
       'website/src/assets/app-icon.png', 'website/src/assets/app-status.png',
       'website/src/assets/app-status-en.jpg', 'website/src/assets/icon.png',
       'website/src/assets/carrier-acceptance-r8.png',
       'website/src/assets/carrier-acceptance-r8.prompt.txt'}
PATTERNS = ('device/*.py', 'device/*.sh', 'driver/*.c', 'driver/*.exports',
            'experiments/q20_autoroot_v2/*.py', 'experiments/q20_autoroot_v2/*.sh',
            'experiments/q20_autoroot_v2/*.md', 'experiments/q20_autoroot_v2/configurations/*.json',
            'experiments/q10_telecom/*.py', 'experiments/q10_telecom/*.md',
            'tools/*.py', 'tools/*.ps1', 'tests/*.py', 'docs/**/*.md', 'materials/*.md', 'materials/*.json', 'profiles/*.json',
            'website/scripts/*.mjs', 'website/tests/*.mjs', 'website/src/*.html',
            'website/src/en/*.html', 'website/src/*.css', 'website/src/*.js',
            'website/src/*.xml', 'website/src/*.json')
HELPER = 'driver/devnp-volte_swcrypto_probe.so'
RECORDING_MANIFEST = 'materials/recording-files.json'
SENSITIVE = {
    'access token': re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[0-9A-Z]{16})'),
    'private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'SSH public key': re.compile(r'(?:ssh-rsa|ssh-ed25519)\s+[A-Za-z0-9+/]{40,}'),
    'IMSI': re.compile(r'(?<![A-Za-z0-9])4600[0-9]{11}(?![A-Za-z0-9])'),
    '15-digit device or SIM identifier': re.compile(r'(?<![A-Za-z0-9])[0-9]{15}(?![A-Za-z0-9])'),
    'device PIN field': re.compile(r'(?i)["\']pin["\']\s*:\s*["\'][0-9a-f]{8}["\']'),
    'ICCID': re.compile(r'(?<![A-Za-z0-9])8986[0-9]{14,18}(?![A-Za-z0-9])'),
    'phone number': re.compile(r'(?<![A-Za-z0-9])(?:\+86[- ]?)?1[3-9][0-9]{9}(?![A-Za-z0-9])'),
    'local user path': re.compile(r'(?i)(?:[A-Z]:[/\\]Users[/\\](?!Public(?:[/\\]|$))[^\s/\\]+|[A-Z]:[/\\]LifeSpace[/\\])'),
}


def recording_files():
    manifest = json.loads((ROOT / RECORDING_MANIFEST).read_text(encoding='utf-8'))
    assert manifest['schema'] == 1
    for name, digest in manifest['files'].items():
        assert name.startswith(('docs/recordings/', 'scripts/recordings/'))
        assert '\\' not in name and '..' not in Path(name).parts
        assert re.fullmatch('[0-9a-f]{64}', digest)
    return manifest['files']


def selected_files():
    files = {ROOT / name for name in TOP | {HELPER}}
    files.update(ROOT / name for name in recording_files())
    for pattern in PATTERNS:
        files.update(ROOT.glob(pattern))
    for path in files:
        assert path.is_file() and not path.is_symlink(), 'Missing or linked release input: ' + str(path.relative_to(ROOT))
        assert path.resolve().is_relative_to(ROOT)
        assert not any(p in ('private', 'downloads', 'build', 'dist', '.git', '__pycache__') for p in path.relative_to(ROOT).parts)
    return sorted(files, key=lambda x: x.relative_to(ROOT).as_posix())


def check(check_git=False):
    files = selected_files()
    names = {p.relative_to(ROOT).as_posix() for p in files}
    if check_git:
        tracked = set(subprocess.check_output(
            ['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0')) - {''}
        assert tracked == names, ('Git/public allowlist mismatch: extra=' +
                                  repr(sorted(tracked - names)) + ', missing=' +
                                  repr(sorted(names - tracked)))
    sources = json.loads((ROOT/'materials/sources.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((ROOT/HELPER).read_bytes()).hexdigest() == sources['helper_sha256']
    manifest = json.loads((ROOT/'materials/payload-manifest.json').read_text(encoding='utf-8'))
    for name, digest in manifest['files'].items():
        assert name in names and hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest, 'Stale payload manifest: ' + name
    from auto_carrier import verify_package as verify_unified
    verify_unified()
    diagnostics = json.loads((ROOT/'materials/desktop-diagnostics.json').read_text(encoding='utf-8'))
    assert diagnostics.get('schema') == 1
    assert set(diagnostics['files']) == {'tools/root_probe.py', 'tools/stage_cleanup.py'}
    for name, digest in diagnostics['files'].items():
        assert name in names and hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest, 'Stale diagnostic manifest: ' + name
    issues = []
    hashes = {}
    recordings = recording_files()
    for path in files:
        name = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        hashes[name] = hashlib.sha256(data).hexdigest()
        if name in recordings:
            assert hashes[name] == recordings[name], 'Changed recording input: ' + name
            if path.suffix in ('.png', '.mp4', '.mp3'):
                valid = (data.startswith(b'\x89PNG\r\n\x1a\n') if path.suffix == '.png' else
                         data[4:8] == b'ftyp' if path.suffix == '.mp4' else
                         data.startswith(b'ID3') or len(data) > 1 and data[0] == 255 and data[1] & 224 == 224)
                assert valid, 'Invalid recording media: ' + name
                continue
        if name in {'assets/icon.png', 'assets/icon-96.png', 'assets/app.ico', 'assets/app.icns'}:
            magic = {'.png': b'\x89PNG\r\n\x1a\n', '.ico': b'\x00\x00\x01\x00', '.icns': b'icns'}
            assert data.startswith(magic[path.suffix]), 'Invalid icon format: ' + name
            continue
        if name == HELPER:
            continue
        if name.startswith('website/src/assets/') and path.suffix in ('.png', '.jpg'):
            assert ((path.suffix == '.png' and data.startswith(b'\x89PNG\r\n\x1a\n')) or
                    (path.suffix == '.jpg' and data.startswith(b'\xff\xd8\xff'))), 'Invalid website image: ' + name
            continue
        text = data.decode('utf-8')
        scan_text = text.replace('\\\\', '\\') if name in recordings else text
        for label, pattern in SENSITIVE.items():
            if pattern.search(scan_text):
                issues.append(name + ': possible ' + label + ' (value withheld)')
        if path.suffix == '.py':
            compile(data, name, 'exec')
        if path.suffix == '.json':
            json.loads(text)
        if path.suffix == '.sh':
            assert b'\r' not in data, 'Shell script must use LF: ' + name
        if path.suffix == '.md':
            for target in re.findall(r'\[[^\]]*\]\(([^\s)]+)\)', text):
                if target.startswith(('https://', 'http://', '#', 'mailto:')):
                    continue
                dest = (path.parent/unquote(target.split('#')[0])).resolve()
                if not dest.is_relative_to(ROOT) or dest.relative_to(ROOT).as_posix() not in names:
                    issues.append(name + ': missing public link ' + target)
    assert not issues, '\n'.join(issues)
    return {'checked_public_files': len(files), 'private_materials_excluded': True,
            'git_allowlist_verified': check_git,
            'payload_hashes_verified': True, 'files': hashes}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-git', action='store_true',
                        help='Require Git to track exactly the selected public files')
    report = check(check_git=parser.parse_args().check_git)
    print(json.dumps({k: v for k, v in report.items() if k != 'files'}, indent=2))
