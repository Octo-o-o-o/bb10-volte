"""Remove a completed, exact staging tree using Python 3.2, not shell rmdir."""
import json
import os
import re
import sys

ROOT_PARENT = '/var/rootdata'


def cleanup(base, names):
    assert os.path.dirname(base) == ROOT_PARENT
    assert re.match(r'^q10_volte_stage_[a-f0-9]{12}$', os.path.basename(base))
    assert os.path.realpath(base) == base and not os.path.islink(base)
    assert isinstance(names, list) and len(names) == len(set(names))
    assert 'stage-cleanup.py' in names and 'profile-request.json' in names
    expected = {'': set(['device', 'driver']), 'device': set(), 'driver': set()}
    for name in names:
        assert isinstance(name, str) and re.match(r'^(?:(?:device|driver)/)?[A-Za-z0-9_.-]+$', name)
        parent, leaf = os.path.split(name)
        assert leaf not in ('.', '..')
        expected[parent].add(leaf)
    # Check the entire tree before removing even one file. Unexpected caches,
    # links or concurrent additions stay intact for explicit inspection.
    for parent, entries in expected.items():
        directory = os.path.join(base, parent)
        assert os.path.isdir(directory) and not os.path.islink(directory)
        assert set(os.listdir(directory)) == entries
    for name in names:
        path = os.path.join(base, name)
        assert os.path.isfile(path) and not os.path.islink(path)
    for name in names:
        os.unlink(os.path.join(base, name))
    for name in ('device', 'driver', ''):
        os.rmdir(os.path.join(base, name))
    return {'stage_removed': True}


if __name__ == '__main__':
    assert len(sys.argv) == 2
    print(json.dumps(cleanup(os.path.dirname(os.path.abspath(__file__)), json.loads(sys.argv[1]))))
