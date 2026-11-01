"""Local, bounded support history. Only projected/scrubbed data reaches disk."""
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import queue
import re
import threading
import traceback
import uuid
import zipfile

from desktop_paths import private_root, resource_root, desktop_release_version

MAX_EVENTS = 400
MAX_SESSIONS = 5
MAX_FILE_BYTES = 2_000_000
TEXT_LIMIT = 1600


def scrub(value):
    text = str(value)[:16000]
    text = re.sub(r'-----BEGIN [^-]*(?:PRIVATE KEY)[^-]*-----.*?(?:-----END [^-]+-----|$)',
                  '[private key removed]', text, flags=re.S)
    text = re.sub(r'(?im)^.*(?:password|passwd|passphrase|secret|api[_ -]?key|authorization|'
                  r'access[_ -]?token|private[_ -]?key|密码|口令|密钥).*$', '[credential removed]', text)
    text = re.sub(r'\b(?:ssh-rsa|ssh-ed25519)\s+\S+(?:[^\r\n]*)', '[key removed]', text)
    text = re.sub(r'(?i)\b(?:Bearer|Basic)\s+\S+', '[credential removed]', text)
    text = re.sub(r'(?i)\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b', '[token removed]', text)
    text = re.sub(r'https?://[^\s<>]+', '[URL removed]', text, flags=re.I)
    text = re.sub(r'(?i)(?:[a-z]:[\\/]|\\\\)[^\r\n<>]*', '[local path removed]', text)
    text = re.sub(r'(?<!\w)/(?:Users|home|tmp|private|var|mnt|data|accounts)/[^\r\n<>]*', '[path removed]', text)
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}', '[email removed]', text)
    text = re.sub(r'(?i)\b(?:imei|imsi|iccid|pin|msisdn|phone|serial|手机号|号码)\s*[:=：]\s*\S+', '[identifier removed]', text)
    text = re.sub(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])', '[address removed]', text)
    text = re.sub(r'(?i)(?<!\w)(?:[0-9a-f]{0,4}:){2,}[0-9a-f:]{0,39}(?!\w)', '[address removed]', text)
    text = re.sub(r'(?<!\w)\+?\d[\d ()-]{6,}\d(?!\w)', '[number removed]', text)
    text = re.sub(r'\b[A-Za-z0-9+/=_-]{40,}\b', '[token removed]', text)
    return text[:TEXT_LIMIT]


def code(value):
    # Error/phase names only; never export arbitrary exception messages as codes.
    value = str(value or '')
    return value if re.fullmatch(r'[A-Za-z][A-Za-z0-9_:-]{0,95}', value) and not re.search(r'\d{7}', value) else 'see_message'


BOOL_FIELDS = {'usb_present', 'usb_network', 'ssh_port', 'can_install', 'can_update', 'can_start',
               'installed', 'installation_pending', 'update_pending', 'update_available', 'registered',
               'enabled', 'manager_alive', 'native_alive', 'status_from_current_boot', 'selected_this_boot',
               'reboot_required', 'automatic_carrier_selection', 'sim_ready', 'lte_ready', 'restored',
               'sim_supported', 'automatic_start'}
CODE_FIELDS = {'phase', 'state', 'outcome', 'id', 'code', 'note', 'error', 'status_error', 'selected_operator',
               'managed_adapter', 'registration', 'ims', 'ran', 'ims_observation_scope',
               'scope_error', 'sim_reason'}
CONTAINERS = {'preflight', 'checks', 'device', 'usb', 'installation', 'current', 'startup_wait', 'status',
              'support', 'network_diagnostics', 'baseline', 'network_service', 'data_service', 'apn'}
NATIVE_PATHS = {'/radio/bin/ims_rrm', '/sbin/io-pkt-v6-hc', '/radio/lib/libradiocontrol.so.0.1',
                '/etc/carrier/config/36.xml', '/radio/bin/qct_rrm', '/usr/sbin/dca'}


def trial_projection(value):
    if not isinstance(value, dict):
        return None
    result = project({key: value.get(key) for key in ('variant', 'automatic_start')})
    if value.get('operator') in ('mobile', 'unicom', 'telecom'):
        result['operator'] = value['operator']
    if value.get('hardware_acceptance') == 'not_established':
        result['hardware_acceptance'] = 'not_established'
    board = value.get('observed_board')
    if isinstance(board, str) and re.fullmatch(r'[A-Z0-9_]{3,32}', board):
        result['observed_board'] = board
    hashes = value.get('native_sha256')
    if isinstance(hashes, dict):
        result['native_sha256'] = {path: digest for path, digest in hashes.items()
            if path in NATIVE_PATHS and isinstance(digest, str) and re.fullmatch(r'[a-f0-9]{64}', digest)}
    return result


