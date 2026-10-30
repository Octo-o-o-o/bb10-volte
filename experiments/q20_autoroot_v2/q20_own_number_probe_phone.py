"""Read-only own-number diagnostics; actual numbers stay in private storage."""
import json
import os
import re
import sys
import time
import q20_volte_phone as q


def main():
    q.setup()
    q.verify()
    folder = q.s.STATE + '/own-number-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    os.mkdir(folder, 0o700)
    report = {'configuration_writes': 0, 'sim_writes': 0, 'phone_folder': folder,
              'paths': {}, 'library_candidates': []}
    paths = set(['/pps/services/cellular/uicc/card0/status_private',
                 '/pps/services/cellular/uicc/card0/status_restricted',
                 '/pps/services/ims/cellular/status_private'])
    for top in ('/pps/services/phone', '/pps/services/cellular/uicc/card0'):
        for directory, dirs, names in os.walk(top):
            dirs[:] = [name for name in dirs if name not in ('calls', 'calldetail', 'calllogs', 'history')]
            if directory.count('/') - top.count('/') > 2:
                dirs[:] = []
                continue
            for name in names:
                if not re.search('call|history|contact', name, re.I):
                    paths.add(directory + '/' + name)
    for index, path in enumerate(sorted(paths)):
        try:
            blob = q.n.read(path)
            if len(blob) > 65536:
                continue
            attrs = q.n.attrs(blob)
            item = {'attribute_names': sorted(attrs), 'number_fields': {}}
            for key in attrs:
                if re.search('number|msisdn|line.?id|caller|subscriber', key, re.I):
                    value = q.n.value(attrs, key)
                    if isinstance(value, str):
                        item['number_fields'][key] = {'type': 'string', 'length': len(value),
                            'has_phone_number_shape': re.match(r'^\+?[0-9]{5,20}$', value) is not None,
                            'empty': not value}
                    elif isinstance(value, (list, dict)):
                        item['number_fields'][key] = {'type': type(value).__name__, 'items': len(value),
                            'keys': sorted(value) if isinstance(value, dict) else None}
                    else:
                        item['number_fields'][key] = {'type': type(value).__name__}
            report['paths'][path] = item
            q.n.atomic(folder + '/object-%03d.txt' % index, blob)
        except (OSError, ValueError, TypeError) as error:
            report['paths'][path] = {'error_type': type(error).__name__}
    for directory in ('/usr/lib', '/base/usr/lib', '/radio/lib'):
        if os.path.isdir(directory):
            report['library_candidates'].extend(directory + '/' + name for name in os.listdir(directory)
                if re.search('phone|telephony|bps', name, re.I))
    q.n.atomic(folder + '/report.json', json.dumps(report, indent=2).encode('ascii'))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
