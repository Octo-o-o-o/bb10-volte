"""Verify current-boot automatic name/IMS recovery and save metadata only."""
import ctypes
import hashlib
import json
import os
import sys
import time
import native as n
import service as s
import profiles
import compatibility as c
import device_info
import operator_name as op
import telecom_native

assert os.geteuid() == 0 and os.uname()[0] == 'QNX' and ctypes.sizeof(ctypes.c_void_p) == 4
assert len(sys.argv) == 2 and sys.argv[1] == 'accept'
facts = device_info.read_identity()
assert facts['variant'] == 'SQN100-3' and facts['os_version'] == '10.3.3.3216'
n.verify_stock()
request = s.load(s.STATE + '/final-name-boot-request.json')
assert request['owner'] == 'q10-final-name-boot-request-v1'
assert request['owner_top_bar_confirmed'] is True and request['owner_normal_menu_reboot'] is True
assert all(type(request[k]) is int and request[k] == 0 for k in
           ('desktop_core_starts', 'desktop_name_starts', 'desktop_enables'))
manifest = s.load(s.BASE + '/installation.json')
assert manifest['owner'] == c.OWNER and set(manifest['files']) == c.FILES
assert manifest['files'] == request['expected_files']
for name, digest in manifest['files'].items():
    assert not os.path.islink(s.BASE + '/' + name)
    assert n.digest(n.read(s.BASE + '/' + name)) == digest
assert not os.path.exists(s.BASE + '/install-transaction.json')
assert n.digest(n.read(c.ADDON + '/init/start.sh')) == manifest['files']['device/addon-start.sh']
assert n.digest(n.read(op.ADDON + '/init/start.sh')) == request['expected_name_entry_sha256']
assert manifest['files']['device/operator-name-start.sh'] == request['expected_name_entry_sha256']
receipt = op.authorized_receipt()
assert profiles.fingerprint(profiles.installed_request(s.BASE)) == receipt['profile_sha256'] == request['profile_sha256']
status = s.read_status()
assert status['boot'] != request['before_boot'] and status['boot'] == s.boot_token()
assert status['phase'] == 'running' and status['status_from_current_boot'] is True
assert status['manager_alive'] is True and status['native_alive'] is True and status['enabled'] is True
assert status['current']['ims'] == 'connected' and status['current']['register_status'] == '200 OK'
assert status['current']['ran'] == 'LTE' and status['current']['radio'] == ['lte']
assert status['manager_pid'] != request['before_manager_pid'] and status['native_pid'] != request['before_native_pid']
assert set(n.ims_pids()) == {status['native_pid']} and s.phone_idle()
worker = op.load(op.WORKER)
assert worker['owner'] == op.OWNER and worker['boot'] == status['boot'] and op.alive(worker['pid'])
assert worker['pid'] != request['before_name_worker_pid']
args = n.command(['/bin/pidin', '-p', str(worker['pid']), '-f', 'A']).decode('ascii')
assert s.BASE + '/device/operator_name.py watch' in args
display = op.observe()
assert display == {'name': op.NAME, 'table_overlay_owned': True, 'worker_alive': True}
rum = n.value(n.attrs(n.read('/pps/services/rum/csm/status_public')), 'network_name')
navigator = n.value(n.attrs(n.read('/pps/system/navigator/status/cellular')), 'dat')['cellular']['operator_name_string']
assert rum == op.NAME and navigator == [op.NAME]
journal = s.load(s.JOURNAL)
assert journal['boot'] == status['boot'] and journal['profile_sha256'] == receipt['profile_sha256']
assert journal['crypto_boot'] == status['boot'] and journal['provider'] == n.crypto_policy()['swcr_id']
assert n.voice_policy() == 3 and telecom_native.ue_usage_policy() == 1
card = str(n.value(n.attrs(n.read('/pps/services/cellular/uicc/card0/status_restricted')), 'imsi'))
assert hashlib.sha256(card.encode('ascii')).hexdigest() == receipt['sim_fingerprint']
timing = status['startup_timing']
result = {'owner': 'q10-operator-name-autostart-accepted-v1', 'variant': 'SQN100-3',
    'profile_sha256': receipt['profile_sha256'], 'sim_fingerprint': receipt['sim_fingerprint'],
    'boot': status['boot'], 'manager_pid': status['manager_pid'], 'native_pid': status['native_pid'],
    'name_worker_pid': worker['pid'], 'new_boot_and_processes_verified': True,
    'name_auto_restored': True, 'IMS_auto_registered': True, 'owner_top_bar_confirmed': True,
    'desktop_core_starts': 0, 'desktop_name_starts': 0, 'desktop_enables': 0,
    'displayed_name': op.NAME, 'name_entry_sha256': request['expected_name_entry_sha256'],
    'manager_to_registered_seconds': round(timing['running'] - timing['manager_started'], 3),
    'full_system_boot_time_measured': False, 'UE_usage_setting': 1, 'voice_policy': 3,
    'network_or_IMS_writes_during_acceptance': 0, 'accepted_at': time.time()}
target = s.STATE + '/operator-name-boot-acceptance.json'
assert not os.path.exists(target), 'Preserve an existing acceptance for inspection'
n.atomic(target, json.dumps(result).encode('ascii'))
assert s.load(target) == result
public = dict(result)
del public['sim_fingerprint']
public['receipt_sha256'] = n.digest(n.read(target))
print(json.dumps(public))
