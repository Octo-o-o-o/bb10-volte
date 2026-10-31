"""Read-only Q20 baseline and startup inventory. Python 3.2 compatible."""
import hashlib
import json
import os
import re
import sys

BASE = '/var/q20_volte'
sys.path.insert(0, BASE + '/device')
import native as n
import profiles
import compatibility as c
import device_info


def main():
    facts = device_info.read_identity()
    assert facts['variant'] == 'SQC100-2' and facts['os_version'] == '10.3.3.3216'
    assert os.geteuid() == 0 and os.uname()[0] == 'QNX'
    carrier = n.attrs(n.read('/pps/services/cellular/uicc/card0/status_private'))
    home = n.value(carrier, 'hplmn', {})
    p = profiles.default()
    p['runtime']['autostart'] = False
    for family in ('unicom', 'mobile', 'telecom'):
        candidate = profiles.read_json(BASE + '/profiles/china-' + family + '.json')
        if home.get('mcc') == candidate['carrier']['mcc'] and home.get('mnc') in candidate['carrier']['mncs']:
            p = candidate
            break
    report = {'identity': facts, 'euid': os.geteuid(), 'profile': p,
              'stock': {}, 'baseline': {}, 'configuration_writes': 0,
              'network': c.read_network(p), 'incoming': c.incoming_diagnostics(),
              'configuration': c.configuration_diagnostics(), 'startup_files': {}, 'script_candidates': []}
    for path, expected in n.STOCK_HASHES.items():
        digest = n.digest(n.read(path))
        report['stock'][path] = {'sha256': digest, 'matches': digest == expected}
    if all(item['matches'] for item in report['stock'].values()):
        for key, fn in (('voice_policy', n.voice_policy), ('crypto', n.crypto_policy),
                        ('ims_pids', n.ims_pids), ('vpn_sessions', n.active_vpn_sessions)):
            try:
                report['baseline'][key] = fn()
            except Exception as error:
                report['baseline'][key] = {'error_type': type(error).__name__}
    info = n.command(['/bin/pidin', 'info']).decode('utf-8', 'replace')
    report['boot_info'] = [line for line in info.splitlines() if re.search('boot|uptime', line, re.I)]
    for path in ('/tmp/root.done', '/var/rootdata', '/var/addons', '/var/etc/autostart.conf',
                 '/var/boottime.txt', '/var/rootdata/q10_volte', '/var/ims/carrier/imsconfig_user.xml'):
        item = {'exists': os.path.exists(path), 'islink': os.path.islink(path)}
        if os.path.isfile(path) and path in ('/var/etc/autostart.conf', '/var/boottime.txt'):
            blob = n.read(path)
            item.update(sha256=n.digest(blob), bytes=len(blob), text=blob.decode('utf-8', 'replace'))
        report['startup_files'][path] = item
    directories = ('/scripts', '/base/scripts', '/etc', '/var/etc',
                   '/apps/sys.android.gYABgKAOw1czN6neiAT72SGO.ns/native/scripts',
                   '/apps/sys.android.gYABgKAOw1czN6neiAT72SGO.ns/native/system/bin',
                   '/var/android')
    for directory in directories:
        if not os.path.isdir(directory):
            continue
        report['script_candidates'].extend(directory + '/' + name for name in sorted(os.listdir(directory))
            if re.search('root|init|start|boot|autorun', name, re.I))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
