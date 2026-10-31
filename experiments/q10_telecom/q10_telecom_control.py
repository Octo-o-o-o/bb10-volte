"""Private task controller: Q10 SQN100-3, pinned Windows USB interface only."""
import datetime
import hashlib
import http.client
import ipaddress
import os
import json
import re
import shlex
import shutil
import socket
import struct
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = Path(os.environ.get('BB10_Q10_REPO', str(ROOT))).resolve()
KIT = Path(os.environ.get('BB10_Q10_SESSION', str(ROOT / 'private/q10-session'))).resolve()
REPORTS = Path(os.environ.get('BB10_Q10_REPORTS', str(ROOT / 'private/q10-reports'))).resolve()
sys.path.insert(0, str(REPO / 'tools'))
import workflow

GUARD = 'case "$(cat /pps/services/deviceproperties)" in *"modelnumber::SQN100-3"*) ;; *) exit 93;; esac; '


class Client(workflow.Client):
    def __init__(self, profile=None, allow_experimental=False):
        super().__init__('q10-telecom-root', KIT / 'ssh_config', profile=profile,
                         allow_experimental=allow_experimental, detect_managed=False)

    def process(self, args, timeout):
        try:
            result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                    timeout=timeout, creationflags=workflow.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired as error:
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            (KIT / ('process-timeout-' + stamp + '.json')).write_text(json.dumps({
                'args': args, 'timeout': timeout, 'outcome': 'unknown_do_not_retry_mutation'}), encoding='utf-8')
            raise workflow.WorkflowError('connection_timeout_state_unknown') from None
        if result.returncode:
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            (KIT / ('process-failure-' + stamp + '.json')).write_text(json.dumps({
                'args': args, 'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr},
                ensure_ascii=False, indent=2), encoding='utf-8')
            code = 'connection_failed' if result.returncode == 255 else 'remote_operation_failed'
            raise workflow.WorkflowError(code)
        return result.stdout

    def remote(self, command, timeout=40):
        record = {'at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'command': command, 'model_guard': 'SQN100-3',
                  'interface': json.loads((KIT / 'session.json').read_text())['interface']}
        events = KIT / 'command-audit-events'
        events.mkdir(exist_ok=True)
        (events / (uuid.uuid4().hex + '.json')).write_text(json.dumps(record), encoding='utf-8')
        lock = KIT / 'command-audit.lock'
        deadline = time.monotonic() + 15
        while True:
            try:
                lock.mkdir()
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise workflow.WorkflowError('audit_lock_pending')
                time.sleep(0.02)
        try:
            with (KIT / 'command-audit.jsonl').open('a', encoding='utf-8') as output:
                output.write(json.dumps(record) + '\n')
        finally:
            lock.rmdir()
        return super().remote(GUARD + command, timeout)


def save(tag, value):
    REPORTS.mkdir(exist_ok=True)
    value['desktop_captured_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    history = REPORTS / 'history'
    history.mkdir(exist_ok=True)
    blob = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    (history / (stamp + '-' + tag + '.json')).write_text(blob, encoding='utf-8')
    (REPORTS / (tag + '.json')).write_text(blob, encoding='utf-8')
    return value


def snapshot_source():
    project = json.loads((REPO / 'project.json').read_text())
    destination = KIT / ('candidate-' + project['version'] + '-r' + str(project['desktop_revision']))
    assert not destination.exists()
    manifest = workflow.verify_package()
    destination.mkdir()
    for name in list(manifest['files']) + ['materials/payload-manifest.json', 'project.json',
            'profiles/china-telecom-46011.json', 'profiles/china-unicom.json']:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / name, target)
    return {'frozen': True, 'payload_files': len(manifest['files']),
            'manifest_sha256': hashlib.sha256((destination / 'materials/payload-manifest.json').read_bytes()).hexdigest()}


def refresh():
    index = json.loads((KIT / 'session.json').read_text())['interface']
    assert type(index) is int and 1 <= index <= 65535
    powershell = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    command = ('Get-NetIPAddress -InterfaceIndex ' + str(index) + ' -AddressFamily IPv4 | '
               'Where-Object AddressState -eq Preferred | Select-Object IPAddress,PrefixLength | ConvertTo-Json -Compress')
    rows = json.loads(subprocess.check_output([powershell, '-NoProfile', '-Command', command], text=True))
    rows = rows if isinstance(rows, list) else [rows]
    assert len(rows) == 1
    local = ipaddress.IPv4Interface(rows[0]['IPAddress'] + '/' + str(rows[0]['PrefixLength']))
    assert local.network.prefixlen == 30
    peer = str(next(ip for ip in local.network.hosts() if ip != local.ip))
    sock = socket.socket()
    sock.settimeout(5)
    sock.setsockopt(socket.IPPROTO_IP, 31, struct.pack('!I', index))
    connection = http.client.HTTPConnection(peer, 80, timeout=5)
    try:
        sock.connect((peer, 80))
        connection.sock = sock
        connection.request('GET', '/cgi-bin/discovery.cgi', headers={'User-Agent': 'QNXWebClient/1.0', 'Connection': 'close'})
        response = connection.getresponse()
        assert response.status == 200
        root = ET.fromstring(response.read(131072))
        facts = {node.tag: node.text for node in root.iter() if node.tag in ('ModelName', 'PlatformVersion')}
        assert facts.get('ModelName') == 'SQN100-3'
    finally:
        connection.close()
        sock.close()
    path = KIT / 'usb_proxy.py'
    text, count = re.subn(r"sock[.]connect\(\('[0-9.]+', 22\)\)", "sock.connect(('" + peer + "', 22))", path.read_text())
    assert count == 1
    path.write_text(text, encoding='utf-8', newline='\n')
    path = KIT / 'ssh_config'
    text, count = re.subn(r'(?m)^(\s*HostName)\s+\S+', r'\g<1> ' + peer, path.read_text())
    assert count == 1
    if 'HostKeyAlias' not in text:
        text = text.replace('    User root\n', '    HostKeyAlias 169.254.0.1\n    User root\n')
    path.write_text(text, encoding='utf-8', newline='\n')
    path = KIT / 'session.json'
    value = json.loads(path.read_text())
    value.update(peer=peer, local_address=str(local.ip), discovery_verified=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    return {'q10_verified': True, 'interface': index, 'peer': peer, 'device': facts, 'host_key_trust_preserved': True}


def main():
    action = sys.argv[1]
    if action == 'snapshot-source':
        result = snapshot_source()
    elif action == 'refresh':
        result = refresh()
    elif action in ('preflight', 'telecom-preflight'):
        profile = REPO / 'profiles/china-telecom-46011.json' if action == 'telecom-preflight' else None
        client = Client(profile, profile is not None)
        result = client.preflight()
        if result['installation']['state'] in ('busy', 'stopped', 'recovery_required'):
            result['service_status'] = workflow.public_status(client.service('status'))
    else:
        raise SystemExit('Use snapshot-source, preflight, telecom-preflight')
    result = save(action, result)
    if 'checks' in result:
        print(json.dumps({key: result.get(key) for key in ('device', 'facts', 'outcome', 'installation',
            'baseline', 'telecom_attach', 'service_status')}, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
