"""Pinned native Mac Root preparation; all operations here are offline from the phone."""
from i18n import tr
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import uuid
import zipfile

from desktop_paths import resource_root, private_root, download_root
from fetch_materials import DownloadError, fetch_entries, sha

ROOT = resource_root()


def fail(code):
    from root_setup import SetupError
    raise SetupError(code)


def specification():
    return json.loads((ROOT / 'materials/macos-root-tools.json').read_text(encoding='utf-8'))


def architecture():
    machine = platform.machine().lower()
    if machine not in ('arm64', 'x86_64'):
        fail('macos_root_architecture_unsupported')
    try:
        version = tuple(int(part) for part in platform.mac_ver()[0].split('.')[:2])
    except ValueError:
        fail('macos_root_version_unsupported')
    if not version or version < (14, 0):
        fail('macos_root_version_unsupported')
    return machine


def fetch(item, cache, progress, proxy=None, offline=False):
    """Fetch exact public artifacts, including anonymously readable GHCR bottles."""
    headers = {'Authorization': 'Bearer QQ=='} if item['url'].startswith('https://ghcr.io/v2/homebrew/core/') else {}
    try:
        fetch_entries([item], cache, progress, proxy, verify_only=offline, headers=headers)
    except FileNotFoundError:
        fail('macos_root_input_missing')
    except DownloadError as error:
        if error.code in ('download_hash_mismatch', 'download_cache_invalid'):
            fail('tool_hash_mismatch')
        raise
    return cache / item['file']


def write_verified(path, data, expected, executable=False):
    if hashlib.sha256(data).hexdigest() != expected:
        fail('tool_hash_mismatch')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as output:
        output.write(data)
    path.chmod(0o700 if executable else 0o600)


def tar_member(archive, name):
    member = archive.getmember(name)
    if not member.isfile() or member.size > 32 * 1024 * 1024:
        fail('tool_hash_mismatch')
    return archive.extractfile(member).read()


def tool_hashes(spec, arch):
    hashes = dict(spec['shared_files'])
    hashes.update({'bb10mt': spec['architectures'][arch]['bb10mt']['sha256'],
                   '7zz': spec['seven_zip']['binary_sha256'],
                   '7zip-License.txt': spec['seven_zip']['license_sha256']})
    for library in spec['architectures'][arch]['libraries']:
        hashes['lib/' + library['library_name']] = library['library_sha256']
        hashes[library['license_file']] = library['license_sha256']
    return hashes


def verified_tools(folder):
    """Recheck tools before every build/flash; no PATH or global-library fallback."""
    work = Path(folder).resolve()
    if work.name != 'autoroot':
        work = work / 'autoroot'
    arch = architecture()
    for name, expected in tool_hashes(specification(), arch).items():
        path = work / name
        if path.is_symlink() or not path.is_file() or sha(path) != expected:
            fail('tool_hash_mismatch')
    loaders = work / 'loaders'
    # The verified loaders.dat/map supply the loader; never scan arbitrary loaders.
    if loaders.is_symlink() or not loaders.is_dir() or any(loaders.iterdir()):
        fail('tool_hash_mismatch')
    return {'bb10mt': work / 'bb10mt', 'seven_zip': work / '7zz',
            'loaders': loaders, 'lib': work / 'lib', 'work': work}


def native_environment(tools):
    env = {name: value for name, value in os.environ.items() if not name.startswith('DYLD_')}
    env.pop('LD_PRELOAD', None)
    env['DYLD_LIBRARY_PATH'] = str(tools['lib'])
    env['DYLD_FALLBACK_LIBRARY_PATH'] = str(tools['lib'])
    return env


