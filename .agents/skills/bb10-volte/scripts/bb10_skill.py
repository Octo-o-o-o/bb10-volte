"""Skill helper entrypoint that locates the bb10-volte checkout and runs tools/ai_skill.py."""
import json
import os
from pathlib import Path
import sys


def find_repo_root():
    candidates = []
    env_root = os.environ.get('BB10_VOLTE_REPO')
    if env_root:
        candidates.append(Path(env_root).expanduser().resolve())
    here = Path(__file__).resolve()
    candidates.extend(here.parents)
    cwd = Path.cwd().resolve()
    candidates.append(cwd)
    candidates.extend(cwd.parents)
    seen = set()
    for folder in candidates:
        if folder in seen:
            continue
        seen.add(folder)
        marker = folder / 'project.json'
        entry = folder / 'tools/ai_skill.py'
        if marker.is_file() and entry.is_file():
            try:
                if json.loads(marker.read_text(encoding='utf-8')).get('name') == 'bb10-volte':
                    return folder
            except (OSError, ValueError):
                continue
    return None


def main(argv=None):
    repo = find_repo_root()
    if repo is None:
        print(json.dumps({
            'ok': False,
            'error': 'bb10_volte_repo_not_found',
            'hint': 'Run from a cloned Octo-o-o-o/bb10-volte repository or set BB10_VOLTE_REPO=/path/to/bb10-volte.',
        }, indent=2))
        return 2
    tools_dir = str(repo / 'tools')
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import ai_skill
    return ai_skill.main(argv)


if __name__ == '__main__':
    raise SystemExit(main())
