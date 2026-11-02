"""Create signed, offline mobile bundles. Private keys never enter release inputs."""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
import sys

ROOT = Path(__file__).resolve().parents[1]
MOBILE_VERSION = json.loads((ROOT / 'project.json').read_text(encoding='utf-8'))['mobile_version']
BUILDER = 'ghcr.io/xiazy/blackberry10-toolchain@sha256:60ce49510a37ed92368cca010bbaabf97b12d209b9fab179e8491b266bb2578f'


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def openssl():
    found = shutil.which('openssl')
    if found:
        return found
    git = shutil.which('git')
    if git:
        for parent in Path(git).resolve().parents:
            candidate = parent / 'mingw64/bin/openssl.exe'
            if candidate.is_file():
                return str(candidate)
    raise RuntimeError('OpenSSL is required to sign mobile release packages')


def public_key(private_key):
    output = subprocess.check_output([openssl(), 'rsa', '-in', str(private_key), '-noout', '-modulus'],
                                     stderr=subprocess.PIPE).decode('ascii').strip()
    if not output.startswith('Modulus='):
        raise ValueError('Unable to read RSA modulus')
    key = {'n': output.split('=', 1)[1].lower(), 'e': 65537}
    if len(key['n']) not in (512, 768, 1024):
        raise ValueError('Use an RSA-2048, RSA-3072 or RSA-4096 release key')
    # Explicitly verify the exponent rather than assuming it from the modulus.
    details = subprocess.check_output([openssl(), 'pkey', '-in', str(private_key), '-text', '-noout'],
                                      stderr=subprocess.PIPE)
    if b'publicExponent: 65537 ' not in details:
        raise ValueError('The release key exponent must be 65537')
    key['key_id'] = sha(canonical(key))
    return key