def prepare_tools(bundle, work, cache, progress, proxy=None, offline=False):
    spec = specification()
    arch = architecture()
    with zipfile.ZipFile(bundle) as archive:
        for member in archive.infolist():
            target = (work / member.filename).resolve()
            if not target.is_relative_to(work.resolve()) or stat.S_ISLNK(member.external_attr >> 16):
                fail('tool_hash_mismatch')
        # Keep the Root recipe/data, never extract the upstream shared login key.
        replaced = {'patchdata/var/etc/ssh/authorized_keys2',
                    'patchdata/var/etc/ssh/ssh_host_rsa_key', 'patchdata/var/etc/ssh/ssh_host_rsa_key.pub'}
        for member in archive.infolist():
            name = member.filename
            if (not name.startswith('patchdata/') or name in replaced or member.is_dir()):
                continue
            target = work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))
            target.chmod(0o600)
        (work / 'patch.txt').write_bytes(archive.read('patch.txt'))
        for name, expected in spec['shared_files'].items():
            write_verified(work / name, archive.read(name), expected)
        tool = spec['architectures'][arch]['bb10mt']
        write_verified(work / 'bb10mt', archive.read(tool['entry']), tool['sha256'], True)
    for library in spec['architectures'][arch]['libraries']:
        path = fetch(library, cache, progress, proxy, offline)
        with tarfile.open(path, 'r:gz') as archive:
            write_verified(work / 'lib' / library['library_name'], tar_member(archive, library['member']), library['library_sha256'])
            write_verified(work / library['license_file'], tar_member(archive, library['license_member']), library['license_sha256'])
    seven = spec['seven_zip']
    with tarfile.open(fetch(seven, cache, progress, proxy, offline), 'r:xz') as archive:
        write_verified(work / '7zz', tar_member(archive, seven['member']), seven['binary_sha256'], True)
        write_verified(work / '7zip-License.txt', tar_member(archive, seven['license_member']), seven['license_sha256'])
    (work / 'loaders').mkdir()
    tools = verified_tools(work)
    result = subprocess.run([str(tools['bb10mt']), '--help'], cwd=work, env=native_environment(tools),
                            capture_output=True, timeout=30)
    if result.returncode or b'BB10 MultiTool' not in result.stdout:
        fail('macos_root_runtime_unavailable')
    return tools


def prepare_identity(kit):
    """Generate this kit's personal credentials without reusing archive defaults."""
    from connection_recovery import protect
    work = kit / 'autoroot'
    original = (work / 'patch.txt').read_text(encoding='utf-8')
    patch = '\n'.join(line for line in original.splitlines()
                      if not line.startswith('removeapp ') and not line.startswith('#sys.')) + '\n'
    (work / 'patch-owner.txt').write_text(patch, encoding='ascii')
    for name in ('q10_root_rsa', 'q10_host_rsa'):
        subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'rsa', '-b', '3072', '-m', 'PEM', '-N', '', '-f', str(kit / name)],
                       check=True, capture_output=True, timeout=45)
        protect(kit / name)
    ssh = work / 'patchdata/var/etc/ssh'
    ssh.mkdir(parents=True, exist_ok=True)
    key = (kit / 'q10_root_rsa.pub').read_text().strip()
    (ssh / 'authorized_keys2').write_text('from="169.254.0.2",no-agent-forwarding,no-port-forwarding,no-X11-forwarding ' + key + '\n', encoding='ascii')
    shutil.copyfile(kit / 'q10_host_rsa', ssh / 'ssh_host_rsa_key')
    shutil.copyfile(kit / 'q10_host_rsa.pub', ssh / 'ssh_host_rsa_key.pub')
    for path in (ssh / 'ssh_host_rsa_key', ssh / 'authorized_keys2'):
        protect(path)
    config = (ssh / 'sshd_config').read_text()
    config = config.replace('AuthorizedKeysFile=/etc/ssh/authorized_keys2 /accounts/devuser/.ssh/authorized_keys2',
                            'AuthorizedKeysFile=/etc/ssh/authorized_keys2')
    if 'PasswordAuthentication=no' not in config:
        fail('tool_hash_mismatch')
    (ssh / 'sshd_config').write_text(config, encoding='ascii')
    host = ' '.join((kit / 'q10_host_rsa.pub').read_text().split()[:2])
    (kit / 'known_hosts').write_text('169.254.0.1 ' + host + '\n', encoding='ascii')
    def quoted(path):
        value = path.as_posix().replace('%', '%%')
        if any(c in value for c in ('"', '\n', '\r')):
            fail('path_unsupported')
        return '"' + value + '"'
    (kit / 'ssh_config').write_text(
        'Host bb10-root q10-root\n    HostName 169.254.0.1\n    User root\n'
        '    IdentityFile ' + quoted(kit / 'q10_root_rsa') + '\n'
        '    UserKnownHostsFile ' + quoted(kit / 'known_hosts') + '\n'
        '    IdentitiesOnly yes\n    StrictHostKeyChecking yes\n    PasswordAuthentication no\n'
        '    BatchMode yes\n    ConnectTimeout 5\n    Ciphers aes128-ctr,aes192-ctr,aes256-ctr\n'
        '    MACs hmac-sha1\n    HostKeyAlgorithms +ssh-rsa\n    PubkeyAcceptedAlgorithms +ssh-rsa\n', encoding='utf-8')
    protect(kit / 'known_hosts')
    protect(kit / 'ssh_config')


