"""Fetch pinned third-party inputs with persistent, hash-checked HTTP resume."""
from i18n import tr
import argparse
from contextlib import contextmanager, nullcontext
from email.utils import parsedate_to_datetime
import hashlib
import http.client
import json
import os
from pathlib import Path
import queue
import re
import shutil
import ssl
import threading
import time
import urllib.error
from urllib.parse import urlsplit
import urllib.request
import uuid

from desktop_paths import resource_root, download_root

ROOT = resource_root()
ATTEMPTS = 5
TIMEOUT = 45  # Socket inactivity, not a deadline for the whole firmware.
CHUNK_SIZE = 256 * 1024
PROBE_BYTES = 256 * 1024
PROBE_TIMEOUT = 3
PROBE_DEADLINE = 6
OVERLAP_BYTES = 64 * 1024
MIRROR_TIMEOUT = 15
SLOW_WINDOW = 20
MIN_SPEED = 16 * 1024
MAX_SOURCES = 6


class DownloadError(RuntimeError):
    def __init__(self, code, filename='', detail=''):
        super().__init__(code)
        self.code = code
        reasons = {
            'download_failed': tr('下载中断，自动重试已用完'),
            'download_http_error': tr('下载服务器拒绝请求'),
            'download_tls_error': tr('无法验证下载服务器的安全证书，请检查系统时间或代理'),
            'download_invalid_response': tr('服务器返回了无效的下载范围或内容'),
            'download_resume_mismatch': tr('节点内容与已有下载进度不一致'),
            'download_hash_mismatch': tr('文件 SHA-256 校验失败，已停止使用该文件'),
            'download_cache_invalid': tr('下载缓存路径或材料清单无效'),
            'download_busy': tr('另一个应用正在下载此文件，请等待其完成'),
            'download_disk_error': tr('无法写入下载目录，请检查剩余空间和目录权限'),
        }
        self.user_message = reasons.get(code, code)
        if detail:
            self.user_message += tr('（') + detail + tr('）')
        if filename:
            self.user_message += tr('：') + filename
        if code not in ('download_busy', 'download_cache_invalid'):
            self.user_message += tr('。已保留可用进度；检查网络或“下载代理”后，再次点击准备按钮。')


class _Retryable(Exception):
    def __init__(self, reason, delay=0, slow=False):
        super().__init__(reason)
        self.delay = delay
        self.slow = slow


class MaterialImportError(RuntimeError):
    """Local import errors carry instructions without suggesting a network retry."""
    def __init__(self, code):
        super().__init__(code)
        self.user_message = {
            'import_source_invalid': tr('无法读取所选文件。请选择浏览器已下载完成的固件压缩包，或检查文件路径和读取权限。'),
            'import_hash_mismatch': tr('所选文件与要求的固件不一致，可能尚未下载完整、已损坏或选错版本。请下载页面指定的完整 .7z 文件，不要解压。原文件和已有缓存均已保留。'),
            'import_insufficient_disk': tr('下载缓存所在磁盘空间不足，无法复制固件。请至少腾出与固件大小相同的空间后重试。'),
            'import_io_error': tr('导入未完成。请检查所选文件是否可读、缓存目录是否可写，以及磁盘空间。原文件和已保存的下载进度均已保留。'),
        }[code]


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _regular(path):
    if path.is_symlink() or path.exists() and not path.is_file():
        raise DownloadError('download_cache_invalid', path.name)


def _input_paths(item, folder):
    name, digest = item['file'], item['sha256']
    if (Path(name).name != name or name in ('.', '..') or '\\' in name or '/' in name or
            not re.fullmatch(r'[0-9a-f]{64}', digest)):
        raise DownloadError('download_cache_invalid')
    target = folder / name
    partial = folder / (name + '.' + digest + '.partial')
    return target, partial


