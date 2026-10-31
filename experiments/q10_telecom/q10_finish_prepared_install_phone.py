"""Finish this one fully written Q10 install only after exact hash/backup proof."""
import ctypes
import hashlib
import json
import os
import re
import sys
import time

BASE = '/var/rootdata/q10_volte'
sys.path.insert(0, BASE + '/device')
import native as n
import compatibility as c
import profiles
import device_info
import service as s
import telecom_attach as t


def verify(expected):
    assert os.geteuid() == 0 and os.uname()[0] == 'QNX' and ctypes.sizeof(ctypes.c_void_p) == 4
    facts = device_info.read_identity()
    assert facts['variant'] == 'SQN100-3' and facts['os_version'] == '10.3.3.3216'
    n.verify_stock()
    stage = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert re.match(r'^/var/rootdata/q10_volte_stage_[a-f0-9]{12}$', stage)
    raw = n.read(stage + '/payload-manifest.json')
    assert n.digest(raw) == expected
    original = json.loads(raw.decode('ascii'))
    installed = s.load(BASE + '/installation.json')
    assert installed['owner'] == original['owner'] == c.OWNER
    assert installed['version'] == original['version'] == '0.4.0'
    assert installed['files'] == original['files'] and set(installed['files']) == c.FILES
    for name, digest in installed['files'].items():
        assert not os.path.islink(BASE + '/' + name)
        assert n.digest(n.read(BASE + '/' + name)) == digest
    assert n.digest(n.read('/var/addons/q10-unicom-volte/init/start.sh')) == original['files']['device/addon-start.sh']
    transaction = s.load(BASE + '/install-transaction.json')
    assert transaction == {'owner': c.OWNER, 'action': 'update', 'previously_enabled': False,
                           'version': '0.4.0', 'phase': 'writing_payload'}
    assert not os.path.exists(BASE + '/enabled') and not os.path.exists(s.LOCK)
    assert s.phone_idle() and not n.ims_pids() and not n.active_vpn_sessions()
    assert n.voice_policy() == 0 and t.native.ue_usage_policy() == 0
    assert n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
    assert all(c.configuration_diagnostics().values()) and t.source_baseline()
    s.ACTIVE_REQUEST = profiles.installed_request(BASE)
    s.ACTIVE_PROFILE = s.ACTIVE_REQUEST['profile']
    assert t.selected(s.ACTIVE_PROFILE)
    assert installed['carrier_profile_sha256'] == profiles.fingerprint(s.ACTIVE_REQUEST)
    assert s.ACTIVE_PROFILE['id'] == 'china-telecom-46011-data-centric'
    assert s.current_usim()
    journal = s.load(s.JOURNAL)
    assert journal['owner'] == c.OWNER and journal['original_voice_policy'] == 0
    assert journal['restore_completed'] is True and journal['native_pid'] is None
    return installed


def main():
    assert len(sys.argv) == 3 and sys.argv[1] in ('prepare', 'finalize')
    installed = verify(sys.argv[2])
    if sys.argv[1] == 'prepare':
        plan = t.prepare(s)
        record = {'action': 'complete_verified_payload_preparation', 'phase': 'waiting_for_desktop_backup',
                  'at': time.time(), 'manifest_sha256': sys.argv[2], 'plan': plan,
                  'configuration_writes': 0, 'enabled': False}
    else:
        folder, value = t.checked_plan(s)
        assert hashlib.sha256(s.current_usim().encode('ascii')).hexdigest() == value['sim_fingerprint']
        record = {'action': 'complete_verified_payload_preparation', 'phase': 'complete',
                  'at': time.time(), 'manifest_sha256': sys.argv[2],
                  'desktop_backup_verified': True, 'configuration_writes': 0, 'enabled': False}
        os.unlink(BASE + '/install-transaction.json')
    n.atomic(s.STATE + '/task-install-recovery.json', json.dumps(record).encode('ascii'))
    print(json.dumps(record))


if __name__ == '__main__':
    main()
