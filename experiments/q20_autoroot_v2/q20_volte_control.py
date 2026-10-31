"""Q20-only local transport; never import the other chat's mutable workflow."""
from pathlib import Path
import datetime
import hashlib
import ast
import http.client
import ipaddress
import json
import os
import shutil
import re
import shlex
import socket
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
KIT = Path(os.environ.get('BB10_Q20_SESSION', str(ROOT / 'private/q20-session'))).resolve()
PAYLOAD = KIT / 'volte-payload'
REPORTS = Path(os.environ.get('BB10_Q20_REPORTS', str(ROOT / 'private/q20-reports'))).resolve()
BASE = '/var/q20_volte'
SSH = shutil.which('ssh.exe') or shutil.which('ssh')
SCP = shutil.which('scp.exe') or shutil.which('scp')
OPTIONS = ['-F', str(KIT / 'ssh_config'), '-o', 'Ciphers=aes128-ctr,aes192-ctr,aes256-ctr']
GUARD = 'case "$(cat /pps/services/deviceproperties)" in *"modelnumber::SQC100-2"*) ;; *) exit 93;; esac; '
ENV = ('LD_LIBRARY_PATH=/base/usr/lib:/base/lib:/base/lib/dll:/radio/lib:/radio/lib/dll:/radio/usr/lib:/proc/boot '
       'PYTHONDONTWRITEBYTECODE=1 PYTHONHOME=/usr PYTHONPATH=' + BASE + '/device:' + BASE +
       ':/usr/lib/python32.zip:/usr/lib/python3.2/lib-dynload ')


def process(args, timeout=40):
    p = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    if p.returncode:
        raise RuntimeError(p.stdout + '\n' + p.stderr)
    return p.stdout


def remote(command, timeout=40):
    return process([SSH, '-n', '-T'] + OPTIONS + ['q20-root', GUARD + command], timeout)


def upload(source, destination):
    remote('test -d ' + shlex.quote(destination.rsplit('/', 1)[0]))
    return process([SCP, '-O', '-q'] + OPTIONS + [str(source), 'q20-root:' + destination])


