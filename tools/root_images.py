"""Model-bound stock inputs and offline Root image verification."""
import json
from pathlib import Path
import re
import shutil
import subprocess

from desktop_paths import resource_root
from fetch_materials import sha

ROOT = resource_root()


def fail(code='image_not_verified'):
    from root_setup import SetupError
    raise SetupError(code)


def recipe(variant):
    from root_setup import catalog, stock_firmware
    if variant not in catalog()['auto_root_variants']:
        fail('root_model_unsupported')
    stock = stock_firmware(variant)
    specs = json.loads((ROOT / 'materials/stock-partitions.json').read_text(encoding='utf-8'))
    expected = specs['families'].get(stock['family'])
    if not expected or expected['firmware_id'] != stock['id'] or expected['stock_sha256'] != stock['extracted_sha256']:
        fail('root_model_unsupported')
    return stock, expected


def extract_stock(stock, archive, destination, seven_zip):
    """Q20 is already an EXE; extract Q10/Passport archives, never execute stock."""
    archive, destination = Path(archive), Path(destination)
    if archive.is_symlink() or not archive.is_file() or sha(archive) != stock['sha256']:
        fail()
    destination.mkdir(exist_ok=False)
    original = destination / stock['extracted_file']
    if stock['file'] == stock['extracted_file']:
        # Identical, immutable input on one filesystem needs no second copy.
        # Deleting either name leaves the other usable. Cross-volume imports
        # and filesystems without hard links retain the ordinary copy fallback.
        try:
            original.hardlink_to(archive)
        except OSError:
            shutil.copyfile(archive, original)
    else:
        from preparation_cache import run_preparation
        result = run_preparation([str(seven_zip), 'e', '-y', str(archive), stock['extracted_file'], '-o' + str(destination)], destination.parent,
                                capture_output=True, timeout=600,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            fail()
    if original.is_symlink() or not original.is_file() or sha(original) != stock['extracted_sha256']:
        fail()
    return original


def verify_build(kit, variant, platform='win32'):
    """Fail closed even when bb10mt logs a patch failure but exits successfully."""
    kit = Path(kit)
    stock, expected = recipe(variant)
    output = kit / 'images'
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '',
                  (kit / 'root-build.log').read_text(encoding='utf-8', errors='replace'))
    if re.search(r'(?im)^\s*(?:error|failed|exception)\b|\b(?:script|patch|command)\s+(?:error|failed)\b', text):
        fail('root_build_failed')
    unchanged = []
    for item in expected['unchanged_partitions']:
        path = output / item['file']
        if path.is_symlink() or not path.is_file() or path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            fail()
        unchanged.append(item['file'])
    stem = Path(stock['extracted_file']).stem
    radios = list(output.glob('*.1.signed'))
    if (len(radios) != 1 or radios[0].name != stem + '.1.signed' or radios[0].is_symlink()
            or sha(radios[0]) != expected['radio_original_sha256']):
        fail()
    if platform == 'darwin':
        systems = list(output.glob('*.0.unsigned'))
        if len(systems) != 1 or systems[0].name != stem + '.0.unsigned' or systems[0].is_symlink():
            fail()
        for source, suffix in ((systems[0], '_os.unsigned'), (radios[0], '_radio.signed')):
            target = output / (stem + suffix)
            if target.exists():
                fail()
            source.rename(target)
        suffixes = ('_os.unsigned', '_radio.signed')
    else:
        suffixes = ('_os.exe', '_radio.exe')
    images = []
    for suffix in suffixes:
        files = list(output.glob('*' + suffix))
        if len(files) != 1 or files[0].name != stem + suffix or files[0].is_symlink() or files[0].stat().st_size == 0:
            fail()
        path = files[0]
        images.append({'file': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path)})
    result = {'offline_build_verified': True, 'phone_connected_or_modified': False,
              'variant': variant, 'firmware_id': stock['id'], 'stock_sha256': stock['extracted_sha256'],
              'platform': platform, 'unchanged_partitions': unchanged,
              'radio_original_sha256': expected['radio_original_sha256'], 'images': images,
              'first_flash_acceptance': 'not_run',
              'keys': 'Private and unique to this prepared kit; image hashes vary with keys'}
    (kit / 'build-verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result
