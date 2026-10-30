"""Desktop presentation language, independent of phone data and locale formatting.

The language is selected once at startup.  A missing or unreadable system
preference deliberately uses Chinese; any known non-Chinese language uses English.
"""
import ctypes
import locale
import os
from pathlib import Path
import re
import sys

from translations_en import ENGLISH


def language_from_tag(tag):
    if not isinstance(tag, str) or not tag.strip():
        return 'zh'
    tag = tag.strip().split(':', 1)[0].split('.', 1)[0].split('@', 1)[0]
    if not tag or tag.lower() in ('c', 'posix', 'und', 'unknown'):
        return 'zh'
    if re.match(r'^(?:(?:zh|zho|chi|cmn|yue)(?:[-_]|$)|chinese(?:\s|_|$))', tag, re.I):
        return 'zh'
    if not re.fullmatch(r'[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{1,8})*', tag):
        return 'zh'
    return 'en'


def _windows_language():
    # LANGID's primary language is in the low ten bits. This reads the UI
    # language rather than the user's date/number formatting locale.
    langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    if not langid:
        return None
    return 'zh' if langid & 0x3ff == 0x04 else 'en'


def _mac_language():
    # The first preferred language is the system UI preference. Avoid shelling
    # out and do not confuse the separate region setting with the UI language.
    core = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    core.CFLocaleCopyPreferredLanguages.restype = ctypes.c_void_p
    core.CFArrayGetCount.argtypes = [ctypes.c_void_p]
    core.CFArrayGetCount.restype = ctypes.c_long
    core.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
    core.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
    core.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
    core.CFStringGetCString.restype = ctypes.c_bool
    core.CFRelease.argtypes = [ctypes.c_void_p]
    languages = core.CFLocaleCopyPreferredLanguages()
    if not languages:
        return None
    try:
        if not core.CFArrayGetCount(languages):
            return None
        value = core.CFArrayGetValueAtIndex(languages, 0)
        buffer = ctypes.create_string_buffer(1024)
        if not value or not core.CFStringGetCString(value, buffer, len(buffer), 0x08000100):
            return None
        return buffer.value.decode('utf-8')
    finally:
        core.CFRelease(languages)


def system_language():
    try:
        if sys.platform == 'win32':
            return language_from_tag(_windows_language())
        if sys.platform == 'darwin':
            return language_from_tag(_mac_language())
        for name in ('LC_ALL', 'LC_MESSAGES', 'LANGUAGE', 'LANG'):
            if os.environ.get(name):
                return language_from_tag(os.environ[name])
        return language_from_tag(locale.getlocale(locale.LC_MESSAGES)[0])
    except Exception:
        return 'zh'


LANGUAGE = system_language()


def tr(text):
    """Translate a presentation string, keeping unknown user content intact."""
    return ENGLISH.get(text, text) if LANGUAGE == 'en' else text


def document_path(path):
    """Use an existing English guide without changing the underlying file data."""
    path = Path(path)
    english = path.with_name(path.stem + '.en' + path.suffix)
    return english if LANGUAGE == 'en' and english.is_file() else path
