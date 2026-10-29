"""Fetch pinned third-party inputs with persistent, hash-checked HTTP resume."""
import argparse
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import time
import urllib.error
import urllib.request
import uuid

from desktop_paths import resource_root, download_root

ROOT = resource_root()
ATTEMPTS = 5
TIMEOUT = 45  # Socket inactivity, not a deadline for the whole firmware.
CHUNK_SIZE = 256 * 1024


class DownloadError(RuntimeError):
    def __init__(self, code, filename='', detail=''):
        super().__init__(code)
        self.code = code
        reasons = {
            'download_failed': '下载中断，自动重试已用完',
            'download_http_error': '下载服务器拒绝请求',
            'download_tls_error': '无法验证下载服务器的安全证书，请检查系统时间或代理',
            'download_invalid_response': '服务器返回了无效的下载范围或内容',
            'download_hash_mismatch': '文件 SHA-256 校验失败，已停止使用该文件',
            'download_cache_invalid': '下载缓存路径或材料清单无效',
            'download_busy': '另一个应用正在下载此文件，请等待其完成',
            'download_disk_error': '无法写入下载目录，请检查剩余空间和目录权限',
        }
        self.user_message = reasons.get(code, code)
        if detail:
            self.user_message += '（' + detail + '）'
        if filename:
            self.user_message += '：' + filename
        if code not in ('download_busy', 'download_cache_invalid'):
            self.user_message += '。已保留可用进度；检查网络或“下载代理”后，再次点击准备按钮。'


class _Retryable(Exception):
    def __init__(self, reason, delay=0):
        super().__init__(reason)
        self.delay = delay


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _regular(path):
    if path.is_symlink() or path.exists() and not path.is_file():
        raise DownloadError('download_cache_invalid', path.name)


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
        if isinstance(validator, str) and len(validator) <= 256 and not re.search(r'[\r\n]', validator):
            return validator
    except (FileNotFoundError, ValueError, AttributeError):
        pass
    return None


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
    raise _Retryable('连接超时' if isinstance(reason, TimeoutError) else '网络连接中断') from None


def _show_progress(progress, name, count, total, started, initial):
    amount = f'{count / 1024 ** 2:.1f} MiB'
    if total is not None:
        amount += f' / {total / 1024 ** 2:.1f} MiB（{count / max(total, 1):.1%}）'
    elapsed = time.monotonic() - started
    speed = f' · {(count - initial) / 1024 ** 2 / elapsed:.2f} MiB/s' if elapsed > 0 and count > initial else ''
    progress(('续传 ' if initial else '下载 ') + name + ' · ' + amount + speed)


def _transfer(item, partial, meta, opener, progress, headers):
    name = item['file']
    offset = partial.stat().st_size if partial.exists() else 0
    request_headers = dict(headers or {})
    request_headers['Accept-Encoding'] = 'identity'
    validator = _metadata(meta)
    if offset:
        request_headers['Range'] = f'bytes={offset}-'
        if validator:
            request_headers['If-Range'] = validator
    progress(('连接服务器，准备续传 ' if offset else '连接服务器，准备下载 ') + name)
    request = urllib.request.Request(item['url'], headers=request_headers)
    try:
        response = opener.open(request, timeout=TIMEOUT)
    except urllib.error.HTTPError as error:
        status, retry_after = error.code, error.headers.get('Retry-After')
        error.close()
        if status == 416 and offset:
            # The final read may have failed after all bytes reached disk.
            if sha(partial) == item['sha256']:
                return
            _quarantine(partial)
            meta.unlink(missing_ok=True)
            raise _Retryable('服务器不接受旧进度，将重新下载') from None
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
            if start != offset or not start <= end < total or length is not None and length != end - start + 1:
                raise DownloadError('download_invalid_response', name)
            current_validator = _validator(response.headers)
            if offset and validator and current_validator and validator != current_validator:
                _quarantine(partial)
                meta.unlink(missing_ok=True)
                raise _Retryable('服务器文件已变化，将重新下载')
            expected_end = end + 1
        elif status == 200:
            if offset:
                progress('服务器未接受续传，将从头下载 ' + name)
            offset, total, expected_end = 0, length, length
        else:
            raise DownloadError('download_invalid_response', name)
        started = last_progress = time.monotonic()
        count = offset
        # Truncate before saving a new validator. A crash cannot leave old bytes
        # associated with a new representation. The pinned hash is authoritative.
        with partial.open('ab' if offset else 'wb') as output:
            meta.write_text(json.dumps({'validator': _validator(response.headers)}), encoding='utf-8')
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
                if incomplete:
                    raise _Retryable('连接提前结束')
                if not chunk:
                    break
        _show_progress(progress, name, count, total, started, offset)
        if expected_end is not None and count != expected_end:
            raise _Retryable('下载尚未完成')
        if total is not None and count < total:
            raise _Retryable('继续下载剩余内容')


