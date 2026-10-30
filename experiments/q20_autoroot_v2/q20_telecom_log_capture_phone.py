"""Read-only current Q20 radio logs; keep raw contents private."""
import json
import os
import time
import q20_volte_phone as q


def main():
    q.setup()
    q.verify()
    folder = q.s.STATE + '/radio-logs-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    os.mkdir(folder, 0o700)
    result = {'variant': 'SQC100-2', 'folder': folder, 'configuration_writes': 0, 'logs': {}}
    for buffer in ('qct_rrm', 'radioctrl', 'cnice'):
        try:
            blob = q.n.command(['/bin/slog2info', '-b', buffer], 12)
            q.n.atomic(folder + '/' + buffer + '.log', blob)
            result['logs'][buffer] = {'bytes': len(blob), 'sha256': q.n.digest(blob)}
        except Exception as error:
            result['logs'][buffer] = {'error_type': type(error).__name__}
    q.n.atomic(folder + '/manifest.json', json.dumps(result, indent=2).encode('ascii'))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