def build_images(kit, original, progress):
    """Run native batch only, then verify every unchanged stock partition."""
    tools = verified_tools(kit / 'autoroot')
    output = kit / 'images'
    output.mkdir()
    progress(tr('原生构建并校验 OS / radio 镜像；不会连接或刷写手机'))
    with (kit / 'root-build.log').open('xb') as log:
        child = subprocess.run([str(tools['bb10mt']), 'batch', '-i', str(original), '-s', 'patch-owner.txt', '-o', str(output)],
                               cwd=tools['work'], env=native_environment(tools), stdout=log, stderr=subprocess.STDOUT,
                               timeout=1800)
    if child.returncode:
        fail('macos_root_build_failed')
    # Upstream can catch script/patch exceptions without a nonzero exit code.
    output_log = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '',
                        (kit / 'root-build.log').read_text(encoding='utf-8', errors='replace'))
    if re.search(r'(?im)^\s*(?:error|failed|exception)\b|\b(?:script|patch|command)\s+(?:error|failed)\b', output_log):
        fail('macos_root_build_failed')
    expected = json.loads((ROOT / 'materials/stock-partitions.json').read_text())
    unchanged = []
    for item in expected['unchanged_partitions']:
        path = output / item['file']
        if path.is_symlink() or not path.is_file() or path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            fail('image_not_verified')
        unchanged.append(item['file'])
    os_files = list(output.glob('*.0.unsigned'))
    radio_files = list(output.glob('*.1.signed'))
    if len(os_files) != 1 or len(radio_files) != 1 or sha(radio_files[0]) != expected['radio_original_sha256']:
        fail('image_not_verified')
    images = []
    for source, name in ((os_files[0], 'Q10_os.unsigned'), (radio_files[0], 'Q10_radio.signed')):
        target = output / name
        source.rename(target)
        images.append({'file': name, 'bytes': target.stat().st_size, 'sha256': sha(target)})
    result = {'offline_build_verified': True, 'phone_connected_or_modified': False, 'platform': 'darwin',
              'unchanged_partitions': unchanged, 'radio_original_sha256': expected['radio_original_sha256'],
              'images': images, 'native_first_flash_acceptance': 'not_run',
              'keys': 'Private and unique to this prepared kit; image hashes vary with keys'}
    (kit / 'build-verification.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def prepare_root_kit_macos(variant, progress, proxy=None, cache_dir=None, offline=False):
    from root_setup import catalog
    if platform.system() != 'Darwin':
        fail('macos_root_architecture_unsupported')
    architecture()
    if variant not in catalog()['auto_root_variants']:
        fail('root_model_unsupported')
    private = private_root()
    private.mkdir(parents=True, mode=0o700, exist_ok=True)
    if shutil.disk_usage(private).free < 15 * 1024 ** 3:
        fail('insufficient_disk')
    cache = Path(cache_dir) if cache_dir else download_root()
    cache.mkdir(parents=True, mode=0o700, exist_ok=True)
    source = json.loads((ROOT / 'materials/sources.json').read_text())
    inputs = {item['id']: item for item in source['verified_inputs']}
    bundle = fetch(inputs['autoroot-v4'], cache, progress, proxy, offline)
    kit = private / ('root-kit-' + uuid.uuid4().hex[:12])
    kit.mkdir(mode=0o700)
    work = kit / 'autoroot'
    work.mkdir(mode=0o700)
    tools = prepare_tools(bundle, work, cache, progress, proxy, offline)
    prepare_identity(kit)
    stock = inputs['stock-q10']
    archive = fetch(stock, cache, progress, proxy, offline)
    stock_dir = kit / 'stock'
    stock_dir.mkdir()
    progress(tr('解包并校验匹配 Q10 的原厂固件'))
    result = subprocess.run([str(tools['seven_zip']), 'e', '-y', str(archive), stock['extracted_file'], '-o' + str(stock_dir)],
                            capture_output=True, timeout=600)
    original = stock_dir / stock['extracted_file']
    if result.returncode or original.is_symlink() or not original.is_file() or sha(original) != stock['extracted_sha256']:
        fail('image_not_verified')
    preparation = {'offline_preparation_complete': True, 'phone_connected_or_modified': False,
                   'platform': 'darwin', 'architecture': architecture(), 'minimum_macos': '14.0',
                   'shared_default_ssh_authorization_replaced': True, 'appworld_preserved': True,
                   'stock_sha256': stock['extracted_sha256'], 'root_bundle_sha256': inputs['autoroot-v4']['sha256'],
                   'tool_hashes': tool_hashes(specification(), architecture())}
    (kit / 'preparation.json').write_text(json.dumps(preparation, indent=2) + '\n')
    build_images(kit, original, progress)
    (kit / 'setup-state.json').write_text(json.dumps({'variant': variant, 'stage': 'prepared', 'platform': 'darwin'}, indent=2) + '\n')
    return str(kit)