def source_urls(item):
    """Only explicit, pinned manifest alternatives; never public proxy discovery."""
    mirrors = item.get('mirrors', [])
    if not isinstance(mirrors, list):
        raise DownloadError('download_cache_invalid')
    urls = []
    for url in [item['url']] + mirrors:
        if not isinstance(url, str):
            raise DownloadError('download_cache_invalid')
        parsed = urlsplit(url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or
                parsed.username or parsed.password or parsed.fragment or re.search(r'[\r\n]', url)):
            raise DownloadError('download_cache_invalid')
        if url not in urls:
            urls.append(url)
    if len(urls) > MAX_SOURCES:
        raise DownloadError('download_cache_invalid')
    return urls


def source_label(url):
    # Do not put signed redirect queries, proxy credentials or tokens in the UI.
    return urlsplit(url).hostname or tr('下载节点')


def _headers_for(item, url, headers):
    values = dict(headers or {})
    primary, candidate = urlsplit(item['url']), urlsplit(url)
    if (primary.scheme, primary.netloc) != (candidate.scheme, candidate.netloc):
        values = {k: v for k, v in values.items()
                  if k.lower() not in ('authorization', 'cookie', 'proxy-authorization')}
    values['Accept-Encoding'] = 'identity'
    return values


def _probe_source(item, url, opener, headers):
    """Bounded payload sample, including connection and first-byte latency."""
    values = _headers_for(item, url, headers)
    values['Range'] = f'bytes=0-{PROBE_BYTES - 1}'
    started, count = time.monotonic(), 0
    with opener.open(urllib.request.Request(url, headers=values), timeout=PROBE_TIMEOUT) as response:
        if response.status not in (200, 206) or response.headers.get('Content-Encoding', 'identity') != 'identity':
            return None
        if response.status == 206:
            match = re.fullmatch(r'bytes 0-([0-9]+)/([0-9]+)', response.headers.get('Content-Range', ''))
            if not match:
                return None
            end, total = map(int, match.groups())
            if end >= total or end >= PROBE_BYTES or item.get('size', total) != total:
                return None
        while count < PROBE_BYTES and time.monotonic() - started < PROBE_TIMEOUT:
            chunk = response.read1(min(64 * 1024, PROBE_BYTES - count))
            if not chunk:
                break
            count += len(chunk)
    return count / max(time.monotonic() - started, 0.001) if count else None


def _rank_sources(item, urls, make_opener, headers, progress):
    progress(tr('正在测速 {} 个下载节点：').format(len(urls)) + item['file'])
    results = queue.Queue()

    def probe(url):
        try:
            speed = _probe_source(item, url, make_opener(), headers)
        except urllib.error.HTTPError as error:
            error.close()
            speed = None
        except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError):
            speed = None
        results.put((url, speed))

    deadline = time.monotonic() + PROBE_DEADLINE
    for url in urls:
        # DNS resolution may outlive a socket timeout. Daemon workers cannot
        # hold the download or app shutdown; at most MAX_SOURCES are created.
        threading.Thread(target=probe, args=(url,), daemon=True).start()
    speeds = {}
    for _ in urls:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            url, speed = results.get(timeout=remaining)
        except queue.Empty:
            break
        if speed is not None:
            speeds[url] = speed
    ranked = sorted(urls, key=lambda url: -speeds.get(url, 0))
    if speeds:
        progress(tr('已选择节点 {} · 测速 {:.2f} MiB/s').format(source_label(ranked[0]), speeds[ranked[0]] / 1024 ** 2))
    else:
        progress(tr('测速暂未成功，将依次尝试下载节点：') + item['file'])
    return ranked


