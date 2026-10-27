"""Keep immutable bundle resources separate from persistent per-user files."""
import os
from pathlib import Path
import sys


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


def prepare_external_programs():
    # PyInstaller sets a DLL search directory inherited by child processes.
    # Our signed SSH client must load its own adjacent crypto library.
    if frozen() and sys.platform == 'win32':
        import ctypes
        if not ctypes.windll.kernel32.SetDllDirectoryW(None):
            raise OSError('Cannot restore the Windows DLL search path')