def project(value, depth=0):
    """Reject unknown fields, paths, raw logs, connection material and identifiers."""
    if depth > 7:
        return None
    if isinstance(value, list):
        return [project(item, depth + 1) for item in value[:80] if isinstance(item, dict)]
    if not isinstance(value, dict):
        return None
    out = {}
    for key, item in value.items():
        if key == 'variant_trial':
            out[key] = trial_projection(item)
        elif key in BOOL_FIELDS and type(item) is bool:
            out[key] = item
        elif key in CODE_FIELDS and isinstance(item, str):
            out[key] = code(item)
        elif key == 'status' and item in ('pass', 'fail', 'warn', 'wait', 'blocked', 'block', 'adapt', 'skip', 'unknown'):
            out[key] = item
        elif key in CONTAINERS and isinstance(item, (dict, list)):
            out[key] = project(item, depth + 1)
        elif key in ('variant', 'hardware_variant', 'ModelName') and isinstance(item, str):
            out[key] = item if re.fullmatch(r'(?:SQN|SQC|SQW|STL|STA)\d{3}-\d', item) else 'unknown'
        elif key in ('os', 'os_version', 'PlatformVersion') and isinstance(item, str):
            out[key] = item if re.fullmatch(r'\d{1,2}(?:\.\d{1,4}){2,3}', item) else 'unknown'
        elif key in ('usb_count', 'attempt', 'max_attempts', 'seconds_per_attempt') and type(item) is int:
            out[key] = max(0, min(item, 10000))
        elif key == 'register_status' and isinstance(item, str):
            out[key] = item if item in ('200 OK', '403 Forbidden', '408 Request Timeout', 'not_registered') else 'unknown'
    return out


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def build_failure_excerpt(folder):
    """Read only the known current build log, never discover arbitrary private files."""
    path = Path(folder) / 'root-build.log'
    try:
        if path.is_symlink() or Path(folder).is_symlink() or Path(folder).is_junction():
            return ''
        with path.open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 32768))
            lines = stream.read(32768).decode('utf-8', errors='replace').splitlines()
        failures = [scrub(line) for line in lines if re.search(
            r'error|failed|exception|missing|not found|错误|失败', line, re.I)]
        return '\n'.join(failures[-16:])[:TEXT_LIMIT]
    except OSError:
        return ''


class Journal:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else private_root() / 'feedback'
        self.session = uuid.uuid4().hex
        self.path = self.directory / ('session-' + self.session + '.json')
        self.events = deque(maxlen=MAX_EVENTS)
        self.lock = threading.RLock()
        self.persistence_ok = True
        self.total = 0

    def record(self, step, action, outcome, *, message='', details=None):
        with self.lock:
            self.total += 1
            event = dict(at=now(), step=code(step), action=code(action), outcome=code(outcome))
            if message:
                event['message'] = scrub(message)
            if isinstance(details, (dict, list)):
                event['details'] = project(details)
            self.events.append(event)
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix('.partial')
                temporary.write_text(json.dumps({'session': self.session, 'events': list(self.events),
                    'total_events': self.total}, ensure_ascii=False), encoding='utf-8')
                temporary.replace(self.path)
                self.persistence_ok = True
            except OSError:
                # Reporting failures must never abort a device operation.
                self.persistence_ok = False

    def history(self):
        with self.lock:
            history = []
            try:
                candidates = [p for p in self.directory.glob('session-*.json')
                              if re.fullmatch(r'session-[0-9a-f]{32}\.json', p.name)
                              and not p.is_symlink() and p != self.path]
                candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                for path in reversed(candidates[:MAX_SESSIONS - 1]):
                    try:
                        if path.stat().st_size > MAX_FILE_BYTES:
                            continue
                        raw = json.loads(path.read_text(encoding='utf-8'))
                        events = []
                        for item in raw.get('events', [])[-MAX_EVENTS:]:
                            if not isinstance(item, dict):
                                continue
                            event = {k: code(item.get(k)) for k in ('step', 'action', 'outcome')}
                            stamp = item.get('at', '')
                            event['at'] = stamp if re.fullmatch(r'[0-9T:.+Z-]{10,40}', stamp) else 'unknown'
                            if item.get('message'):
                                event['message'] = scrub(item['message'])
                            if isinstance(item.get('details'), (dict, list)):
                                event['details'] = project(item['details'])
                            events.append(event)
                        history.append({'session': path.stem[8:], 'events': events,
                                        'truncated': raw.get('total_events', 0) != len(events)})
                    except (OSError, ValueError, TypeError, AttributeError):
                        continue
            except OSError:
                pass
            history.append({'session': self.session, 'events': list(self.events),
                            'truncated': self.total > len(self.events)})
            return history

    def bundle(self, step, note=''):
        try:
            release = desktop_release_version(json.loads((resource_root() / 'project.json').read_text(encoding='utf-8')))
        except (OSError, ValueError, KeyError):
            release = 'unknown'
        return {'schema': 'bb10-feedback/v1', 'feedback_id': uuid.uuid4().hex[:12],
                'created_at': now(), 'step': code(step), 'app_version': release,
                'desktop': {'system': platform.system(), 'release': platform.release(),
                            'machine': platform.machine(), 'python': platform.python_version()},
                'note': scrub(note), 'persistence_ok': self.persistence_ok,
                'limits': {'sessions': MAX_SESSIONS, 'events_per_session': MAX_EVENTS,
                           'raw_device_logs_included': False, 'automatic_upload': False},
                'sessions': self.history()}