def invoke(name, arguments='', timeout=90):
    assert name.endswith('_phone.py') and '/' not in name
    path = BASE + '/' + name
    names = sorted((PAYLOAD / 'device').glob('*.py'))
    with (KIT / 'volte-command-audit.jsonl').open('a', encoding='utf-8') as audit:
        audit.write(json.dumps({'at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'script': name, 'arguments': arguments,
            'service_start_requested': name == 'q20_volte_phone.py' and arguments in ('launch', 'boot')}) + '\n')
    trust = ' && '.join('(test ! -e ' + shlex.quote(BASE + '/device/' + p.name) +
                        ' || /proc/boot/pathtrust ' + shlex.quote('!' + BASE + '/device/' + p.name) + ')'
                        for p in names)
    for helper in ('q20_volte_phone.py', 'q20_own_number_auto.py', 'q20_telecom_carrier.py',
                   'q20_telecom_dca_usage_phone.py', 'q20_telecom_native_probe_phone.py'):
        trust += (' && (test ! -e ' + shlex.quote(BASE + '/' + helper) +
                  ' || /proc/boot/pathtrust ' + shlex.quote('!' + BASE + '/' + helper) + ')')
    stdout = remote(trust + ' && /proc/boot/pathtrust ' + shlex.quote('!' + path) +
                    ' && ' + ENV + '/usr/bin/python3.2 ' + shlex.quote(path) + ' ' + arguments, timeout)
    result = json.loads(stdout)
    result['desktop_captured_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    REPORTS.mkdir(parents=True, exist_ok=True)
    stem = name[:-9] + '-' + (arguments or 'snapshot').replace(' ', '_')
    output = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    history = REPORTS / 'history'
    history.mkdir(exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    (history / (stamp + '-' + stem + '.json')).write_text(output, encoding='utf-8')
    (REPORTS / (stem + '.json')).write_text(output, encoding='utf-8')
    return result


def refresh_connection():
    session_path = KIT / 'session.json'
    session = json.loads(session_path.read_text())
    index = session['interface']
    assert type(index) is int and 1 <= index <= 65535
    ps = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    command = ('Get-NetIPAddress -InterfaceIndex ' + str(index) +
        ' -AddressFamily IPv4 | Where-Object AddressState -eq Preferred |'
        ' Select-Object IPAddress,PrefixLength | ConvertTo-Json -Compress')
    rows = json.loads(process([ps, '-NoProfile', '-Command', command], 15))
    rows = rows if isinstance(rows, list) else [rows]
    assert len(rows) == 1
    local = ipaddress.IPv4Interface(rows[0]['IPAddress'] + '/' + str(rows[0]['PrefixLength']))
    assert local.network.prefixlen == 30
    peer = str(next(value for value in local.network.hosts() if value != local.ip))
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
        xml = ET.fromstring(response.read(131072))
        fields = {item.tag: item.text for item in xml.iter() if item.tag in ('ModelName', 'PlatformVersion')}
        assert fields.get('ModelName') == 'SQC100-2', 'The USB peer is not the authorized Q20'
    finally:
        connection.close()
        sock.close()
    proxy_path = KIT / 'usb_proxy.py'
    proxy = re.sub(r"sock[.]connect\(\('[0-9.]+', 22\)\)", "sock.connect(('" + peer + "', 22))", proxy_path.read_text())
    proxy_path.write_text(proxy, encoding='utf-8')
    config_path = KIT / 'ssh_config'
    config = re.sub(r'(?m)^(\s*HostName)\s+\S+', r'\g<1> ' + peer, config_path.read_text())
    config_path.write_text(config, encoding='utf-8')
    session.update(peer_address=peer, local_address=str(local.ip))
    session_path.write_text(json.dumps(session, indent=2) + '\n', encoding='utf-8')
    return {'q20_verified': True, 'peer_address': peer, 'host_key_trust_unchanged': True, 'device': fields}


def stage():
    remote('test ! -e ' + BASE + ' && mkdir -m 755 ' + BASE +
           ' && mkdir -m 755 ' + BASE + '/device ' + BASE + '/driver ' + BASE + '/profiles' +
           ' && mkdir -m 700 ' + BASE + '/state')
    for name in ('device/native.py', 'device/profiles.py', 'device/device_info.py', 'device/compatibility.py'):
        upload(PAYLOAD / name, BASE + '/' + name)
    for family in ('unicom', 'mobile', 'telecom'):
        name = 'profiles/china-' + family + '.json'
        upload(PAYLOAD / name, BASE + '/' + name)
    source = Path(__file__).with_name('q20_volte_probe_phone.py')
    upload(source, BASE + '/' + source.name)
    return {'staged': True, 'base': BASE, 'variant': 'SQC100-2', 'network_configuration_changed': False}


def snapshot():
    """Prepare immutable inputs offline; never create or modify SSH keys."""
    source = ROOT / 'opensource/q10-unicom-volte'
    if not (source / 'project.json').is_file():
        source = ROOT
    manifest = json.loads((source / 'materials/payload-manifest.json').read_text())
    assert not PAYLOAD.exists(), 'Preserve the existing Q20 source snapshot'
    blobs = {name: (source / name).read_bytes() for name in manifest['files']}
    assert all(hashlib.sha256(blobs[name]).hexdigest() == digest for name, digest in manifest['files'].items())
    PAYLOAD.mkdir(parents=True)
    for name, blob in blobs.items():
        path = PAYLOAD / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    for name in ('project.json', 'profiles/china-unicom.json', 'profiles/china-mobile.json', 'profiles/china-telecom.json'):
        path = PAYLOAD / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((source / name).read_bytes())
    (PAYLOAD / 'upstream-payload-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='ascii')
    return {'snapshot_verified': True, 'files': len(blobs), 'phone_modified': False}


def stage_service():
    # The public working tree belongs to concurrent chats. All inputs below
    # come from this task's immutable, independently verified snapshot.
    upstream = json.loads((PAYLOAD / 'upstream-payload-manifest.json').read_text())
    files = {name: PAYLOAD / name for name in upstream['files'] if not name.endswith('.sh')}
    for name, path in files.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == upstream['files'][name]
    source = Path(__file__).with_name('q20_volte_phone.py')
    files[source.name] = source
    baseline = json.loads((REPORTS / 'q20_volte_probe-snapshot.json').read_text())
    profile = baseline['profile']
    assert baseline['network']['mcc'] == '460' and baseline['network']['mnc'] == '01'
    profile.update(id='q20-sqc100-2-unicom-46001', label='Q20 SQC100-2 China Unicom 460-01')
    profile['carrier']['mncs'] = ['01']
    request = {'schema': 1, 'profile': profile, 'allow_experimental': True}
    profile_path = KIT / 'q20-profile-request.json'
    profile_path.write_text(json.dumps(request, sort_keys=True, separators=(',', ':')) + '\n', encoding='ascii')
    files['profile-request.json'] = profile_path
    manifest = {'schema': 1, 'owner': 'q20-sqc100-2-volte-v1',
                'files': {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}}
    manifest_path = KIT / 'q20-payload-manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='ascii')
    remote('test ! -e ' + BASE + '/runtime && mkdir -m 755 ' + BASE + '/runtime ' + BASE + '/runtime/carrier')
    for name, path in files.items():
        upload(path, BASE + '/' + name)
    upload(manifest_path, BASE + '/payload-manifest.json')
    remote('chmod 755 ' + BASE + '/driver/devnp-volte_swcrypto_probe.so && chmod 600 ' +
           BASE + '/q20_volte_phone.py ' + BASE + '/profile-request.json ' + BASE + '/payload-manifest.json')
    return {'service_staged': True, 'files': len(files), 'autostart_enabled': False,
            'network_configuration_changed': False}


def prepare_boot():
    # Only the launch-control wrapper changes; the active native binary,
    # service implementation, profile and mapped driver remain byte-identical.
    assert invoke('q20_volte_phone.py', 'status')['registered'] is True
    source = Path(__file__).with_name('q20_volte_phone.py')
    start = Path(__file__).with_name('q20_volte_start.sh')
    installer = Path(__file__).with_name('q20_volte_boot_install_phone.py')
    receipt = KIT / 'manual-call-acceptance.json'
    assert json.loads(receipt.read_text())['sip_dialogs_verified'] is True
    tree = ast.parse(installer.read_text())
    hook = ast.literal_eval(next(node.value for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'HOOK' for target in node.targets)))
    if not (KIT / 'btool').is_file():
        btool = '/apps/sys.android.gYABgKAOw1czN6neiAT72SGO.ns/native/system/xbin/btool'
        remote('test -f ' + btool)
        process([SCP, '-O', '-q'] + OPTIONS + ['q20-root:' + btool, str(KIT / 'btool')])
    original = (KIT / 'btool').read_bytes()
    assert b'codex-q20-volte-boot-v1' not in original, 'Preserve the original pre-install Root script'
    plan = {'btool_before_sha256': hashlib.sha256(original).hexdigest(),
            'btool_after_sha256': hashlib.sha256(original.replace(b'. /base/scripts/sudtools.sh\n',
                hook + b'. /base/scripts/sudtools.sh\n', 1)).hexdigest(),
            'start_sha256': hashlib.sha256(start.read_bytes()).hexdigest()}
    plan_path = KIT / 'boot-plan.json'
    plan_path.write_text(json.dumps(plan, indent=2) + '\n', encoding='ascii')
    manifest_path = KIT / 'q20-payload-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['files']['q20_volte_phone.py'] = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest['files']['start.sh'] = plan['start_sha256']
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='ascii')
    for src, name in ((source, 'q20_volte_phone.py'), (start, 'start.sh'),
                      (manifest_path, 'payload-manifest.json'),
                      (installer, installer.name), (receipt, 'state/manual-call-acceptance.json'),
                      (plan_path, 'state/boot-plan.json')):
        upload(src, BASE + '/' + name)
    remote('chmod 700 ' + BASE + '/start.sh && /proc/boot/pathtrust !' + BASE +
           '/q20_volte_phone.py && /proc/boot/pathtrust !' + BASE + '/start.sh')
    deployment = KIT / 'deployed-q20-adapter'
    deployment.mkdir(exist_ok=True)
    for p in (source, start, installer, manifest_path, receipt, plan_path):
        (deployment / p.name).write_bytes(p.read_bytes())
    return {'boot_plan_staged': True, 'autostart_enabled': False, 'root_script_changed': False,
            'manual_calls_verified': True, 'mapped_driver_rewritten': False}


def stage_revision():
    state = invoke('q20_volte_phone.py', 'status')
    assert state.get('manager_alive') is False and state.get('enabled') is False
    manifest = json.loads(remote('cat ' + BASE + '/payload-manifest.json'))
    changes = {'q20_volte_phone.py': Path(__file__).with_name('q20_volte_phone.py'),
               'q20_own_number_auto.py': Path(__file__).with_name('q20_own_number_auto.py'),
               'q20_telecom_carrier.py': Path(__file__).with_name('q20_telecom_carrier.py'),
               'q20_telecom_dca_usage_phone.py': Path(__file__).with_name('q20_telecom_dca_usage_phone.py'),
               'q20_telecom_native_probe_phone.py': Path(__file__).with_name('q20_telecom_native_probe_phone.py'),
               'start.sh': Path(__file__).with_name('q20_volte_start.sh')}
    for name, path in changes.items():
        manifest['files'][name] = hashlib.sha256(path.read_bytes()).hexdigest()
        upload(path, BASE + '/' + name)
    source = Path(__file__).with_name('q20_profile_switch_phone.py')
    upload(source, BASE + '/' + source.name)
    path = KIT / 'q20-payload-manifest.json'
    path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='ascii')
    upload(path, BASE + '/payload-manifest.json')
    remote('chmod 700 ' + BASE + '/start.sh && /proc/boot/pathtrust !' + BASE + '/q20_volte_phone.py' +
           ' && /proc/boot/pathtrust !' + BASE + '/q20_own_number_auto.py')
    deployment = KIT / 'deployed-q20-adapter'
    for name, source in changes.items():
        (deployment / source.name).write_bytes(source.read_bytes())
    (deployment / path.name).write_bytes(path.read_bytes())
    return {'wrapper_revision_staged': True, 'operator_templates_available': ['unicom', 'mobile', 'telecom'],
            'automatic_own_number_display': True, 'autostart_enabled': False,
            'mapped_driver_rewritten': False, 'network_configuration_written': False}


if __name__ == '__main__':
    action = sys.argv[1]
    value = (snapshot() if action == 'snapshot' else refresh_connection() if action == 'refresh' else
             stage() if action == 'stage' else stage_service() if action == 'stage-service' else
             prepare_boot() if action == 'prepare-boot' else
             stage_revision() if action == 'stage-revision' else
             invoke('q20_volte_boot_install_phone.py') if action == 'install-boot' else
             invoke('q20_volte_probe_phone.py') if action == 'probe' else
             invoke('q20_volte_phone.py', action) if action in ('precheck', 'launch', 'status', 'stop') else None)
    assert value is not None
    print(json.dumps(value, ensure_ascii=False, indent=2))