def import_material(item, source, folder=None, progress=None):
    """Copy a user-selected archive into the cache, promoting only its pinned hash.

    Never opens a URL, moves the source, extracts a file or launches a tool.
    The download lock also protects against other importing/downloading apps.
    """
    folder = Path(folder) if folder else download_root()
    source = Path(source).expanduser()
    target, partial = _input_paths(item, folder)
    progress = progress or (lambda text: print(text, flush=True))
    temporary = None
    temporary_created = False
    try:
        if not source.is_file():
            raise MaterialImportError('import_source_invalid')
        try:
            input_file = source.open('rb')
        except OSError:
            raise MaterialImportError('import_source_invalid') from None
        with input_file:
            total = os.fstat(input_file.fileno()).st_size
            folder.mkdir(parents=True, exist_ok=True)
            with _download_lock(partial.with_name(partial.name + '.lock')):
                _regular(target)
                same_file = target.exists() and source.samefile(target)
                if not same_file and shutil.disk_usage(folder).free < total:
                    raise MaterialImportError('import_insufficient_disk')
                h, count, last_progress = hashlib.sha256(), 0, time.monotonic()
                progress(tr('正在校验并导入 ') + item['file'] + tr('，请稍候…'))
                # An independent file leaves resumable downloads and an existing
                # cache intact until the entire selected input is verified.
                if not same_file:
                    temporary = folder / (item['file'] + '.' + uuid.uuid4().hex + '.importing')
                output_file = temporary.open('xb') if temporary else nullcontext()
                temporary_created = temporary is not None
                with output_file as output:
                    while chunk := input_file.read(CHUNK_SIZE):
                        h.update(chunk)
                        if output:
                            output.write(chunk)
                        count += len(chunk)
                        if time.monotonic() - last_progress >= 0.5:
                            progress(tr('校验并导入 {} · {:.1f} / {:.1f} MiB（{:.1%}）').format(
                                item['file'], count / 1024 ** 2, total / 1024 ** 2, count / max(total, 1)))
                            last_progress = time.monotonic()
                if h.hexdigest() != item['sha256']:
                    raise MaterialImportError('import_hash_mismatch')
                if temporary:
                    temporary.replace(target)
                progress(tr('固件已导入并通过 SHA-256 校验：') + item['file'])
                return target
    except OSError:
        raise MaterialImportError('import_io_error') from None
    finally:
        if temporary_created:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # Never hide the actual import error; .importing is not used as cache.


@contextmanager
def _download_lock(path):
    """OS-owned lock: released on exit/crash; never unlink a locked inode."""
    _regular(path)
    with path.open('a+b') as lock:
        if lock.seek(0, 2) == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise DownloadError('download_busy') from None
        try:
            yield
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _quarantine(path):
    if path.exists():
        path.rename(path.with_name(path.name + '.invalid-' + uuid.uuid4().hex[:8]))


def _metadata(path):
    _regular(path)
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        validator = value.get('validator')
        if not isinstance(validator, str) or len(validator) > 256 or re.search(r'[\r\n]', validator):
            value['validator'] = None
        return value
    except (FileNotFoundError, ValueError, AttributeError):
        pass
    return {}


def _validator(headers):
    etag = headers.get('ETag', '')
    return etag if etag.startswith('"') else headers.get('Last-Modified')


def _retry_delay(value):
    try:
        delay = int(value)
    except (TypeError, ValueError):
        try:
            delay = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):
            return 0
    return max(0, min(delay, 60))


def _network_error(error, name):
    reason = getattr(error, 'reason', error)
    if isinstance(reason, ssl.SSLCertVerificationError):
        raise DownloadError('download_tls_error', name) from None
    raise _Retryable(tr('连接超时') if isinstance(reason, TimeoutError) else tr('网络连接中断')) from None


def _show_progress(progress, name, count, total, started, initial):
    amount = f'{count / 1024 ** 2:.1f} MiB'
    if total is not None:
        amount += f' / {total / 1024 ** 2:.1f} MiB' + tr('（') + f'{count / max(total, 1):.1%}' + tr('）')
    elapsed = time.monotonic() - started
    speed = f' · {(count - initial) / 1024 ** 2 / elapsed:.2f} MiB/s' if elapsed > 0 and count > initial else ''
    progress((tr('续传 ') if initial else tr('下载 ')) + name + ' · ' + amount + speed)