def write_bundle(path, payload):
    """All ZIP entries are generated from the preview, never copied from private/."""
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.partial')
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('feedback.json', json.dumps(payload, ensure_ascii=False, indent=2))
            rows = []
            for session in payload['sessions']:
                rows.append('SESSION ' + session['session'])
                for event in session['events']:
                    rows.append('{at}  {step}/{action}  {outcome}  {message}'.format(message=event.get('message', ''),
                                **{k: event[k] for k in ('at', 'step', 'action', 'outcome')}))
            archive.writestr('timeline.txt', '\n'.join(rows))
            archive.writestr('README.txt', 'BB10 VoLTE feedback / 问题反馈\nID: ' + payload['feedback_id'] +
                '\n请检查内容后，将整个 ZIP 发给开发者：octoooo@octoooo.com，或通过原联系渠道发送。'
                '\nReview this ZIP before sharing it with the developer. Nothing was uploaded.'
                '\nOnly app operation history is included. No SSH material, raw phone/SIP logs, or phone backups.'
                '\n历史仅覆盖启用此功能后的最近 5 次启动，每次最多 400 条；早于该版本的错误无法自动补回。\n')
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def journal_for(widget):
    root = widget._root()
    journal = getattr(root, '_feedback_journal', None)
    if journal is None:
        journal = root._feedback_journal = Journal()
    return journal


class FeedbackQueue(queue.Queue):
    def __init__(self, widget, step):
        super().__init__()
        self.journal = journal_for(widget)
        self.step, self.action = step, 'open'
        self.journal.record(step, 'open', 'ready')

    def begin(self, action):
        self.action = action
        self.journal.record(self.step, action, 'started')

    def failure(self, error):
        # File basename + line/function identify unexpected failures without
        # exposing exception arguments, command output, locals or source lines.
        frames = traceback.extract_tb(error.__traceback__)[-8:]
        message = type(error).__name__ + '\n' + '\n'.join(
            Path(frame.filename).name + ':' + str(frame.lineno) + ' ' + frame.name for frame in frames)
        if getattr(error, 'feedback_log', ''):
            message += '\n' + scrub(error.feedback_log)
        self.journal.record(self.step, self.action, 'failed', message=message)

    def put(self, item, *args, **kwargs):
        try:
            kind, value = item[0], item[1]
            if kind not in ('candidate', 'connection', 'prepared_script'):
                action = self.action
                outcome, message, details = 'finished', '', None
                if len(item) == 3:  # AutoCarrierWindow
                    action, value, error = item
                    outcome = 'failed' if error else 'finished'
                    message = error or ''
                elif kind == 'progress':
                    outcome = 'progress'
                    message = ' / '.join(map(str, value)) if isinstance(value, tuple) else str(value)
                elif kind in ('error', 'download_error'):
                    outcome = 'failed'
                    message = str(value[0] if isinstance(value, tuple) else value)
                    details = value[1] if isinstance(value, tuple) and len(value) > 1 else None
                elif kind == 'result':
                    action, value = value
                if isinstance(value, dict):
                    details = value
                    snapshot = value.get('preflight') or value
                    if value.get('error'):
                        outcome, message = 'failed', str(value['error'])
                    elif (snapshot.get('scope_error') or snapshot.get('sim_supported') is False or
                          snapshot.get('outcome') in ('not_ready', 'unsupported', 'needs_adaptation') or
                          any(c.get('status') in ('fail', 'wait', 'blocked', 'block', 'adapt')
                              for c in snapshot.get('checks', []))):
                        outcome = 'needs_attention'
                self.journal.record(self.step, action, outcome, message=message, details=details)
        except Exception:
            # Event delivery is more important than support logging.
            self.journal.persistence_ok = False
        return super().put(item, *args, **kwargs)
