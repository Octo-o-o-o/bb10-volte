"""Reuse the desktop's public support destinations and original QR pixels."""
import json
from pathlib import Path
import struct

from support_config import OCTOLAB_URL, PROJECT_WEBSITE_URL, REPOSITORY_URL, QR_FILES, SUPPORT_ICON

ROOT = Path(__file__).resolve().parents[1]
LINKS = {'github': REPOSITORY_URL, 'studio': OCTOLAB_URL, 'website': PROJECT_WEBSITE_URL}


def support_files():
    return [SUPPORT_ICON] + [name for choices in QR_FILES.values() for name in choices.values()]


def prepare_support_assets(root=ROOT):
    root = Path(root)
    assets = root / 'mobile/native/assets/support'
    assets.mkdir(parents=True, exist_ok=True)
    names = support_files()
    unexpected = {p.name for p in assets.iterdir()} - {Path(name).name for name in names}
    if unexpected:
        raise ValueError('Unexpected support assets; inspect before packaging: ' + ', '.join(sorted(unexpected)))
    for name in names:
        data = (root / name).read_bytes()
        if data[:8] != b'\x89PNG\r\n\x1a\n':
            raise ValueError('Support image is not a PNG: ' + name)
        width, height = struct.unpack('>II', data[16:24])
        if name != SUPPORT_ICON and (width != height or not 1 <= width <= 264):
            raise ValueError('Preserve the verified support image at its original size: ' + name)
        (assets / Path(name).name).write_bytes(data)
    lines = ['// Generated from tools/support_config.py by tools/mobile_support.py.',
             '#ifndef BB10_SUPPORT_LINKS_H', '#define BB10_SUPPORT_LINKS_H',
             'struct SupportLink { const char *id; const char *url; };',
             'static const SupportLink SUPPORT_LINKS[] = {']
    for key, url in sorted(LINKS.items()):
        if not url.startswith('https://'):
            raise ValueError('Support links must use HTTPS')
        lines.append('    {' + json.dumps(key) + ', ' + json.dumps(url) + '},')
    lines.extend(['    {0, 0}', '};', '#endif', ''])
    generated = root / 'mobile/native/src/generated'
    generated.mkdir(parents=True, exist_ok=True)
    (generated / 'support_links.h').write_text('\n'.join(lines), encoding='utf-8', newline='\n')


def verify_bar_support(archive, root=ROOT):
    root = Path(root)
    expected = {'native/assets/support/' + Path(name).name: (root / name).read_bytes()
                for name in support_files()}
    for path in (root / 'mobile/native/assets').glob('*.qml'):
        expected['native/assets/' + path.name] = path.read_bytes()
    actual_support = {name for name in archive.namelist()
                      if name.startswith('native/assets/support/') and not name.endswith('/')}
    if actual_support != {name for name in expected if '/support/' in name}:
        raise ValueError('BAR support assets differ from the public allowlist')
    for name, data in expected.items():
        if archive.read(name) != data:
            raise ValueError('BAR contains stale UI or changed support pixels: ' + name)


if __name__ == '__main__':
    prepare_support_assets()
