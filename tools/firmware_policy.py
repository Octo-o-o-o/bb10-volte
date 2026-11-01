"""Exact BB10 baseline policy, shared by connection and destructive workflows."""
from dataclasses import dataclass
import re

TARGET_OS = '10.3.3.3216'


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,6}', value):
        return None
    return tuple(int(part) for part in value.split('.'))


@dataclass(frozen=True)
class FirmwareState:
    state: str
    current: str
    target: str = TARGET_OS


def assess_version(value):
    current = version_tuple(value)
    target = version_tuple(TARGET_OS)
    if current is None:
        return FirmwareState('unknown', '')
    normalized = '.'.join(str(part) for part in current)
    return FirmwareState('ready' if current == target else 'upgrade' if current < target else 'newer', normalized)


def baseline_error(device):
    state = assess_version((device or {}).get('PlatformVersion')).state
    return {'unknown': 'firmware_version_unknown', 'upgrade': 'firmware_upgrade_required',
            'newer': 'firmware_downgrade_blocked'}.get(state)