def _transfer(item, partial, meta, opener, progress, headers, *, url=None, multiple=False, switch_slow=False):
    name = item['file']
    url = url or item['url']
    offset = partial.stat().st_size if partial.exists() else 0
    request_headers = _headers_for(item, url, headers)
    previous = _metadata(meta)
    same_source = previous.get('url') == url or not multiple and not previous.get('url')
    validator = previous.get('validator') if same_source else None
    range_start = max(0, offset - OVERLAP_BYTES) if offset and not same_source else offset
    if offset:
        request_headers['Range'] = f'bytes={range_start}-'
        if validator:
            request_headers['If-Range'] = validator
    progress((tr('连接服务器，准备续传 ') if offset else tr('连接服务器，准备下载 ')) + name)
    request = urllib.request.Request(url, headers=request_headers)
    try:
        response = opener.open(request, timeout=MIRROR_TIMEOUT if multiple else TIMEOUT)
    except urllib.error.HTTPError as error:
        status, retry_after = error.code, error.headers.get('Retry-After')
        error.close()
        if status == 416 and offset:
            # The final read may have failed after all bytes reached disk.
            if sha(partial) == item['sha256']:
                return
            if multiple:
                raise DownloadError('download_invalid_response', name, tr('节点不接受已有下载范围')) from None
            _quarantine(partial)
            meta.unlink(missing_ok=True)
            raise _Retryable(tr('服务器不接受旧进度，将重新下载')) from None
        if status in (408, 429, 500, 502, 503, 504):
            raise _Retryable('HTTP ' + str(status), _retry_delay(retry_after)) from None
        raise DownloadError('download_http_error', name, 'HTTP ' + str(status)) from None
    except (OSError, urllib.error.URLError, http.client.HTTPException) as error:
        _network_error(error, name)
    with response:
        if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
            raise DownloadError('download_invalid_response', name)
        length = response.headers.get('Content-Length')
        if length is not None and not re.fullmatch(r'[0-9]+', length):
            raise DownloadError('download_invalid_response', name)
        length = int(length) if length is not None else None
        status = response.status
        if status == 206:
            match = re.fullmatch(r'bytes ([0-9]+)-([0-9]+)/([0-9]+)', response.headers.get('Content-Range', ''))
            if not match:
                raise DownloadError('download_invalid_response', name)
            start, end, total = map(int, match.groups())
            if start != range_start or not start <= end < total or length is not None and length != end - start + 1:
                raise DownloadError('download_invalid_response', name)
            current_validator = _validator(response.headers)
            if offset and validator and current_validator and validator != current_validator:
                _quarantine(partial)
                meta.unlink(missing_ok=True)
                raise _Retryable(tr('服务器文件已变化，将重新下载'))
            expected_end = end + 1
        elif status == 200:
            if offset:
                progress(tr('服务器未接受续传，将从头下载 ') + name)
            offset, total, expected_end = 0, length, length
        else:
            raise DownloadError('download_invalid_response', name)
        if item.get('size') is not None and total is not None and total != item['size']:
            raise DownloadError('download_invalid_response', name, tr('节点文件大小与固定版本不符'))
        if status == 206 and offset and not same_source:
            # ETags belong to one origin. Compare actual overlapping bytes
            # before appending data from another mirror (also after restart).
            overlap = bytearray()
            while len(overlap) < offset - range_start:
                try:
                    chunk = response.read1(offset - range_start - len(overlap))
                except (OSError, urllib.error.URLError, http.client.HTTPException) as error:
                    _network_error(error, name)
                if not chunk:
                    raise _Retryable(tr('节点未返回完整的续传校验片段'))
                overlap.extend(chunk)
            with partial.open('rb') as saved:
                saved.seek(range_start)
                if saved.read(len(overlap)) != overlap:
                    raise DownloadError('download_resume_mismatch', name)
        started = last_progress = time.monotonic()
        window_started, window_count = started, offset
        count = offset
        # Truncate before saving a new validator. A crash cannot leave old bytes
        # associated with a new representation. The pinned hash is authoritative.
        with partial.open('ab' if offset else 'wb') as output:
            meta.write_text(json.dumps({'url': url, 'validator': _validator(response.headers)}), encoding='utf-8')
            _show_progress(progress, name, count, total, started, offset)
            while True:
                incomplete = False
                try:
                    chunk = response.read1(CHUNK_SIZE)
                except http.client.IncompleteRead as error:
                    chunk, incomplete = error.partial, True
                except (OSError, urllib.error.URLError, http.client.HTTPException) as error:
                    _network_error(error, name)
                if chunk:
                    if expected_end is not None and count + len(chunk) > expected_end:
                        raise DownloadError('download_invalid_response', name)
                    output.write(chunk)
                    count += len(chunk)
                if time.monotonic() - last_progress >= 1:
                    _show_progress(progress, name, count, total, started, offset)
                    last_progress = time.monotonic()
                if switch_slow and time.monotonic() - window_started >= SLOW_WINDOW:
                    now = time.monotonic()
                    if chunk and (expected_end is None or count < expected_end) and (count - window_count) / (now - window_started) < MIN_SPEED:
                        raise _Retryable(tr('节点持续低速，尝试其他节点'), slow=True)
                    window_started, window_count = now, count
                if incomplete:
                    raise _Retryable(tr('连接提前结束'))
                if not chunk:
                    break
        _show_progress(progress, name, count, total, started, offset)
        if expected_end is not None and count != expected_end:
            raise _Retryable(tr('下载尚未完成'))
        if total is not None and count < total:
            raise _Retryable(tr('继续下载剩余内容'))


