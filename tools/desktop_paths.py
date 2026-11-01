"""Keep immutable bundle resources separate from persistent per-user files."""
import os
from pathlib import Path
import re
import sys


def desktop_release_version(project):
    revision = project.get('desktop_revision')
    if revision is not None and (type(revision) is not int or revision < 1):
        raise ValueError('Invalid desktop revision')
    result = project['version'] + ('-r' + str(revision) if revision else '')
    preview = project.get('preview_id')
    if preview is not None:
        if not isinstance(preview, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', preview):
            raise ValueError('Invalid preview identifier')
        result += '-preview-' + preview
    return result


def frozen():
    return bool(getattr(sys, 'frozen', False))


def resource_root():
    return Path(sys._MEIPASS) if frozen() else Path(__file__).resolve().parents[1]


def private_root():
    if not frozen():
        return resource_root() / 'private'
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/bb10-volte/private'
    local = Path(os.environ.get('LOCALAPPDATA') or (Path.home() / 'AppData' / 'Local'))
    return local / 'bb10-volte' / 'private'


def download_root():
    return private_root() / 'downloads' if frozen() else resource_root() / 'downloads'


def prepare_external_programs():
    # PyInstaller sets a DLL search directory inherited by child processes.
    # Our signed SSH client must load its own adjacent crypto library.
    if frozen() and sys.platform == 'win32':
        import ctypes
        if not ctypes.windll.kernel32.SetDllDirectoryW(None):
            raise OSError('Cannot restore the Windows DLL search path')
