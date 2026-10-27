"""Desktop SSH controller. Uses your existing verified root SSH connection."""
import argparse
import datetime
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = '/var/rootdata/q10_volte'
ENV = ('LD_LIBRARY_PATH=/base/usr/lib:/base/lib:/base/lib/dll:/radio/lib:/radio/lib/dll:/radio/usr/lib:/proc/boot '
       'PYTHONHOME=/usr PYTHONPATH=/usr/lib/python32.zip:/usr/lib/python3.2/lib-dynload ')
FILES = ['device/install.py', 'device/service.py', 'device/native.py', 'device/ims_image.py',
         'device/radio_api.py', 'device/run.sh', 'device/addon-start.sh', 'driver/devnp-volte_swcrypto_probe.so']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['manifest', 'install', 'update', 'check', 'status', 'start', 'stop', 'enable', 'disable', 'uninstall', 'collect'])
    parser.add_argument('--host', default='q10-root')
    parser.add_argument('--ssh-config', type=Path, help='Private SSH config with strict host-key checking and your own key')
    args = parser.parse_args()
    assert re.fullmatch(r'[A-Za-z0-9_.-]+', args.host), 'Use a simple configured SSH host alias'
    manifest = {'owner': 'q10-unicom-volte-v1', 'version': '0.1.0',
                'files': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in FILES}}
    manifest_path = ROOT/'materials/payload-manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2)+'\n', encoding='ascii')
    if args.action == 'manifest':
        print(json.dumps(manifest, indent=2))
        return
    options = ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=5',
               '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2']
    if args.ssh_config:
        options += ['-F', str(args.ssh_config.resolve())]
    ssh = shutil.which('ssh') or shutil.which('ssh.exe')
    scp = shutil.which('scp') or shutil.which('scp.exe')
    assert ssh and scp, 'Install OpenSSH client tools first'

    def remote(command, timeout=30):
        result = subprocess.run([ssh, '-n']+options+[args.host, command], capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(result.stderr[-2000:])
        return result.stdout

    if args.action in ('install', 'update'):
        stage = '/var/rootdata/q10_volte_stage_'+uuid.uuid4().hex[:12]
        remote('test ! -e '+shlex.quote(stage)+' && mkdir '+shlex.quote(stage)+' && chmod 700 '+shlex.quote(stage)+
               ' && mkdir '+shlex.quote(stage+'/device')+' '+shlex.quote(stage+'/driver'))
        for name in FILES + ['payload-manifest.json']:
            local = manifest_path if name == 'payload-manifest.json' else ROOT/name
            subprocess.run([scp, '-O', '-q']+options+[str(local), args.host+':'+stage+'/'+name], check=True, timeout=30)
        path = stage+'/device/install.py'
        trust = ' && '.join('/proc/boot/pathtrust !'+shlex.quote(stage+'/'+name)
                            for name in FILES if name.endswith('.py'))
        output = remote(trust+' && '+ENV+'/usr/bin/python3.2 '+
                        shlex.quote(path)+' '+args.action+' '+shlex.quote(stage), 90)
        print(output.strip())
    elif args.action == 'collect':
        folder = ROOT/'private'/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        folder.mkdir(parents=True, exist_ok=False, mode=0o700)
        if sys.platform == 'win32':
            account = subprocess.check_output(['whoami'], text=True).strip()
            subprocess.run(['icacls', str(folder), '/inheritance:r', '/grant:r',
                            account+':(OI)(CI)F', 'SYSTEM:(OI)(CI)F'], check=True, capture_output=True)
        subprocess.run([scp,'-O','-q','-r']+options+[args.host+':'+BASE+'/state', str(folder)], check=True, timeout=60)
        subprocess.run([scp,'-O','-q']+options+[args.host+':'+BASE+'/installation.json',str(folder/'installation.json')],check=True,timeout=20)
        (folder/'status.json').write_text(remote('/proc/boot/pathtrust !'+BASE+'/device/run.sh && /bin/sh '+BASE+'/device/run.sh status'), encoding='utf-8')
        print('PRIVATE device journal/logs saved to '+str(folder))
    elif args.action in ('enable', 'disable', 'uninstall'):
        print(remote('/proc/boot/pathtrust !'+BASE+'/device/install.py && '+
                     '/proc/boot/pathtrust !'+BASE+'/device/native.py && '+
                     ENV+'/usr/bin/python3.2 '+BASE+'/device/install.py '+args.action, 150).strip())
    else:
        print(remote('/proc/boot/pathtrust !'+BASE+'/device/run.sh && /bin/sh '+BASE+'/device/run.sh '+args.action, 90).strip())


if __name__ == '__main__':
    main()