def _fetch(item, folder, opener, progress, verify_only, headers):
    name, digest = item['file'], item['sha256']
    if (Path(name).name != name or name in ('.', '..') or '\\' in name or '/' in name or
            not re.fullmatch(r'[0-9a-f]{64}', digest)):
        raise DownloadError('download_cache_invalid')
    target = folder / name
    partial = folder / (name + '.' + digest + '.partial')
    meta = partial.with_name(partial.name + '.json')
    with _download_lock(partial.with_name(partial.name + '.lock')):
        for path in (target, partial, meta):
            _regular(path)
        if target.exists():
            progress('校验 ' + name)
            if sha(target) == digest:
                return
            if verify_only:
                raise DownloadError('download_hash_mismatch', name)
            _quarantine(target)
            progress('缓存校验失败，已隔离，将重新获取 ' + name)
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
                progress('已找回旧版下载进度 ' + name)
        if partial.exists():
            progress('检查已保存的下载 ' + name)
            if sha(partial) == digest:
                partial.replace(target)
                meta.unlink(missing_ok=True)
                return
        hash_failures = 0
        for attempt in range(ATTEMPTS):
            try:
                _transfer(item, partial, meta, opener, progress, headers)
                progress('校验 ' + name)
                if sha(partial) != digest:
                    _quarantine(partial)
                    meta.unlink(missing_ok=True)
                    hash_failures += 1
                    if hash_failures > 1 or attempt == ATTEMPTS - 1:
                        raise DownloadError('download_hash_mismatch', name)
                    raise _Retryable('文件校验失败，重新下载一次')
                partial.replace(target)
                meta.unlink(missing_ok=True)
                return
            except _Retryable as error:
                if attempt == ATTEMPTS - 1:
                    raise DownloadError('download_failed', name, str(error)) from None
                delay = max(2 ** attempt, error.delay)
                progress(f'{name}：{error}；{delay:g} 秒后自动重试（{attempt + 2}/{ATTEMPTS}），保留已下载进度')
                time.sleep(delay)


def fetch_entries(entries, folder=None, progress=None, proxy=None, verify_only=False, *, headers=None):
    folder = Path(folder) if folder else download_root()
    progress = progress or (lambda text: print(text, flush=True))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': proxy, 'http': proxy})
                                         if proxy else urllib.request.ProxyHandler())
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for item in entries:
            _fetch(item, folder, opener, progress, verify_only, headers)
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
    args = parser.parse_args(argv)
    entries = json.loads((ROOT / 'materials/sources.json').read_text())['verified_inputs']
    if args.with_usb_drivers:
        entries += json.loads((ROOT / 'materials/usb-drivers.json').read_text())['parts']
    try:
        fetch_entries(entries, proxy=args.proxy, verify_only=args.verify_only)
    except DownloadError as error:
        raise SystemExit(error.user_message) from None


if __name__ == '__main__':
    main()
