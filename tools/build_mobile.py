"""Build the native ARMv7 BAR in the pinned, isolated BB10 builder container."""
import argparse
import json
from pathlib import Path
import subprocess
import re
import xml.etree.ElementTree as ET
from package_mobile import ROOT, BUILDER, MOBILE_VERSION, package, prepare_assets


def build(key, version=MOBILE_VERSION):
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('Mobile/BAR version must have four numeric components')
    source = ROOT / 'mobile/native'
    (source / 'build').mkdir(parents=True, exist_ok=True)
    command = ['docker', 'run', '--rm', '--network', 'none', '--cap-drop', 'ALL',
               '--security-opt', 'no-new-privileges', '-v', str(source) + ':/src',
               '-w', '/src', BUILDER]
    subprocess.run(command + ['bb10-cc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                             'src/joblauncher.c', '-o', 'build/job-launcher'], check=True)
    prepared = prepare_assets(key, version)
    subprocess.run(command + ['cmake', '-S', '/src', '-B', '/src/build/cmake',
        '-DCMAKE_TOOLCHAIN_FILE=/opt/bb10-toolchain.cmake', '-DBB10_ALLOW_INCOMPLETE_BUNDLE=OFF',
        '-DBB10_MOBILE_VERSION=' + version, '-DBB10_PUBLIC_KEY_ID=' + prepared[3]['key_id']], check=True)
    subprocess.run(command + ['cmake', '--build', '/src/build/cmake', '--parallel', '2'], check=True)
    # Generate beside the source descriptor so relative assets keep their exact
    # packager semantics. This file and all outputs are excluded from releases.
    descriptor = (source / 'bar-descriptor.xml').read_text(encoding='utf-8')
    descriptor = re.sub(r'<versionNumber>[^<]+</versionNumber>',
                        '<versionNumber>' + '.'.join(version.split('.')[:3]) + '</versionNumber>', descriptor)
    descriptor = re.sub(r'<buildId>[^<]+</buildId>', '<buildId>' + version.split('.')[3] + '</buildId>', descriptor)
    ET.fromstring(descriptor)
    (source / 'bar-descriptor.build.xml').write_text(descriptor, encoding='utf-8', newline='\n')
    subprocess.run(command + ['blackberry-nativepackager', '-devMode', '-package',
        'build/com.octolab.bb10volte.bar', 'bar-descriptor.build.xml', '-configuration', 'Device-Debug'], check=True)
    bar = source / 'build/com.octolab.bb10volte.bar'
    if not bar.is_file():
        raise RuntimeError('The native builder did not produce the expected BAR')
    return package(key, version, bar)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key', type=Path, required=True)
    parser.add_argument('--version', default=MOBILE_VERSION)
    args = parser.parse_args()
    print(json.dumps(build(args.key, args.version), indent=2))