def _fetch(item, folder, make_opener, progress, verify_only, headers):
    name, digest = item['file'], item['sha256']
    target, partial = _input_paths(item, folder)
    meta = partial.with_name(partial.name + '.json')
    with _download_lock(partial.with_name(partial.name + '.lock')):
        for path in (target, partial, meta):
            _regular(path)
        if target.exists():
            progress(tr('校验 ') + name)
            if sha(target) == digest:
                return
            if verify_only:
                raise DownloadError('download_hash_mismatch', name)
            _quarantine(target)
            progress(tr('缓存校验失败，已隔离，将重新获取 ') + name)
        if verify_only:
            raise FileNotFoundError('Missing: ' + name)
        if not partial.exists():
            # Adopt only the old downloader's exact random-suffix naming scheme.
            legacy = [path for path in folder.iterdir()
                      if re.fullmatch(re.escape(name) + r'\.[0-9a-f]{8}\.partial', path.name)
                      and not path.is_symlink() and path.is_file()]
            if legacy:
                max(legacy, key=lambda path: path.stat().st_size).rename(partial)
                meta.unlink(missing_ok=True)
                progress(tr('已找回旧版下载进度 ') + name)
        if partial.exists():
            progress(tr('检查已保存的下载 ') + name)
            if sha(partial) == digest:
                partial.replace(target)
                meta.unlink(missing_ok=True)
                return
            if item.get('size') is not None and partial.stat().st_size > item['size']:
                _quarantine(partial)
                meta.unlink(missing_ok=True)
        urls = source_urls(item)
        multiple = len(urls) > 1
        if multiple:
            urls = _rank_sources(item, urls, make_opener, headers, progress)
        attempts = max(ATTEMPTS, len(urls) * 2) if multiple else ATTEMPTS
        failures = {url: 0 for url in urls}
        hash_failures = {url: 0 for url in urls}
        ready_at = {url: 0 for url in urls}
        blocked = set()
        resume_conflicts = set()
        slow_sources = set()
        clean_restart = False
        preferred = last_url = None
        last_error = DownloadError('download_failed', name)
        for attempt in range(attempts):
            candidates = [url for url in urls if url not in blocked]
            if not candidates and resume_conflicts and not clean_restart and partial.exists():
                # All remaining sources disagree with the saved tail. Keep the
                # rejected partial for diagnosis, and try one clean recovery.
                _quarantine(partial)
                meta.unlink(missing_ok=True)
                blocked.difference_update(resume_conflicts)
                candidates = [url for url in urls if url not in blocked]
                clean_restart = True
                progress(tr('已有进度无法与可用节点匹配，已隔离旧进度，将重新下载 ') + name)
            if not candidates:
                break
            eligible = [url for url in candidates if ready_at[url] <= time.monotonic()]
            url = (preferred if preferred in candidates else
                   min(eligible, key=lambda value: failures[value]) if eligible else
                   min(candidates, key=lambda value: ready_at[value]))
            preferred = None
            delay = max(0, ready_at[url] - time.monotonic())
            if delay:
                progress(tr('{}：{:.0f} 秒后自动重试（{}/{}），保留已下载进度').format(name, delay, attempt + 1, attempts))
                time.sleep(delay)
            if multiple:
                progress((tr('切换节点 ') if last_url and last_url != url else tr('使用节点 ')) + source_label(url) + tr('：') + name)
            last_url = url
            offset = partial.stat().st_size if partial.exists() else 0
            show = (lambda text: progress('[' + source_label(url) + '] ' + text)) if multiple else progress
            try:
                _transfer(item, partial, meta, make_opener(), show, headers, url=url,
                          multiple=multiple, switch_slow=multiple and len(candidates) > 1 and url not in slow_sources)
                progress(tr('校验 ') + name)
                if sha(partial) != digest:
                    _quarantine(partial)
                    meta.unlink(missing_ok=True)
                    hash_failures[url] += 1
                    if hash_failures[url] > 1 or multiple and not offset or attempt == attempts - 1:
                        raise DownloadError('download_hash_mismatch', name)
                    # A bad old prefix must not condemn a healthy finishing
                    # mirror. Give it one clean download after discarding it.
                    preferred = url
                    raise _Retryable(tr('文件校验失败，重新下载一次'))
                partial.replace(target)
                meta.unlink(missing_ok=True)
                return
            except _Retryable as error:
                last_error = DownloadError('download_failed', name, str(error))
                if error.slow:
                    # If every mirror is slow, settle on a previously tried
                    # source instead of repeatedly interrupting useful progress.
                    slow_sources.add(url)
                failures[url] += 1
                delay = max(2 ** min(failures[url] - 1, 5), error.delay)
                if not multiple and attempt < attempts - 1:
                    progress(tr('{}：{}；{:g} 秒后自动重试（{}/{}），保留已下载进度').format(name, error, delay, attempt + 2, attempts))
                    time.sleep(delay)
                else:
                    ready_at[url] = time.monotonic() + delay
                    progress(tr('节点 {}：{}；已保留下载进度').format(source_label(url), error))
            except DownloadError as error:
                if not multiple or error.code not in ('download_http_error', 'download_tls_error',
                                                       'download_invalid_response', 'download_hash_mismatch',
                                                       'download_resume_mismatch'):
                    raise
                blocked.add(url)
                if error.code == 'download_resume_mismatch':
                    resume_conflicts.add(url)
                last_error = error
                progress(tr('节点 {} 本次不可用：{}').format(source_label(url), error.user_message))
        raise last_error


