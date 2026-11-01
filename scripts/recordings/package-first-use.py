"""Finalize local tutorial artifacts and their explicit release allowlist; no upload."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / 'docs/recordings'


def public_files():
    names = ['FIRST-USE-RECORDING.md', 'first-use.scenario.json', 'first-use.steps.json',
             'first-use-narrated.mp4', 'first-use-assembled.mp4', 'first-use-cover.png',
             'first-use-report.json', 'first-use-assemble-report.json',
             'first-use-narrated-narration-report.json', 'first-use-narrated-narration.vtt',
             'first-use.srt', 'first-use-subtitles.srt', 'first-use-subtitles.ass',
             'first-use-cover-cover-report.json', 'first-use-cover-embed-report.json',
             'first-use-media-report.json', 'first-use-review.html']
    files = [D / name for name in names]
    for folder, patterns in {
        'first-use-build': ['??-*-narrated.mp4', '??-*-report.json', '??-*-narration.vtt'],
        'first-use-raw': ['*.mp4', '*.capture.json'],
        'first-use-cover-candidates': ['*.png', '*.json'],
        'first-use-frame-review-final': ['*.png', '*.json'],
        'first-use-manual-review': ['*.png', '*.json'],
        'first-use-assembled-segments': ['*.png', '*.mp4'],
    }.items():
        for pattern in patterns:
            files.extend((D / folder).glob(pattern))
    scripts = ROOT / 'scripts/recordings'
    files.extend(scripts.glob('*first-use*.py'))
    files.extend(scripts.glob('*first-use*.mjs'))
    return sorted(set(files))


def portable(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, str):
        for prefix in (str(ROOT) + '\\', ROOT.as_posix() + '/'):
            value = value.replace(prefix, '')
        # The build environment may appear in FFprobe metadata or command arrays.
        for prefix in (str(Path.home()), Path.home().as_posix()):
            value = value.replace(prefix, '<user-home>')
        return value.replace('\\', '/')
    if isinstance(value, list):
        return [portable(item) for item in value]
    if isinstance(value, dict):
        return {key: portable(item) for key, item in value.items()}
    return value


if __name__ == '__main__':
    narration = json.loads((D / 'first-use-narrated-narration-report.json').read_text(encoding='utf-8'))
    report_path = D / 'first-use-report.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    intro = narration.get('coverIntro', {}).get('introDurationMs', 0)
    shift = intro - report.get('coverIntroMs', 0)
    for cue in report['captions']:
        for key in ('startMs', 'endMs'):
            if key in cue:
                cue[key] += shift
    report.update(durationMs=narration['timeline']['outputDurationMs'], coverIntroMs=intro,
                  video='docs/recordings/first-use-narrated.mp4', mp4='docs/recordings/first-use-narrated.mp4')
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    files = public_files()
    for path in files:
        if path.suffix == '.json' and path.exists():
            value = json.loads(path.read_text(encoding='utf-8-sig'))
            path.write_text(json.dumps(portable(value), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    target = ROOT / 'website/src/assets/tutorial'
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(D / 'first-use-narrated.mp4', target / 'first-use.mp4')
    shutil.copyfile(D / 'first-use-cover.png', target / 'first-use-cover.png')
    manifest_path = ROOT / 'materials/recording-files.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['scope'] = ('Reviewed historical Q10 demonstration and Windows first-use training with mock data; '
                         'not evidence of new hardware acceptance. Includes reproducible scripts and sanitized review artifacts.')
    for path in files:
        if path.exists():
            manifest['files'][path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest['files'] = dict(sorted(manifest['files'].items()))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'tutorial_public_files': len(files), 'local_packaging_only': True}))
