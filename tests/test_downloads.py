"""Real loopback HTTP faults; no Internet, firmware execution or phone access."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import queue
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import i18n
i18n.LANGUAGE = 'zh'  # Progress-message assertions below use Chinese.
import fetch_materials as f
import macos_root
import setup_wizard


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.data = bytes(range(256)) * 4096 + b'pinned tail'
        self.requests, self.messages, self.responses = [], [], []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                fixture.requests.append(dict(self.headers))
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/asset')
                    self.end_headers()
                    return
                status, headers, body = (fixture.responses.pop(0) if fixture.responses else fixture.normal(self.headers))
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, str(value))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)
        self.item = {'file': 'firmware.7z', 'sha256': hashlib.sha256(self.data).hexdigest(),
                     'url': 'http://127.0.0.1:' + str(self.server.server_port) + '/asset'}
        self.target = self.folder / self.item['file']
        self.partial = self.folder / (self.item['file'] + '.' + self.item['sha256'] + '.partial')
        self.meta = self.partial.with_name(self.partial.name + '.json')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for mocker in (patch.object(f.urllib.request, 'build_opener', return_value=opener),
                       patch.object(f.time, 'sleep'), patch.object(f, 'ATTEMPTS', 3)):
            mocker.start()
            self.addCleanup(mocker.stop)

    def normal(self, headers):
        start = int(headers.get('Range', 'bytes=0-')[6:-1])
        if start >= len(self.data):
            return 416, {'Content-Range': f'bytes */{len(self.data)}'}, b''
        body = self.data[start:]
        values = {'Content-Length': len(body), 'ETag': '"version-one"'}
        if headers.get('Range'):
            values['Content-Range'] = f'bytes {start}-{len(self.data) - 1}/{len(self.data)}'
        return (206 if headers.get('Range') else 200), values, body

    def fetch(self, **kwargs):
        return f.fetch_entries([self.item], self.folder, self.messages.append, **kwargs)

    def assert_complete(self):
        self.assertEqual(self.target.read_bytes(), self.data)
        self.assertFalse(self.partial.exists())
        self.assertFalse(self.meta.exists())

    def test_disconnect_resumes_exact_persisted_offset_with_validator(self):
        cut = 345678
        self.responses.append((200, {'Content-Length': len(self.data), 'ETag': '"version-one"'}, self.data[:cut]))
        self.fetch()
        self.assert_complete()
        self.assertEqual(self.requests[1]['Range'], f'bytes={cut}-')
        self.assertEqual(self.requests[1]['If-Range'], '"version-one"')
        self.assertEqual(self.requests[1]['Accept-Encoding'], 'identity')
        self.assertTrue(any('100.0%' in text for text in self.messages))
        self.assertTrue(any('MiB/s' in text for text in self.messages))

    def test_exhausted_retries_preserve_progress_for_next_invocation(self):
        cut = 12345
        self.responses = [(200, {'Content-Length': len(self.data)}, self.data[:cut]),
                          (503, {}, b'busy'), (503, {}, b'busy')]
        with self.assertRaisesRegex(f.DownloadError, 'download_failed'):
            self.fetch()
        self.assertFalse(self.target.exists())
        self.assertEqual(self.partial.read_bytes(), self.data[:cut])
        self.fetch()
        self.assert_complete()
        self.assertEqual(self.requests[-1]['Range'], f'bytes={cut}-')

    def test_redirect_preserves_resume_headers(self):
        self.partial.write_bytes(self.data[:123])
        self.item['url'] = self.item['url'].replace('/asset', '/redirect')
        self.fetch()
        self.assert_complete()
        self.assertEqual([r['Range'] for r in self.requests], ['bytes=123-', 'bytes=123-'])

    def test_ignored_range_or_if_range_change_replaces_instead_of_appending(self):
        self.partial.write_bytes(b'old bytes')
        self.meta.write_text(json.dumps({'validator': '"old-version"'}))
        self.responses.append((200, {'Content-Length': len(self.data), 'ETag': '"new-version"'}, self.data))
        self.fetch()
        self.assert_complete()
        self.assertEqual(self.requests[0]['If-Range'], '"old-version"')
        self.assertTrue(any('从头下载' in text for text in self.messages))

    def test_changed_validator_in_206_restarts_without_mixing_files(self):
        self.partial.write_bytes(b'bad prefix')
        self.meta.write_text(json.dumps({'validator': '"old-version"'}))
        self.fetch()
        self.assert_complete()
        self.assertEqual(len(self.requests), 2)
        self.assertNotIn('Range', self.requests[1])

    def test_malformed_206_never_appends(self):
        prefix = self.data[:123]
        for value in ('bytes 0-122/1000', 'bytes 123-1000/1000', 'bytes 123-999/*', 'nonsense'):
            with self.subTest(content_range=value):
                self.partial.write_bytes(prefix)
                self.responses.append((206, {'Content-Range': value}, b'not the right bytes'))
                with self.assertRaisesRegex(f.DownloadError, 'download_invalid_response'):
                    self.fetch()
                self.assertEqual(self.partial.read_bytes(), prefix)
                self.assertFalse(self.target.exists())

    def test_contradictory_range_length_and_encoded_bodies_are_rejected(self):
        for headers in ({'Content-Range': 'bytes 1-9/10', 'Content-Length': '8'},
                        {'Content-Range': 'bytes 1-9/10', 'Content-Encoding': 'gzip'},
                        {'Content-Range': 'bytes 1-9/10', 'Content-Length': '-3'}):
            self.partial.write_bytes(b'x')
            self.responses.append((206, headers, b'bad body'))
            with self.assertRaisesRegex(f.DownloadError, 'download_invalid_response'):
                self.fetch()
            self.assertEqual(self.partial.read_bytes(), b'x')

    def test_416_for_stale_partial_restarts_and_preserves_rejected_bytes(self):
        self.partial.write_bytes(b'x' * (len(self.data) + 100))
        self.fetch()
        self.assert_complete()
        self.assertNotIn('Range', self.requests[1])
        self.assertEqual(len(list(self.folder.glob('*.invalid-*'))), 1)

    def test_complete_partial_promotes_without_network(self):
        self.partial.write_bytes(self.data)
        self.fetch()
        self.assert_complete()
        self.assertEqual(self.requests, [])

    def test_old_random_partial_is_adopted_and_largest_one_resumed(self):
        small = self.folder / 'firmware.7z.1234abcd.partial'
        large = self.folder / 'firmware.7z.abcde123.partial'
        unrelated = self.folder / 'another.7z.abcde123.partial'
        small.write_bytes(self.data[:123])
        large.write_bytes(self.data[:2345])
        unrelated.write_bytes(b'untouched')
        self.fetch()
        self.assert_complete()
        self.assertEqual(self.requests[0]['Range'], 'bytes=2345-')
        self.assertTrue(small.exists())
        self.assertFalse(large.exists())
        self.assertEqual(unrelated.read_bytes(), b'untouched')

    def test_retryable_http_uses_bounded_backoff_and_retry_after(self):
        self.responses = [(429, {'Retry-After': '7'}, b'busy'), (503, {}, b'busy')]
        self.fetch()
        self.assert_complete()
        self.assertEqual([call.args[0] for call in f.time.sleep.call_args_list], [7, 2])

    def test_permanent_http_failure_is_actionable_without_retries(self):
        self.responses.append((403, {}, b'secret upstream detail'))
        with self.assertRaises(f.DownloadError) as result:
            self.fetch()
        self.assertIn('HTTP 403', result.exception.user_message)
        self.assertNotIn('secret', result.exception.user_message)
        self.assertEqual(len(self.requests), 1)

    def test_hash_failure_refetches_once_then_never_promotes_bad_bytes(self):
        self.responses = [(200, {}, b'bad data'), (200, {}, b'bad data')]
        with self.assertRaisesRegex(f.DownloadError, 'download_hash_mismatch'):
            self.fetch()
        self.assertFalse(self.target.exists())
        self.assertFalse(self.partial.exists())
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(len(list(self.folder.glob('*.invalid-*'))), 2)

    def test_corrupt_old_partial_can_recover_by_clean_refetch(self):
        self.partial.write_bytes(b'corrupted prefix')
        self.fetch()
        self.assert_complete()
        self.assertEqual(len(self.requests), 2)
        self.assertNotIn('Range', self.requests[1])

    def test_bad_final_cache_is_repaired_online_but_not_modified_offline(self):
        self.target.write_bytes(b'bad cache')
        with self.assertRaisesRegex(f.DownloadError, 'download_hash_mismatch'):
            self.fetch(verify_only=True)
        self.assertEqual(self.target.read_bytes(), b'bad cache')
        self.assertEqual(self.requests, [])
        self.fetch()
        self.assert_complete()
        self.requests.clear()
        self.fetch(verify_only=True)
        self.assertEqual(self.requests, [])

    def test_missing_offline_input_keeps_partial_and_does_not_connect(self):
        self.partial.write_bytes(self.data[:123])
        with self.assertRaises(FileNotFoundError):
            self.fetch(verify_only=True)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.partial.stat().st_size, 123)

    def test_missing_content_length_still_requires_pinned_hash(self):
        self.responses.append((200, {}, self.data))
        self.fetch()
        self.assert_complete()

    def test_second_downloader_cannot_write_same_partial(self):
        with f._download_lock(self.partial.with_name(self.partial.name + '.lock')):
            with self.assertRaisesRegex(f.DownloadError, 'download_busy'):
                self.fetch()
        self.assertEqual(self.requests, [])
        self.fetch()
        self.assert_complete()

    def test_process_exit_releases_lock_and_resume_survives_restart(self):
        lock = self.partial.with_name(self.partial.name + '.lock')
        script = ('import sys,time; from pathlib import Path; from fetch_materials import _download_lock; '
                  'lock=_download_lock(Path(sys.argv[1])); lock.__enter__(); '
                  'print("ready",flush=True); time.sleep(30)')
        child = subprocess.Popen([sys.executable, '-c', script, str(lock)], cwd=f.ROOT / 'tools',
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            with self.assertRaisesRegex(f.DownloadError, 'download_busy'):
                self.fetch()
            self.partial.write_bytes(self.data[:12345])
        finally:
            child.terminate()
            child.communicate(timeout=5)
        self.fetch()
        self.assert_complete()
        self.assertEqual(self.requests[-1]['Range'], 'bytes=12345-')

    def test_certificate_failure_is_not_retried_or_exposed_raw(self):
        opener = MagicMock()
        opener.open.side_effect = urllib.error.URLError(ssl.SSLCertVerificationError('private proxy address'))
        with patch.object(f.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(f.DownloadError) as result:
                self.fetch()
        self.assertEqual(result.exception.code, 'download_tls_error')
        self.assertNotIn('private proxy', result.exception.user_message)
        self.assertEqual(opener.open.call_count, 1)

    def test_disk_write_failure_is_not_retried_as_network_failure(self):
        original = Path.open
        def open_path(path, *args, **kwargs):
            if path == self.partial and args and args[0] == 'wb':
                raise OSError('No space left on device')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', open_path):
            with self.assertRaisesRegex(f.DownloadError, 'download_disk_error'):
                self.fetch()
        self.assertEqual(len(self.requests), 1)
        f.time.sleep.assert_not_called()

    def test_mac_adapter_uses_shared_resume_with_anonymous_bottle_header(self):
        item = dict(self.item, url='https://ghcr.io/v2/homebrew/core/example/blobs/sha256:fixture')
        with patch.object(macos_root, 'fetch_entries') as fetch:
            self.assertEqual(macos_root.fetch(item, self.folder, self.messages.append, 'http://proxy', True), self.target)
        self.assertEqual(fetch.call_args.kwargs, {'verify_only': True, 'headers': {'Authorization': 'Bearer QQ=='}})
        with patch.object(macos_root, 'fetch_entries', side_effect=FileNotFoundError):
            with self.assertRaisesRegex(RuntimeError, 'macos_root_input_missing'):
                macos_root.fetch(self.item, self.folder, self.messages.append, offline=True)

    def test_cli_delegates_to_same_downloader(self):
        with patch.object(f, 'fetch_entries') as fetch:
            f.main(['--proxy', 'http://proxy', '--verify-only'])
        self.assertTrue(fetch.call_args.kwargs['verify_only'])
        self.assertEqual(fetch.call_args.kwargs['proxy'], 'http://proxy')

    def test_wizard_shows_download_reason_and_enables_retry(self):
        wizard = MagicMock()
        wizard.busy = False
        wizard.events = queue.Queue()
        error = f.DownloadError('download_failed', 'firmware.7z', 'HTTP 503')
        with patch.object(setup_wizard.threading, 'Thread', side_effect=lambda target, **_: MagicMock(start=target)):
            setup_wizard.SetupWizard.start(wizard, 'prepare', MagicMock(side_effect=error))
        setup_wizard.SetupWizard.drain(wizard)
        self.assertFalse(wizard.busy)
        wizard.status.configure.assert_called_with(text=error.user_message)
        wizard.progress.stop.assert_called_once()
        self.assertEqual(wizard.refresh.call_count, 2)


if __name__ == '__main__':
    unittest.main()
