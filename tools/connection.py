"""Find user-owned BB10 SSH profiles without weakening device trust."""
import json
import ipaddress
from pathlib import Path
import shlex
import sys
import uuid

from desktop_paths import frozen, private_root, resource_root
from workflow import Client, WorkflowError

ALIASES = ('bb10-root', 'q10-root')


def aliases(path):
    found = []
    try:
        for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
            words = shlex.split(line, comments=True)
            if words and words[0].lower() == 'host':
                found.extend(word for word in words[1:] if word in ALIASES)
    except (OSError, UnicodeError, ValueError):
        pass
    return list(dict.fromkeys(found))


def matching_alias(path, host):
    choices = aliases(path)
    if host in ALIASES and host not in choices and choices:
        return next((alias for alias in ALIASES if alias in choices), host)
    return host


def saved_connection(require_files=True):
    try:
        data = json.loads((private_root() / 'connection.json').read_text(encoding='utf-8'))
        if set(data) == {'host', 'config'} and isinstance(data['host'], str) and isinstance(data['config'], str):
            if not require_files or not data['config'] or Path(data['config']).is_file():
                return data
    except (OSError, ValueError, TypeError):
        pass
    return None


def save_connection(host, config):
    # Store references only. Private keys and trust records stay in their own kit.
    folder = private_root()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'connection.json'
    temporary = folder / ('connection-' + uuid.uuid4().hex + '.json')
    temporary.write_text(json.dumps({'host': host, 'config': str(config)}, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def root_kit_configs(folder):
    # First-use preparation creates a fresh root-kit-<id> for each attempt.
    # Inspect only this application's immediate kit directories, never the disk.
    return ([folder / 'root-kit/ssh_config'] + sorted(folder.glob('root-kit-*/ssh_config'))
            + sorted(folder.glob('recovery-*/ssh_config')))


def candidate_connections():
    saved = saved_connection()
    result = [dict(saved, saved=True)] if saved else []
    paths = root_kit_configs(private_root())
    paths += [Path.home() / '.ssh/config', Path(sys.executable).parent / 'ssh_config']
    roots = [resource_root()] if not frozen() else []
    # A portable executable next to its source checkout can reuse that owner's
    # prepared kit. Do not recursively search the user's disk for credentials.
    for parent in list(Path(sys.executable).resolve().parents)[:5]:
        try:
            if json.loads((parent / 'project.json').read_text(encoding='utf-8')).get('name') == 'bb10-volte':
                roots.append(parent)
        except (OSError, ValueError, AttributeError):
            pass
    for root in roots:
        paths.extend(root_kit_configs(root / 'private'))
        if root.parent.name == 'opensource':
            paths.append(root.parent.parent / 'tools/volte_session/private/ssh_config')
    seen = {(item['host'], item['config']) for item in result}
    for path in paths:
        if not path.is_file():
            continue
        for host in ALIASES:
            if host not in aliases(path):
                continue
            pair = (host, str(path.resolve()))
            if pair not in seen:
                result.append({'host': pair[0], 'config': pair[1], 'saved': False})
                seen.add(pair)
    return result


def dynamic_usb_link():
    """Return (peer, source) when a single attached BB10 uses a non-0.1 /30 USB link."""
    try:
        import root_setup
        usb = root_setup.local_usb_state()
    except Exception:
        return None
    if type(usb.get('usb_count')) is not int or usb['usb_count'] != 1:
        return None
    peer = str(usb.get('usb_peer') or '')
    source = str(usb.get('usb_source_address') or '')
    try:
        subnet = ipaddress.IPv4Network(source + '/30', strict=False)
        first, second = list(subnet.hosts())
        if (not ipaddress.IPv4Address(peer).is_link_local or
                not ipaddress.IPv4Address(source).is_link_local or
                peer != str(first) or source != str(second)):
            return None
    except ValueError:
        return None
    if peer == '169.254.0.1' or peer == source:
        return None
    return peer, source


def _apply_dynamic_usb_peer(client, link):
    if not link:
        return client
    peer, source = link
    try:
        effective = client.process([client.ssh, '-G'] + client.options + [client.host], 10)
        values = dict(line.split(' ', 1) for line in effective.splitlines() if ' ' in line)
        if (values.get('hostname') != '169.254.0.1' or values.get('user') != 'root' or
                values.get('proxycommand', 'none') != 'none' or values.get('proxyjump', 'none') != 'none'):
            return client
    except WorkflowError:
        return client
    trust_alias = values.get('hostkeyalias', 'none')
    if trust_alias == 'none':
        trust_alias = '169.254.0.1'
    client.options[:0] = ['-o', 'HostName=' + peer, '-o', 'BindAddress=' + source,
                          '-o', 'ProxyCommand=none', '-o', 'ProxyJump=none',
                          '-o', 'HostKeyAlias=' + trust_alias]
    return client


def resolve_connection(host, config, **client_options):
    client_options.setdefault('detect_managed', True)
    if config:
        choice = {'host': matching_alias(config, host), 'config': config}
        client = Client(choice['host'], choice['config'], **client_options)
        link = dynamic_usb_link() if choice['host'] in ALIASES else None
        if link:
            _apply_dynamic_usb_peer(client, link)
        return client, choice
    candidates = candidate_connections()
    # A nonstandard alias was supplied explicitly: use the owner's system SSH
    # configuration rather than substituting a different device.
    if host not in ALIASES:
        return Client(host, None, **client_options), {'host': host, 'config': ''}
    errors = []
    link = None
    link_checked = False
    for choice in candidates:
        client = Client(choice['host'], choice['config'] or None, **client_options)
        try:
            if not choice['saved']:
                effective = client.process([client.ssh, '-G'] + client.options + [client.host], 10)
                values = dict(line.split(' ', 1) for line in effective.splitlines() if ' ' in line)
                if (values.get('hostname') != '169.254.0.1' or values.get('user') != 'root' or
                        values.get('proxycommand', 'none') != 'none' or values.get('proxyjump', 'none') != 'none'):
                    continue
            if client.remote('echo BB10_CONNECTION_READY', timeout=12).strip() == 'BB10_CONNECTION_READY':
                return client, {'host': choice['host'], 'config': choice['config']}
        except WorkflowError as error:
            if error.code in ('connection_failed', 'connection_refused', 'connection_timeout_state_unknown'):
                if not link_checked:
                    link = dynamic_usb_link()
                    link_checked = True
                if link:
                    retry_client = _apply_dynamic_usb_peer(
                        Client(choice['host'], choice['config'] or None, **client_options), link)
                    try:
                        if retry_client.remote('echo BB10_CONNECTION_READY', timeout=12).strip() == 'BB10_CONNECTION_READY':
                            return retry_client, {'host': choice['host'], 'config': choice['config']}
                    except WorkflowError as retry_error:
                        errors.append(retry_error.code)
                        continue
            errors.append(error.code)
    if errors and all(code == 'host_key_mismatch' for code in errors):
        raise WorkflowError('host_key_mismatch')
    if errors and all(code == 'connection_refused' for code in errors):
        raise WorkflowError('connection_refused')
    if errors and all(code in ('connection_refused', 'connection_failed', 'connection_timeout_state_unknown') for code in errors):
        raise WorkflowError('connection_failed')
    if 'authentication_failed' in errors:
        raise WorkflowError('authentication_failed')
    raise WorkflowError('connection_setup_required')