def fetch_entries(entries, folder=None, progress=None, proxy=None, verify_only=False, *, headers=None):
    folder = Path(folder) if folder else download_root()
    progress = progress or (lambda text: print(text, flush=True))
    def make_opener():
        return urllib.request.build_opener(urllib.request.ProxyHandler({'https': proxy, 'http': proxy})
                                          if proxy else urllib.request.ProxyHandler())
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for item in entries:
            _fetch(item, folder, make_opener, progress, verify_only, headers)
    except FileNotFoundError:
        if verify_only:
            raise
        raise DownloadError('download_disk_error') from None
    except OSError:
        raise DownloadError('download_disk_error') from None
    return folder


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--with-usb-drivers', action='store_true', help='Also fetch the optional verified Windows USB driver archive')
    parser.add_argument('--proxy', help='Optional explicit HTTP proxy URL')
    parser.add_argument('--variant', help='Exact hardware variant, e.g. SQC100-1 or SQW100-4; omit to fetch tools only')
    args = parser.parse_args(argv)
    entries = json.loads((ROOT / 'materials/sources.json').read_text())['verified_inputs']
    entries = [item for item in entries if not item['id'].startswith('stock-')]
    if args.variant:
        from root_setup import SetupError, stock_firmware
        try:
            entries.append(stock_firmware(args.variant))
        except SetupError as error:
            parser.error(str(error))
    if args.with_usb_drivers:
        entries += json.loads((ROOT / 'materials/usb-drivers.json').read_text())['parts']
    try:
        fetch_entries(entries, proxy=args.proxy, verify_only=args.verify_only)
    except DownloadError as error:
        raise SystemExit(error.user_message) from None


if __name__ == '__main__':
    main()