def create_key(private_key, public_file):
    private_key, public_file = Path(private_key), Path(public_file)
    if private_key.exists() or public_file.exists():
        raise ValueError('Refusing to replace an existing release key')
    private_key.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([openssl(), 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072',
                    '-out', str(private_key)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    os.chmod(private_key, 0o600)
    public_file.parent.mkdir(parents=True, exist_ok=True)
    key = public_key(private_key)
    public_file.write_bytes(canonical(key) + b'\n')
    return key['key_id']


def sign(data, private_key):
    with tempfile.TemporaryDirectory() as temporary:
        source, result = Path(temporary) / 'manifest', Path(temporary) / 'signature'
        source.write_bytes(data)
        subprocess.run([openssl(), 'dgst', '-sha256', '-sign', str(private_key), '-out', str(result),
                        str(source)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.read_bytes()


def entry_module():
    spec = importlib.util.spec_from_file_location('mobile_entry_check', ROOT / 'mobile/runtime/entry.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def trial_inputs():
    blobs = {}
    # Generate the exact desktop trial catalog at build time. Device code never
    # imports desktop tools or accepts an arbitrary profile from shared storage.
    if str(ROOT / 'device') not in sys.path:
        sys.path.insert(0, str(ROOT / 'device'))
    if str(ROOT / 'tools') not in sys.path:
        sys.path.insert(0, str(ROOT / 'tools'))
    import variant_trials
    import device_support
    import profiles
    trials = []
    for variant in sorted(device_support.catalog()):
        for operator in sorted(profiles.TRIAL_OPERATORS):
            plan = variant_trials.plan(variant, operator)
            if plan['route'] not in ('manual_candidate', 'read_only_lifecycle_pending'):
                continue
            profile = variant_trials.profile(variant, operator)
            blobs['profiles/' + profile['id'] + '.json'] = profiles.canonical(profile)
            trials.append(dict(profile_id=profile['id'], variant=variant, operator=operator,
                               route=plan['route']))
    blobs['materials/variant-trials.json'] = canonical({'schema': 1, 'cases': trials})
    return blobs


def bundle_inputs(key):
    blobs = {}
    launcher = ROOT / 'mobile/native/build/job-launcher'
    if not launcher.is_file() or launcher.is_symlink():
        raise ValueError('Build the QNX background launcher with tools/build_mobile.py first')
    blobs['runtime/job-launcher'] = launcher.read_bytes()
    for manifest_name in ('unified-payload.json', 'payload-manifest.json'):
        payload = json.loads((ROOT / 'materials' / manifest_name).read_text(encoding='ascii'))
        for name, expected in payload['files'].items():
            source = ROOT / name
            if source.is_symlink() or sha(source.read_bytes()) != expected:
                raise ValueError('Stale device manifest; review changes before regenerating: ' + name)
    for source in sorted((ROOT / 'mobile/runtime').glob('*.py')):
        blob = source.read_bytes().replace(b'\r\n', b'\n')
        if source.name == 'entry.py':
            needle = b'RELEASE_KEY = None  # substituted by tools/package_mobile.py'
            if blob.count(needle) != 1:
                raise ValueError('Unexpected entry point key placeholder')
            blob = blob.replace(needle, b'RELEASE_KEY = ' + repr(key).encode('ascii'))
        blobs['runtime/' + source.name] = blob
    for source in sorted((ROOT / 'device').glob('*')):
        if source.suffix in ('.py', '.sh'):
            blobs['payload/device/' + source.name] = source.read_bytes()
    blobs['payload/driver/devnp-volte_swcrypto_probe.so'] = (ROOT / 'driver/devnp-volte_swcrypto_probe.so').read_bytes()
    blobs['payload/payload.json'] = (ROOT / 'materials/unified-payload.json').read_bytes()
    blobs['payload/payload-manifest.json'] = (ROOT / 'materials/payload-manifest.json').read_bytes()
    for source in sorted((ROOT / 'profiles').glob('*.json')):
        blobs['profiles/' + source.name] = source.read_bytes()
    blobs.update(trial_inputs())
    for name in ('unified-carrier-acceptance.json', 'sms-device-validation-2026-11-01.json'):
        blobs['materials/' + name] = (ROOT / 'materials' / name).read_bytes()
    return blobs


def make_bundle(private_key, version=MOBILE_VERSION):
    key = public_key(private_key)
    expected = json.loads((ROOT / 'materials/mobile-release-key.json').read_text(encoding='ascii'))
    if key != expected:
        raise ValueError('Signing key does not match the pinned release public key')
    blobs = bundle_inputs(key)
    manifest = {'schema': 2, 'kind': 'bb10-volte-mobile', 'protocol': 2, 'version': version,
                'files': {name: {'sha256': sha(data), 'size': len(data)} for name, data in blobs.items()}}
    raw = canonical(manifest)
    signature = canonical({'algorithm': 'RSASSA-PKCS1-v1_5-SHA256', 'key_id': key['key_id'],
                           'signature': base64.b64encode(sign(raw, private_key)).decode('ascii')})
    entry_module().validate_manifest(raw, signature, key)
    return blobs, raw, signature, key


def write_zip(path, blobs):
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(blobs.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 2, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100600 << 16)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)


def prepare_assets(private_key, version=MOBILE_VERSION):
    from mobile_support import prepare_support_assets
    prepare_support_assets(ROOT)
    blobs, manifest, signature, key = make_bundle(private_key, version)
    assets = ROOT / 'mobile/native/assets'
    for name, data in dict(blobs, **{'manifest.json': manifest, 'manifest.sig.json': signature}).items():
        destination = assets / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    return blobs, manifest, signature, key


def package(private_key, version=MOBILE_VERSION, bar=None):
    blobs, manifest, signature, key = prepare_assets(private_key, version)
    destination = ROOT / 'dist/mobile'
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / ('bb10-volte-' + version + '-update.zip')
    write_zip(archive, dict(blobs, **{'manifest.json': manifest, 'manifest.sig.json': signature}))
    entry_module().read_archive(str(archive.resolve()), key)
    artifacts = {archive.name: sha(archive.read_bytes())}
    if bar is not None:
        bar = Path(bar)
        with zipfile.ZipFile(bar) as parsed:
            from mobile_support import verify_bar_support
            verify_bar_support(parsed, ROOT)
            names = parsed.namelist()
            if 'META-INF/MANIFEST.MF' not in names:
                raise ValueError('BAR is missing platform manifest')
            platform = parsed.read('META-INF/MANIFEST.MF')
            if b'com.octolab.bb10volte' not in platform or not any(name.endswith('entry.py') for name in names):
                raise ValueError('BAR identity or runtime assets mismatch')
            for name, data in dict(blobs, **{'manifest.json': manifest, 'manifest.sig.json': signature}).items():
                if parsed.read('native/assets/' + name) != data:
                    raise ValueError('BAR contains stale or different signed assets: ' + name)
        out = destination / ('bb10-volte-' + version + '.bar')
        shutil.copyfile(bar, out)
        artifacts[out.name] = sha(out.read_bytes())
        bootstrap = destination / ('bb10-volte-' + version + '-bootstrap.zip')
        instructions = (ROOT / 'mobile/bootstrap/INSTALL.txt').read_bytes().replace(b'VERSION', version.encode('ascii'))
        package_manifest = ('Package-Id: bb10-volte-mobile\nPackage-Name: BB10 VoLTE\n'
                            'Package-Version: ' + version + '\n').encode('ascii')
        write_zip(bootstrap, {'MANIFEST': package_manifest, 'pkg.bar': out.read_bytes(),
                             'INSTALL.txt': instructions})
        artifacts[bootstrap.name] = sha(bootstrap.read_bytes())
    index = {'schema': 2, 'version': version, 'package_url':
             'https://bb10-downloads.octoooo.com/mobile/' + archive.name,
             'sha256': artifacts[archive.name], 'size': archive.stat().st_size,
             'title': 'BB10 VoLTE mobile preview', 'key_id': key['key_id']}
    (destination / 'latest.json').write_bytes(canonical(index) + b'\n')
    artifacts['latest.json'] = sha((destination / 'latest.json').read_bytes())
    (destination / 'SHA256SUMS.txt').write_text(''.join(digest + '  ' + name + '\n'
        for name, digest in sorted(artifacts.items())), encoding='ascii', newline='\n')
    report = {'schema': 1, 'version': version, 'protocol': 2, 'publisher_key_id': key['key_id'],
              'builder_image': BUILDER, 'artifacts': artifacts,
              'bundle_signature_verified': True, 'hardware_acceptance': 'not_established_by_packaging'}
    (destination / 'package-validation.json').write_bytes(canonical(report) + b'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('generate-key', 'prepare', 'package'))
    parser.add_argument('--key', type=Path, required=True)
    parser.add_argument('--public-key', type=Path, default=ROOT / 'materials/mobile-release-key.json')
    parser.add_argument('--version', default=MOBILE_VERSION)
    parser.add_argument('--bar', type=Path)
    args = parser.parse_args()
    if args.action == 'generate-key':
        result = {'key_id': create_key(args.key, args.public_key)}
    elif args.action == 'prepare':
        result = {'key_id': prepare_assets(args.key, args.version)[3]['key_id'], 'prepared': True}
    else:
        result = package(args.key, args.version, args.bar)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
