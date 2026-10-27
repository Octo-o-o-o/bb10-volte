"""Command-line entry to the same fixed workflow used by the desktop GUI."""
import argparse
import json
import sys
from pathlib import Path
from workflow import Client, WorkflowError, write_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['manifest', 'preflight', 'check', 'install', 'update',
                        'setup', 'status', 'start', 'stop', 'enable', 'disable', 'uninstall', 'collect'])
    parser.add_argument('--host', default='q10-root')
    parser.add_argument('--ssh-config', type=Path)
    parser.add_argument('--report', type=Path, help='Save the sanitized result as JSON')
    parser.add_argument('--profile', type=Path, help='Validated operator profile JSON; defaults to the recorded Unicom baseline')
    parser.add_argument('--allow-experimental', action='store_true', help='Allow untested devices/operators only when every native/device gate passes')
    args = parser.parse_args()
    try:
        if args.action == 'manifest':
            result = write_manifest()
        else:
            client = Client(args.host, args.ssh_config, profile=args.profile, allow_experimental=args.allow_experimental)
            if args.action in ('check', 'preflight'):
                result = client.preflight()
            elif args.action in ('install', 'update', 'setup'):
                result = client.install('update' if args.action == 'update' else 'install', start=args.action == 'setup')
            else:
                result = client.action(args.action)
        output = json.dumps(result, ensure_ascii=True, indent=2)
        if args.report:
            args.report.write_text(output + '\n', encoding='utf-8')
        print(output)
        return 2 if args.action in ('check', 'preflight') and result['outcome'] not in ('compatible', 'experimental') else 0
    except (WorkflowError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
