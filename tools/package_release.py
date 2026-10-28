"""Create and round-trip verify a public source ZIP using the audited allowlist."""
import hashlib
import json
import zipfile
from check_release import ROOT, check
from desktop_paths import desktop_release_version


def main():
    report = check()
    project = json.loads((ROOT/'project.json').read_text(encoding='utf-8'))
    name = project['name'] + '-' + desktop_release_version(project) + '-experimental'
    folder = ROOT/'dist'
    folder.mkdir(exist_ok=True)
    output = folder/(name+'.zip')
    part = output.with_suffix('.zip.partial')
    manifest = {'project': project, 'files': report['files'],
                'scope': 'Public source, documentation, manifests and the source-built helper only'}
    with zipfile.ZipFile(part, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for filename in sorted(report['files']):
            info = zipfile.ZipInfo(name+'/'+filename, (2026, 10, 27, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if filename.endswith('.sh') else 0o100644) << 16
            z.writestr(info, (ROOT/filename).read_bytes())
        info = zipfile.ZipInfo(name+'/RELEASE-MANIFEST.json', (2026, 10, 27, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, json.dumps(manifest, indent=2).encode('utf-8'))
    with zipfile.ZipFile(part) as z:
        assert z.testzip() is None
        assert len(z.namelist()) == len(report['files'])+1
        for filename, digest in report['files'].items():
            assert hashlib.sha256(z.read(name+'/'+filename)).hexdigest() == digest
    part.replace(output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(digest+'  '+output.name+'\n', encoding='ascii')
    print(json.dumps({'archive': str(output), 'sha256': digest, 'public_files': len(report['files']),
                      'roundtrip_verified': True, 'state': project['state']}))


if __name__ == '__main__':
    main()
